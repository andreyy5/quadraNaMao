from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.agenda.models import Reserva
from apps.agenda.services import _split_by_hour
from apps.clientes.services import anonymize_client
from apps.financeiro import services as fin
from apps.financeiro.models import Caixa, ContaPagar, ContaReceber, FormaPagamento, Lancamento
from apps.pdv import services as pdv_services
from apps.relatorios import services as rel
from conftest import DAY, at, make_cliente, make_espaco, make_produto, with_register

D = Decimal
PIX, DINHEIRO = FormaPagamento.PIX, FormaPagamento.DINHEIRO


def today():
    return timezone.localdate()


def conta_of(reserva):
    return ContaReceber.all_tenants.get(reserva=reserva)


def bill(tenant, valor, vencimento=None, categoria="ENERGIA", descricao="Conta"):
    return ContaPagar.all_tenants.create(
        estabelecimento=tenant,
        descricao=descricao,
        categoria=categoria,
        valor=D(valor),
        vencimento=vencimento or today(),
    )


def book(espaco, cliente, hour=10, day=None, **kwargs):
    day = day or today()
    return agenda_services.create_reservation(
        espaco, cliente, at(hour, day=day), at(hour + 1, day=day), **kwargs
    )


# --- Fluxo de caixa


def test_cashflow_separates_income_refunds_bills_and_drawer_moves(tenant, espaco, cliente, owner):
    with_register(owner)
    reserva = book(espaco, cliente)
    recebimento = fin.receive_account(conta_of(reserva), D("100"), PIX, owner)
    agua = make_produto(tenant, preco=D("5"))
    pdv_services.complete_sale(tenant, {agua.pk: 2}, DINHEIRO, usuario=owner)
    fin.pay_bill(bill(tenant, "40"), PIX, owner, from_register=False)
    fin.move_cash(owner, entra=True, valor=D("50"))
    fin.reverse_entry(recebimento, owner, "Cliente desistiu")

    report = rel.cashflow_report(tenant, today(), today())

    assert report["entradas"] == D("110")
    assert report["saidas"] == D("140")
    assert report["saldo"] == D("-30")
    assert {row["label"]: row["total"] for row in report["por_origem"]} == {
        "Reserva": D("100"),
        "Venda": D("10"),
    }
    assert {row["label"]: row["total"] for row in report["por_categoria"]} == {
        "Devoluções a clientes": D("100"),
        "Energia": D("40"),
    }
    assert report["gaveta_colocado"] == D("50")
    day = report["series"][-1]
    assert (day["entradas"], day["saidas"], day["acumulado"]) == (D("110"), D("140"), D("-30"))


def test_bill_paid_at_the_register_reversed_and_then_paid_at_the_bank_counts_once(tenant, owner):
    with_register(owner)
    fin.move_cash(owner, entra=True, valor=D("100"))
    conta = bill(tenant, "80", categoria="ALUGUEL")
    fin.pay_bill(conta, DINHEIRO, owner)
    pagamento = Lancamento.all_tenants.get(origem=Lancamento.Origem.CONTA_PAGAR)
    fin.reverse_entry(pagamento, owner)
    fin.pay_bill(ContaPagar.all_tenants.get(pk=conta.pk), PIX, owner, from_register=False)

    assert rel.cashflow_report(tenant, today(), today())["saidas"] == D("80")
    assert rel.money_totals(tenant, today(), today())["despesas"] == D("80")


def test_forecast_uses_open_receivables_and_bills_by_week(tenant, espaco, cliente):
    book(espaco, cliente, day=today() + timedelta(days=2))
    book(espaco, cliente, day=today() - timedelta(days=3))
    bill(tenant, "300", vencimento=today() + timedelta(days=9))
    bill(tenant, "45", vencimento=today() - timedelta(days=1))
    bill(tenant, "999", vencimento=today() + timedelta(days=40))

    previsto = rel.forecast(tenant, today())

    assert (previsto["receber"], previsto["pagar"], previsto["saldo"]) == (D("100"), D("300"), D("-200"))
    assert (previsto["atrasado_receber"], previsto["atrasado_pagar"]) == (D("100"), D("45"))
    assert [w["acumulado"] for w in previsto["semanas"]][:2] == [D("100"), D("-200")]
    assert previsto["semanas"][-1]["last"] == today() + timedelta(days=29)
    assert [c.valor for c in previsto["proximas_contas"]] == [D("300")]


# --- Visão geral


