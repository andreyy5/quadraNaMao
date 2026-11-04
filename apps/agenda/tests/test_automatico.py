"""Reserva por modalidade: quem reserva escolhe o horário e o sistema escolhe o espaço."""

from datetime import datetime, time, timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda import online, services
from apps.agenda.models import Bloqueio, Reserva
from apps.espacos.models import Espaco
from apps.espacos.services import modality_groups, save_weekly_hours, space_modalities
from conftest import DAY, HX, TZ, at, make_cliente, make_espaco


def areia(tenant, nome, ordem=0, modalidades="Beach tênis, futevôlei", **kwargs):
    espaco = make_espaco(tenant, nome, **kwargs)
    espaco.modalidades = modalidades
    espaco.ordem = ordem
    espaco.save()
    return espaco


@pytest.fixture
def quadras(tenant):
    return [areia(tenant, "Areia 1", 0), areia(tenant, "Areia 2", 1), areia(tenant, "Areia 3", 2)]


def options(espacos, inicio, fim):
    return [(espaco, inicio, fim) for espaco in espacos]


def ranked_names(espacos, inicio, fim, **kwargs):
    return [espaco.nome for espaco, _, _ in services.rank_spaces(options(espacos, inicio, fim), **kwargs)]


# --- Modalidades


def test_modalities_merge_spelling_and_fall_back_to_the_type(tenant):
    a1 = areia(tenant, "Areia 1", modalidades="Beach tênis; Futevôlei")
    a2 = areia(tenant, "Areia 2", modalidades="beach tenis, vôlei de praia")
    society = make_espaco(tenant, "Society")
    society.tipo = Espaco.Tipo.CAMPO
    society.save()

    groups = {grupo.key: grupo for grupo in modality_groups([a1, a2, society])}

    assert list(groups) == ["beach-tenis", "futevolei", "volei-de-praia", "campo"]
    assert groups["beach-tenis"].label == "Beach tênis"
    assert groups["beach-tenis"].espacos == [a1, a2] and groups["beach-tenis"].automatic
    assert not groups["futevolei"].automatic
    assert space_modalities(society) == ["Campo"]


# --- Organização automática


def test_prefers_the_space_that_keeps_the_agenda_compact(quadras, cliente):
    a1, a2, a3 = quadras
    services.create_reservation(a2, cliente, at(18), at(19))
    # Colado no jogo das 18h, a Areia 2 fica com a noite inteira de uma vez nas outras.
    assert ranked_names(quadras, at(19), at(20))[0] == "Areia 2"
    # Sem jogo nenhum no dia, vale a ordem de exibição.
    assert ranked_names(quadras, at(19), at(20), ignore=Reserva.all_tenants.get())[0] == "Areia 1"


def test_avoids_leaving_a_gap_too_short_to_sell(quadras, cliente):
    a1, a2, _ = quadras
    services.create_reservation(a1, cliente, at(18), at(19, 30))
    # 20h na Areia 1 deixaria 19:30-20:00 sobrando: meia hora que ninguém compra.
    names = ranked_names(quadras[:2], at(20), at(21))
    assert names == ["Areia 2", "Areia 1"]


def test_busy_blocked_or_closed_spaces_are_left_out(tenant, quadras, cliente):
    a1, a2, a3 = quadras
    services.create_reservation(a1, cliente, at(19), at(20))
    services.create_block(a2, at(18), at(21), Bloqueio.Motivo.CHUVA)
    save_weekly_hours(
        a3, [{"dia_semana": dia, "aberto": True, "abre": time(8), "fecha": time(18)} for dia in range(7)]
    )
    assert ranked_names(quadras, at(19), at(20)) == []


def test_auto_reservation_falls_to_the_next_space_when_the_best_is_taken(quadras, cliente):
    a1, a2, _ = quadras
    outro = make_cliente(a1.estabelecimento, "Outro", "+5511977770009")
    services.create_reservation(a1, outro, at(19), at(20))
    stale = [(a1, at(19), at(20)), (a2, at(19), at(20))]
    # Simula a corrida: a ordenação foi feita antes de a Areia 1 ser ocupada.
    with mock.patch.object(services, "rank_spaces", return_value=stale):
        reserva = services.create_reservation_auto(stale, cliente, modalidade="Beach tênis")
    assert reserva.espaco == a2 and reserva.modalidade == "Beach tênis"


def test_auto_reservation_without_any_free_space(quadras, cliente):
    for espaco in quadras:
        services.create_block(espaco, at(19), at(20), Bloqueio.Motivo.MANUTENCAO)
    with pytest.raises(services.NoSpaceAvailable, match="Nenhum espaço de beach tênis livre"):
        services.create_reservation_auto(options(quadras, at(19), at(20)), cliente, modalidade="Beach tênis")


# --- Painel da equipe


def panel_payload(**overrides):
    data = {
        "modalidade": "beach-tenis",
        "espaco": "",
        "data": DAY.isoformat(),
        "hora": "19:00",
        "duracao": 60,
        "valor_total": "",
        "observacoes": "",
        "cliente": "",
        "cliente_nome": "Marina Duarte",
        "cliente_telefone": "(11) 98888-7777",
    }
    data.update(overrides)
    return data


def test_panel_books_the_best_space_automatically(owner_client, quadras, cliente):
    services.create_reservation(quadras[1], cliente, at(18), at(19))
    response = owner_client.post(reverse("agenda:reserva_create"), panel_payload(), headers=HX)
    assert response.status_code == 204
    assert "em Areia 2" in response.headers["HX-Trigger"].encode().decode("unicode_escape")
    reserva = Reserva.all_tenants.get(cliente__nome="Marina Duarte")
    assert (reserva.espaco.nome, reserva.modalidade, reserva.valor_total) == ("Areia 2", "Beach tênis", 100)


