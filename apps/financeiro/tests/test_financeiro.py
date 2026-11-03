import importlib
import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.agenda.models import Reserva
from apps.clientes.services import anonymize_client
from apps.financeiro import services
from apps.financeiro.models import Caixa, ContaBase, ContaPagar, ContaReceber, FormaPagamento, Lancamento
from apps.pdv import services as pdv_services
from apps.pdv.models import Venda
from apps.relatorios.services import revenue_report
from conftest import (
    DAY,
    HX,
    at,
    cashier,
    make_cliente,
    make_espaco,
    make_produto,
    make_tenant,
    make_user,
    with_register,
)

PIX, DINHEIRO = FormaPagamento.PIX, FormaPagamento.DINHEIRO
D = Decimal


def conta_of(reserva):
    return ContaReceber.all_tenants.get(reserva=reserva)


def refresh(obj):
    return type(obj).all_tenants.get(pk=obj.pk)


@pytest.fixture
def reserva(espaco, cliente):
    return agenda_services.create_reservation(espaco, cliente, at(10), at(11))


# --- Caixa


def test_register_opens_once_per_operator(owner):
    caixa = services.open_register(owner, D("50"))
    assert caixa.is_open
    with pytest.raises(services.RegisterAlreadyOpen):
        services.open_register(owner)
    assert services.current_register(owner) == caixa


def test_closing_compares_counted_cash_with_expected(tenant, owner, reserva):
    caixa = services.open_register(owner, D("50"))
    services.receive_account(conta_of(reserva), D("60"), DINHEIRO, owner)
    services.receive_account(conta_of(reserva), D("40"), PIX, owner)
    services.move_cash(owner, entra=False, valor=D("20"), descricao="Gelo")

    caixa = services.close_register(caixa, D("85"), owner, "Faltou troco")

    assert caixa.saldo_esperado == D("90")  # 50 + 60 em dinheiro - 20 retirados
    assert caixa.diferenca == D("-5")
    assert not caixa.is_open
    with pytest.raises(services.RegisterClosed):
        services.move_cash(owner, entra=True, valor=D("1"))
    with pytest.raises(services.RegisterAlreadyClosed):
        services.close_register(caixa, D("0"), owner)


def test_cannot_take_more_cash_than_there_is(owner):
    services.open_register(owner, D("10"))
    with pytest.raises(services.NotEnoughCash):
        services.move_cash(owner, entra=False, valor=D("10.01"))


def test_receiving_needs_an_open_register(owner, reserva):
    with pytest.raises(services.RegisterClosed):
        services.receive_account(conta_of(reserva), D("10"), PIX, owner)
    assert conta_of(reserva).valor_pago == 0


# --- Reserva e conta a receber


def test_every_reservation_gets_a_receivable(reserva, cliente):
    conta = conta_of(reserva)
    assert (conta.valor, conta.vencimento, conta.cliente, conta.status) == (D("100"), DAY, cliente, "ABERTA")
    assert conta.categoria == "RESERVA"


def test_receivable_follows_reservation_changes(reserva, espaco, cliente):
    agenda_services.update_reservation(reserva, espaco, cliente, at(12), at(13), D("150"))
    conta = conta_of(reserva)
    assert conta.valor == D("150")
    assert "12:00" in conta.descricao

    agenda_services.cancel_reservation(reserva)
    assert conta_of(reserva).status == "CANCELADA"


def test_partial_and_full_payment_of_a_reservation(reserva, owner):
    with_register(owner)
    services.receive_account(conta_of(reserva), D("30"), PIX, owner)
    assert refresh(reserva).valor_pago == D("30")
    assert conta_of(reserva).status == "ABERTA"

    with pytest.raises(services.AmountAboveBalance):
        services.receive_account(conta_of(reserva), D("70.01"), PIX, owner)

    services.receive_account(conta_of(reserva), D("70"), PIX, owner)
    conta = conta_of(reserva)
    assert conta.status == "PAGA"
    assert conta.pago_em is not None
    assert refresh(reserva).is_paid
    with pytest.raises(services.AccountNotOpen):
        services.receive_account(conta, D("1"), PIX, owner)


def test_editing_a_reservation_does_not_lose_what_was_paid(reserva, espaco, cliente, owner):
    with_register(owner)
    services.receive_account(conta_of(reserva), D("100"), PIX, owner)
    stale = Reserva.all_tenants.get(pk=reserva.pk)
    stale.valor_pago = D("0")  # cópia carregada antes do pagamento
    agenda_services.update_reservation(stale, espaco, cliente, at(10), at(11), D("120"))
    assert refresh(reserva).valor_pago == D("100")
    assert conta_of(reserva).status == "ABERTA"
    assert conta_of(reserva).saldo == D("20")


