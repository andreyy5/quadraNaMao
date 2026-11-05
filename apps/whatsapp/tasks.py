from celery import shared_task

from . import services


@shared_task
def deliver_message(mensagem_id):
    services.deliver(mensagem_id)


@shared_task
def process_webhook(payload):
    """O webhook responde na hora para a Meta e o processamento fica para cá (planner, seção 7)."""
    services.handle_webhook(payload)


@shared_task
def send_due_reminders():
    return services.send_due_reminders()


@shared_task
def send_due_charges():
    return services.send_due_charges()
