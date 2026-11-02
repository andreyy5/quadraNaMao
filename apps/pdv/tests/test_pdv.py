import json
import threading
from decimal import Decimal

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.estoque.models import MovimentacaoEstoque, Produto
from apps.estoque.services import InsufficientStock
from apps.pdv import services
from apps.pdv.models import ItemVenda, Venda
from conftest import HX, at, make_cliente, make_espaco, make_produto, make_tenant, make_user

PIX = Venda.Forma.PIX


def stock(produto):
    return Produto.all_tenants.get(pk=produto.pk).estoque_atual


def items_of(venda):
    return list(ItemVenda.all_tenants.filter(venda=venda))


@pytest.fixture
def reserva(espaco, cliente):
    return agenda_services.create_reservation(espaco, cliente, at(10), at(11))


def test_sale_lowers_stock_and_uses_the_registered_price(tenant, owner):
    agua = make_produto(tenant, nome="Água", preco=Decimal("4"), estoque=10)
    refri = make_produto(tenant, nome="Refri", preco=Decimal("6.50"), estoque=5)

    venda = services.complete_sale(tenant, {agua.pk: 2, refri.pk: 1}, PIX, usuario=owner)

    assert venda.status == Venda.Status.CONCLUIDA
    assert venda.total == Decimal("14.50")
    assert venda.concluida_em is not None
    assert stock(agua) == 8
    assert stock(refri) == 4
    mov = MovimentacaoEstoque.all_tenants.get(produto=agua, tipo="SAIDA")
    assert (mov.tipo, mov.origem, mov.quantidade, mov.saldo_apos) == ("SAIDA", "VENDA", -2, 8)
    assert mov.referencia == f"Venda #{venda.numero}"


