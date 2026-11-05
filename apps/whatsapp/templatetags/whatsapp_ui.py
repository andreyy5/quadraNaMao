from urllib.parse import quote

from django import template

from apps.clientes.templatetags.clientes_ui import whatsapp_url

from ..modelos import MODELOS
from ..services import charge_message

register = template.Library()


@register.filter
def cobranca_whatsapp_url(conta):
    """Abre o WhatsApp de quem atende com a cobrança já escrita, com o mesmo texto do envio automático.

    Não tem custo e não depende do módulo automático: quem manda é a pessoa, pelo próprio celular.
    """
    url = whatsapp_url(conta.cliente.telefone) if conta.cliente_id else ""
    if not url:
        return ""
    modelo, params = charge_message(conta)
    return f"{url}?text={quote(MODELOS[modelo].render(params))}"
