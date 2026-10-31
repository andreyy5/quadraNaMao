from django import template

from apps.clientes.services import format_phone

register = template.Library()


@register.filter
def telefone(value):
    return format_phone(value)
