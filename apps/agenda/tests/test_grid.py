from datetime import time, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.agenda import services
from apps.agenda.models import Bloqueio
from apps.espacos.models import DiaSemana, Espaco, TabelaPreco
from apps.espacos.services import load_schedule, save_price_rules, save_weekly_hours
from conftest import DAY, at, make_espaco


def kinds(column):
    return [cell.kind for cell in column.cells]


def test_grid_splits_open_hours_in_slots(espaco):
    column = services.build_day_grid(espaco, DAY)
    assert len(column.cells) == 14
    assert set(kinds(column)) == {"free"}
    assert column.cells[0].inicio == at(8)
    assert column.cells[0].valor == Decimal("100.00")
    assert column.cells[-1].fim == at(22)


def test_grid_shows_reservations_blocks_and_partial_gaps(espaco, cliente):
    services.create_reservation(espaco, cliente, at(9), at(10, 30))
    services.create_block(espaco, at(14), at(16), Bloqueio.Motivo.MANUTENCAO)
    column = services.build_day_grid(espaco, DAY)
    assert kinds(column)[:3] == ["free", "reserved", "free"]
    # Depois de uma reserva de 1h30, o próximo horário livre começa às 10:30.
    gap = column.cells[2]
    assert (gap.inicio, gap.fim, gap.valor) == (at(10, 30), at(11, 30), Decimal("100.00"))
    blocked = [cell for cell in column.cells if cell.kind == "blocked"]
    assert len(blocked) == 1
    assert (blocked[0].inicio, blocked[0].fim) == (at(14), at(16))


def test_cancelled_reservation_is_not_shown(espaco, cliente):
    reserva = services.create_reservation(espaco, cliente, at(9), at(10))
    services.cancel_reservation(reserva)
    assert "reserved" not in kinds(services.build_day_grid(espaco, DAY))


