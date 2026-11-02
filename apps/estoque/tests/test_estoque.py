from decimal import Decimal

import pytest
from django.urls import reverse

from apps.estoque import services
from apps.estoque.models import MovimentacaoEstoque, Produto
from conftest import HX, make_produto, make_user


def fresh(produto):
    return Produto.all_tenants.get(pk=produto.pk)


def test_entry_raises_balance_and_records_movement(tenant, owner):
    produto = make_produto(tenant)
    services.register_entry(produto, 5, usuario=owner, custo=Decimal("2.50"))
    produto = fresh(produto)
    assert produto.estoque_atual == 15
    assert produto.custo == Decimal("2.50")
    mov = MovimentacaoEstoque.all_tenants.filter(produto=produto).first()
    assert (mov.tipo, mov.quantidade, mov.saldo_apos, mov.usuario) == ("ENTRADA", 5, 15, owner)


def test_loss_cannot_leave_stock_negative(tenant):
    produto = make_produto(tenant, estoque=3)
    with pytest.raises(services.InsufficientStock):
        services.register_loss(produto, 4)
    assert fresh(produto).estoque_atual == 3
    services.register_loss(produto, 3)
    assert fresh(produto).estoque_atual == 0


def test_negative_stock_when_the_establishment_allows_it(tenant):
    tenant.permite_estoque_negativo = True
    tenant.save()
    produto = make_produto(tenant, estoque=1)
    services.register_loss(produto, 3)
    assert fresh(produto).estoque_atual == -2


def test_count_sets_the_balance_and_records_the_difference(tenant):
    produto = make_produto(tenant, estoque=10)
    mov = services.adjust_to_count(produto, 7)
    assert fresh(produto).estoque_atual == 7
    assert (mov.tipo, mov.quantidade, mov.saldo_apos) == ("AJUSTE", -3, 7)
    assert services.adjust_to_count(produto, 7) is None


@pytest.mark.parametrize("quantidade", [0, -1])
def test_invalid_quantities_are_rejected(tenant, quantidade):
    produto = make_produto(tenant)
    with pytest.raises(services.InvalidQuantity):
        services.register_entry(produto, quantidade)
    with pytest.raises(services.InvalidQuantity):
        services.register_loss(produto, quantidade)


def test_unstocked_product_has_no_movements(tenant):
    produto = make_produto(tenant, nome="Aluguel de bola", estoque=None)
    with pytest.raises(services.NotStocked):
        services.register_entry(produto, 1)


def test_low_stock_flags(tenant):
    produto = make_produto(tenant, estoque=5, minimo=5)
    assert produto.is_low and not produto.is_out
    assert make_produto(tenant, nome="Zerado", estoque=0).is_out
    sem_controle = make_produto(tenant, nome="Aluguel", estoque=None)
    assert not sem_controle.is_low and not sem_controle.is_out


def test_overview_counts_low_products_and_value_at_cost(tenant):
    make_produto(tenant, nome="A", estoque=10, minimo=2, custo=Decimal("2"))
    make_produto(tenant, nome="B", estoque=1, minimo=5, custo=Decimal("3"))
    make_produto(tenant, nome="Aluguel", estoque=None)
    overview = services.stock_overview(tenant)
    assert overview["total"] == 3
    assert overview["low"] == 1
    assert overview["value"] == Decimal("23")


def product_payload(**overrides):
    return {
        "nome": "Água",
        "categoria": "BEBIDA",
        "preco_venda": "4,50",
        "custo": "",
        "controla_estoque": "on",
        "estoque_inicial": "12",
        "estoque_minimo": "3",
        "codigo": "",
        "ativo": "on",
        **overrides,
    }


def test_create_product_with_initial_stock(owner_client, tenant):
    response = owner_client.post(reverse("estoque:create"), product_payload())
    assert response.status_code == 302
    produto = Produto.all_tenants.get(estabelecimento=tenant, nome="Água")
    assert produto.preco_venda == Decimal("4.50")
    assert produto.estoque_atual == 12
    assert MovimentacaoEstoque.all_tenants.filter(produto=produto, observacao="Estoque inicial").exists()


