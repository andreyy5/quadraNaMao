"""Regras da agenda: grade de horários, reservas e bloqueios.

Quem garante que não há reserva duplicada é a constraint do banco. O código abaixo só
traduz o erro dela em uma mensagem amigável, e usa `all_tenants` com filtro explícito
para funcionar fora de uma requisição (tarefas agendadas e, depois, o agente de IA).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.espacos.models import Espaco
from apps.espacos.services import load_schedule, load_schedules
from apps.financeiro.models import Pagamento
from apps.financeiro.services import sync_reservation_account
from apps.whatsapp.services import notify_reservation

from .models import CONFLICT_CONSTRAINT, Bloqueio, Reserva, ReservaEvento

PIXELS_PER_HOUR = 72
DEFAULT_FIRST_HOUR = 8
DEFAULT_LAST_HOUR = 22


class ReservationError(Exception):
    """Regra de negócio violada. A mensagem pode ser mostrada ao usuário."""


class ReservationConflict(ReservationError):
    def __init__(self):
        super().__init__("Esse horário já está reservado. Escolha outro horário ou espaço.")


class SpaceBlocked(ReservationError):
    def __init__(self, bloqueio):
        motivo = bloqueio.get_motivo_display().lower()
        super().__init__(f"Esse horário está bloqueado ({motivo}). Escolha outro horário ou espaço.")


class OutsideOpeningHours(ReservationError):
    def __init__(self):
        super().__init__("Esse horário está fora do funcionamento do espaço.")


class InvalidPeriod(ReservationError):
    def __init__(self):
        super().__init__("O fim precisa ser depois do início.")


class ReservationClosed(ReservationError):
    def __init__(self, reserva):
        super().__init__(
            f"Esta reserva já está {reserva.get_status_display().lower()} e não pode mais mudar."
        )


class TenantMismatch(ReservationError):
    def __init__(self):
        super().__init__("Espaço e cliente não pertencem ao mesmo estabelecimento.")


@dataclass
class Cell:
    """Um bloco na coluna da agenda: horário livre, reserva ou bloqueio."""

    kind: str
    inicio: datetime
    fim: datetime
    valor: Decimal | None = None
    reserva: Reserva | None = None
    bloqueio: Bloqueio | None = None
    has_block: bool = False
    is_past: bool = False
    top: int = 0
    height: int = 0

    @property
    def minutes(self):
        return int((self.fim - self.inicio).total_seconds() / 60)

    @property
    def is_compact(self):
        return self.height < 52


@dataclass
class Column:
    """Uma coluna da grade: um espaço em um dia."""

    espaco: Espaco
    day: date
    cells: list = field(default_factory=list)
    is_closed: bool = False
    now_top: int | None = None


@dataclass
class Grid:
    columns: list
    hours: list
    height: int
    first_hour: int


def _overlapping(model, espacos, start, end):
    """Registros que tocam o período, agrupados por espaço."""
    queryset = model.all_tenants.filter(espaco__in=espacos, inicio__lt=end, fim__gt=start)
    if model is Reserva:
        queryset = queryset.exclude(status=Reserva.Status.CANCELADA).select_related("cliente", "espaco")
    grouped = defaultdict(list)
    for item in queryset.order_by("inicio"):
        grouped[item.espaco_id].append(item)
    return grouped


def _build_cells(schedule, day, reservas, bloqueios, now):
    period = schedule.period(day)
    if period is None:
        return None
    opens, closes = period
    reservas = [r for r in reservas if r.inicio < closes and r.fim > opens]
    bloqueios = [b for b in bloqueios if b.inicio < closes and b.fim > opens]

    cells = []
    cursor = opens
    while cursor < closes:
        current = next((r for r in reservas if r.inicio <= cursor < r.fim), None)
        if current:
            end = min(current.fim, closes)
            has_block = any(b.inicio < end and b.fim > cursor for b in bloqueios)
            cells.append(Cell("reserved", cursor, end, reserva=current, has_block=has_block))
            cursor = end
            continue

        next_reserva = min((r.inicio for r in reservas if r.inicio > cursor), default=closes)
        block = next((b for b in bloqueios if b.inicio <= cursor < b.fim), None)
        if block:
            end = min(block.fim, next_reserva, closes)
            cells.append(Cell("blocked", cursor, end, bloqueio=block))
            cursor = end
            continue

        next_block = min((b.inicio for b in bloqueios if b.inicio > cursor), default=closes)
        slot_end = cursor + timedelta(minutes=schedule.slot_minutes(cursor, day))
        end = min(slot_end, next_reserva, next_block, closes)
        cells.append(Cell("free", cursor, end, valor=schedule.quote(cursor, end), is_past=end <= now))
        cursor = end
    return cells


def _layout(columns, schedule_tz, now):
    """Calcula a posição em pixels de cada bloco e a régua de horas."""

    def minutes_from_midnight(moment, day):
        midnight = datetime.combine(day, datetime.min.time(), tzinfo=schedule_tz)
        return int((moment - midnight).total_seconds() / 60)

    starts, ends = [], []
    for column in columns:
        if column.cells:
            starts.append(minutes_from_midnight(column.cells[0].inicio, column.day))
            ends.append(minutes_from_midnight(column.cells[-1].fim, column.day))
    first_hour = min(starts) // 60 if starts else DEFAULT_FIRST_HOUR
    last_hour = -(-max(ends) // 60) if ends else DEFAULT_LAST_HOUR
    last_hour = max(last_hour, first_hour + 1)
    height = (last_hour - first_hour) * PIXELS_PER_HOUR

    def to_pixels(minutes):
        return (minutes - first_hour * 60) * PIXELS_PER_HOUR // 60

    for column in columns:
        for cell in column.cells:
            cell.top = to_pixels(minutes_from_midnight(cell.inicio, column.day))
            cell.height = to_pixels(minutes_from_midnight(cell.fim, column.day)) - cell.top
        now_minutes = minutes_from_midnight(now, column.day)
        if first_hour * 60 <= now_minutes <= last_hour * 60:
            column.now_top = to_pixels(now_minutes)

    hours = [
        {"label": f"{hour % 24:02d}:00", "top": (hour - first_hour) * PIXELS_PER_HOUR}
        for hour in range(first_hour, last_hour)
    ]
    return Grid(columns=columns, hours=hours, height=height, first_hour=first_hour)


def _build_grid(pairs, tz):
    """Monta a grade para pares (espaço, dia), com todas as consultas feitas de uma vez."""
    espacos = list({espaco.pk: espaco for espaco, _ in pairs}.values())
    days = [day for _, day in pairs]
    # Um dia a mais nas pontas cobre as reservas que atravessam a meia-noite.
    start = datetime.combine(min(days) - timedelta(days=1), datetime.min.time(), tzinfo=tz)
    end = datetime.combine(max(days) + timedelta(days=2), datetime.min.time(), tzinfo=tz)

    schedules = load_schedules(espacos)
    reservas = _overlapping(Reserva, espacos, start, end)
    bloqueios = _overlapping(Bloqueio, espacos, start, end)
    now = timezone.now().astimezone(tz)

    columns = []
    for espaco, day in pairs:
        cells = _build_cells(schedules[espaco.pk], day, reservas[espaco.pk], bloqueios[espaco.pk], now)
        columns.append(Column(espaco=espaco, day=day, cells=cells or [], is_closed=cells is None))
    return _layout(columns, tz, now)


def build_day_grid(espaco, day):
    return _build_grid([(espaco, day)], espaco.estabelecimento.timezone).columns[0]


def build_day_agenda(estabelecimento, day):
    """Todos os espaços ativos em um dia, lado a lado."""
    espacos = Espaco.all_tenants.filter(estabelecimento=estabelecimento, ativo=True).select_related(
        "estabelecimento"
    )
    return _build_grid([(espaco, day) for espaco in espacos], estabelecimento.timezone) if espacos else None


def build_week_agenda(espaco, monday):
    """Um espaço ao longo de uma semana."""
    pairs = [(espaco, monday + timedelta(days=offset)) for offset in range(7)]
    return _build_grid(pairs, espaco.estabelecimento.timezone)


def quote_price(espaco, inicio, fim):
    return load_schedule(espaco).quote(inicio, fim)


def _record(reserva, acao, usuario, detalhes=""):
    ReservaEvento.all_tenants.create(
        estabelecimento_id=reserva.estabelecimento_id,
        reserva=reserva,
        acao=acao,
        usuario=usuario,
        detalhes=detalhes,
    )


def _lock_spaces(*espacos):
    """Enfileira, por espaço, quem grava reservas e bloqueios. Ordem fixa evita deadlock."""
    ids = sorted({espaco.pk for espaco in espacos})
    list(Espaco.all_tenants.select_for_update().filter(pk__in=ids).order_by("pk"))


def _check_available(espaco, inicio, fim):
    if fim <= inicio:
        raise InvalidPeriod
    if not load_schedule(espaco).contains(inicio, fim):
        raise OutsideOpeningHours
    bloqueio = Bloqueio.all_tenants.filter(espaco=espaco, inicio__lt=fim, fim__gt=inicio).first()
    if bloqueio:
        raise SpaceBlocked(bloqueio)


def free_starts(espaco, day, minutes, ignore=None):
    """Inícios livres no dia para essa duração, seguindo a grade do espaço. Horários que já passaram ficam de fora.

    Olha também o expediente do dia anterior: 00:30 de sábado pode ser ainda a noite de sexta.
    """
    schedule = load_schedule(espaco)
    duration = timedelta(minutes=minutes)
    now = timezone.now()
    starts = []
    for opening_day in (day - timedelta(days=1), day):
        period = schedule.period(opening_day)
        if period is None:
            continue
        opens, closes = period
        busy = _overlapping(Bloqueio, [espaco], opens, closes)[espaco.pk] + [
            reserva
            for reserva in _overlapping(Reserva, [espaco], opens, closes)[espaco.pk]
            if reserva != ignore
        ]
        cursor = opens
        while cursor + duration <= closes:
            clash = next(
                (item for item in busy if item.inicio < cursor + duration and item.fim > cursor), None
            )
            if clash:
                cursor = clash.fim.astimezone(schedule.tz)
                continue
            if cursor.date() == day and cursor >= now:
                starts.append(cursor)
            cursor += timedelta(minutes=schedule.slot_minutes(cursor, opening_day))
    return starts


def slot_problem(espaco, inicio, fim, ignore=None):
    """Por que o período não pode ser reservado, ou None se está livre.

    Serve só para avisar antes de salvar: quem garante de verdade é a constraint, ao gravar.
    """
    try:
        _check_available(espaco, inicio, fim)
    except ReservationError as exc:
        return str(exc)
    if any(reserva != ignore for reserva in _overlapping(Reserva, [espaco], inicio, fim)[espaco.pk]):
        return str(ReservationConflict())
    return None


def _notify(reserva, kind):
    """Avisa o cliente pelo WhatsApp depois que a transação confirmar. As regras de quem recebe ficam lá.

    Com o WhatsApp desligado no momento da mudança, nem agenda o aviso.
    """
    if not reserva.estabelecimento.whatsapp_ativo:
        return
    reserva_id = reserva.pk
    transaction.on_commit(lambda: notify_reservation(reserva_id, kind))


def _is_conflict(error):
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == CONFLICT_CONSTRAINT


def create_reservation(
    espaco,
    cliente,
    inicio,
    fim,
    valor_total=None,
    observacoes="",
    usuario=None,
    origem=Reserva.Origem.PAINEL,
    status=Reserva.Status.CONFIRMADA,
    expira_em=None,
    valor_sinal=Decimal("0"),
    mensalista=None,
    notify=True,
):
    if espaco.estabelecimento_id != cliente.estabelecimento_id:
        raise TenantMismatch
    with transaction.atomic():
        _lock_spaces(espaco)
        _check_available(espaco, inicio, fim)
        if valor_total is None:
            valor_total = quote_price(espaco, inicio, fim) or Decimal("0")
        try:
            with transaction.atomic():
                reserva = Reserva.all_tenants.create(
                    estabelecimento_id=espaco.estabelecimento_id,
                    espaco=espaco,
                    cliente=cliente,
                    inicio=inicio,
                    fim=fim,
                    valor_total=valor_total,
                    observacoes=observacoes,
                    origem=origem,
                    status=status,
                    expira_em=expira_em,
                    valor_sinal=valor_sinal,
                    mensalista=mensalista,
                    criado_por=usuario,
                )
        except IntegrityError as exc:
            if _is_conflict(exc):
                raise ReservationConflict from exc
            raise
        _record(reserva, ReservaEvento.Acao.CRIADA, usuario)
        sync_reservation_account(reserva)
        if notify and status == Reserva.Status.CONFIRMADA:
            _notify(reserva, "confirmada")
    return reserva


def update_reservation(reserva, espaco, cliente, inicio, fim, valor_total, observacoes="", usuario=None):
    """Altera ou remarca. Só repete as checagens de agenda se o horário ou o espaço mudar."""
    if (
        espaco.estabelecimento_id != cliente.estabelecimento_id
        or espaco.estabelecimento_id != reserva.estabelecimento_id
    ):
        raise TenantMismatch
    if reserva.status == Reserva.Status.CANCELADA:
        raise ReservationClosed(reserva)

    moved = reserva.espaco_id != espaco.pk or reserva.inicio != inicio or reserva.fim != fim
    with transaction.atomic():
        _lock_spaces(espaco, reserva.espaco)
        if moved:
            _check_available(espaco, inicio, fim)
        detalhes = ""
        if moved:
            tz = espaco.estabelecimento.timezone
            detalhes = f"De {reserva.inicio.astimezone(tz):%d/%m %H:%M} em {reserva.espaco.nome}"
        reserva.espaco = espaco
        reserva.cliente = cliente
        reserva.inicio = inicio
        reserva.fim = fim
        reserva.valor_total = valor_total
        reserva.observacoes = observacoes
        try:
            with transaction.atomic():
                # Sem `valor_pago`: quem cuida dele é o financeiro, e esta cópia pode estar velha.
                reserva.save(
                    update_fields=[
                        "espaco",
                        "cliente",
                        "inicio",
                        "fim",
                        "valor_total",
                        "observacoes",
                        "atualizado_em",
                    ]
                )
        except IntegrityError as exc:
            if _is_conflict(exc):
                raise ReservationConflict from exc
            raise
        _record(reserva, ReservaEvento.Acao.ALTERADA, usuario, detalhes)
        sync_reservation_account(reserva)
        if moved and reserva.status == Reserva.Status.CONFIRMADA:
            _notify(reserva, "remarcada")
    return reserva


def _change_status(reserva, status, acao, usuario, detalhes="", notify_kind=None):
    with transaction.atomic():
        current = Reserva.all_tenants.select_for_update().get(pk=reserva.pk)
        if not current.is_open:
            raise ReservationClosed(current)
        current.status = status
        current.save(update_fields=["status", "atualizado_em"])
        _record(current, acao, usuario, detalhes)
        sync_reservation_account(current)
        if status == Reserva.Status.CANCELADA:
            Pagamento.all_tenants.filter(reserva=current, status=Pagamento.Status.PENDENTE).update(
                status=(
                    Pagamento.Status.EXPIRADO
                    if acao == ReservaEvento.Acao.EXPIRADA
                    else Pagamento.Status.CANCELADO
                )
            )
        if notify_kind:
            _notify(current, notify_kind)
    reserva.status = status
    return reserva


def cancel_reservation(reserva, usuario=None, detalhes="", notify=True):
    return _change_status(
        reserva,
        Reserva.Status.CANCELADA,
        ReservaEvento.Acao.CANCELADA,
        usuario,
        detalhes,
        notify_kind="cancelada" if notify else None,
    )


def confirm_reservation(reserva, usuario=None, detalhes=""):
    """Pendente vira confirmada quando o sinal é pago. Já confirmada, não faz nada."""
    with transaction.atomic():
        current = Reserva.all_tenants.select_for_update().get(pk=reserva.pk)
        if current.status != Reserva.Status.PENDENTE:
            return current
        current.status = Reserva.Status.CONFIRMADA
        current.expira_em = None
        current.save(update_fields=["status", "expira_em", "atualizado_em"])
        _record(current, ReservaEvento.Acao.CONFIRMADA, usuario, detalhes)
        sync_reservation_account(current)
        _notify(current, "confirmada")
    return current


def expire_pending_reservations(estabelecimento=None, now=None):
    """Cancela as pendentes cujo prazo do sinal passou, liberando o horário. Pode rodar quantas vezes for."""
    now = now or timezone.now()
    queryset = Reserva.all_tenants.filter(status=Reserva.Status.PENDENTE, expira_em__lt=now)
    if estabelecimento is not None:
        queryset = queryset.filter(estabelecimento=estabelecimento)
    expired = 0
    for reserva in queryset:
        try:
            _change_status(
                reserva,
                Reserva.Status.CANCELADA,
                ReservaEvento.Acao.EXPIRADA,
                None,
                "Sinal não pago no prazo",
                notify_kind="expirada",
            )
        except ReservationClosed:
            continue
        expired += 1
    return expired


def mark_completed(reserva, usuario=None):
    return _change_status(reserva, Reserva.Status.CONCLUIDA, ReservaEvento.Acao.CONCLUIDA, usuario)


def mark_no_show(reserva, usuario=None):
    return _change_status(reserva, Reserva.Status.NAO_COMPARECEU, ReservaEvento.Acao.NAO_COMPARECEU, usuario)


def affected_reservations(bloqueios):
    """Reservas em aberto que caem dentro dos bloqueios informados."""
    reservas = {}
    for bloqueio in bloqueios:
        queryset = Reserva.all_tenants.filter(
            espaco_id=bloqueio.espaco_id,
            inicio__lt=bloqueio.fim,
            fim__gt=bloqueio.inicio,
            status__in=[Reserva.Status.PENDENTE, Reserva.Status.CONFIRMADA],
        ).select_related("cliente", "espaco")
        for reserva in queryset:
            reservas[reserva.pk] = reserva
    return sorted(reservas.values(), key=lambda reserva: reserva.inicio)


def create_block(espaco, inicio, fim, motivo, descricao="", usuario=None):
    """Cria o bloqueio mesmo havendo reservas no período e devolve as que foram afetadas."""
    if fim <= inicio:
        raise InvalidPeriod
    with transaction.atomic():
        _lock_spaces(espaco)
        bloqueio = Bloqueio.all_tenants.create(
            estabelecimento_id=espaco.estabelecimento_id,
            espaco=espaco,
            inicio=inicio,
            fim=fim,
            motivo=motivo,
            descricao=descricao,
            criado_por=usuario,
        )
    return bloqueio, affected_reservations([bloqueio])


def _day_timeline(column, now):
    """Resumo de uma coluna para a linha do dia.

    As posições vão como texto para a localização não trocar o ponto por vírgula no CSS.
    """
    if not column.cells:
        return {"espaco": column.espaco, "is_closed": True, "occupancy": 0, "segments": []}
    start, end = column.cells[0].inicio, column.cells[-1].fim
    total = end - start

    def percent(delta):
        return f"{delta * 100 / total:.2f}"

    busy = sum(cell.minutes for cell in column.cells if cell.kind == "reserved")
    available = sum(cell.minutes for cell in column.cells if cell.kind in ("reserved", "free"))
    return {
        "espaco": column.espaco,
        "is_closed": False,
        "occupancy": round(busy * 100 / available) if available else 0,
        "opens": start,
        "closes": end,
        "now": percent(now - start) if start <= now <= end else None,
        "segments": [
            {
                "kind": cell.kind,
                "left": percent(cell.inicio - start),
                "width": percent(cell.fim - cell.inicio),
            }
            for cell in column.cells
            if cell.kind != "free"
        ],
    }


def day_summary(estabelecimento, day):
    """Números do dia para a tela inicial."""
    agenda = build_day_agenda(estabelecimento, day)
    if agenda is None:
        return {"reservas": [], "occupancy": 0, "expected": Decimal("0"), "free_slots": 0, "timelines": []}
    reservas, free_slots, busy, available = [], 0, 0, 0
    for column in agenda.columns:
        for cell in column.cells:
            if cell.kind == "reserved":
                reservas.append(cell.reserva)
                busy += cell.minutes
                available += cell.minutes
            elif cell.kind == "free":
                free_slots += 0 if cell.is_past else 1
                available += cell.minutes
    now = timezone.now()
    return {
        "reservas": sorted(reservas, key=lambda reserva: reserva.inicio),
        "occupancy": round(busy * 100 / available) if available else 0,
        "expected": sum((reserva.valor_total for reserva in reservas), Decimal("0")),
        "free_slots": free_slots,
        "timelines": [_day_timeline(column, now) for column in agenda.columns],
    }


def occupancy_by_space(estabelecimento, first, last):
    """Ocupação de cada espaço no período, em % das horas abertas."""
    espacos = list(
        Espaco.all_tenants.filter(estabelecimento=estabelecimento, ativo=True).select_related(
            "estabelecimento"
        )
    )
    if not espacos:
        return []
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    grid = _build_grid([(espaco, day) for espaco in espacos for day in days], estabelecimento.timezone)
    busy = Counter()
    available = Counter()
    for column in grid.columns:
        for cell in column.cells:
            if cell.kind in ("reserved", "free"):
                available[column.espaco.pk] += cell.minutes
            if cell.kind == "reserved":
                busy[column.espaco.pk] += cell.minutes
    rows = [
        {
            "espaco": espaco,
            "occupancy": round(busy[espaco.pk] * 100 / available[espaco.pk]) if available[espaco.pk] else 0,
        }
        for espaco in espacos
    ]
    return sorted(rows, key=lambda row: row["occupancy"], reverse=True)


def week_strip(estabelecimento, day):
    """Os sete dias da semana de `day`, com a quantidade de reservas de cada um."""
    tz = estabelecimento.timezone
    monday = day - timedelta(days=day.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
    inicios = (
        Reserva.all_tenants.filter(
            estabelecimento=estabelecimento, inicio__gte=start, inicio__lt=start + timedelta(days=7)
        )
        .exclude(status=Reserva.Status.CANCELADA)
        .values_list("inicio", flat=True)
    )
    counts = Counter(inicio.astimezone(tz).date() for inicio in inicios)
    today = timezone.now().astimezone(tz).date()
    days = [monday + timedelta(days=offset) for offset in range(7)]
    return [
        {
            "day": item,
            "count": counts[item],
            "dots": range(min(counts[item], 3)),
            "is_today": item == today,
            "is_selected": item == day,
        }
        for item in days
    ]