def test_overview_compares_with_the_previous_period(tenant, espaco, cliente, owner):
    with_register(owner)
    reserva = book(espaco, cliente)
    fin.receive_account(conta_of(reserva), D("100"), PIX, owner)
    Lancamento.all_tenants.update(criado_em=timezone.now() - timedelta(days=1))
    reserva2 = book(espaco, cliente, hour=12)
    fin.receive_account(conta_of(reserva2), D("100"), PIX, owner)
    fin.receive_account(conta_of(book(espaco, cliente, hour=14)), D("50"), PIX, owner)

    report = rel.overview_report(tenant, today(), today())
    kpis = {item["label"]: item for item in report["kpis"]}

    assert kpis["Faturamento"]["value"] == D("150")
    assert (kpis["Faturamento"]["delta"], kpis["Faturamento"]["good"]) == (50, True)
    assert kpis["Reservas"]["value"] == 3
    assert report["previous"] == (today() - timedelta(days=1), today() - timedelta(days=1))


def test_delta_signs_follow_whether_up_is_good():
    assert rel.kpi("Contas pagas", D("120"), D("100"), up_is_good=False)["good"] is False
    assert rel.kpi("Faturamento", D("80"), D("100"))["delta"] == -20
    assert rel.kpi("Faturamento", D("80"), D("0"))["delta"] is None


# --- Reservas


def test_bookings_report_numbers_and_heatmap(tenant, espaco, cliente):
    book(espaco, cliente, 10, day=DAY)
    book(espaco, cliente, 12, day=DAY, origem=Reserva.Origem.ONLINE, modalidade="Beach tênis")
    agenda_services.mark_no_show(book(espaco, cliente, 14, day=DAY))
    agenda_services.cancel_reservation(book(espaco, cliente, 16, day=DAY))

    report = rel.bookings_report(tenant, DAY, DAY)
    kpis = {item["label"]: item["value"] for item in report["kpis"]}

    assert kpis["Reservas"] == 3
    assert kpis["Horas vendidas"] == D("3.0")
    assert kpis["Cancelamentos"] == 25  # 1 de 4
    assert kpis["Não compareceu"] == 33  # 1 de 3
    assert kpis["Ocupação"] == 21  # 3 de 14 horas abertas
    assert {row["label"]: row["total"] for row in report["por_origem"]} == {
        "Painel": 2,
        "Link público": 1,
    }
    assert [row["label"] for row in report["por_modalidade"]] == ["Beach tênis"]
    terca = report["heatmap"]["rows"][DAY.weekday()]
    by_hour = {cell["hour"]: cell["share"] for cell in terca["cells"]}
    assert (by_hour[10], by_hour[11], by_hour[16]) == (100, 0, 0)
    quarta = report["heatmap"]["rows"][(DAY.weekday() + 1) % 7]
    assert all(cell["share"] is None for cell in quarta["cells"])  # fora do período: sem horas abertas


def test_split_by_hour_handles_partial_hours_and_midnight():
    midnight = at(0)
    assert list(_split_by_hour(at(9, 30), at(11), midnight)) == [(9, 30.0), (10, 60.0)]
    late = list(_split_by_hour(at(23, 30), at(23, 30) + timedelta(hours=1), midnight))
    assert late == [(23, 30.0), (24, 30.0)]


# --- Clientes


def test_clients_report_top_new_lost_and_debtors(tenant, espaco, cliente):
    habitual = make_cliente(tenant, "Habitual", "+5511977770001")
    for weeks in (8, 9, 10):
        book(espaco, habitual, day=today() - timedelta(weeks=weeks))
    novo = make_cliente(tenant, "Novo", "+5511977770002")
    book(espaco, novo, 8)
    book(espaco, cliente, 10)
    book(espaco, cliente, 12)
    book(espaco, cliente, 14, day=today() - timedelta(days=60))
    anonimo = make_cliente(tenant, "Apagado", "+5511977770003")
    book(espaco, anonimo, 16)
    anonymize_client(anonimo)

    report = rel.clients_report(tenant, today(), today())
    kpis = {item["label"]: item["value"] for item in report["kpis"]}

    assert [row["cliente"] for row in report["top"]] == [cliente, novo]
    assert (kpis["Clientes que jogaram"], kpis["Clientes novos"], kpis["Voltaram mais de uma vez"]) == (
        2,
        1,
        1,
    )
    assert [row["cliente"] for row in report["sumidos"]] == [habitual]
    devedores = {row["cliente"]: row["valor"] for row in report["devedores"]}
    assert devedores == {habitual: D("300"), cliente: D("100")}


# --- Vendas