def test_receivable_description_does_not_carry_the_client_name(reserva, cliente):
    anonymize_client(cliente)
    assert cliente.nome.split()[0] not in conta_of(reserva).descricao


@pytest.mark.django_db(transaction=True)
def test_concurrent_payments_do_not_overpay():
    tenant = make_tenant("concorrencia-fin")
    espaco = make_espaco(tenant)
    reserva = agenda_services.create_reservation(espaco, make_cliente(tenant), at(10), at(11))
    usuarios = [cashier(tenant), with_register(make_user(tenant, "outro@x.test", "ATENDENTE"))]
    barrier = threading.Barrier(2)
    results = []

    def attempt(usuario):
        try:
            barrier.wait()
            services.receive_account(conta_of(reserva), D("100"), PIX, usuario)
            results.append("ok")
        except services.FinanceError:
            results.append("recusado")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=[usuario]) for usuario in usuarios]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["ok", "recusado"]
    assert conta_of(reserva).valor_pago == D("100")
    assert Lancamento.all_tenants.filter(reserva=reserva).count() == 1


# --- Reserva e comanda juntas


def test_charge_reservation_with_its_tab_in_one_go(tenant, reserva, owner):
    agua = make_produto(tenant, preco=D("5"))
    comanda = pdv_services.add_to_tab(tenant, reserva, {agua.pk: 4})
    with_register(owner)

    result = pdv_services.charge_reservation(reserva, D("100"), DINHEIRO, owner, recebido=D("150"))

    assert result["total"] == D("120")
    assert result["troco"] == D("30")
    assert refresh(comanda).status == Venda.Status.CONCLUIDA
    assert conta_of(reserva).status == "PAGA"
    origens = sorted(Lancamento.all_tenants.values_list("origem", flat=True))
    assert origens == ["RESERVA", "VENDA"]


def test_charge_only_the_tab(tenant, reserva, owner):
    agua = make_produto(tenant, preco=D("5"))
    pdv_services.add_to_tab(tenant, reserva, {agua.pk: 2})
    with_register(owner)
    result = pdv_services.charge_reservation(reserva, D("0"), PIX, owner)
    assert result["total"] == D("10")
    assert conta_of(reserva).valor_pago == 0


def test_cash_short_of_the_total_charges_nothing(tenant, reserva, owner):
    with_register(owner)
    with pytest.raises(pdv_services.InsufficientPayment):
        pdv_services.charge_reservation(reserva, D("100"), DINHEIRO, owner, recebido=D("50"))
    assert not Lancamento.all_tenants.exists()


# --- Vendas e estornos


def test_sale_enters_the_sellers_register_and_cancel_reverses_it(tenant, owner):
    agua = make_produto(tenant, preco=D("4"))
    vendedor = cashier(tenant)
    venda = pdv_services.complete_sale(tenant, {agua.pk: 2}, PIX, usuario=vendedor)
    assert refresh(venda).caixa == services.current_register(vendedor)
    assert Lancamento.all_tenants.get(venda=venda).valor == D("8")

    pdv_services.cancel_sale(venda, usuario=with_register(owner))

    estorno = Lancamento.all_tenants.get(origem="ESTORNO")
    assert estorno.caixa == services.current_register(owner)
    assert estorno.tipo == "SAIDA"
    assert services.register_summary(services.current_register(owner))["vendas"] == D("-8")


def test_sale_without_open_register_is_refused(tenant, owner):
    agua = make_produto(tenant)
    with pytest.raises(services.RegisterClosed):
        pdv_services.complete_sale(tenant, {agua.pk: 1}, PIX, usuario=owner)
    assert refresh(agua).estoque_atual == 10
    assert not Venda.all_tenants.exists()


def test_reverse_reopens_the_account(reserva, owner):
    with_register(owner)
    lancamento = services.receive_account(conta_of(reserva), D("100"), PIX, owner)
    services.reverse_entry(lancamento, owner, "Devolvido")
    assert conta_of(reserva).status == "ABERTA"
    assert refresh(reserva).valor_pago == 0
    with pytest.raises(services.CannotReverse):
        services.reverse_entry(refresh(lancamento), owner)


def test_sale_income_is_not_reversed_by_hand(tenant, owner):
    agua = make_produto(tenant)
    venda = pdv_services.complete_sale(tenant, {agua.pk: 1}, PIX, usuario=with_register(owner))
    with pytest.raises(services.CannotReverse):
        services.reverse_entry(Lancamento.all_tenants.get(venda=venda), owner)


