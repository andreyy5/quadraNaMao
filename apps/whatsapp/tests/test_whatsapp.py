import hashlib
import hmac
import io
import json
import urllib.error
from datetime import datetime, time, timedelta
from unittest import mock

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.agenda.models import Bloqueio
from apps.clientes.services import anonymize_client
from apps.whatsapp import services
from apps.whatsapp.models import Mensagem
from apps.whatsapp.provider import CloudAPIProvider, ProviderError
from conftest import TZ, make_cliente, make_espaco

HX = {"HX-Request": "true"}


@pytest.fixture
def ligado(tenant):
    tenant.whatsapp_ativo = True
    tenant.whatsapp_phone_number_id = "1234567890"
    tenant.save()
    return tenant


@pytest.fixture
def aceita(cliente):
    cliente.aceite_whatsapp = True
    cliente.save()
    return cliente


def futuro(hours=26):
    inicio = (
        (timezone.now() + timedelta(hours=hours)).astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    )
    return inicio, inicio + timedelta(hours=1)


@pytest.fixture
def espaco_24h(tenant):
    return make_espaco(tenant, "24 horas", abre=time(0), fecha=time(0))


def reservar(espaco, cliente, hours=26, capture=None):
    inicio, fim = futuro(hours)
    if capture is None:
        return agenda_services.create_reservation(espaco, cliente, inicio, fim)
    with capture(execute=True):
        return agenda_services.create_reservation(espaco, cliente, inicio, fim)


# --- Quando mandar


def test_confirmation_goes_to_clients_who_accepted(
    ligado, espaco_24h, aceita, django_capture_on_commit_callbacks
):
    reserva = reservar(espaco_24h, aceita, capture=django_capture_on_commit_callbacks)
    mensagem = Mensagem.all_tenants.get()
    assert (mensagem.template, mensagem.status, mensagem.reserva) == (
        "reserva_confirmada",
        "ENVIADA",
        reserva,
    )
    assert mensagem.corpo.startswith("Olá, João! Sua reserva em Arena-A está confirmada")
    assert mensagem.wa_id.startswith("console-")
    assert "{{" not in mensagem.corpo


@pytest.mark.parametrize("situacao", ["sem_aceite", "desligado", "passado"])
def test_no_automatic_message(tenant, espaco_24h, cliente, situacao, django_capture_on_commit_callbacks):
    tenant.whatsapp_ativo = situacao != "desligado"
    tenant.save()
    cliente.aceite_whatsapp = situacao != "sem_aceite"
    cliente.save()
    reservar(
        espaco_24h,
        cliente,
        hours=-3 if situacao == "passado" else 26,
        capture=django_capture_on_commit_callbacks,
    )
    assert not Mensagem.all_tenants.exists()


def test_cancellation_and_reschedule_messages(ligado, espaco_24h, aceita, django_capture_on_commit_callbacks):
    reserva = reservar(espaco_24h, aceita, capture=django_capture_on_commit_callbacks)
    inicio, fim = futuro(30)
    with django_capture_on_commit_callbacks(execute=True):
        agenda_services.update_reservation(reserva, espaco_24h, aceita, inicio, fim, reserva.valor_total)
    with django_capture_on_commit_callbacks(execute=True):
        agenda_services.cancel_reservation(reserva)
    templates = list(Mensagem.all_tenants.order_by("pk").values_list("template", flat=True))
    assert templates == ["reserva_confirmada", "reserva_confirmada", "reserva_cancelada"]


def test_reminder_is_sent_once(ligado, espaco_24h, aceita):
    reserva = reservar(espaco_24h, aceita, hours=2)
    Mensagem.all_tenants.all().delete()
    assert services.send_due_reminders() == 1
    assert services.send_due_reminders() == 0
    mensagem = Mensagem.all_tenants.get()
    assert mensagem.template == "lembrete_reserva"
    reserva.refresh_from_db()
    assert reserva.lembrete_enviado_em is not None


def test_reminder_respects_the_configured_hours(ligado, espaco_24h, aceita):
    reservar(espaco_24h, aceita, hours=5)
    assert services.send_due_reminders() == 0
    ligado.lembrete_horas = 0
    ligado.save()
    reservar(espaco_24h, aceita, hours=1)
    assert services.send_due_reminders() == 0


def test_block_notice_from_the_impact_screen(owner_client, ligado, espaco_24h, aceita):
    reserva = reservar(espaco_24h, aceita)
    Mensagem.all_tenants.all().delete()
    bloqueio, _ = agenda_services.create_block(espaco_24h, reserva.inicio, reserva.fim, Bloqueio.Motivo.CHUVA)
    response = owner_client.post(reverse("agenda:bloqueio_avisar"), {"ids": str(bloqueio.pk)})
    assert response.status_code == 302
    mensagem = Mensagem.all_tenants.get()
    assert mensagem.template == "aviso_remarcacao"
    assert "chuva" in mensagem.corpo