def test_panel_needs_a_space_or_a_modality(owner_client, quadras):
    response = owner_client.post(reverse("agenda:reserva_create"), panel_payload(modalidade=""), headers=HX)
    assert "Escolha o espaço ou a modalidade" in response.content.decode()


def test_panel_with_an_explicit_space_keeps_it(owner_client, quadras):
    data = panel_payload(espaco=quadras[2].pk)
    assert owner_client.post(reverse("agenda:reserva_create"), data, headers=HX).status_code == 204
    reserva = Reserva.all_tenants.get()
    assert reserva.espaco == quadras[2] and reserva.modalidade == "Beach tênis"


def test_panel_opens_on_automatic_and_shows_where_the_game_goes(owner_client, quadras, cliente):
    form = owner_client.get(reverse("agenda:reserva_create"), {"data": DAY.isoformat()}, headers=HX).context[
        "form"
    ]
    assert form.auto_available
    assert form.initial["espaco"] is None and form.initial["modalidade"] == "beach-tenis"

    services.create_reservation(quadras[0], cliente, at(10), at(11))
    params = {
        "modalidade": "beach-tenis",
        "espaco": "",
        "data": DAY.isoformat(),
        "hora": "11:00",
        "duracao": 60,
    }
    slots = owner_client.get(reverse("agenda:reserva_slots"), params, headers=HX)
    assert "10:00" in slots.context["slots"]  # livre nas outras areias
    assert slots.context["destino"] == quadras[0]
    assert "vai para" in slots.content.decode()


def test_panel_from_a_grid_cell_keeps_that_space(owner_client, quadras):
    params = {"espaco": quadras[1].pk, "data": DAY.isoformat(), "hora": "10:00", "minutos": 60}
    form = owner_client.get(reverse("agenda:reserva_create"), params, headers=HX).context["form"]
    assert form.initial["espaco"] == quadras[1]


def test_panel_without_equivalent_spaces_looks_as_before(owner_client, espaco):
    form = owner_client.get(reverse("agenda:reserva_create"), headers=HX).context["form"]
    assert not form.auto_available
    assert form.initial["espaco"] == espaco
    assert (
        'name="modalidade"'
        not in owner_client.get(reverse("agenda:reserva_create"), headers=HX).content.decode()
    )


def test_panel_does_not_offer_other_establishments_spaces(owner_client, quadras, other_tenant):
    areia(other_tenant, "Areia alheia")
    form = owner_client.get(reverse("agenda:reserva_create"), headers=HX).context["form"]
    assert [e.nome for e in form.modalidades[0].espacos] == ["Areia 1", "Areia 2", "Areia 3"]


# --- Link público


@pytest.fixture
def loja(tenant):
    tenant.reserva_online_ativa = True
    tenant.save()
    return tenant


def amanha(hour=10):
    day = timezone.now().astimezone(TZ).date() + timedelta(days=1)
    return datetime.combine(day, time(hour), tzinfo=TZ)


def test_public_page_lists_modalities_and_times_of_any_space(client, loja, quadras, cliente):
    services.create_reservation(quadras[0], cliente, amanha(19), amanha(20))
    url = reverse("publico:reservar", args=[loja.slug])
    response = client.get(url, {"data": amanha().date().isoformat(), "modalidade": "futevolei"})
    content = response.content.decode()
    assert "Beach tênis" in content and "Futevôlei" in content
    assert response.context["modalidade"].key == "futevolei"
    assert amanha(19) in response.context["starts"]  # a Areia 1 está ocupada, as outras não


def test_public_booking_goes_to_the_best_space(client, loja, quadras, cliente):
    services.create_reservation(quadras[2], cliente, amanha(18), amanha(19))
    data = {
        "modalidade": "beach-tenis",
        "data": amanha().date().isoformat(),
        "hora": "19:00",
        "nome": "Lia Souza",
        "telefone": "(11) 97777-1111",
    }
    assert client.post(reverse("publico:reservar", args=[loja.slug]), data).status_code == 302
    reserva = Reserva.all_tenants.get(cliente__nome="Lia Souza")
    assert (reserva.espaco.nome, reserva.modalidade) == ("Areia 3", "Beach tênis")


def test_public_preview_shows_space_and_price(client, loja, quadras):
    params = {"modalidade": "beach-tenis", "data": amanha().date().isoformat(), "hora": "19:00"}
    response = client.get(reverse("publico:previa", args=[loja.slug]), params)
    content = response.content.decode()
    assert "Areia 1" in content and "R$ 100,00" in content and "pago no local" in content

    for espaco in quadras:
        services.create_block(espaco, amanha(19), amanha(20), Bloqueio.Motivo.CHUVA)
    taken = client.get(reverse("publico:previa", args=[loja.slug]), params).content.decode()
    assert "acabou de ser ocupado" in taken
    assert client.get(reverse("publico:previa", args=[loja.slug]), {"modalidade": "x"}).status_code == 404


def test_book_online_tries_the_next_space_when_the_best_was_just_taken(loja, quadras, cliente):
    a1, a2, _ = quadras
    inicio = amanha(19)
    stale = [(a1, inicio, inicio + timedelta(hours=1)), (a2, inicio, inicio + timedelta(hours=1))]
    services.create_reservation(a1, cliente, inicio, inicio + timedelta(hours=1))
    with (
        mock.patch.object(online, "_options", return_value=stale),
        mock.patch.object(online, "rank_spaces", return_value=stale),
    ):
        reserva, _ = online.book_online(loja, [a1, a2], inicio, "Lia", "(11) 97777-1111")
    assert reserva.espaco == a2