def test_reservation_inside_block_stays_visible_and_flagged(espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    services.create_block(espaco, at(9), at(12), Bloqueio.Motivo.CHUVA)
    cells = [c for c in services.build_day_grid(espaco, DAY).cells if c.kind != "free"]
    assert [c.kind for c in cells] == ["blocked", "reserved", "blocked"]
    assert cells[1].has_block


def test_closed_day(espaco):
    save_weekly_hours(espaco, [{"dia_semana": DAY.weekday(), "aberto": False, "abre": None, "fecha": None}])
    column = services.build_day_grid(espaco, DAY)
    assert column.is_closed
    assert column.cells == []


def test_hours_past_midnight_belong_to_the_opening_day(tenant, cliente):
    espaco = make_espaco(tenant, "Noturna", abre=time(18), fecha=time(1))
    next_day = DAY + timedelta(days=1)
    column = services.build_day_grid(espaco, DAY)
    assert column.cells[0].inicio == at(18)
    assert column.cells[-1].fim == at(1, day=next_day)
    assert len(column.cells) == 7

    # 00:00 do dia seguinte ainda é o expediente que abriu ontem.
    reserva = services.create_reservation(espaco, cliente, at(0, day=next_day), at(1, day=next_day))
    assert reserva.valor_total == Decimal("100.00")
    assert "reserved" in kinds(services.build_day_grid(espaco, DAY))


def test_midnight_closing_time(tenant, cliente):
    espaco = make_espaco(tenant, "Até meia-noite", abre=time(8), fecha=time(0))
    column = services.build_day_grid(espaco, DAY)
    assert column.cells[-1].fim == at(0, day=DAY + timedelta(days=1))
    assert services.create_reservation(espaco, cliente, at(23), at(0, day=DAY + timedelta(days=1)))


def test_quote_spans_price_ranges_and_prorates(tenant):
    espaco = make_espaco(tenant, "Dois preços", valor=Decimal("0"))
    TabelaPreco.all_tenants.filter(espaco=espaco).delete()
    save_price_rules(espaco, DiaSemana.values, time(8), time(18), 60, Decimal("100"))
    save_price_rules(espaco, DiaSemana.values, time(18), time(22), 60, Decimal("150"))
    assert services.quote_price(espaco, at(17), at(19)) == Decimal("250.00")
    assert services.quote_price(espaco, at(17, 30), at(18, 30)) == Decimal("125.00")


def test_quote_without_price_range_returns_none(tenant):
    espaco = make_espaco(tenant, "Sem preço")
    TabelaPreco.all_tenants.filter(espaco=espaco).delete()
    assert services.quote_price(espaco, at(10), at(11)) is None
    column = services.build_day_grid(espaco, DAY)
    assert column.cells[0].valor is None
    assert column.cells[0].minutes == 60


def test_slot_duration_comes_from_price_table(tenant):
    espaco = make_espaco(tenant, "Slots de 90")
    TabelaPreco.all_tenants.filter(espaco=espaco).update(duracao_slot_minutos=90)
    assert load_schedule(espaco).slot_minutes(at(10)) == 90
    assert services.build_day_grid(espaco, DAY).cells[0].fim == at(9, 30)


def test_day_agenda_query_count_does_not_grow_with_spaces(tenant, espaco, cliente):
    def count_queries():
        with CaptureQueriesContext(connection) as ctx:
            services.build_day_agenda(tenant, DAY)
        return len(ctx)

    services.create_reservation(espaco, cliente, at(9), at(10))
    before = count_queries()
    for index in range(4):
        extra = make_espaco(tenant, f"Extra {index}")
        services.create_reservation(extra, cliente, at(9), at(10))
    assert count_queries() == before


def test_pixel_layout_is_proportional(espaco):
    grid = services.build_day_agenda(espaco.estabelecimento, DAY)
    cell = grid.columns[0].cells[1]
    assert cell.top == services.PIXELS_PER_HOUR
    assert cell.height == services.PIXELS_PER_HOUR
    assert grid.height == 14 * services.PIXELS_PER_HOUR
    assert grid.hours[0]["label"] == "08:00"


def test_day_summary(espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(12))
    summary = services.day_summary(espaco.estabelecimento, DAY)
    assert len(summary["reservas"]) == 1
    assert summary["expected"] == Decimal("200.00")
    assert summary["occupancy"] == 14


def test_week_strip_counts_reservations_per_day(tenant, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))
    services.create_reservation(espaco, cliente, at(12), at(13))
    cancelled = services.create_reservation(espaco, cliente, at(14), at(15))
    services.cancel_reservation(cancelled)

    strip = services.week_strip(tenant, DAY)

    assert [item["day"].weekday() for item in strip] == list(range(7))
    selected = next(item for item in strip if item["is_selected"])
    assert selected["day"] == DAY
    assert selected["count"] == 2
    assert len(selected["dots"]) == 2
    assert sum(item["count"] for item in strip) == 2


def test_week_strip_uses_the_local_day_near_midnight(tenant, cliente):
    espaco = make_espaco(tenant, "24 horas", abre=time(0), fecha=time(0))
    services.create_reservation(espaco, cliente, at(23), at(23, 30))

    strip = services.week_strip(tenant, DAY)

    # 23h em São Paulo já é o dia seguinte em UTC.
    assert next(item for item in strip if item["day"] == DAY)["count"] == 1


def test_day_summary_timeline_positions_use_a_dot_for_css(tenant, espaco, cliente):
    services.create_reservation(espaco, cliente, at(10), at(11))

    line = services.day_summary(tenant, DAY)["timelines"][0]

    assert line["espaco"] == espaco
    assert line["occupancy"] == 7
    assert line["now"] is None
    # Aberto das 8h às 22h: a reserva começa em 2/14 do dia e ocupa 1/14.
    assert line["segments"] == [{"kind": "reserved", "left": "14.29", "width": "7.14"}]


def test_day_summary_timeline_marks_a_closed_day(tenant):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome="Sem horário", tipo=Espaco.Tipo.AREIA)

    line = services.day_summary(tenant, DAY)["timelines"][0]

    assert line["espaco"] == espaco
    assert line["is_closed"] is True
    assert line["segments"] == []