# --- Provedor da Meta


def fake_response(payload):
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return response


@override_settings(WHATSAPP_ACCESS_TOKEN="token-x", WHATSAPP_API_VERSION="v21.0")
def test_cloud_provider_sends_the_template_with_parameters():
    with mock.patch(
        "urllib.request.urlopen", return_value=fake_response({"messages": [{"id": "wamid.1"}]})
    ) as call:
        wa_id = CloudAPIProvider().send(
            phone_number_id="999", to="+5511977770001", template="lembrete_reserva", params=["João", "19:00"]
        )
    request = call.call_args.args[0]
    body = json.loads(request.data)
    assert wa_id == "wamid.1"
    assert request.full_url == "https://graph.facebook.com/v21.0/999/messages"
    assert request.headers["Authorization"] == "Bearer token-x"
    assert body["to"] == "5511977770001"
    assert body["template"]["language"]["code"] == "pt_BR"
    assert body["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "João"},
        {"type": "text", "text": "19:00"},
    ]


@override_settings(WHATSAPP_ACCESS_TOKEN="token-x")
def test_cloud_provider_reports_meta_errors():
    error = urllib.error.HTTPError(
        "url",
        400,
        "Bad Request",
        {},
        io.BytesIO(json.dumps({"error": {"message": "Template não aprovado"}}).encode()),
    )
    with mock.patch("urllib.request.urlopen", side_effect=error), pytest.raises(
        ProviderError, match="400: Template"
    ):
        CloudAPIProvider().send(phone_number_id="999", to="+5511977770001", text="oi")


def test_cloud_provider_without_credentials_fails_clearly():
    with pytest.raises(ProviderError, match="não configurado"):
        CloudAPIProvider().send(phone_number_id="", to="+5511977770001", text="oi")


@override_settings(WHATSAPP_PROVIDER="cloud", WHATSAPP_ACCESS_TOKEN="")
def test_failed_delivery_is_recorded(ligado, espaco_24h, aceita, django_capture_on_commit_callbacks):
    reservar(espaco_24h, aceita, capture=django_capture_on_commit_callbacks)
    mensagem = Mensagem.all_tenants.get()
    assert mensagem.status == "FALHOU"
    assert "não configurado" in mensagem.erro


# --- Webhook


def signed_post(client, payload, secret="segredo-de-teste"):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        reverse("whatsapp:webhook"),
        body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": signature},
    )


