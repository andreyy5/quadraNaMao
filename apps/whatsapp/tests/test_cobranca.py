"""Cobrança de contas a receber: aviso automático pelo WhatsApp, botão manual e a página do link."""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda import services as agenda_services
from apps.clientes.services import anonymize_client
from apps.financeiro import cobranca
from apps.financeiro import services as finance_services
from apps.financeiro.models import Categoria, ContaReceber, FormaPagamento
from apps.whatsapp import services
from apps.whatsapp.models import Mensagem
from conftest import DAY, at, cashier

# Terça, 04/03/2031, às 10h: dentro do horário em que a cobrança sai.
NOW = at(10)


@pytest.fixture
def ligado(tenant):
    tenant.whatsapp_ativo = True
    tenant.whatsapp_phone_number_id = "1234567890"
    tenant.cobranca_dias_antes = 2
    tenant.cobranca_dias_atraso = 3
    tenant.chave_pix = "pix@arena.test"
    tenant.pix_cidade = "Sao Paulo"
    tenant.save()
    return tenant


@pytest.fixture
def aceita(cliente):
    cliente.aceite_whatsapp = True
    cliente.save()
    return cliente


def nova_conta(tenant, cliente, vencimento=DAY, valor="120", **fields):
    return ContaReceber.all_tenants.create(
        estabelecimento=tenant,
        cliente=cliente,
        descricao="Mensalidade Areia 1",
        categoria=Categoria.MENSALIDADE,
        valor=Decimal(valor),
        vencimento=vencimento,
        **fields,
    )


def link_path(conta):
    return reverse("cobranca:conta", args=[conta.estabelecimento.slug, cobranca.account_token(conta)])


# --- Envio automático


def test_reminder_before_the_due_date_is_sent_once(ligado, aceita):
    conta = nova_conta(ligado, aceita, vencimento=DAY + timedelta(days=1))
    assert services.send_due_charges(NOW) == 1
    assert services.send_due_charges(NOW) == 0
    mensagem = Mensagem.all_tenants.get()
    assert (mensagem.template, mensagem.cliente) == ("pagamento_lembrete", aceita)
    assert mensagem.corpo.startswith(
        "Olá, João! Passando para lembrar de um pagamento na Arena-A com vencimento amanhã (05/03): "
        "Mensalidade Areia 1, no valor de R$ 120,00. Para ver os detalhes e pagar, acesse "
        f"{cobranca.account_url(conta)} ."
    )
    conta.refresh_from_db()
    assert conta.aviso_vencimento_em == NOW


def test_reminder_waits_for_the_configured_days(ligado, aceita):
    nova_conta(ligado, aceita, vencimento=DAY + timedelta(days=3))
    assert services.send_due_charges(NOW) == 0
    assert services.send_due_charges(NOW + timedelta(days=1)) == 1
    assert "com vencimento em sex., 07/03:" in Mensagem.all_tenants.get().corpo


def test_reminder_on_the_due_date(ligado, aceita):
    ligado.cobranca_dias_antes = 0
    ligado.save()
    nova_conta(ligado, aceita, vencimento=DAY + timedelta(days=1))
    assert services.send_due_charges(NOW) == 0
    nova_conta(ligado, aceita, vencimento=DAY)
    assert services.send_due_charges(NOW) == 1
    assert "com vencimento hoje (04/03):" in Mensagem.all_tenants.get().corpo


def test_overdue_notice_after_the_configured_days(ligado, aceita):
    conta = nova_conta(ligado, aceita, vencimento=DAY - timedelta(days=2))
    assert services.send_due_charges(NOW) == 0
    assert services.send_due_charges(NOW + timedelta(days=1)) == 1
    assert services.send_due_charges(NOW + timedelta(days=2)) == 0
    mensagem = Mensagem.all_tenants.get()
    assert mensagem.template == "pagamento_atrasado"
    assert mensagem.corpo.startswith(
        "Olá, João. Consta em aberto um pagamento na Arena-A que venceu em dom., 02/03:"
    )
    conta.refresh_from_db()
    assert conta.aviso_atraso_em is not None


def test_partial_payment_charges_only_what_is_left(ligado, aceita):
    conta = nova_conta(ligado, aceita, vencimento=DAY)
    finance_services.receive_account(conta, Decimal("20"), FormaPagamento.DINHEIRO, cashier(ligado))
    assert services.send_due_charges(NOW) == 1
    assert "no valor de R$ 100,00." in Mensagem.all_tenants.get().corpo


def test_old_debts_get_no_message_when_the_notice_is_turned_on(ligado, aceita):
    nova_conta(ligado, aceita, vencimento=DAY - timedelta(days=30))
    assert services.send_due_charges(NOW) == 0


@pytest.mark.parametrize("hour", [7, 20, 23])
def test_charges_only_in_business_hours(ligado, aceita, hour):
    nova_conta(ligado, aceita, vencimento=DAY)
    assert services.send_due_charges(at(hour)) == 0


