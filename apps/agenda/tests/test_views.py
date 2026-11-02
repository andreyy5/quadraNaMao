import json
from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.agenda import services
from apps.agenda.models import Bloqueio, Reserva, ReservaEvento
from apps.clientes.models import Cliente
from apps.espacos.services import save_weekly_hours
from conftest import DAY, HX, at


def payload(espaco, **overrides):
    data = {
        "espaco": espaco.pk,
        "data": DAY.isoformat(),
        "hora": "10:00",
        "duracao": 60,
        "valor_total": "100,00",
        "observacoes": "",
        "cliente": "",
        "cliente_nome": "Marina Duarte",
        "cliente_telefone": "(11) 98888-7777",
    }
    data.update(overrides)
    return data


def test_day_view_renders_grid(owner_client, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    response = owner_client.get(reverse("agenda:day"), {"data": DAY.isoformat()})
    assert response.status_code == 200
    assert cliente.nome.encode() in response.content
    assert b"QuadraNaM\xc3\xa3o!" in response.content


def test_week_view_renders_seven_columns(owner_client, espaco):
    response = owner_client.get(reverse("agenda:week"), {"data": DAY.isoformat(), "espaco": espaco.pk})
    assert response.status_code == 200
    assert len(response.context["grid"].columns) == 7


def test_invalid_date_falls_back_to_today(owner_client, espaco):
    assert owner_client.get(reverse("agenda:day"), {"data": "2031-99-99"}).status_code == 200
    assert owner_client.get(reverse("agenda:week"), {"data": "lixo"}).status_code == 200


def test_create_form_is_prefilled_from_the_slot(owner_client, espaco):
    response = owner_client.get(
        reverse("agenda:reserva_create"),
        {"espaco": espaco.pk, "data": DAY.isoformat(), "hora": "10:00", "minutos": 60},
        headers=HX,
    )
    assert response.status_code == 200
    assert "<html" not in response.content.decode()
    assert b'value="100,00"' in response.content
    assert b'value="10:00"' in response.content


def test_create_reservation_creates_new_client(owner_client, owner, espaco):
    response = owner_client.post(reverse("agenda:reserva_create"), payload(espaco), headers=HX)
    assert response.status_code == 204
    events = json.loads(response.headers["HX-Trigger"])
    assert events["toast"]["message"] == "Reserva confirmada."
    reserva = Reserva.all_tenants.get()
    assert reserva.cliente.telefone == "+5511988887777"
    assert reserva.criado_por == owner


def test_create_reservation_reuses_client_by_phone(owner_client, espaco, cliente):
    data = payload(espaco, cliente_nome="Outro nome", cliente_telefone="11987650001")
    assert owner_client.post(reverse("agenda:reserva_create"), data, headers=HX).status_code == 204
    assert Cliente.all_tenants.count() == 1
    assert Cliente.all_tenants.get().nome == cliente.nome


def test_conflict_shows_friendly_message_and_does_not_keep_new_client(owner_client, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    response = owner_client.post(reverse("agenda:reserva_create"), payload(espaco), headers=HX)
    assert response.status_code == 200
    assert "Esse horário já está reservado" in response.content.decode()
    assert Cliente.all_tenants.count() == 1


def test_invalid_phone_and_missing_name_show_errors(owner_client, espaco):
    data = payload(espaco, cliente_nome=" ", cliente_telefone="123")
    response = owner_client.post(reverse("agenda:reserva_create"), data, headers=HX)
    content = response.content.decode()
    assert response.status_code == 200
    assert "Informe o nome do cliente." in content
    assert "Telefone inválido" in content
    assert Reserva.all_tenants.count() == 0


def test_non_numeric_duration_does_not_crash(owner_client, espaco):
    response = owner_client.post(reverse("agenda:reserva_create"), payload(espaco, duracao="abc"), headers=HX)
    assert response.status_code == 200


def test_form_post_without_htmx_redirects(owner_client, espaco):
    response = owner_client.post(reverse("agenda:reserva_create"), payload(espaco))
    assert response.status_code == 302
    assert response.url == reverse("agenda:day")


def test_detail_page_works_with_and_without_htmx(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    url = reverse("agenda:reserva_detail", args=[reserva.pk])
    assert "<html" in owner_client.get(url).content.decode()
    assert "<html" not in owner_client.get(url, headers=HX).content.decode()


def test_update_reschedules_and_logs(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    data = payload(espaco, hora="15:00", cliente=cliente.pk)
    response = owner_client.post(reverse("agenda:reserva_update", args=[reserva.pk]), data, headers=HX)
    assert response.status_code == 204
    reserva.refresh_from_db()
    assert reserva.inicio == at(15)
    assert ReservaEvento.all_tenants.filter(reserva=reserva, acao="ALTERADA").exists()


def test_cancel_view(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    url = reverse("agenda:reserva_cancel", args=[reserva.pk])
    assert owner_client.get(url, headers=HX).status_code == 200
    assert owner_client.post(url, headers=HX).status_code == 204
    reserva.refresh_from_db()
    assert reserva.status == Reserva.Status.CANCELADA


def test_status_view_rejects_unknown_action(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    url = reverse("agenda:reserva_status", args=[reserva.pk])
    assert owner_client.post(url, {"acao": "hackear"}, headers=HX).status_code == 404
    assert owner_client.post(url, {"acao": "concluida"}, headers=HX).status_code == 204
    reserva.refresh_from_db()
    assert reserva.status == Reserva.Status.CONCLUIDA


def test_quote_endpoint(owner_client, espaco):
    params = {"espaco": espaco.pk, "data": DAY.isoformat(), "hora": "10:00", "duracao": 120}
    response = owner_client.get(reverse("agenda:reserva_quote"), params, headers=HX)
    assert b'value="200,00"' in response.content


def test_block_without_affected_reservations(owner_client, espaco):
    data = {
        "espacos": [espaco.pk],
        "data": DAY.isoformat(),
        "hora_inicio": "10:00",
        "hora_fim": "12:00",
        "motivo": "CHUVA",
    }
    response = owner_client.post(reverse("agenda:bloqueio_create"), data, headers=HX)
    assert response.status_code == 204
    assert Bloqueio.all_tenants.count() == 1


def test_block_with_affected_reservations_goes_to_impact_page(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    data = {"espacos": [espaco.pk], "data": DAY.isoformat(), "dia_todo": "on", "motivo": "CHUVA"}
    response = owner_client.post(reverse("agenda:bloqueio_create"), data, headers=HX)
    target = response.headers["HX-Redirect"]
    page = owner_client.get(target)
    assert page.status_code == 200
    assert reserva in page.context["reservas"]


def test_bulk_cancel_and_safe_redirect(owner_client, espaco, cliente):
    first = services.create_reservation(espaco, cliente, at(10), at(11))
    second = services.create_reservation(espaco, cliente, at(11), at(12))
    url = reverse("agenda:reserva_bulk_cancel")
    response = owner_client.post(url, {"reservas": [first.pk], "next": "https://malicioso.example/"})
    assert response.url == reverse("agenda:day")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == Reserva.Status.CANCELADA
    assert second.status == Reserva.Status.CONFIRMADA


def test_delete_block_frees_slot(owner_client, espaco):
    bloqueio, _ = services.create_block(espaco, at(10), at(11), Bloqueio.Motivo.CHUVA)
    assert owner_client.post(reverse("agenda:bloqueio_delete", args=[bloqueio.pk])).status_code == 302
    assert not Bloqueio.all_tenants.exists()


def test_block_form_starts_with_nothing_selected(owner_client, espaco):
    form = owner_client.get(reverse("agenda:bloqueio_create"), headers=HX).context["form"]
    assert "espacos" not in form.initial
    assert not form.initial.get("dia_todo")


def test_dashboard_has_no_query_per_reservation(owner_client, espaco, cliente, django_assert_max_num_queries):
    today = timezone.localdate()
    rows = [{"dia_semana": dia, "aberto": True, "abre": time(0), "fecha": time(0)} for dia in range(7)]
    save_weekly_hours(espaco, rows)
    for hour in range(6, 12):
        start = datetime.combine(today, time(hour), tzinfo=timezone.get_current_timezone())
        services.create_reservation(espaco, cliente, start, start + timedelta(hours=1))
    with django_assert_max_num_queries(20):
        owner_client.get(reverse("relatorios:dashboard"))


def test_block_form_requires_time_when_not_all_day(owner_client, espaco):
    data = {"espacos": [espaco.pk], "data": DAY.isoformat(), "motivo": "CHUVA"}
    response = owner_client.post(reverse("agenda:bloqueio_create"), data, headers=HX)
    assert response.status_code == 200
    assert "Informe o horário" in response.content.decode()


def test_day_view_shows_week_strip_and_keeps_day_in_new_reservation(owner_client, espaco):
    response = owner_client.get(reverse("agenda:day"), {"data": DAY.isoformat()})
    assert len(response.context["day_strip"]) == 7
    assert 'id="day-strip"' in response.content.decode()
    assert f"{reverse('agenda:reserva_create')}?data={DAY.isoformat()}" in response.content.decode()


def test_reservation_form_explains_when_there_is_no_space(owner_client):
    content = owner_client.get(reverse("agenda:reserva_create"), headers=HX).content.decode()
    assert "primeiro cadastre um espaço" in content
    assert "<form" not in content


def test_reservation_detail_links_to_whatsapp(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    content = owner_client.get(
        reverse("agenda:reserva_detail", args=[reserva.pk]), headers=HX
    ).content.decode()
    assert f"https://wa.me/{cliente.telefone.removeprefix('+')}?text=" in content


def slots(client, espaco, **overrides):
    params = {"espaco": espaco.pk, "data": DAY.isoformat(), "hora": "10:00", "duracao": 60, **overrides}
    return client.get(reverse("agenda:reserva_slots"), params, headers=HX)


def test_slots_endpoint_lists_free_times_and_marks_the_chosen_one(owner_client, espaco):
    response = slots(owner_client, espaco)
    assert "10:00" in response.context["slots"]
    assert response.context["problem"] is None
    assert "10:00 está livre" in response.content.decode()


def test_slots_endpoint_warns_about_a_conflict_before_saving(owner_client, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    response = slots(owner_client, espaco)
    assert "10:00" not in response.context["slots"]
    assert "já está reservado" in response.content.decode()


def test_slots_endpoint_frees_the_reservation_being_edited(owner_client, espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(10), at(11))
    response = slots(owner_client, espaco, reserva=reserva.pk)
    assert "10:00" in response.context["slots"]
    assert response.context["problem"] is None


def test_slots_endpoint_without_a_valid_space_shows_nothing(owner_client):
    response = owner_client.get(reverse("agenda:reserva_slots"), {"espaco": 999, "duracao": 60}, headers=HX)
    assert response.status_code == 200
    assert not response.context.get("ready")


def test_reservation_form_opens_short_when_a_free_slot_was_clicked(owner_client, espaco):
    url = reverse("agenda:reserva_create")
    params = {"espaco": espaco.pk, "data": DAY.isoformat(), "hora": "10:00", "minutos": 60}
    assert owner_client.get(url, params, headers=HX).context["slot_chosen"] is True
    assert owner_client.get(url, headers=HX).context["slot_chosen"] is False


def test_reservation_form_keeps_a_duration_outside_the_standard_options(owner_client, espaco):
    url = reverse("agenda:reserva_create")
    content = owner_client.get(url, {"espaco": espaco.pk, "minutos": 75}, headers=HX).content.decode()
    assert 'value="75"' in content
    assert "75 min" in content


def test_reservation_form_marks_the_chosen_space_and_duration(owner_client, espaco):
    url = reverse("agenda:reserva_create")
    form = owner_client.get(url, {"espaco": espaco.pk, "minutos": 90}, headers=HX).context["form"]
    assert next(option for option in form["duracao"] if option.data["selected"]).data["value"] == 90
    assert next(option for option in form["espaco"] if option.data["selected"]).data["value"] == espaco.pk


def test_block_form_offers_reasons_as_options(owner_client, espaco):
    content = owner_client.get(reverse("agenda:bloqueio_create"), headers=HX).content.decode()
    assert 'name="motivo"' in content
    assert 'value="CHUVA"' in content


def test_new_reservation_opens_on_the_first_free_time(owner_client, espaco, cliente):
    tomorrow_start = at(8, day=timezone.localdate() + timedelta(days=30))
    services.create_reservation(espaco, cliente, tomorrow_start, tomorrow_start + timedelta(hours=1))
    params = {"espaco": espaco.pk, "data": tomorrow_start.date().isoformat()}
    form = owner_client.get(reverse("agenda:reserva_create"), params, headers=HX).context["form"]
    assert form.initial["hora"] == time(9)


def test_reservation_form_stays_short_when_only_the_client_is_wrong(owner_client, espaco):
    data = payload(espaco, cliente_nome="", compacto="1")
    response = owner_client.post(reverse("agenda:reserva_create"), data, headers=HX)
    assert response.context["slot_chosen"] is True


def test_reservation_form_expands_on_a_time_error(owner_client, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    response = owner_client.post(reverse("agenda:reserva_create"), payload(espaco, compacto="1"), headers=HX)
    assert "já está reservado" in response.content.decode()
    assert response.context["slot_chosen"] is False