def test_item_keeps_the_price_of_the_moment_of_sale(tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    venda = services.complete_sale(tenant, {agua.pk: 1}, PIX)
    Produto.all_tenants.filter(pk=agua.pk).update(preco_venda=Decimal("9"))
    assert items_of(venda)[0].preco_unitario == Decimal("4")


def test_sale_without_enough_stock_saves_nothing(tenant):
    agua = make_produto(tenant, nome="Água", estoque=10)
    refri = make_produto(tenant, nome="Refri", estoque=1)

    with pytest.raises(InsufficientStock):
        services.complete_sale(tenant, {agua.pk: 2, refri.pk: 3}, PIX)

    assert stock(agua) == 10
    assert stock(refri) == 1
    assert not Venda.all_tenants.exists()
    assert not MovimentacaoEstoque.all_tenants.filter(tipo="SAIDA").exists()


def test_sale_goes_through_when_negative_stock_is_allowed(tenant):
    tenant.permite_estoque_negativo = True
    tenant.save()
    agua = make_produto(tenant, estoque=1)
    services.complete_sale(tenant, {agua.pk: 3}, PIX)
    assert stock(agua) == -2


def test_unstocked_product_sells_without_movement(tenant):
    bola = make_produto(tenant, nome="Aluguel de bola", estoque=None)
    services.complete_sale(tenant, {bola.pk: 2}, PIX)
    assert stock(bola) == 0
    assert not MovimentacaoEstoque.all_tenants.filter(produto=bola).exists()


def test_empty_cart_and_unavailable_product_are_rejected(tenant, other_tenant):
    with pytest.raises(services.EmptyCart):
        services.complete_sale(tenant, {}, PIX)
    inativo = make_produto(tenant, nome="Inativo", ativo=False)
    with pytest.raises(services.ProductUnavailable):
        services.complete_sale(tenant, {inativo.pk: 1}, PIX)
    alheio = make_produto(other_tenant, nome="Alheio")
    with pytest.raises(services.ProductUnavailable):
        services.complete_sale(tenant, {alheio.pk: 1}, PIX)
    assert stock(alheio) == 10


def test_absurd_quantity_is_rejected(tenant):
    bola = make_produto(tenant, nome="Aluguel", estoque=None)
    with pytest.raises(services.InvalidCartQuantity):
        services.complete_sale(tenant, {bola.pk: 10**12}, PIX)
    assert not Venda.all_tenants.exists()


def test_changed_price_is_not_charged_silently(tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    with pytest.raises(services.PriceChanged):
        services.complete_sale(tenant, {agua.pk: 1}, PIX, total_esperado=Decimal("3.50"))
    assert services.complete_sale(tenant, {agua.pk: 1}, PIX, total_esperado=Decimal("4.00")).pk


def test_cash_records_the_change(tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    venda = services.complete_sale(tenant, {agua.pk: 1}, Venda.Forma.DINHEIRO, recebido=Decimal("10"))
    assert venda.valor_recebido == Decimal("10")
    assert venda.troco == Decimal("6")


def test_cash_below_the_total_cancels_everything(tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    with pytest.raises(services.InsufficientPayment):
        services.complete_sale(tenant, {agua.pk: 1}, Venda.Forma.DINHEIRO, recebido=Decimal("1"))
    assert stock(agua) == 10
    assert not Venda.all_tenants.exists()


def test_numbers_are_sequential_per_establishment(tenant, other_tenant):
    agua = make_produto(tenant)
    outra = make_produto(other_tenant)
    assert services.complete_sale(tenant, {agua.pk: 1}, PIX).numero == 1
    assert services.complete_sale(tenant, {agua.pk: 1}, PIX).numero == 2
    assert services.complete_sale(other_tenant, {outra.pk: 1}, PIX).numero == 1


def test_tab_lowers_stock_now_and_is_paid_later(tenant, reserva):
    agua = make_produto(tenant, preco=Decimal("4"))
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 2})
    assert venda.status == Venda.Status.ABERTA
    assert venda.cliente == reserva.cliente
    assert venda.concluida_em is None
    assert stock(agua) == 8

    venda = services.close_tab(venda, PIX)
    assert venda.status == Venda.Status.CONCLUIDA
    assert venda.forma_pagamento == PIX
    assert venda.concluida_em is not None
    with pytest.raises(services.SaleClosed):
        services.close_tab(venda, PIX)


def test_new_consumption_goes_to_the_same_tab(tenant, reserva):
    agua = make_produto(tenant, nome="Água", preco=Decimal("4"))
    refri = make_produto(tenant, nome="Refri", preco=Decimal("6"))
    primeira = services.add_to_tab(tenant, reserva, {agua.pk: 1})
    segunda = services.add_to_tab(tenant, reserva, {agua.pk: 2, refri.pk: 1})
    assert primeira.pk == segunda.pk
    assert segunda.total == Decimal("18")
    assert {(i.produto_id, i.quantidade) for i in items_of(segunda)} == {(agua.pk, 3), (refri.pk, 1)}


def test_tab_keeps_separate_lines_when_the_price_changes(tenant, reserva):
    agua = make_produto(tenant, preco=Decimal("4"))
    services.add_to_tab(tenant, reserva, {agua.pk: 1})
    Produto.all_tenants.filter(pk=agua.pk).update(preco_venda=Decimal("5"))
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 1})
    assert venda.total == Decimal("9")
    assert len(items_of(venda)) == 2


def test_cancelled_reservation_does_not_receive_consumption(tenant, reserva):
    agua = make_produto(tenant)
    agenda_services.cancel_reservation(reserva)
    reserva.refresh_from_db()
    with pytest.raises(services.InvalidReservation):
        services.add_to_tab(tenant, reserva, {agua.pk: 1})


def test_foreign_reservation_is_rejected(tenant, other_tenant, reserva):
    alheio = make_produto(other_tenant)
    with pytest.raises(services.InvalidReservation):
        services.add_to_tab(other_tenant, reserva, {alheio.pk: 1})


def test_remove_item_returns_stock_and_updates_total(tenant, reserva):
    agua = make_produto(tenant, nome="Água", preco=Decimal("4"))
    refri = make_produto(tenant, nome="Refri", preco=Decimal("6"))
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 2, refri.pk: 1})
    item = next(i for i in items_of(venda) if i.produto_id == refri.pk)

    venda = services.remove_tab_item(item)

    assert venda.total == Decimal("8")
    assert stock(refri) == 10


