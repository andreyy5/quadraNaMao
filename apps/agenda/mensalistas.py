"""Mensalistas: o horário fixo vira reservas de verdade algumas semanas à frente.

Quando uma semana não pode ser reservada (bloqueio, outra reserva, espaço fechado), fica um aviso
para o dono, em vez de falhar calado (planner, seção 6.1).
"""

import calendar
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.financeiro.models import Categoria, ContaBase, ContaReceber

from .models import Mensalista, MensalistaAviso, Reserva
from .services import ReservationError, cancel_reservation, create_reservation

HORIZON_WEEKS = 8
SCHEDULE_FIELDS = (
    "espaco_id",
    "dia_semana",
    "hora",
    "duracao_minutos",
    "data_inicio",
    "data_fim",
    "cobranca",
    "valor",
)


def _today(mensalista):
    return timezone.now().astimezone(mensalista.estabelecimento.timezone).date()


def _first_weekday(start, weekday):
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _next_due(after, day):
    """Primeiro vencimento no dia escolhido, a partir de `after`."""
    month_day = min(day, calendar.monthrange(after.year, after.month)[1])
    candidate = after.replace(day=month_day)
    if candidate >= after:
        return candidate
    year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def generate_reservations(mensalista, until=None):
    """Cria as reservas que faltam até o horizonte. Não duplica e não insiste em semanas com aviso."""
    tz = mensalista.estabelecimento.timezone
    today = _today(mensalista)
    until = until or today + timedelta(weeks=HORIZON_WEEKS)
    if mensalista.data_fim:
        until = min(until, mensalista.data_fim)
    start = max(mensalista.data_inicio, today)
    existing = {
        inicio.astimezone(tz).date()
        for inicio in Reserva.all_tenants.filter(mensalista=mensalista).values_list("inicio", flat=True)
    }
    warned = set(MensalistaAviso.all_tenants.filter(mensalista=mensalista).values_list("data", flat=True))
    valor = mensalista.valor if mensalista.cobranca == Mensalista.Cobranca.POR_JOGO else 0
    created = 0
    day = _first_weekday(start, mensalista.dia_semana)
    while day <= until:
        if day not in existing and day not in warned:
            inicio = datetime.combine(day, mensalista.hora, tzinfo=tz)
            if inicio > timezone.now():
                try:
                    create_reservation(
                        mensalista.espaco,
                        mensalista.cliente,
                        inicio,
                        inicio + timedelta(minutes=mensalista.duracao_minutos),
                        valor_total=valor,
                        usuario=mensalista.criado_por,
                        origem=Reserva.Origem.MENSALISTA,
                        mensalista=mensalista,
                        notify=False,
                    )
                    created += 1
                except ReservationError as exc:
                    MensalistaAviso.all_tenants.get_or_create(
                        estabelecimento_id=mensalista.estabelecimento_id,
                        mensalista=mensalista,
                        data=day,
                        defaults={"motivo": str(exc)[:200]},
                    )
        day += timedelta(weeks=1)
    Mensalista.all_tenants.filter(pk=mensalista.pk).update(gerado_ate=until)
    return created


def _setup_billing(mensalista):
    """Na cobrança mensal, uma conta a receber que se repete todo mês. Por jogo, cada reserva tem a sua."""
    if mensalista.cobranca != Mensalista.Cobranca.MENSAL or mensalista.conta_mensal_id:
        return
    conta = ContaReceber.all_tenants.create(
        estabelecimento_id=mensalista.estabelecimento_id,
        cliente=mensalista.cliente,
        categoria=Categoria.MENSALIDADE,
        descricao=f"Mensalidade {mensalista.espaco.nome} · {mensalista.get_dia_semana_display()} {mensalista.hora:%H:%M}",
        valor=mensalista.valor,
        vencimento=_next_due(mensalista.data_inicio, mensalista.dia_vencimento),
        recorrencia=ContaBase.Recorrencia.MENSAL,
        criado_por=mensalista.criado_por,
    )
    mensalista.conta_mensal = conta
    mensalista.save(update_fields=["conta_mensal", "atualizado_em"])


def _stop_billing(mensalista):
    if mensalista.conta_mensal_id:
        ContaReceber.all_tenants.filter(pk=mensalista.conta_mensal_id).update(
            recorrencia=ContaBase.Recorrencia.NENHUMA
        )


def _cancel_future(mensalista, after, usuario, motivo, detach=False):
    """Cancela as reservas futuras ainda em aberto do mensalista, a partir do dia seguinte a `after`.

    Com `detach`, as canceladas saem do mensalista, para a geração refazer aquelas semanas no horário
    novo. Um jogo que a equipe cancelou antes continua ligado e a semana continua pulada.
    """
    tz = mensalista.estabelecimento.timezone
    limite = datetime.combine(after + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    cancelled = 0
    for reserva in Reserva.all_tenants.filter(
        mensalista=mensalista,
        inicio__gte=max(limite, timezone.now()),
        status__in=[Reserva.Status.PENDENTE, Reserva.Status.CONFIRMADA],
    ):
        cancel_reservation(reserva, usuario, motivo, notify=False)
        if detach:
            Reserva.all_tenants.filter(pk=reserva.pk).update(mensalista=None)
        cancelled += 1
    MensalistaAviso.all_tenants.filter(mensalista=mensalista, data__gt=after).delete()
    return cancelled


@transaction.atomic
def create_mensalista(mensalista, usuario=None):
    mensalista.criado_por = usuario
    mensalista.save()
    _setup_billing(mensalista)
    generate_reservations(mensalista)
    return mensalista


@transaction.atomic
def update_mensalista(mensalista, before, usuario=None):
    """Mudou o horário, o espaço, as datas ou o valor: refaz as reservas futuras com os dados novos."""
    mensalista.save()
    if any(getattr(before, field) != getattr(mensalista, field) for field in SCHEDULE_FIELDS):
        _cancel_future(
            mensalista, _today(mensalista) - timedelta(days=1), usuario, "Mensalista alterado", detach=True
        )
        if before.cobranca != mensalista.cobranca or before.valor != mensalista.valor:
            _stop_billing(mensalista)
            mensalista.conta_mensal = None
            mensalista.save(update_fields=["conta_mensal", "atualizado_em"])
            _setup_billing(mensalista)
        generate_reservations(mensalista)
    return mensalista


@transaction.atomic
def end_mensalista(mensalista, data_fim, usuario=None):
    """Encerra: cancela os jogos depois da data e para a cobrança mensal. O histórico fica."""
    mensalista.data_fim = data_fim
    mensalista.save(update_fields=["data_fim", "atualizado_em"])
    cancelled = _cancel_future(mensalista, data_fim, usuario, "Mensalista encerrado")
    _stop_billing(mensalista)
    return cancelled


def generate_all(estabelecimento=None):
    """Rotina diária: mantém as próximas semanas reservadas para todos os mensalistas em vigor."""
    queryset = Mensalista.all_tenants.select_related("estabelecimento", "espaco", "cliente")
    if estabelecimento is not None:
        queryset = queryset.filter(estabelecimento=estabelecimento)
    total = 0
    for mensalista in queryset:
        if mensalista.data_fim is None or mensalista.data_fim >= _today(mensalista):
            total += generate_reservations(mensalista)
    return total