def test_sales_report_margin_and_cancellations(tenant, owner):
    with_register(owner)
    agua = make_produto(tenant, "Água", preco=D("5"), custo=D("2"))
    bola = make_produto(tenant, "Aluguel de bola", preco=D("10"), estoque=None)
    pdv_services.complete_sale(tenant, {agua.pk: 4, bola.pk: 1}, PIX, usuario=owner)
    cancelada = pdv_services.complete_sale(tenant, {agua.pk: 1}, DINHEIRO, usuario=owner)
    pdv_services.cancel_sale(cancelada, usuario=owner)

    report = rel.sales_report(tenant, today(), today())
    kpis = {item["label"]: item for item in report["kpis"]}

    assert kpis["Vendido no PDV"]["value"] == D("30")
    assert kpis["Vendas"]["value"] == 1
    assert kpis["Margem estimada"]["value"] == D("12")  # só a água tem custo: 4 × (5 - 2)
    assert kpis["Vendas canceladas"]["value"] == D("5")
    produtos = {p["nome"]: p for p in report["produtos"]}
    assert (produtos["Água"]["quantidade"], produtos["Água"]["margem_pct"]) == (4, 60)
    assert produtos["Aluguel de bola"]["margem"] is None


# --- Caixas


def test_registers_report_differences_and_forgotten_registers(tenant, espaco, cliente, owner, attendant):
    with_register(owner)
    fin.move_cash(owner, entra=True, valor=D("100"))
    fin.receive_account(conta_of(book(espaco, cliente)), D("100"), DINHEIRO, owner)
    caixa = fin.current_register(owner)
    fin.close_register(caixa, D("190"), owner, "Faltou troco")
    with_register(attendant)
    Caixa.all_tenants.filter(operador=attendant).update(criado_em=timezone.now() - timedelta(days=2))

    report = rel.registers_report(tenant, today(), today())
    kpis = {item["label"]: item["value"] for item in report["kpis"]}

    assert (kpis["Caixas fechados"], kpis["Com diferença"], kpis["Faltas"], kpis["Sobras"]) == (
        1,
        1,
        D("10"),
        0,
    )
    assert report["fechados"][0].recebido == D("100")
    assert report["por_operador"][0]["diferenca"] == D("-10")
    assert [(c.operador, c.antigo) for c in report["abertos"]] == [(attendant, True)]


# --- Telas


TABS = ["relatorio", "fluxo", "reservas", "clientes", "vendas", "caixas"]


@pytest.mark.parametrize("tab", TABS)
def test_every_tab_renders_and_exports(owner_client, tenant, espaco, cliente, owner, tab):
    with_register(owner)
    fin.receive_account(conta_of(book(espaco, cliente)), D("100"), PIX, owner)
    url = reverse(f"relatorios:{tab}")
    page = owner_client.get(url, {"periodo": "30"})
    assert page.status_code == 200
    assert 'aria-current="page"' in page.content.decode()

    export = owner_client.get(url, {"periodo": "30", "formato": "csv"})
    assert export["Content-Type"].startswith("text/csv")
    assert "attachment" in export["Content-Disposition"]
    content = export.content.decode("utf-8")
    assert content.startswith("﻿") and ";" in content.splitlines()[0]


def test_csv_uses_brazilian_number_and_date_format(owner_client, tenant, espaco, cliente, owner):
    with_register(owner)
    fin.receive_account(conta_of(book(espaco, cliente)), D("100"), PIX, owner)
    content = owner_client.get(
        reverse("relatorios:fluxo"), {"periodo": "7", "formato": "csv"}
    ).content.decode()
    assert f"{today():%d/%m/%Y};100,00;0,00;100,00;100,00" in content


def test_attendant_has_no_reports(client, attendant):
    client.force_login(attendant)
    for tab in TABS:
        assert client.get(reverse(f"relatorios:{tab}")).status_code == 403
    assert reverse("relatorios:relatorio") not in client.get(reverse("relatorios:dashboard")).content.decode()


def test_reports_only_see_their_own_establishment(owner_client, tenant, other_tenant):
    alheio = make_espaco(other_tenant, "Quadra alheia")
    estranho = make_cliente(other_tenant, "Cliente Alheio", "+5511977770000")
    book(alheio, estranho)
    for tab in ["relatorio", "reservas", "clientes"]:
        content = owner_client.get(reverse(f"relatorios:{tab}"), {"periodo": "7"}).content.decode()
        assert "Cliente Alheio" not in content and "Quadra alheia" not in content