# --- Contas a pagar


def bill(tenant, valor="300", vencimento=DAY, **fields):
    return ContaPagar.all_tenants.create(
        estabelecimento=tenant,
        descricao="Energia",
        categoria="ENERGIA",
        valor=D(valor),
        vencimento=vencimento,
        **fields
    )


def test_pay_bill_from_register_or_from_the_bank(tenant, owner):
    caixa = services.open_register(owner, D("500"))
    services.pay_bill(bill(tenant), DINHEIRO, owner)
    assert services.register_summary(caixa)["dinheiro_esperado"] == D("200")

    banco = services.pay_bill(bill(tenant, "80"), PIX, owner, from_register=False)
    assert banco.status == "PAGA"
    assert not Lancamento.all_tenants.filter(conta_pagar=banco).exists()

    with pytest.raises(services.NotEnoughCash):
        services.pay_bill(bill(tenant, "999"), DINHEIRO, owner)


def test_cancel_account_rules(tenant, owner, reserva):
    with pytest.raises(services.AccountLocked):
        services.cancel_account(conta_of(reserva))
    conta = bill(tenant)
    assert services.cancel_account(conta).status == "CANCELADA"


# --- Recorrência


@pytest.mark.parametrize(
    ("base", "recorrencia", "step", "expected"),
    [
        (date(2031, 1, 31), "MENSAL", 1, date(2031, 2, 28)),
        (date(2031, 1, 31), "MENSAL", 2, date(2031, 3, 31)),
        (date(2032, 2, 29), "ANUAL", 1, date(2033, 2, 28)),
        (date(2031, 3, 4), "SEMANAL", 2, date(2031, 3, 18)),
        (date(2031, 11, 15), "MENSAL", 2, date(2032, 1, 15)),
    ],
)
def test_next_due_date(base, recorrencia, step, expected):
    assert services.next_due_date(base, recorrencia, step) == expected


def test_recurring_bills_are_created_ahead_and_never_duplicated(tenant):
    origem = bill(tenant, vencimento=date(2031, 1, 10), recorrencia="MENSAL")
    created = services.generate_recurring_accounts(tenant, today=date(2031, 3, 1))
    datas = sorted(ContaPagar.all_tenants.exclude(pk=origem.pk).values_list("vencimento", flat=True))
    assert datas == [date(2031, 2, 10), date(2031, 3, 10)]
    assert created == 2
    assert services.generate_recurring_accounts(tenant, today=date(2031, 3, 1)) == 0


def test_stop_repeating(tenant):
    origem = bill(tenant, vencimento=date(2031, 1, 10), recorrencia="MENSAL")
    services.generate_recurring_accounts(tenant, today=date(2031, 1, 20))
    filha = ContaPagar.all_tenants.get(recorrencia_origem=origem)
    services.cancel_account(filha, stop_repeating=True)
    assert services.generate_recurring_accounts(tenant, today=date(2031, 6, 1)) == 0


# --- Fase 3 pronta quando: o fechamento bate com as reservas e as vendas do dia


def test_closing_matches_the_days_reservations_and_sales(tenant, espaco, cliente, owner):
    agua = make_produto(tenant, preco=D("5"))
    caixa = services.open_register(owner, D("100"))
    primeira = agenda_services.create_reservation(espaco, cliente, at(9), at(10))
    segunda = agenda_services.create_reservation(espaco, cliente, at(18), at(19))
    pdv_services.add_to_tab(tenant, segunda, {agua.pk: 4})

    services.receive_account(conta_of(primeira), D("100"), PIX, owner)
    pdv_services.complete_sale(tenant, {agua.pk: 2}, DINHEIRO, usuario=owner)
    pdv_services.charge_reservation(segunda, D("100"), DINHEIRO, owner)
    cancelada = pdv_services.complete_sale(tenant, {agua.pk: 1}, PIX, usuario=owner)
    pdv_services.cancel_sale(cancelada, usuario=owner)

    summary = services.register_summary(caixa)
    assert summary["reservas"] == D("200")
    assert summary["vendas"] == D("30")  # 10 no balcão + 20 da comanda; a cancelada sai
    assert summary["recebido"] == D("230")
    formas = {row["forma"]: row["total"] for row in summary["por_forma"]}
    assert formas == {"PIX": D("100"), "DINHEIRO": D("130")}

    caixa = services.close_register(caixa, D("230"), owner)
    assert caixa.saldo_esperado == D("230")  # 100 de troco + 130 em dinheiro
    assert caixa.diferenca == 0