def test_removing_the_last_item_cancels_the_tab(tenant, reserva):
    agua = make_produto(tenant)
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 1})
    venda = services.remove_tab_item(items_of(venda)[0])
    assert venda.status == Venda.Status.CANCELADA
    assert stock(agua) == 10
    # A reserva pode abrir outra comanda depois disso.
    assert services.add_to_tab(tenant, reserva, {agua.pk: 1}).pk != venda.pk


def test_cancel_returns_stock_and_keeps_the_record(tenant, owner):
    agua = make_produto(tenant)
    bola = make_produto(tenant, nome="Aluguel", estoque=None)
    venda = services.complete_sale(tenant, {agua.pk: 3, bola.pk: 1}, PIX)

    venda = services.cancel_sale(venda, usuario=owner, motivo="Cobrado errado")

    assert stock(agua) == 10
    assert venda.status == Venda.Status.CANCELADA
    assert venda.cancelada_por == owner
    assert venda.motivo_cancelamento == "Cobrado errado"
    assert len(items_of(venda)) == 2
    assert MovimentacaoEstoque.all_tenants.filter(produto=agua, origem="CANCELAMENTO", quantidade=3).exists()
    with pytest.raises(services.SaleClosed):
        services.cancel_sale(venda)


def test_day_summary_counts_only_paid_sales_and_reports_open_tabs(tenant, reserva):
    agua = make_produto(tenant, preco=Decimal("4"))
    services.complete_sale(tenant, {agua.pk: 1}, PIX)
    services.complete_sale(tenant, {agua.pk: 2}, Venda.Forma.DINHEIRO)
    cancelada = services.complete_sale(tenant, {agua.pk: 1}, PIX)
    services.cancel_sale(cancelada)
    services.add_to_tab(tenant, reserva, {agua.pk: 5})

    summary = services.day_summary(tenant, timezone.localdate())

    assert summary["total"] == Decimal("12")
    assert summary["count"] == 2
    assert {row["forma"]: row["total"] for row in summary["por_forma"]} == {
        "DINHEIRO": Decimal("8"),
        "PIX": Decimal("4"),
    }
    assert summary["tabs_total"] == Decimal("20")
    assert summary["tabs_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_sales_do_not_oversell():
    tenant = make_tenant("concorrencia-pdv")
    produto = make_produto(tenant, estoque=3)
    attempts = 8
    barrier = threading.Barrier(attempts)
    results = []

    def attempt():
        try:
            barrier.wait()
            services.complete_sale(tenant, {produto.pk: 1}, PIX)
            results.append("ok")
        except InsufficientStock:
            results.append("sem estoque")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("ok") == 3
    assert results.count("sem estoque") == attempts - 3
    assert stock(produto) == 0
    numeros = sorted(Venda.all_tenants.filter(estabelecimento=tenant).values_list("numero", flat=True))
    assert numeros == [1, 2, 3]


# --- Telas


def checkout(client, produto, quantidade=1, **extra):
    data = {"produto": [produto.pk], "quantidade": [quantidade], "forma": "PIX", **extra}
    return client.post(reverse("pdv:finalizar"), data, headers=HX)


def triggers(response):
    return json.loads(response.headers["HX-Trigger"])


def test_pdv_page_lists_only_active_products(owner_client, tenant):
    make_produto(tenant, nome="Água")
    make_produto(tenant, nome="Parado", ativo=False)
    response = owner_client.get(reverse("pdv:home"))
    assert [p["nome"] for p in response.context["pdv_data"]["produtos"]] == ["Água"]
    assert "Parado" not in response.content.decode()


def test_pdv_page_only_offers_categories_in_use(owner_client, tenant):
    make_produto(tenant)
    assert owner_client.get(reverse("pdv:home")).context["categorias"] == [("BEBIDA", "Bebida")]


def test_pdv_page_without_products_points_to_registration(owner_client):
    assert reverse("estoque:create") in owner_client.get(reverse("pdv:home")).content.decode()


def test_pdv_page_offers_todays_reservations_and_keeps_the_requested_one(owner_client, espaco, cliente):
    make_produto(espaco.estabelecimento)
    outro_dia = agenda_services.create_reservation(espaco, cliente, at(10), at(11))
    response = owner_client.get(reverse("pdv:home"), {"reserva": outro_dia.pk})
    data = response.context["pdv_data"]
    assert data["reservaSelecionada"] == outro_dia.pk
    assert [r["id"] for r in data["reservas"]] == [outro_dia.pk]
    assert owner_client.get(reverse("pdv:home")).context["pdv_data"]["reservas"] == []


def test_checkout_completes_the_sale(owner_client, tenant, owner):
    agua = make_produto(tenant, preco=Decimal("4"))
    response = checkout(owner_client, agua, 2, total="8.00")
    assert response.status_code == 204
    assert "concluída" in triggers(response)["toast"]["message"]
    venda = Venda.all_tenants.get()
    assert venda.criado_por == owner
    assert stock(agua) == 8


def test_checkout_ignores_any_price_sent_by_the_browser(owner_client, tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    checkout(owner_client, agua, 1, preco="0.01")
    assert Venda.all_tenants.get().total == Decimal("4")


def test_checkout_reports_the_change_for_cash(owner_client, tenant):
    agua = make_produto(tenant, preco=Decimal("4"))
    response = checkout(owner_client, agua, 1, forma="DINHEIRO", recebido="10.00")
    assert "Troco: R$ 6,00" in triggers(response)["toast"]["message"]


def test_checkout_without_stock_warns_and_refreshes_the_screen(owner_client, tenant):
    agua = make_produto(tenant, estoque=1)
    response = checkout(owner_client, agua, 5)
    events = triggers(response)
    assert events["toast"]["level"] == "error"
    assert "Estoque insuficiente" in events["toast"]["message"]
    assert "data:changed" in events
    assert response.headers["HX-Reswap"] == "none"
    assert not Venda.all_tenants.exists()


def test_checkout_requires_a_payment_method_or_a_reservation(owner_client, tenant):
    agua = make_produto(tenant)
    response = owner_client.post(
        reverse("pdv:finalizar"), {"produto": [agua.pk], "quantidade": [1]}, headers=HX
    )
    assert triggers(response)["toast"]["level"] == "error"
    assert not Venda.all_tenants.exists()


def test_checkout_on_a_reservation_opens_a_tab(owner_client, tenant, reserva):
    agua = make_produto(tenant)
    response = checkout(owner_client, agua, 1, forma="", reserva=reserva.pk)
    assert "comanda" in triggers(response)["toast"]["message"]
    assert Venda.all_tenants.get().status == Venda.Status.ABERTA


def test_reservation_detail_shows_its_consumption(owner_client, tenant, reserva):
    agua = make_produto(tenant)
    url = reverse("agenda:reserva_detail", args=[reserva.pk])
    assert "Nada lançado" in owner_client.get(url, headers=HX).content.decode()
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 1})
    assert reverse("pdv:venda_detail", args=[venda.pk]) in owner_client.get(url, headers=HX).content.decode()


