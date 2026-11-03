"""Toda reserva passa a ter uma conta a receber. Cria as das reservas que já existiam."""

from zoneinfo import ZoneInfo

from django.db import migrations


def create_reservation_accounts(apps, schema_editor):
    Reserva = apps.get_model("agenda", "Reserva")
    ContaReceber = apps.get_model("financeiro", "ContaReceber")
    existing = set(ContaReceber.objects.filter(reserva__isnull=False).values_list("reserva_id", flat=True))
    novas = []
    for reserva in Reserva.objects.select_related("espaco", "estabelecimento").exclude(pk__in=existing):
        local = reserva.inicio.astimezone(ZoneInfo(reserva.estabelecimento.fuso_horario))
        if reserva.status == "CANCELADA":
            status = "CANCELADA"
        elif reserva.valor_pago >= reserva.valor_total:
            status = "PAGA"
        else:
            status = "ABERTA"
        novas.append(
            ContaReceber(
                estabelecimento_id=reserva.estabelecimento_id,
                reserva=reserva,
                cliente_id=reserva.cliente_id,
                categoria="RESERVA",
                descricao=f"Reserva {reserva.espaco.nome} · {local:%d/%m %H:%M}",
                valor=reserva.valor_total,
                valor_pago=reserva.valor_pago,
                vencimento=local.date(),
                status=status,
                criado_por_id=reserva.criado_por_id,
            )
        )
    ContaReceber.objects.bulk_create(novas)


class Migration(migrations.Migration):
    dependencies = [
        ("agenda", "0002_initial"),
        ("financeiro", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_reservation_accounts, migrations.RunPython.noop)]
