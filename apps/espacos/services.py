"""Regras de horário e preço de um espaço, e as modalidades que ele atende."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.text import slugify

from .models import DiaSemana, HorarioFuncionamento, TabelaPreco

DEFAULT_SLOT_MINUTES = 60
MINUTES_IN_DAY = 24 * 60


class PriceRuleOverlap(Exception):
    def __init__(self, dia_semana_label):
        super().__init__(f"Já existe uma faixa de preço nesse horário na {dia_semana_label}.")


def _to_minutes(value):
    return value.hour * 60 + value.minute


def _rule_range(rule):
    """Faixa em minutos desde a meia-noite do dia de operação. Fim <= início vira o dia."""
    start = _to_minutes(rule.hora_inicio)
    end = _to_minutes(rule.hora_fim)
    if end <= start:
        end += MINUTES_IN_DAY
    return start, end


class Schedule:
    """Horários e preços de um espaço, já carregados, para consultas sem novas queries."""

    def __init__(self, horarios, regras, tz):
        self.tz = tz
        self.horarios = {horario.dia_semana: horario for horario in horarios}
        self.regras = defaultdict(list)
        for regra in regras:
            self.regras[regra.dia_semana].append(regra)

    def midnight(self, day):
        return datetime.combine(day, time.min, tzinfo=self.tz)

    def period(self, day):
        """Abertura e fechamento do dia, ou None se o espaço não abre."""
        horario = self.horarios.get(day.weekday())
        if horario is None:
            return None
        opens = datetime.combine(day, horario.abre, tzinfo=self.tz)
        closes_on = day if horario.fecha > horario.abre else day + timedelta(days=1)
        return opens, datetime.combine(closes_on, horario.fecha, tzinfo=self.tz)

    def operating_day(self, moment):
        """Dia ao qual o instante pertence: 00:30 de sábado pode ser ainda a sexta-feira."""
        local = moment.astimezone(self.tz)
        previous = local.date() - timedelta(days=1)
        period = self.period(previous)
        if period and period[0] <= local < period[1]:
            return previous
        return local.date()

    def contains(self, inicio, fim):
        period = self.period(self.operating_day(inicio))
        return period is not None and period[0] <= inicio and fim <= period[1]

    def rule_at(self, moment, day=None):
        day = day or self.operating_day(moment)
        offset = (moment.astimezone(self.tz) - self.midnight(day)).total_seconds() / 60
        for regra in self.regras[day.weekday()]:
            start, end = _rule_range(regra)
            if start <= offset < end:
                return regra
        return None

    def slot_minutes(self, moment, day=None):
        regra = self.rule_at(moment, day)
        return regra.duracao_slot_minutos if regra else DEFAULT_SLOT_MINUTES

    def quote(self, inicio, fim):
        """Valor do período, proporcional aos minutos. None se algum trecho não tem preço."""
        day = self.operating_day(inicio)
        total = Decimal("0")
        cursor = inicio
        while cursor < fim:
            regra = self.rule_at(cursor, day)
            if regra is None:
                return None
            rule_end = self.midnight(day) + timedelta(minutes=_rule_range(regra)[1])
            chunk_end = min(fim, rule_end)
            minutes = Decimal(int((chunk_end - cursor).total_seconds() / 60))
            total += regra.valor * minutes / regra.duracao_slot_minutos
            cursor = chunk_end
        return total.quantize(Decimal("0.01"))


# Espaço sem modalidade cadastrada vale pelo tipo.
TIPO_COMO_MODALIDADE = {"CAMPO": "Campo", "QUADRA": "Quadra", "AREIA": "Areia"}


def space_modalities(espaco):
    """Modalidades do espaço, na grafia do cadastro ("Beach tênis, futevôlei")."""
    labels = [part.strip() for part in re.split(r"[,;/]", espaco.modalidades) if part.strip()]
    return labels or [TIPO_COMO_MODALIDADE[espaco.tipo]]


@dataclass
class Modalidade:
    """Uma modalidade e os espaços que a aceitam. Esses espaços são tratados como equivalentes."""

    key: str
    label: str
    espacos: list = field(default_factory=list)

    @property
    def tema(self):
        return self.espacos[0].tema

    @property
    def automatic(self):
        """Há escolha a fazer: o sistema decide entre mais de um espaço."""
        return len(self.espacos) > 1


def modality_groups(espacos):
    """Modalidades oferecidas, na ordem dos espaços. "Beach Tênis" e "beach tenis" são a mesma."""
    groups = {}
    for espaco in espacos:
        for label in space_modalities(espaco):
            key = slugify(label)
            if not key:
                continue
            group = groups.setdefault(key, Modalidade(key, label[:1].upper() + label[1:]))
            if espaco not in group.espacos:
                group.espacos.append(espaco)
    return list(groups.values())


def price_rule_siblings(regra):
    """Faixas iguais em outros dias: para o dono, são uma linha só da tabela."""
    return TabelaPreco.all_tenants.filter(
        espaco_id=regra.espaco_id,
        hora_inicio=regra.hora_inicio,
        hora_fim=regra.hora_fim,
        duracao_slot_minutos=regra.duracao_slot_minutos,
        valor=regra.valor,
        valor_sinal=regra.valor_sinal,
    )


def _days_label(dias):
    labels = DiaSemana.labels
    if len(dias) == len(labels):
        return "Todos os dias"
    if len(dias) >= 2 and dias == list(range(dias[0], dias[-1] + 1)):
        return f"{labels[dias[0]]} a {labels[dias[-1]].lower()}"
    return ", ".join(labels[dia] for dia in dias)


def group_price_rules(regras):
    """Junta as faixas iguais para exibir a tabela de preços de forma resumida."""
    groups = {}
    for regra in regras:
        key = (regra.hora_inicio, regra.hora_fim, regra.duracao_slot_minutos, regra.valor, regra.valor_sinal)
        groups.setdefault(key, []).append(regra)
    rows = []
    for items in groups.values():
        dias = sorted(item.dia_semana for item in items)
        rows.append({"regra": items[0], "dias": dias, "label": _days_label(dias)})
    return sorted(rows, key=lambda row: (row["dias"][0], row["regra"].hora_inicio))


def load_schedules(espacos):
    """Carrega de uma vez os horários e preços de vários espaços."""
    espacos = list(espacos)
    ids = [espaco.pk for espaco in espacos]
    horarios = defaultdict(list)
    for horario in HorarioFuncionamento.all_tenants.filter(espaco_id__in=ids):
        horarios[horario.espaco_id].append(horario)
    regras = defaultdict(list)
    for regra in TabelaPreco.all_tenants.filter(espaco_id__in=ids):
        regras[regra.espaco_id].append(regra)
    return {
        espaco.pk: Schedule(horarios[espaco.pk], regras[espaco.pk], espaco.estabelecimento.timezone)
        for espaco in espacos
    }


def load_schedule(espaco):
    return load_schedules([espaco])[espaco.pk]


@transaction.atomic
def save_weekly_hours(espaco, rows):
    """Substitui os horários da semana. Cada linha: dia_semana, aberto, abre, fecha."""
    HorarioFuncionamento.all_tenants.filter(espaco=espaco).delete()
    HorarioFuncionamento.all_tenants.bulk_create(
        HorarioFuncionamento(
            estabelecimento_id=espaco.estabelecimento_id,
            espaco=espaco,
            dia_semana=row["dia_semana"],
            abre=row["abre"],
            fecha=row["fecha"],
        )
        for row in rows
        if row["aberto"]
    )


@transaction.atomic
def save_price_rules(espaco, dias, hora_inicio, hora_fim, duracao, valor, valor_sinal=None, instance=None):
    """Cria uma faixa por dia marcado. Ao editar, o grupo original é substituído."""
    if instance is not None:
        price_rule_siblings(instance).delete()

    candidate = TabelaPreco(hora_inicio=hora_inicio, hora_fim=hora_fim)
    start, end = _rule_range(candidate)
    existing = defaultdict(list)
    for regra in TabelaPreco.all_tenants.filter(espaco=espaco):
        existing[regra.dia_semana].append(regra)

    created = []
    for dia in dias:
        for regra in existing[dia]:
            other_start, other_end = _rule_range(regra)
            if start < other_end and other_start < end:
                raise PriceRuleOverlap(regra.get_dia_semana_display().lower())
        created.append(
            TabelaPreco.all_tenants.create(
                estabelecimento_id=espaco.estabelecimento_id,
                espaco=espaco,
                dia_semana=dia,
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                duracao_slot_minutos=duracao,
                valor=valor,
                valor_sinal=valor_sinal,
            )
        )
    return created
