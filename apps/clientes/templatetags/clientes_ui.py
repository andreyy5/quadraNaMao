from django import template

from apps.clientes.services import format_phone

register = template.Library()


@register.filter
def telefone(value):
    return format_phone(value)


@register.filter
def whatsapp_url(value):
    """Link para abrir a conversa no WhatsApp. Cliente anonimizado não tem telefone e fica sem link."""
    digits = (value or "").removeprefix("+")
    return f"https://wa.me/{digits}" if digits.isdigit() else ""
