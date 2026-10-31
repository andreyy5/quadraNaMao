import pytest
from django.urls import reverse

from apps.agenda import services as agenda_services
from apps.agenda.models import Reserva
from apps.clientes.models import Cliente
from apps.clientes.services import (
    ANONYMIZED_NAME,
    InvalidPhone,
    anonymize_client,
    find_or_create_client,
    format_phone,
    normalize_phone,
    search_clients,
)
from apps.estabelecimentos.tenancy import tenant_context
from conftest import HX, at, make_cliente


@pytest.mark.parametrize(
    "raw",
    ["11987654321", "(11) 98765-4321", "11 98765 4321", "+55 11 98765-4321", "5511987654321"],
)
def test_normalizes_mobile_numbers_to_e164(raw):
    assert normalize_phone(raw) == "+5511987654321"


@pytest.mark.parametrize("raw", ["", None, "123", "abc", "(00) 00000-0000"])
def test_rejects_invalid_numbers(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)


def test_format_phone():
    assert format_phone("+5511987654321") == "(11) 98765-4321"
    assert format_phone("anon-5") == "—"


def test_find_or_create_does_not_duplicate_or_rename(tenant):
    first = find_or_create_client(tenant, "Ana", "(11) 98765-4321")
    second = find_or_create_client(tenant, "Outro Nome", "11987654321")
    assert first.pk == second.pk
    assert second.nome == "Ana"


def test_search_ignores_accents_and_matches_phone(tenant, cliente):
    make_cliente(tenant, "Marina", "+5511900000000")
    with tenant_context(tenant):
        assert list(search_clients("joao")) == [cliente]
        assert list(search_clients("JOÃO")) == [cliente]
        assert list(search_clients("98765")) == [cliente]
        assert search_clients("").count() == 2


def test_form_normalizes_phone_and_blocks_duplicate(owner_client, cliente):
    url = reverse("clientes:create")
    response = owner_client.post(url, {"nome": "Novo", "telefone": "(11) 98765-0001"})
    assert response.status_code == 200
    assert "Já existe um cliente" in response.content.decode()

    assert owner_client.post(url, {"nome": "Novo", "telefone": "(21) 99876-5432"}).status_code == 302
    assert Cliente.all_tenants.filter(telefone="+5521998765432").exists()


def test_editing_keeps_own_phone_valid(owner_client, cliente):
    url = reverse("clientes:update", args=[cliente.pk])
    response = owner_client.post(url, {"nome": "Nome Novo", "telefone": "11987650001"})
    assert response.status_code == 302
    cliente.refresh_from_db()
    assert cliente.nome == "Nome Novo"


def test_search_endpoint_requires_two_characters(owner_client, cliente):
    url = reverse("clientes:search")
    assert b"Pereira" not in owner_client.get(url, {"cliente_nome": "j"}, headers=HX).content
    assert b"Pereira" in owner_client.get(url, {"cliente_nome": "jo"}, headers=HX).content


def test_anonymize_removes_personal_data_and_keeps_history(tenant, espaco, cliente):
    reserva = agenda_services.create_reservation(
        espaco, cliente, at(10), at(11), observacoes="Ligar para João"
    )
    cliente.email = "joao@example.com"
    cliente.save()
    anonymize_client(cliente)
    cliente.refresh_from_db()
    assert cliente.nome == ANONYMIZED_NAME
    assert cliente.telefone == f"anon-{cliente.pk}"
    assert cliente.email == ""
    reserva = Reserva.all_tenants.get(pk=reserva.pk)
    assert reserva.observacoes == ""
    with tenant_context(tenant):
        assert not search_clients("").exists()


def test_anonymized_client_page_still_opens(owner_client, cliente):
    anonymize_client(cliente)
    assert owner_client.get(reverse("clientes:detail", args=[cliente.pk])).status_code == 200
    assert owner_client.get(reverse("clientes:update", args=[cliente.pk])).status_code == 404
