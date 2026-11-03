"""Pix: o código "copia e cola" no padrão do Banco Central (BR Code) e os provedores de cobrança.

O provedor `estatico` gera o código com a chave do estabelecimento: funciona em qualquer banco, mas
quem confirma o pagamento é a equipe. Um provedor de cobrança (PSP) confirma sozinho pelo webhook;
para ligar um, implemente `PixProvider` e aponte `PIX_PROVIDER` para ele.
"""

import secrets
import string
import unicodedata

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.utils.safestring import mark_safe

TXID_ALPHABET = string.ascii_uppercase + string.digits


def crc16(payload):
    """CRC16-CCITT (polinômio 0x1021, valor inicial 0xFFFF), exigido no fim do BR Code."""
    crc = 0xFFFF
    for byte in payload.encode():
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def _field(identifier, value):
    return f"{identifier}{len(value):02d}{value}"


def _plain(text, limit):
    """Nome e cidade do recebedor: sem acento, em maiúsculas e no tamanho máximo do padrão."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char) and ord(char) < 128)
    cleaned = "".join(char for char in ascii_only.upper() if char.isalnum() or char == " ")
    return " ".join(cleaned.split())[:limit] or "RECEBEDOR"


def new_txid():
    """Identificador da cobrança: até 25 letras e números, como pede o padrão."""
    return "QNM" + "".join(secrets.choice(TXID_ALPHABET) for _ in range(22))


def brcode(chave, nome, cidade, valor, txid):
    """Pix copia e cola com valor fixo e identificador da cobrança."""
    conta = _field("00", "br.gov.bcb.pix") + _field("01", chave.strip())
    payload = (
        _field("00", "01")
        + _field("26", conta)
        + _field("52", "0000")
        + _field("53", "986")
        + _field("54", f"{valor:.2f}")
        + _field("58", "BR")
        + _field("59", _plain(nome, 25))
        + _field("60", _plain(cidade or "BRASIL", 15))
        + _field("62", _field("05", txid[:25]))
        + "6304"
    )
    return payload + crc16(payload)


def qr_svg(payload):
    """QR Code em SVG, sem depender de biblioteca de imagem."""
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return mark_safe(image.to_string(encoding="unicode"))


class PixProvider:
    code = ""
    # Confirma o pagamento sozinho (webhook do provedor). O estático depende da equipe.
    automatic = False

    def create_charge(self, estabelecimento, valor, txid, expira_em):
        """Devolve {"copia_e_cola": ..., "id_externo": ...}."""
        raise NotImplementedError


class StaticPixProvider(PixProvider):
    code = "estatico"

    def create_charge(self, estabelecimento, valor, txid, expira_em):
        codigo = brcode(
            estabelecimento.chave_pix, estabelecimento.nome, estabelecimento.pix_cidade, valor, txid
        )
        return {"copia_e_cola": codigo, "id_externo": ""}


class FakePixProvider(StaticPixProvider):
    """Para desenvolvimento e testes: a página de pagamento ganha um botão que simula o aviso do provedor."""

    code = "simulado"
    automatic = True


PROVIDERS = {provider.code: provider for provider in (StaticPixProvider, FakePixProvider)}


def get_provider():
    return PROVIDERS[getattr(settings, "PIX_PROVIDER", "estatico")]()