def test_product_name_and_code_are_unique_per_establishment(owner_client, tenant):
    make_produto(tenant, nome="Água", codigo="789")
    response = owner_client.post(reverse("estoque:create"), product_payload())
    assert "Já existe um produto com esse nome" in response.content.decode()
    response = owner_client.post(reverse("estoque:create"), product_payload(nome="Outra", codigo="789"))
    assert "Já existe um produto com esse código" in response.content.decode()


def test_editing_a_product_does_not_touch_the_balance(owner_client, tenant):
    produto = make_produto(tenant, estoque=9)
    data = product_payload(nome="Novo nome", estoque_inicial="500")
    assert owner_client.post(reverse("estoque:update", args=[produto.pk]), data).status_code == 302
    produto = fresh(produto)
    assert produto.nome == "Novo nome"
    assert produto.estoque_atual == 9


def test_move_modal_registers_entry_loss_and_count(owner_client, tenant):
    produto = make_produto(tenant, estoque=10)
    url = reverse("estoque:movimentar", args=[produto.pk])
    base = {"quantidade": 5, "custo": "", "observacao": ""}
    assert owner_client.post(url, {**base, "tipo": "ENTRADA"}, headers=HX).status_code == 204
    assert fresh(produto).estoque_atual == 15
    owner_client.post(url, {**base, "tipo": "PERDA", "quantidade": 2}, headers=HX)
    assert fresh(produto).estoque_atual == 13
    owner_client.post(url, {**base, "tipo": "AJUSTE", "quantidade": 0}, headers=HX)
    assert fresh(produto).estoque_atual == 0


def test_move_modal_shows_stock_errors(owner_client, tenant):
    produto = make_produto(tenant, estoque=1)
    url = reverse("estoque:movimentar", args=[produto.pk])
    data = {"tipo": "PERDA", "quantidade": 5, "custo": "", "observacao": ""}
    assert "Estoque insuficiente" in owner_client.post(url, data, headers=HX).content.decode()
    data = {"tipo": "ENTRADA", "quantidade": 0, "custo": "", "observacao": ""}
    assert "maior que zero" in owner_client.post(url, data, headers=HX).content.decode()


def test_move_modal_does_not_exist_for_unstocked_product(owner_client, tenant):
    produto = make_produto(tenant, nome="Aluguel", estoque=None)
    assert owner_client.get(reverse("estoque:movimentar", args=[produto.pk]), headers=HX).status_code == 404


def test_list_filters(owner_client, tenant):
    make_produto(tenant, nome="Cheio", estoque=10, minimo=2)
    make_produto(tenant, nome="Quase", estoque=1, minimo=2)
    make_produto(tenant, nome="Parado", ativo=False)
    url = reverse("estoque:list")
    assert {p.nome for p in owner_client.get(url).context["produtos"]} == {"Cheio", "Quase"}
    assert [p.nome for p in owner_client.get(url, {"filtro": "baixo"}).context["produtos"]] == ["Quase"]
    assert [p.nome for p in owner_client.get(url, {"filtro": "inativos"}).context["produtos"]] == ["Parado"]
    assert [p.nome for p in owner_client.get(url, {"q": "quas"}).context["produtos"]] == ["Quase"]


def test_attendant_has_no_access_to_stock(client, attendant, tenant):
    produto = make_produto(tenant)
    client.force_login(attendant)
    assert client.get(reverse("estoque:list")).status_code == 403
    assert client.get(reverse("estoque:create")).status_code == 403
    assert client.get(reverse("estoque:movimentar", args=[produto.pk]), headers=HX).status_code == 403
    assert reverse("estoque:list") not in client.get(reverse("relatorios:dashboard")).content.decode()


def test_manager_has_access_to_stock_but_not_to_settings(client, tenant):
    client.force_login(make_user(tenant, "gerente@a.test", "GERENTE"))
    assert client.get(reverse("estoque:list")).status_code == 200
    assert client.get(reverse("espacos:list")).status_code == 403