@pytest.mark.parametrize(
    "situacao",
    ["sem_aceite", "desligado", "whatsapp_desligado", "paga", "recem_lancada", "reserva", "anonimizado"],
)
def test_no_charge_message(ligado, aceita, espaco, situacao):
    vencimento = DAY + timedelta(days=1)
    if situacao == "reserva":
        # A reserva tem conta própria, mas já tem confirmação e lembrete do jogo.
        agenda_services.create_reservation(espaco, aceita, at(19, day=vencimento), at(20, day=vencimento))
    else:
        conta = nova_conta(ligado, aceita, vencimento=vencimento)
    if situacao == "sem_aceite":
        aceita.aceite_whatsapp = False
        aceita.save()
    elif situacao == "desligado":
        ligado.cobranca_dias_antes = None
        ligado.save()
    elif situacao == "whatsapp_desligado":
        ligado.whatsapp_ativo = False
        ligado.save()
    elif situacao == "paga":
        finance_services.receive_account(conta, conta.valor, FormaPagamento.PIX, cashier(ligado))
    elif situacao == "recem_lancada":
        ContaReceber.all_tenants.filter(pk=conta.pk).update(criado_em=NOW - timedelta(minutes=10))
    elif situacao == "anonimizado":
        anonymize_client(aceita)
    assert services.send_due_charges(NOW) == 0
    assert not Mensagem.all_tenants.exists()


def test_new_due_date_gets_new_notices(owner_client, ligado, aceita):
    conta = nova_conta(ligado, aceita, vencimento=DAY, aviso_vencimento_em=NOW, aviso_atraso_em=NOW)
    data = {
        "descricao": conta.descricao,
        "cliente": aceita.pk,
        "categoria": "MENSALIDADE",
        "valor": "120,00",
        "vencimento": (DAY + timedelta(days=10)).isoformat(),
        "recorrencia": "NENHUMA",
        "observacoes": "",
    }
    assert owner_client.post(reverse("financeiro:receber_update", args=[conta.pk]), data).status_code == 302
    conta.refresh_from_db()
    assert (conta.aviso_vencimento_em, conta.aviso_atraso_em) == (None, None)


def test_settings_screen_saves_the_charge_notices(owner_client, ligado):
    data = {
        "whatsapp_ativo": "on",
        "whatsapp_phone_number_id": "1234567890",
        "lembrete_horas": "3",
        "cobranca_dias_antes": "",
        "cobranca_dias_atraso": "7",
    }
    page = owner_client.get(reverse("estabelecimentos:whatsapp")).content.decode()
    assert "Não lembrar" in page
    assert owner_client.post(reverse("estabelecimentos:whatsapp"), data).status_code == 302
    ligado.refresh_from_db()
    assert (ligado.cobranca_dias_antes, ligado.cobranca_dias_atraso) == (None, 7)


# --- Botão de cobrar pelo celular de quem atende


@pytest.mark.parametrize("modulo", [True, False])
def test_charge_button_opens_whatsapp_with_the_message(owner_client, tenant, cliente, modulo):
    conta = nova_conta(tenant, cliente, vencimento=timezone.localdate() + timedelta(days=1))
    with override_settings(WHATSAPP_ENABLED=modulo):
        content = owner_client.get(reverse("financeiro:receber")).content.decode()
    assert f"https://wa.me/{cliente.telefone.removeprefix('+')}?text=" in content
    assert quote("Passando para lembrar de um pagamento na Arena-A com vencimento amanhã") in content
    assert quote(cobranca.account_url(conta)) in content
    # O botão não manda nada pelo sistema: quem envia é a pessoa.
    assert not Mensagem.all_tenants.exists()


def test_no_charge_button_for_a_game_that_has_not_happened(owner_client, espaco, cliente):
    amanha = timezone.localdate() + timedelta(days=1)
    agenda_services.create_reservation(espaco, cliente, at(19, day=amanha), at(20, day=amanha))
    content = owner_client.get(reverse("financeiro:receber")).content.decode()
    assert "Reserva Areia 1" in content
    assert 'aria-label="Cobrar' not in content


# --- Página do link


def test_link_page_shows_the_pix_of_what_is_left(client, ligado, cliente):
    conta = nova_conta(ligado, cliente)
    finance_services.receive_account(conta, Decimal("20"), FormaPagamento.DINHEIRO, cashier(ligado))
    conta.refresh_from_db()
    response = client.get(link_path(conta))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Mensalidade Areia 1" in content
    assert "Já recebemos R$ 20,00 de R$ 120,00." in content
    codigo = cobranca.pix_code(conta)
    assert "5406100.00" in codigo
    assert codigo in content
    assert "<svg" in content


def test_link_page_without_pix_key(client, tenant, cliente):
    conta = nova_conta(tenant, cliente)
    content = client.get(link_path(conta)).content.decode()
    assert "Para pagar, fale com a equipe" in content
    assert "Pix copia e cola" not in content


@pytest.mark.parametrize("status", ["paga", "cancelada"])
def test_link_page_after_the_account_is_closed(client, ligado, cliente, status):
    conta = nova_conta(ligado, cliente)
    if status == "paga":
        finance_services.receive_account(conta, conta.valor, FormaPagamento.PIX, cashier(ligado))
        expected = "Pagamento recebido"
    else:
        finance_services.cancel_account(conta)
        expected = "não está mais valendo"
    content = client.get(link_path(conta)).content.decode()
    assert expected in content
    assert "Pix copia e cola" not in content


def test_link_only_opens_with_a_valid_token_on_its_own_establishment(client, ligado, other_tenant, cliente):
    conta = nova_conta(ligado, cliente)
    token = cobranca.account_token(conta)
    assert client.get(reverse("cobranca:conta", args=[ligado.slug, token + "x"])).status_code == 404
    assert client.get(reverse("cobranca:conta", args=[other_tenant.slug, token])).status_code == 404
