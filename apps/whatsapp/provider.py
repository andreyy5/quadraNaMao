"""Quem entrega as mensagens. A troca de provedor não mexe no resto do sistema (planner, seção 7).

- `console`: não envia nada; registra no log e no histórico. Padrão em desenvolvimento e testes.
- `cloud`: WhatsApp Business Cloud API, direto da Meta. Precisa do token e do ID do número.
"""

import json
import logging
import urllib.error
import urllib.request
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Falha ao entregar. A mensagem vai para o histórico como falha, com este texto."""


class ConsoleProvider:
    code = "console"

    def send(self, *, phone_number_id, to, template=None, params=(), language="pt_BR", text=None):
        logger.info("WhatsApp (console) para %s: %s %s", to, template or "texto", list(params) or text)
        return f"console-{uuid.uuid4().hex}"


class CloudAPIProvider:
    code = "cloud"
    timeout = 15

    def send(self, *, phone_number_id, to, template=None, params=(), language="pt_BR", text=None):
        token = settings.WHATSAPP_ACCESS_TOKEN
        if not token or not phone_number_id:
            raise ProviderError("WhatsApp não configurado: falta o token de acesso ou o ID do número.")
        body = {"messaging_product": "whatsapp", "to": to.lstrip("+")}
        if template:
            body["type"] = "template"
            body["template"] = {"name": template, "language": {"code": language}}
            if params:
                body["template"]["components"] = [
                    {"type": "body", "parameters": [{"type": "text", "text": str(value)} for value in params]}
                ]
        else:
            body["type"] = "text"
            body["text"] = {"body": text, "preview_url": True}

        url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ProviderError(_meta_error(exc)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("Sem conexão com o WhatsApp. A mensagem pode ser reenviada.") from exc
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Resposta inesperada do WhatsApp.") from exc


def _meta_error(exc):
    try:
        error = json.loads(exc.read()).get("error", {})
    except (ValueError, AttributeError):
        error = {}
    message = error.get("error_user_msg") or error.get("message") or exc.reason
    return f"{exc.code}: {message}"[:300]


PROVIDERS = {provider.code: provider for provider in (ConsoleProvider, CloudAPIProvider)}


def get_provider():
    return PROVIDERS[settings.WHATSAPP_PROVIDER]()
