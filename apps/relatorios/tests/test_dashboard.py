from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.agenda import services
from apps.relatorios.services import setup_checklist
from conftest import TZ, make_espaco


def test_empty_dashboard_shows_checklist_for_owner(owner_client):
    response = owner_client.get(reverse("relatorios:dashboard"))
    assert response.status_code == 200
    assert "Primeiros passos" in response.content.decode()


def test_attendant_does_not_see_checklist(client, attendant):
    client.force_login(attendant)
    assert "Primeiros passos" not in client.get(reverse("relatorios:dashboard")).content.decode()


def test_checklist_disappears_when_setup_is_done(tenant, espaco, cliente):
    assert setup_checklist(tenant)[3]["done"] is False
    start = datetime.combine(timezone.localdate() + timedelta(days=30), time(10), tzinfo=TZ)
    services.create_reservation(espaco, cliente, start, start + timedelta(hours=1))
    assert setup_checklist(tenant) is None


def test_dashboard_lists_todays_reservation(owner_client, tenant, cliente):
    # Abre o dia inteiro para o teste passar em qualquer horário.
    espaco = make_espaco(tenant, "24 horas", abre=time(0), fecha=time(0))
    now = timezone.now().astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    start = now + timedelta(hours=1)
    if start.date() != now.date():
        start = now
    services.create_reservation(espaco, cliente, start, start + timedelta(hours=1))
    response = owner_client.get(reverse("relatorios:dashboard"))
    assert len(response.context["summary"]["reservas"]) == 1
    assert cliente.nome in response.content.decode()