# --- Relatório


def test_report_counts_income_minus_reversals_by_form_and_space(tenant, espaco, cliente, owner):
    today = timezone.localdate()
    with_register(owner)
    reserva = agenda_services.create_reservation(espaco, cliente, at(10, day=today), at(11, day=today))
    services.receive_account(conta_of(reserva), D("100"), PIX, owner)
    agua = make_produto(tenant, preco=D("5"))
    venda = pdv_services.complete_sale(tenant, {agua.pk: 2}, DINHEIRO, usuario=owner)
    pdv_services.cancel_sale(venda, usuario=owner)
    services.pay_bill(bill(tenant, "40"), PIX, owner, from_register=False)
    services.move_cash(owner, entra=True, valor=D("50"))

    report = revenue_report(tenant, today, today)

    assert report["faturamento"] == D("100")
    assert report["despesas"] == D("40")
    assert report["resultado"] == D("60")
    assert [(row["label"], row["total"]) for row in report["por_forma"]] == [("Pix", D("100"))]
    assert [(row["label"], row["total"]) for row in report["por_espaco"]] == [(espaco.nome, D("100"))]
    assert report["series"][-1]["height"] == "100.00"


def test_report_lists_overdue_receivables(tenant, espaco, cliente):
    past = timezone.localdate() - timedelta(days=3)
    agenda_services.create_reservation(espaco, cliente, at(10, day=past), at(11, day=past))
    report = revenue_report(tenant, past, timezone.localdate())
    assert report["inadimplencia"] == D("100")
    assert report["atrasadas_count"] == 1


# --- Telas e permissões