def test_tab_flow_through_the_screens(owner_client, tenant, reserva):
    agua = make_produto(tenant, nome="Água", preco=Decimal("4"))
    venda = services.add_to_tab(tenant, reserva, {agua.pk: 2})
    assert "Água" in owner_client.get(reverse("pdv:comandas")).content.decode()
    assert (
        "Receber"
        in owner_client.get(reverse("pdv:venda_detail", args=[venda.pk]), headers=HX).content.decode()
    )

    response = owner_client.post(reverse("pdv:receber", args=[venda.pk]), {"forma": "PIX"}, headers=HX)

    assert response.status_code == 204
    venda.refresh_from_db()
    assert venda.status == Venda.Status.CONCLUIDA
    assert "Nenhuma comanda aberta" in owner_client.get(reverse("pdv:comandas")).content.decode()


def test_sales_page_shows_the_day(owner_client, tenant):
    agua = make_produto(tenant, nome="Água", preco=Decimal("4"))
    services.complete_sale(tenant, {agua.pk: 2}, PIX)
    response = owner_client.get(reverse("pdv:vendas"))
    assert len(response.context["vendas"]) == 1
    assert response.context["summary"]["total"] == Decimal("8")
    assert "2x Água" in response.content.decode()
    assert not owner_client.get(reverse("pdv:vendas"), {"data": "2031-03-04"}).context["vendas"]


