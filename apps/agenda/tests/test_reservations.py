import threading
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from apps.agenda import services
from apps.agenda.models import Bloqueio, Reserva, ReservaEvento
from conftest import at, make_cliente, make_espaco, make_tenant


def book(espaco, cliente, start=10, end=11, **kwargs):
    return services.create_reservation(espaco, cliente, at(start), at(end), **kwargs)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (at(10), at(11)),
        (at(10, 30), at(11, 30)),
        (at(9, 30), at(10, 30)),
        (at(9), at(12)),
        (at(10, 15), at(10, 45)),
    ],
)
def test_overlap_is_rejected(espaco, cliente, start, end):
    book(espaco, cliente)
    with pytest.raises(services.ReservationConflict):
        services.create_reservation(espaco, cliente, start, end)
    assert Reserva.all_tenants.count() == 1


def test_adjacent_reservations_are_allowed(espaco, cliente):
    book(espaco, cliente, 10, 11)
    book(espaco, cliente, 11, 12)
    book(espaco, cliente, 9, 10)
    assert Reserva.all_tenants.count() == 3


def test_same_time_in_another_space_is_allowed(tenant, espaco, cliente):
    book(espaco, cliente)
    book(make_espaco(tenant, "Areia 2"), cliente)
    assert Reserva.all_tenants.count() == 2


def test_cancelled_reservation_frees_the_slot(espaco, cliente):
    reserva = book(espaco, cliente)
    services.cancel_reservation(reserva)
    assert book(espaco, cliente).status == Reserva.Status.CONFIRMADA


def test_constraint_protects_even_without_the_service_layer(tenant, espaco, cliente):
    book(espaco, cliente)
    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.all_tenants.create(
            estabelecimento=tenant, espaco=espaco, cliente=cliente, inicio=at(10, 30), fim=at(11, 30)
        )


def test_end_before_start_is_rejected_by_the_database(tenant, espaco, cliente):
    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.all_tenants.create(
            estabelecimento=tenant, espaco=espaco, cliente=cliente, inicio=at(11), fim=at(10)
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_bookings_only_one_wins():
    tenant = make_tenant("concorrencia")
    espaco = make_espaco(tenant)
    cliente = make_cliente(tenant)
    attempts = 8
    barrier = threading.Barrier(attempts)
    results = []

    def attempt():
        try:
            barrier.wait()
            services.create_reservation(espaco, cliente, at(10), at(11))
            results.append("ok")
        except services.ReservationConflict:
            results.append("conflict")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["conflict"] * (attempts - 1) + ["ok"]
    assert Reserva.all_tenants.filter(espaco=espaco).count() == 1


def test_outside_opening_hours_is_rejected(espaco, cliente):
    with pytest.raises(services.OutsideOpeningHours):
        book(espaco, cliente, 6, 7)
    with pytest.raises(services.OutsideOpeningHours):
        book(espaco, cliente, 21, 23)


def test_blocked_period_rejects_new_reservation(espaco, cliente):
    services.create_block(espaco, at(10), at(12), Bloqueio.Motivo.CHUVA)
    with pytest.raises(services.SpaceBlocked):
        book(espaco, cliente, 11, 12)
    assert book(espaco, cliente, 12, 13)


def test_price_is_calculated_when_value_is_omitted(espaco, cliente):
    assert book(espaco, cliente, 10, 12).valor_total == Decimal("200.00")


def test_explicit_value_is_kept(espaco, cliente):
    assert book(espaco, cliente, valor_total=Decimal("75.50")).valor_total == Decimal("75.50")


def test_other_tenant_client_is_rejected(espaco, other_tenant):
    with pytest.raises(services.TenantMismatch):
        book(espaco, make_cliente(other_tenant))


def test_move_to_taken_slot_is_rejected_and_keeps_original(espaco, cliente):
    book(espaco, cliente, 10, 11)
    other = book(espaco, cliente, 12, 13)
    with pytest.raises(services.ReservationConflict):
        services.update_reservation(other, espaco, cliente, at(10), at(11), Decimal("100"))
    other = Reserva.all_tenants.get(pk=other.pk)
    assert other.inicio == at(12)


def test_editing_notes_inside_a_block_is_allowed(espaco, cliente):
    reserva = book(espaco, cliente)
    services.create_block(espaco, at(9), at(12), Bloqueio.Motivo.CHUVA)
    services.update_reservation(
        reserva, espaco, cliente, reserva.inicio, reserva.fim, reserva.valor_total, "Nova nota"
    )
    assert Reserva.all_tenants.get(pk=reserva.pk).observacoes == "Nova nota"


def test_moving_into_a_block_is_rejected(espaco, cliente):
    reserva = book(espaco, cliente, 15, 16)
    services.create_block(espaco, at(9), at(12), Bloqueio.Motivo.CHUVA)
    with pytest.raises(services.SpaceBlocked):
        services.update_reservation(reserva, espaco, cliente, at(10), at(11), Decimal("100"))


def test_cancelled_reservation_cannot_change_status_or_be_edited(espaco, cliente):
    reserva = book(espaco, cliente)
    services.cancel_reservation(reserva)
    with pytest.raises(services.ReservationClosed):
        services.mark_completed(reserva)
    with pytest.raises(services.ReservationClosed):
        services.update_reservation(reserva, espaco, cliente, at(12), at(13), Decimal("100"))


def test_status_changes_and_audit_trail(espaco, cliente, owner):
    reserva = book(espaco, cliente, usuario=owner)
    services.mark_no_show(reserva, usuario=owner)
    assert Reserva.all_tenants.get(pk=reserva.pk).status == Reserva.Status.NAO_COMPARECEU
    eventos = ReservaEvento.all_tenants.filter(reserva=reserva)
    assert {e.acao for e in eventos} == {ReservaEvento.Acao.CRIADA, ReservaEvento.Acao.NAO_COMPARECEU}
    assert {e.usuario for e in eventos} == {owner}


def test_block_returns_affected_reservations_only(espaco, cliente):
    inside = book(espaco, cliente, 10, 11)
    book(espaco, cliente, 14, 15)
    cancelled = book(espaco, cliente, 11, 12)
    services.cancel_reservation(cancelled)
    _, affected = services.create_block(espaco, at(9), at(13), Bloqueio.Motivo.CHUVA)
    assert [r.pk for r in affected] == [inside.pk]


def test_invalid_block_period_is_rejected(espaco):
    with pytest.raises(services.InvalidPeriod):
        services.create_block(espaco, at(12), at(10), Bloqueio.Motivo.OUTRO)
