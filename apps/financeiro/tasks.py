from celery import shared_task

from apps.estabelecimentos.models import Estabelecimento

from .services import generate_recurring_accounts


@shared_task
def generate_all_recurring_accounts():
    """Roda uma vez por dia. As telas também garantem as repetições, para não depender só do agendador."""
    return sum(generate_recurring_accounts(tenant) for tenant in Estabelecimento.objects.filter(ativo=True))
