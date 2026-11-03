from celery import shared_task

from . import mensalistas
from .services import expire_pending_reservations


@shared_task
def expire_pending():
    """A cada poucos minutos: libera os horários cujo sinal não foi pago no prazo."""
    return expire_pending_reservations()


@shared_task
def generate_mensalista_reservations():
    """Uma vez por dia: mantém as próximas semanas dos mensalistas reservadas."""
    return mensalistas.generate_all()
