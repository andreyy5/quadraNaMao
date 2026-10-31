"""Nenhuma consulta pode vazar dados entre estabelecimentos."""

import pytest
from django.urls import reverse

from apps.agenda import services
from apps.agenda.forms import ReservaForm
from apps.agenda.models import Bloqueio, Reserva, ReservaEvento
from apps.clientes.models import Cliente
from apps.espacos.models import Espaco, HorarioFuncionamento, TabelaPreco
from apps.estabelecimentos.tenancy import get_current_tenant, tenant_context
from conftest import DAY, HX, at, make_cliente, make_espaco, make_user

TENANT_MODELS = [Espaco, HorarioFuncionamento, TabelaPreco, Cliente, Reserva, Bloqueio, ReservaEvento]


@pytest.fixture
def foreign(other_tenant):
    """Dados completos do outro estabelecimento."""
    espaco = make_espaco(other_tenant, "Quadra alheia")
    cliente = make_cliente(other_tenant, "Cliente Alheio", "+5511977770000")
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    bloqueio, _ = services.create_block(espaco, at(14), at(15), Bloqueio.Motivo.CHUVA)
    return {
        "espaco": espaco,
        "cliente": cliente,
        "reserva": reserva,
        "bloqueio": bloqueio,
        "preco": TabelaPreco.all_tenants.filter(espaco=espaco).first(),
        "user": make_user(other_tenant, "dono@b.test"),
    }


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_manager_without_tenant_fails_closed(foreign, model):
    assert get_current_tenant() is None
    assert model.all_tenants.exists()
    assert not model.objects.exists()


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_manager_filters_by_current_tenant(foreign, tenant, other_tenant, model):
    with tenant_context(tenant):
        assert not model.objects.exists()
    with tenant_context(other_tenant):
        assert model.objects.exists()


def test_tenant_is_cleared_after_each_request(owner_client):
    owner_client.get(reverse("relatorios:dashboard"))
    assert get_current_tenant() is None


@pytest.mark.parametrize(
    ("route", "key"),
    [
        ("agenda:reserva_detail", "reserva"),
        ("agenda:reserva_update", "reserva"),
        ("agenda:reserva_cancel", "reserva"),
        ("clientes:detail", "cliente"),
        ("clientes:update", "cliente"),
        ("clientes:anonymize", "cliente"),
        ("espacos:update", "espaco"),
        ("espacos:horarios", "espaco"),
        ("espacos:precos", "espaco"),
        ("espacos:preco_create", "espaco"),
        ("contas:equipe_update", "user"),
    ],
)
def test_foreign_objects_return_404(owner_client, foreign, route, key):
    assert owner_client.get(reverse(route, args=[foreign[key].pk])).status_code == 404


@pytest.mark.parametrize(
    ("route", "key", "data"),
    [
        ("agenda:reserva_cancel", "reserva", {}),
        ("agenda:reserva_status", "reserva", {"acao": "concluida"}),
        ("agenda:bloqueio_delete", "bloqueio", {}),
        ("clientes:anonymize", "cliente", {}),
    ],
)
def test_foreign_objects_cannot_be_changed(owner_client, foreign, route, key, data):
    assert owner_client.post(reverse(route, args=[foreign[key].pk]), data).status_code == 404
    reserva = Reserva.all_tenants.get(pk=foreign["reserva"].pk)
    assert reserva.status == Reserva.Status.CONFIRMADA
    assert Bloqueio.all_tenants.filter(pk=foreign["bloqueio"].pk).exists()
    assert Cliente.all_tenants.get(pk=foreign["cliente"].pk).anonimizado_em is None


def test_foreign_price_rule_routes_return_404(owner_client, espaco, foreign):
    preco = foreign["preco"]
    assert (
        owner_client.get(reverse("espacos:preco_update", args=[foreign["espaco"].pk, preco.pk])).status_code
        == 404
    )
    assert owner_client.get(reverse("espacos:preco_update", args=[espaco.pk, preco.pk])).status_code == 404
    assert owner_client.post(reverse("espacos:preco_delete", args=[espaco.pk, preco.pk])).status_code == 404
    assert TabelaPreco.all_tenants.filter(pk=preco.pk).exists()


def test_impact_page_hides_foreign_blocks(owner_client, foreign):
    url = reverse("agenda:bloqueio_impact")
    assert owner_client.get(url, {"ids": foreign["bloqueio"].pk}).status_code == 404


def test_bulk_cancel_ignores_foreign_reservations(owner_client, foreign):
    owner_client.post(reverse("agenda:reserva_bulk_cancel"), {"reservas": [foreign["reserva"].pk]})
    assert Reserva.all_tenants.get(pk=foreign["reserva"].pk).status == Reserva.Status.CONFIRMADA


def test_lists_and_search_do_not_leak(owner_client, espaco, foreign):
    assert (
        "Quadra alheia"
        not in owner_client.get(reverse("agenda:day"), {"data": DAY.isoformat()}).content.decode()
    )
    assert "Quadra alheia" not in owner_client.get(reverse("espacos:list")).content.decode()
    assert "Cliente Alheio" not in owner_client.get(reverse("clientes:list")).content.decode()
    response = owner_client.get(reverse("clientes:search"), {"cliente_nome": "Alheio"}, headers=HX)
    assert "Cliente Alheio" not in response.content.decode()
    assert "dono@b.test" not in owner_client.get(reverse("contas:equipe")).content.decode()


def test_reservation_form_only_offers_own_records(tenant, espaco, foreign):
    with tenant_context(tenant):
        form = ReservaForm()
        assert list(form.fields["espaco"].queryset) == [espaco]
        assert not form.fields["cliente"].queryset.filter(pk=foreign["cliente"].pk).exists()


def test_post_with_foreign_space_or_client_is_rejected(owner_client, espaco, foreign):
    base = {
        "data": DAY.isoformat(),
        "hora": "16:00",
        "duracao": 60,
        "cliente_nome": "Teste",
        "cliente_telefone": "11987654321",
    }
    url = reverse("agenda:reserva_create")
    response = owner_client.post(url, {**base, "espaco": foreign["espaco"].pk}, headers=HX)
    assert response.status_code == 200
    response = owner_client.post(
        url, {**base, "espaco": espaco.pk, "cliente": foreign["cliente"].pk}, headers=HX
    )
    assert response.status_code == 200
    assert not Reserva.all_tenants.filter(espaco=espaco).exists()
    assert Reserva.all_tenants.filter(espaco=foreign["espaco"]).count() == 1


def test_same_phone_can_exist_in_two_tenants(tenant, foreign):
    assert make_cliente(tenant, "Mesmo telefone", foreign["cliente"].telefone)


def test_inactive_tenant_loses_access(client, owner, tenant):
    client.force_login(owner)
    tenant.ativo = False
    tenant.save()
    response = client.get(reverse("relatorios:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("contas:login")
