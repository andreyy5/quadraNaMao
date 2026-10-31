from decimal import Decimal

from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def brl(value):
    """Formata como moeda brasileira: 1200.5 vira R$ 1.200,50."""
    if value is None or value == "":
        return "—"
    return f"R$ {number_format(Decimal(value), decimal_pos=2, force_grouping=True)}"


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    """Marca o item do menu cujo caminho corresponde à página atual."""
    path = context["request"].path
    for prefix in prefixes:
        if (prefix == "/" and path == "/") or (prefix != "/" and path.startswith(prefix)):
            return "is-active"
    return ""
