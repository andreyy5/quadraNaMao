from decimal import Decimal

from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def brl(value):
    """Formata como moeda brasileira: 1200.5 vira R$ 1.200,50."""
    if value is None or value == "":
        return "—"
    value = Decimal(value)
    sinal = "-" if value < 0 else ""
    return f"{sinal}R$ {number_format(abs(value), decimal_pos=2, force_grouping=True)}"


@register.filter
def initials(name):
    """Iniciais para o avatar: João da Silva vira JS."""
    parts = (name or "").split()
    return "".join(part[0] for part in (parts[:1] + parts[1:][-1:])).upper()


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    """Marca o item do menu cujo caminho corresponde à página atual."""
    path = context["request"].path
    for prefix in prefixes:
        if (prefix == "/" and path == "/") or (prefix != "/" and path.startswith(prefix)):
            return "is-active"
    return ""