def test_manager_cancels_a_paid_sale(owner_client, tenant):
    agua = make_produto(tenant)
    venda = services.complete_sale(tenant, {agua.pk: 1}, PIX)
    url = reverse("pdv:cancelar", args=[venda.pk])
    assert owner_client.post(url, {"motivo": "Teste"}, headers=HX).status_code == 204
    assert stock(agua) == 10


def test_attendant_sells_and_fixes_tabs_but_cannot_cancel_paid_sales(client, attendant, tenant, reserva):
    agua = make_produto(tenant)
    client.force_login(attendant)
    assert client.get(reverse("pdv:home")).status_code == 200
    assert checkout(client, agua, 1).status_code == 204
    paga = Venda.all_tenants.get()

    detail = client.get(reverse("pdv:venda_detail", args=[paga.pk]), headers=HX).content.decode()
    assert "Cancelar venda" not in detail
    assert client.post(reverse("pdv:cancelar", args=[paga.pk]), {}, headers=HX).status_code == 403
    paga.refresh_from_db()
    assert paga.status == Venda.Status.CONCLUIDA

    comanda = services.add_to_tab(tenant, reserva, {agua.pk: 1})
    assert client.post(reverse("pdv:cancelar", args=[comanda.pk]), {}, headers=HX).status_code == 204


def test_tenant_isolation_on_all_screens(owner_client, tenant, other_tenant):
    outro_dono = make_user(other_tenant, "dono@b.test")
    alheio = make_produto(other_tenant, nome="Produto alheio")
    espaco = make_espaco(other_tenant, "Quadra alheia")
    cliente = make_cliente(other_tenant, "Cliente Alheio", "+5511977770000")
    reserva_alheia = agenda_services.create_reservation(espaco, cliente, at(10), at(11))
    venda = services.complete_sale(other_tenant, {alheio.pk: 1}, PIX, usuario=outro_dono)
    comanda = services.add_to_tab(other_tenant, reserva_alheia, {alheio.pk: 1})
    item = items_of(comanda)[0]

    for url in [reverse("pdv:home"), reverse("pdv:vendas"), reverse("pdv:comandas"), reverse("estoque:list")]:
        assert "alheio" not in owner_client.get(url).content.decode().lower()
    assert owner_client.get(reverse("pdv:venda_detail", args=[venda.pk]), headers=HX).status_code == 404
    assert owner_client.post(reverse("pdv:cancelar", args=[venda.pk]), headers=HX).status_code == 404
    assert (
        owner_client.post(reverse("pdv:receber", args=[comanda.pk]), {"forma": "PIX"}, headers=HX).status_code
        == 404
    )
    assert owner_client.post(reverse("pdv:remover_item", args=[item.pk]), headers=HX).status_code == 404
    assert owner_client.get(reverse("estoque:detail", args=[alheio.pk])).status_code == 404
    assert owner_client.post(reverse("estoque:update", args=[alheio.pk]), {}).status_code == 404

    # Produto e reserva de outro estabelecimento não entram por parâmetro.
    make_produto(tenant, nome="Meu")
    assert triggers(checkout(owner_client, alheio, 1))["toast"]["level"] == "error"
    meu = Produto.all_tenants.get(estabelecimento=tenant, nome="Meu")
    assert (
        triggers(checkout(owner_client, meu, 1, forma="", reserva=reserva_alheia.pk))["toast"]["level"]
        == "error"
    )
    assert not Venda.all_tenants.filter(estabelecimento=tenant).exists()


def test_dashboard_hides_sales_until_there_are_products(owner_client, tenant):
    url = reverse("relatorios:dashboard")
    assert "Vendas de hoje" not in owner_client.get(url).content.decode()
    make_produto(tenant)
    assert "Vendas de hoje" in owner_client.get(url).content.decode()
