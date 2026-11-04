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
from apps.clientes.templatetags.clientes_ui import whatsapp_url
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


def test_palette_finds_clients_and_actions_without_accents(owner_client, cliente):
    url = reverse("clientes:palette")
    response = owner_client.get(url, {"q": "joao"}, headers=HX)
    assert cliente in response.context["clientes"]

    labels = [action["label"] for action in owner_client.get(url, {"q": "espacos"}).context["actions"]]
    assert labels == ["Espaços"]


def test_palette_finds_action_by_related_term(owner_client):
    response = owner_client.get(reverse("clientes:palette"), {"q": "chuva"})
    assert [action["label"] for action in response.context["actions"]] == ["Bloquear horário"]


def test_palette_hides_owner_actions_from_attendant(client, attendant):
    client.force_login(attendant)
    labels = [action["label"] for action in client.get(reverse("clientes:palette")).context["actions"]]
    assert "Nova reserva" in labels
    assert "Espaços" not in labels
    assert "Equipe" not in labels


def test_palette_says_when_nothing_matches(owner_client):
    assert "Nada encontrado" in owner_client.get(reverse("clientes:palette"), {"q": "xyzw"}).content.decode()


def test_whatsapp_url_is_empty_for_anonymized_client():
    assert whatsapp_url("+5511987650001") == "https://wa.me/5511987650001"
    assert whatsapp_url("anon-12") == ""
    assert whatsapp_url("") == ""


def test_list_shows_games_last_played_and_overdue(owner_client, tenant, espaco, cliente):
    from datetime import timedelta

    from django.utils import timezone

    from apps.agenda.services import cancel_reservation, create_reservation
    from conftest import at

    past = timezone.localdate() - timedelta(days=5)
    create_reservation(espaco, cliente, at(10, day=past), at(11, day=past))
    cancel_reservation(create_reservation(espaco, cliente, at(12, day=past), at(13, day=past)))
    future = timezone.localdate() + timedelta(days=5)
    create_reservation(espaco, cliente, at(10, day=future), at(11, day=future))

    row = owner_client.get(reverse("clientes:list")).context["clientes"][0]
    assert row.n_reservas == 2  # a cancelada não conta
    assert timezone.localtime(row.ultima_reserva).date() == past  # o jogo futuro não é "último"
    assert row.em_atraso == 100


def test_list_keeps_alphabetical_order(owner_client, tenant):
    from conftest import make_cliente

    for nome, telefone in [
        ("Zeca", "+5511977770001"),
        ("Ana", "+5511977770002"),
        ("Maria", "+5511977770003"),
    ]:
        make_cliente(tenant, nome, telefone)
    nomes = [c.nome for c in owner_client.get(reverse("clientes:list")).context["clientes"]]
    assert nomes == sorted(nomes)
