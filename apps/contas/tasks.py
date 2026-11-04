from smtplib import SMTPException

from celery import shared_task
from django.core.mail import EmailMultiAlternatives


@shared_task(autoretry_for=(OSError, SMTPException), retry_backoff=True, max_retries=3)
def send_email(subject, body, from_email, to, html=None):
    """Envio fora da requisição: o provedor lento não trava a tela nem revela se o e-mail existe."""
    message = EmailMultiAlternatives(subject, body, from_email, to)
    if html:
        message.attach_alternative(html, "text/html")
    message.send()
