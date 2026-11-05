"""Roda uma vez todas as rotinas agendadas. Útil sem o agendador do Celery, num cron do servidor."""

from django.core.management.base import BaseCommand

from apps.agenda import mensalistas
from apps.agenda.services import expire_pending_reservations
from apps.estabelecimentos.models import Estabelecimento
from apps.financeiro.services import generate_recurring_accounts
from apps.whatsapp.services import send_due_charges, send_due_reminders


class Command(BaseCommand):
    help = (
        "Expira sinais vencidos, gera reservas de mensalistas e contas recorrentes e envia lembretes "
        "e cobranças."
    )

    def handle(self, *args, **options):
        expiradas = expire_pending_reservations()
        geradas = mensalistas.generate_all()
        contas = sum(
            generate_recurring_accounts(tenant) for tenant in Estabelecimento.objects.filter(ativo=True)
        )
        lembretes = send_due_reminders()
        cobrancas = send_due_charges()
        self.stdout.write(
            f"Reservas expiradas: {expiradas}. Reservas de mensalistas: {geradas}. "
            f"Contas recorrentes: {contas}. Lembretes: {lembretes}. Cobranças: {cobrancas}."
        )