def test_open_move_and_close_through_the_screens(owner_client, owner):
    assert (
        owner_client.post(reverse("financeiro:abrir"), {"saldo_inicial": "50,00"}, headers=HX).status_code
        == 204
    )
    caixa = services.current_register(owner)
    data = {"tipo": "SAI", "valor": "10,00", "descricao": "Gelo"}
    assert owner_client.post(reverse("financeiro:movimento"), data, headers=HX).status_code == 204
    page = owner_client.get(reverse("financeiro:caixa")).content.decode()
    assert "Gelo" in page

    response = owner_client.post(
        reverse("financeiro:fechar", args=[caixa.pk]),
        {"saldo_conferido": "40,00", "observacao": ""},
        headers=HX,
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == reverse("financeiro:caixa_detail", args=[caixa.pk])
    assert refresh(caixa).diferenca == 0


def test_attendant_counts_cash_without_seeing_the_expected_amount(attendant, owner):
    from django.test import Client

    attendant_client, manager_client = Client(), Client()
    attendant_client.force_login(attendant)
    manager_client.force_login(owner)
    caixa = services.open_register(attendant, D("100"))
    url = reverse("financeiro:fechar", args=[caixa.pk])
    attendant_modal = attendant_client.get(url, headers=HX).content.decode()
    assert "Esperado" not in attendant_modal
    manager_modal = manager_client.get(
        reverse("financeiro:fechar", args=[caixa.pk]), headers=HX
    ).content.decode()
    assert "Esperado" in manager_modal


def test_attendant_cannot_close_someone_elses_register(client, attendant, owner):
    caixa = services.open_register(owner)
    client.force_login(attendant)
    assert client.get(reverse("financeiro:fechar", args=[caixa.pk]), headers=HX).status_code == 403
    assert client.get(reverse("financeiro:caixa_detail", args=[caixa.pk])).status_code == 404


def test_attendant_uses_the_register_but_not_accounts_or_reports(client, attendant):
    client.force_login(attendant)
    assert client.get(reverse("financeiro:caixa")).status_code == 200
    for name in ["financeiro:receber", "financeiro:pagar", "financeiro:caixas", "relatorios:relatorio"]:
        assert client.get(reverse(name)).status_code == 403


def test_receive_reservation_screen(owner_client, owner, reserva):
    url = reverse("financeiro:receber_reserva", args=[reserva.pk])
    assert "abra o seu caixa" in owner_client.get(url, headers=HX).content.decode()
    with_register(owner)
    data = {"valor": "100,00", "forma": "DINHEIRO", "recebido": "120,00"}
    response = owner_client.post(url, data, headers=HX)
    assert response.status_code == 204
    assert "Troco: R$ 20,00" in response.headers["HX-Trigger"].encode().decode("unicode_escape")
    assert refresh(reserva).is_paid


def test_account_screens(owner_client, tenant, owner):
    data = {
        "descricao": "Aluguel",
        "fornecedor": "Imobiliária",
        "categoria": "ALUGUEL",
        "valor": "1.500,00",
        "vencimento": DAY.isoformat(),
        "recorrencia": "MENSAL",
        "observacoes": "",
    }
    assert owner_client.post(reverse("financeiro:pagar_create"), data).status_code == 302
    conta = ContaPagar.all_tenants.get(descricao="Aluguel")
    assert conta.valor == D("1500")
    assert conta.criado_por == owner
    assert "Aluguel" in owner_client.get(reverse("financeiro:pagar")).content.decode()
    response = owner_client.post(
        reverse("financeiro:pagar_baixa", args=[conta.pk]), {"forma": "PIX"}, headers=HX
    )
    assert response.status_code == 204
    assert refresh(conta).status == ContaBase.Status.PAGA


def test_stock_purchase_can_create_a_bill(owner_client, tenant):
    produto = make_produto(tenant)
    data = {
        "tipo": "ENTRADA",
        "quantidade": 12,
        "custo": "2,50",
        "observacao": "",
        "gerar_conta": "on",
        "fornecedor": "Distribuidora",
        "vencimento": DAY.isoformat(),
    }
    response = owner_client.post(reverse("estoque:movimentar", args=[produto.pk]), data, headers=HX)
    assert response.status_code == 204
    conta = ContaPagar.all_tenants.get()
    assert (conta.valor, conta.fornecedor, conta.categoria) == (D("30"), "Distribuidora", "FORNECEDOR")


def test_finance_is_isolated_between_establishments(owner_client, other_tenant):
    outro = make_user(other_tenant, "dono@b.test")
    caixa = services.open_register(outro)
    espaco = make_espaco(other_tenant, "Quadra alheia")
    reserva = agenda_services.create_reservation(
        espaco, make_cliente(other_tenant, "Cliente Alheio", "+5511977770000"), at(10), at(11)
    )
    lancamento = services.receive_account(conta_of(reserva), D("100"), PIX, outro)
    conta = bill(other_tenant)

    assert owner_client.get(reverse("financeiro:caixa_detail", args=[caixa.pk])).status_code == 404
    assert owner_client.get(reverse("financeiro:fechar", args=[caixa.pk]), headers=HX).status_code == 404
    assert (
        owner_client.get(reverse("financeiro:estornar", args=[lancamento.pk]), headers=HX).status_code == 404
    )
    assert (
        owner_client.get(reverse("financeiro:receber_reserva", args=[reserva.pk]), headers=HX).status_code
        == 404
    )
    assert owner_client.get(reverse("financeiro:pagar_baixa", args=[conta.pk]), headers=HX).status_code == 404
    for url in [reverse("financeiro:receber"), reverse("financeiro:pagar"), reverse("financeiro:caixas")]:
        content = owner_client.get(url).content.decode()
        assert "alheia" not in content.lower() and "Energia" not in content
    assert (
        revenue_report(owner_client.get(reverse("financeiro:caixa")).wsgi_request.tenant, DAY, DAY)[
            "faturamento"
        ]
        == 0
    )
    assert Caixa.all_tenants.filter(estabelecimento=other_tenant).count() == 1


def test_migration_creates_accounts_for_existing_reservations(reserva):
    ContaReceber.all_tenants.filter(reserva=reserva).delete()
    from django.db.migrations.executor import MigrationExecutor

    migration = importlib.import_module("apps.financeiro.migrations.0002_contas_das_reservas")
    # Como na migração de verdade: modelos históricos, sem o filtro por estabelecimento.
    state = MigrationExecutor(connection).loader.project_state(("financeiro", "0002_contas_das_reservas"))
    migration.create_reservation_accounts(state.apps, None)
    conta = conta_of(reserva)
    assert (conta.valor, conta.status, conta.vencimento) == (D("100"), "ABERTA", DAY)


def test_money_fields_accept_brazilian_thousands():
    from apps.espacos.forms import MoneyField

    field = MoneyField(max_digits=9, decimal_places=2, localize=True)
    for raw in ["1.500,00", "1500,00", "1500.00", "R$ 1.500", "1.500"]:
        assert field.clean(raw) == D("1500"), raw
    assert field.clean("4,50") == D("4.50")
    assert field.clean("4.5") == D("4.5")


def test_negative_amounts_are_formatted_like_the_screen():
    from apps.estabelecimentos.templatetags.ui import brl

    assert brl(D("-140")) == "-R$ 140,00"
    assert brl(D("1500.5")) == "R$ 1.500,50"
