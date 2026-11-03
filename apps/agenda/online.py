"""Reserva pelo link público e o sinal por Pix.

O cliente escolhe um horário livre, informa nome e WhatsApp e, se a faixa de preço tiver sinal e o
estabelecimento tiver chave Pix, a reserva nasce pendente, com prazo para pagar. Pago o sinal, ela é
confirmada; vencido o prazo, é cancelada e o horário volta a ficar livre.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.clientes.services import find_or_create_client
from apps.espacos.models import Espaco
from apps.espacos.services import load_schedule
from apps.financeiro.models import ContaReceber, FormaPagamento, Pagamento
from apps.financeiro.services import create_pix_charge, online_register, receive_account
from apps.whatsapp.services import notify_reservation

from .models import Reserva
from .services import confirm_reservation, create_reservation, expire_pending_reservations, free_starts

BOOKING_DAYS_AHEAD = 30
TOKEN_SALT = "pagamento-pix"


class OnlineBookingError(Exception):
    """A mensagem pode ser mostrada ao cliente."""


def public_spaces(estabelecimento):
    return list(Espaco.all_tenants.filter(estabelecimento=estabelecimento, ativo=True))


def booking_days(estabelecimento):
    today = timezone.now().astimezone(estabelecimento.timezone).date()
    return [today + timedelta(days=offset) for offset in range(BOOKING_DAYS_AHEAD)]


def slot_minutes(espaco, day):
    """Duração do horário vendido pelo link: a da faixa de preço do dia, ou uma hora."""
    schedule = load_schedule(espaco)
    period = schedule.period(day)
    return schedule.slot_minutes(period[0], day) if period else 60


def public_starts(espaco, day):
    if day not in booking_days(espaco.estabelecimento):
        return []
    return free_starts(espaco, day, slot_minutes(espaco, day))


def deposit_for(espaco, inicio):
    regra = load_schedule(espaco).rule_at(inicio)
    return regra.valor_sinal if regra and regra.valor_sinal else Decimal("0")


def payment_token(pagamento):
    return signing.dumps(pagamento.pk, salt=TOKEN_SALT)


def payment_from_token(token):
    try:
        pk = signing.loads(token, salt=TOKEN_SALT)
    except signing.BadSignature:
        return None
    return (
        Pagamento.all_tenants.select_related("reserva__espaco", "reserva__cliente", "estabelecimento")
        .filter(pk=pk)
        .first()
    )


def payment_url(pagamento):
    path = reverse("publico:pagamento", args=[pagamento.estabelecimento.slug, payment_token(pagamento)])
    return settings.SITE_URL.rstrip("/") + path


@transaction.atomic
def book_online(estabelecimento, espaco, inicio, nome, telefone, aceite_whatsapp=False):
    """Cria a reserva do link público. Devolve (reserva, pagamento); sem sinal, o pagamento é None."""
    if not estabelecimento.reserva_online_ativa:
        raise OnlineBookingError("Este estabelecimento não está recebendo reservas pelo link agora.")
    if espaco.estabelecimento_id != estabelecimento.pk or not espaco.ativo:
        raise OnlineBookingError("Escolha um dos espaços da lista.")
    if not nome.strip():
        raise OnlineBookingError("Informe seu nome.")

    expire_pending_reservations(estabelecimento)
    local_day = inicio.astimezone(estabelecimento.timezone).date()
    if inicio not in public_starts(espaco, local_day):
        raise OnlineBookingError("Esse horário acabou de ser ocupado. Escolha outro.")

    cliente = find_or_create_client(estabelecimento, nome, telefone)
    if aceite_whatsapp and not cliente.aceite_whatsapp:
        cliente.aceite_whatsapp = True
        cliente.save(update_fields=["aceite_whatsapp", "atualizado_em"])
    if Reserva.all_tenants.filter(cliente=cliente, status=Reserva.Status.PENDENTE).exists():
        raise OnlineBookingError(
            "Você já tem uma reserva aguardando o pagamento do sinal. Pague ou espere o prazo."
        )

    fim = inicio + timedelta(minutes=slot_minutes(espaco, local_day))
    sinal = deposit_for(espaco, inicio)
    if sinal <= 0 or not estabelecimento.chave_pix:
        reserva = create_reservation(espaco, cliente, inicio, fim, origem=Reserva.Origem.ONLINE)
        return reserva, None

    expira_em = timezone.now() + timedelta(minutes=estabelecimento.prazo_sinal_minutos)
    reserva = create_reservation(
        espaco,
        cliente,
        inicio,
        fim,
        origem=Reserva.Origem.ONLINE,
        status=Reserva.Status.PENDENTE,
        expira_em=expira_em,
        valor_sinal=sinal,
    )
    pagamento = create_pix_charge(reserva, sinal, expira_em)
    url = payment_url(pagamento)
    transaction.on_commit(lambda: notify_reservation(reserva.pk, "pendente", payment_url=url))
    return reserva, pagamento


@transaction.atomic
def confirm_pix_payment(pagamento):
    """Pagamento avisado pelo provedor: entra no caixa online e confirma a reserva.

    Se o aviso chegar depois do prazo, a reserva já foi cancelada e o horário pode ter sido vendido:
    o pagamento fica marcado para a equipe resolver (devolver ou remarcar), sem confirmar nada sozinho.
    """
    pagamento = Pagamento.all_tenants.select_for_update().get(pk=pagamento.pk)
    if pagamento.status in (Pagamento.Status.PAGO, Pagamento.Status.PAGO_ATRASADO):
        return pagamento
    reserva = Reserva.all_tenants.select_related("estabelecimento").get(pk=pagamento.reserva_id)
    pagamento.pago_em = timezone.now()
    if reserva.status != Reserva.Status.PENDENTE:
        pagamento.status = Pagamento.Status.PAGO_ATRASADO
        pagamento.save(update_fields=["status", "pago_em", "atualizado_em"])
        return pagamento
    conta = ContaReceber.all_tenants.get(reserva=reserva)
    lancamento = receive_account(
        conta, pagamento.valor, FormaPagamento.PIX, None, caixa=online_register(reserva.estabelecimento)
    )
    pagamento.status = Pagamento.Status.PAGO
    pagamento.lancamento = lancamento
    pagamento.save(update_fields=["status", "pago_em", "lancamento", "atualizado_em"])
    confirm_reservation(reserva, detalhes="Pix confirmado pelo provedor")
    return pagamento


def settle_manual_deposit(reserva, lancamento, usuario):
    """A equipe recebeu o sinal pelo painel (Pix estático ou dinheiro): confirma quando ele estiver pago."""
    reserva = Reserva.all_tenants.get(pk=reserva.pk)
    if reserva.status != Reserva.Status.PENDENTE or reserva.valor_pago < reserva.valor_sinal:
        return reserva
    Pagamento.all_tenants.filter(reserva=reserva, status=Pagamento.Status.PENDENTE).update(
        status=Pagamento.Status.PAGO, pago_em=timezone.now(), lancamento=lancamento
    )
    return confirm_reservation(reserva, usuario, "Sinal recebido no balcão")


def parse_start(estabelecimento, data, hora):
    """Data e hora escolhidas no link, no fuso do estabelecimento."""
    return datetime.combine(data, hora, tzinfo=estabelecimento.timezone)