def test_period_presets_and_custom_range(owner_client):
    response = owner_client.get(reverse("relatorios:relatorio"), {"periodo": "ano"})
    assert response.context["first"] == today().replace(month=1, day=1)
    custom = owner_client.get(reverse("relatorios:fluxo"), {"de": "2031-03-10", "ate": "2031-03-01"})
    assert (str(custom.context["first"]), str(custom.context["last"])) == ("2031-03-01", "2031-03-10")
    longo = owner_client.get(reverse("relatorios:reservas"), {"de": "2028-01-01", "ate": "2031-03-01"})
    assert (longo.context["last"] - longo.context["first"]).days == rel.MAX_REPORT_DAYS - 1
    assert longo.context["report"]["ocupacao_desde"] is not None


# --- Conferência do caixa


def test_reservation_value_cannot_drop_below_what_was_received(tenant, espaco, cliente, owner):
    with_register(owner)
    reserva = book(espaco, cliente)
    fin.receive_account(conta_of(reserva), D("100"), PIX, owner)
    with pytest.raises(agenda_services.BelowAmountPaid, match="100,00 recebidos"):
        agenda_services.update_reservation(reserva, espaco, cliente, reserva.inicio, reserva.fim, D("80"))
    agenda_services.update_reservation(reserva, espaco, cliente, reserva.inicio, reserva.fim, D("100"))


def test_online_register_closes_against_the_bank_statement(owner_client, tenant, espaco, cliente):
    caixa = fin.online_register(tenant)
    fin.receive_account(conta_of(book(espaco, cliente)), D("30"), PIX, None, caixa=caixa)
    form = owner_client.get(reverse("financeiro:fechar", args=[caixa.pk]), headers={"HX-Request": "true"})
    assert "saldo_conferido" not in form.content.decode()
    assert "extrato" in form.content.decode()
    response = owner_client.post(
        reverse("financeiro:fechar", args=[caixa.pk]),
        {"observacao": "Conferido"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code in (200, 204)
    caixa.refresh_from_db()
    assert (caixa.is_open, caixa.diferenca, caixa.saldo_conferido) == (False, D("0"), D("0"))
    assert fin.online_register(tenant).pk != caixa.pk  # o próximo Pix abre outro


def test_dashboard_warns_about_registers_left_open(owner_client, client, owner, attendant):
    with_register(attendant)
    Caixa.all_tenants.filter(operador=attendant).update(criado_em=timezone.now() - timedelta(days=1, hours=1))
    assert "aberto desde outro dia" in owner_client.get(reverse("relatorios:dashboard")).content.decode()
    client.force_login(attendant)
    assert "aberto desde outro dia" not in client.get(reverse("relatorios:dashboard")).content.decode()


def test_register_closings_and_reports_tell_the_same_story(tenant, espaco, cliente, owner, attendant):
    """O que os caixas dizem que receberam é o que os relatórios mostram, com estornos e Pix online."""
    with_register(owner)
    with_register(attendant)
    fin.move_cash(owner, entra=True, valor=D("200"))
    fin.receive_account(conta_of(book(espaco, cliente, 8)), D("100"), DINHEIRO, owner)
    parcial = fin.receive_account(conta_of(book(espaco, cliente, 10)), D("40"), PIX, attendant)
    agua = make_produto(tenant, preco=D("6"))
    pdv_services.complete_sale(tenant, {agua.pk: 3}, DINHEIRO, usuario=attendant)
    fin.receive_account(
        conta_of(book(espaco, cliente, 12)), D("30"), PIX, None, caixa=fin.online_register(tenant)
    )
    fin.reverse_entry(parcial, owner, "Lançado no cliente errado")
    fin.pay_bill(bill(tenant, "50"), DINHEIRO, owner)

    caixas = Caixa.all_tenants.filter(estabelecimento=tenant)
    recebido = sum((fin.register_summary(caixa)["recebido"] for caixa in caixas), D("0"))
    contas = sum((fin.register_summary(caixa)["contas_pagar"] for caixa in caixas), D("0"))
    fluxo = rel.cashflow_report(tenant, today(), today())
    geral = rel.revenue_report(tenant, today(), today())

    assert recebido == geral["faturamento"] == D("148")  # 100 + 40 + 18 + 30 - 40
    assert fluxo["entradas"] - fluxo["saidas"] == recebido + contas == D("98")
    assert -contas == geral["despesas"] == D("50")
    dinheiro_owner = fin.register_summary(fin.current_register(owner))["dinheiro_esperado"]
    assert dinheiro_owner == D("250")  # 200 colocados + 100 recebidos - 50 da conta