def inbound(phone_number_id, wa_id, texto, numero="5511987650001"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {"from": numero, "id": wa_id, "type": "text", "text": {"body": texto}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


def status_update(wa_id, status, **extra):
    return {"entry": [{"changes": [{"value": {"statuses": [{"id": wa_id, "status": status, **extra}]}}]}]}


def test_webhook_verification(client):
    url = reverse("whatsapp:webhook")
    ok = client.get(
        url, {"hub.mode": "subscribe", "hub.verify_token": "token-de-teste", "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.content == b"42"
    bad = client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_webhook_rejects_unsigned_or_forged_requests(client, ligado):
    payload = inbound("1234567890", "wamid.x", "oi")
    assert (
        client.post(reverse("whatsapp:webhook"), payload, content_type="application/json").status_code == 403
    )
    assert signed_post(client, payload, secret="outro").status_code == 403
    assert not Mensagem.all_tenants.exists()


def test_delivery_status_only_moves_forward(
    client, ligado, espaco_24h, aceita, django_capture_on_commit_callbacks
):
    reservar(espaco_24h, aceita, capture=django_capture_on_commit_callbacks)
    mensagem = Mensagem.all_tenants.get()
    signed_post(client, status_update(mensagem.wa_id, "read"))
    signed_post(client, status_update(mensagem.wa_id, "delivered"))
    mensagem.refresh_from_db()
    assert mensagem.status == "LIDA"
    signed_post(client, status_update(mensagem.wa_id, "failed", errors=[{"title": "Número inválido"}]))
    mensagem.refresh_from_db()
    assert (mensagem.status, mensagem.erro) == ("FALHOU", "Número inválido")


def test_inbound_message_is_stored_once_and_opens_the_window(client, ligado, aceita):
    assert signed_post(client, inbound("1234567890", "wamid.in1", "Tem horário amanhã?")).status_code == 200
    signed_post(client, inbound("1234567890", "wamid.in1", "Tem horário amanhã?"))
    mensagem = Mensagem.all_tenants.get()
    assert (mensagem.direcao, mensagem.cliente, mensagem.corpo) == ("ENTRADA", aceita, "Tem horário amanhã?")
    assert services.window_open(ligado, aceita.telefone)


def test_opt_out_and_back_in_by_message(client, ligado, aceita):
    signed_post(client, inbound("1234567890", "wamid.a", "SAIR"))
    aceita.refresh_from_db()
    assert aceita.aceite_whatsapp is False
    assert Mensagem.all_tenants.filter(direcao="SAIDA", corpo__contains="VOLTAR").exists()

    signed_post(client, inbound("1234567890", "wamid.b", "Voltar"))
    aceita.refresh_from_db()
    assert aceita.aceite_whatsapp is True


def test_inbound_for_another_number_does_not_reach_this_establishment(client, ligado, other_tenant):
    other_tenant.whatsapp_ativo = True
    other_tenant.whatsapp_phone_number_id = "555"
    other_tenant.save()
    signed_post(client, inbound("555", "wamid.z", "oi"))
    signed_post(client, inbound("desconhecido", "wamid.y", "oi"))
    assert list(Mensagem.all_tenants.values_list("estabelecimento_id", flat=True)) == [other_tenant.pk]


# --- Conversas e respostas


def test_reply_only_inside_the_24h_window(owner_client, client, ligado, aceita):
    url = reverse("whatsapp:conversa", args=[aceita.telefone.lstrip("+")])
    signed_post(client, inbound("1234567890", "wamid.c", "Oi"))
    owner_client.post(url, {"texto": "Temos sim, às 19h."})
    assert Mensagem.all_tenants.filter(direcao="SAIDA", corpo="Temos sim, às 19h.").exists()

    Mensagem.all_tenants.filter(direcao="ENTRADA").update(criado_em=timezone.now() - timedelta(hours=25))
    with pytest.raises(services.WhatsAppError, match="24 horas"):
        services.reply(ligado, aceita.telefone, "Ainda dá?", None)


def test_conversations_are_isolated(owner_client, client, ligado, other_tenant):
    other_tenant.whatsapp_ativo = True
    other_tenant.whatsapp_phone_number_id = "555"
    other_tenant.save()
    make_cliente(other_tenant, "Cliente Alheio", "+5511977770000")
    signed_post(client, inbound("555", "wamid.w", "segredo", numero="5511977770000"))
    assert "Cliente Alheio" not in owner_client.get(reverse("whatsapp:conversas")).content.decode()
    assert owner_client.get(reverse("whatsapp:conversa", args=["5511977770000"])).status_code == 404


def test_anonymizing_a_client_erases_message_contents(
    ligado, espaco_24h, aceita, django_capture_on_commit_callbacks
):
    reservar(espaco_24h, aceita, capture=django_capture_on_commit_callbacks)
    anonymize_client(aceita)
    mensagem = Mensagem.all_tenants.get()
    assert mensagem.corpo == "" and mensagem.parametros == [] and "98765" not in mensagem.telefone


# --- Ajustes


def test_settings_save_and_test_message(owner_client, tenant):
    url = reverse("estabelecimentos:whatsapp")
    data = {"whatsapp_ativo": "on", "whatsapp_phone_number_id": "1234567890", "lembrete_horas": 3}
    assert owner_client.post(url, data).status_code == 302
    tenant.refresh_from_db()
    assert tenant.whatsapp_ativo and tenant.whatsapp_phone_number_id == "1234567890"

    owner_client.post(url, {"teste": "1", "telefone": "(11) 98888-7777"})
    mensagem = Mensagem.all_tenants.get()
    assert (mensagem.template, mensagem.telefone, mensagem.status) == (
        "hello_world",
        "+5511988887777",
        "ENVIADA",
    )


def test_phone_number_id_belongs_to_one_establishment(owner_client, other_tenant):
    other_tenant.whatsapp_phone_number_id = "777"
    other_tenant.save()
    data = {"whatsapp_ativo": "on", "whatsapp_phone_number_id": "777", "lembrete_horas": 3}
    content = owner_client.post(reverse("estabelecimentos:whatsapp"), data).content.decode()
    assert "já está ligado a outro estabelecimento" in content


def test_attendant_cannot_change_whatsapp_settings(client, attendant):
    client.force_login(attendant)
    assert client.get(reverse("estabelecimentos:whatsapp")).status_code == 403
    assert client.get(reverse("whatsapp:conversas")).status_code == 200


def test_reservation_in_the_past_never_gets_a_reminder(ligado, espaco_24h, aceita):
    inicio = datetime.combine(timezone.localdate() - timedelta(days=1), time(10), tzinfo=TZ)
    agenda_services.create_reservation(espaco_24h, aceita, inicio, inicio + timedelta(hours=1))
    assert services.send_due_reminders() == 0
