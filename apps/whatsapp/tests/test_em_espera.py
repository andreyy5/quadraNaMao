"""Com WHATSAPP_ENABLED desligado (o padrão), o módulo fica em espera: some das telas e não manda nada."""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.whatsapp import services
from apps.whatsapp.models import Mensagem

pytestmark = pytest.mark.usefixtures("off")


@pytest.fixture
def off():
    with override_settings(WHATSAPP_ENABLED=False):
        yield


@pytest.fixture
def ligado_na_loja(tenant, cliente):
    tenant.whatsapp_ativo = True
    tenant.reserva_online_ativa = True
    tenant.save()
    cliente.aceite_whatsapp = True
    cliente.save()
    return tenant


def test_menu_and_settings_hide_whatsapp(owner_client, ligado_na_loja):
    page = owner_client.get(reverse("relatorios:dashboard")).content.decode()
    assert reverse("whatsapp:conversas") not in page
    assert (
        reverse("estabelecimentos:whatsapp")
        not in owner_client.get(reverse("estabelecimentos:ajustes")).content.decode()
    )
    # O botão de chamar no WhatsApp pelo celular continua: não depende do módulo.
    assert owner_client.get(reverse("clientes:list")).status_code == 200


@pytest.mark.parametrize("url", ["whatsapp:conversas", "whatsapp:webhook", "estabelecimentos:whatsapp"])
def test_screens_do_not_exist(owner_client, url):
    assert owner_client.get(reverse(url)).status_code == 404


def test_nothing_is_sent(ligado_na_loja, espaco, cliente, django_capture_on_commit_callbacks):
    inicio = timezone.now() + timedelta(hours=2)
    with django_capture_on_commit_callbacks(execute=True):
        agenda_services.create_reservation(espaco, cliente, inicio, inicio + timedelta(hours=1))
    assert services.send_due_reminders() == 0
    assert services.send_due_charges() == 0
    assert not Mensagem.all_tenants.exists()


def test_public_link_does_not_ask_for_whatsapp_consent(client, ligado_na_loja, espaco):
    content = client.get(reverse("publico:reservar", args=[ligado_na_loja.slug])).content.decode()
    assert 'name="aceite_whatsapp"' not in content


def test_block_notice_button_is_gone(owner_client, ligado_na_loja):
    assert owner_client.post(reverse("agenda:bloqueio_avisar"), {"ids": "1"}).status_code == 404
