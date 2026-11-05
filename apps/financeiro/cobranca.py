"""Cobrança de conta a receber por link: o cliente abre, vê quanto deve e paga pelo Pix.

O Pix é sempre o da chave do estabelecimento, com o valor em aberto: quem confirma o pagamento é a
equipe, dando baixa na conta. O link vai na mensagem de cobrança do WhatsApp, automática ou manual.
"""

from django.conf import settings
from django.core import signing
from django.urls import reverse

from . import pix
from .models import ContaReceber

TOKEN_SALT = "cobranca-conta"


def account_token(conta):
    return signing.dumps(conta.pk, salt=TOKEN_SALT)


def account_from_token(token):
    try:
        pk = signing.loads(token, salt=TOKEN_SALT)
    except signing.BadSignature:
        return None
    return ContaReceber.all_tenants.select_related("estabelecimento").filter(pk=pk).first()


def account_url(conta):
    path = reverse("cobranca:conta", args=[conta.estabelecimento.slug, account_token(conta)])
    return settings.SITE_URL.rstrip("/") + path


def pix_code(conta):
    """Pix copia e cola do valor em aberto. Sem chave Pix cadastrada ou sem saldo, não há código."""
    estabelecimento = conta.estabelecimento
    if not estabelecimento.chave_pix or not conta.is_open or conta.saldo <= 0:
        return ""
    # O identificador aponta para a conta: ajuda a equipe a achar o pagamento no extrato.
    return pix.brcode(
        estabelecimento.chave_pix,
        estabelecimento.nome,
        estabelecimento.pix_cidade,
        conta.saldo,
        f"QNMC{conta.pk}",
    )
