import re

import phonenumbers
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.agenda.models import Reserva

from .models import Cliente

ANONYMIZED_NAME = "Cliente anonimizado"


class InvalidPhone(Exception):
    def __init__(self):
        super().__init__("Telefone inválido. Informe o DDD e o número, como (11) 98888-7777.")


def normalize_phone(raw):
    """Converte para E.164. Sem código do país, assume Brasil."""
    try:
        parsed = phonenumbers.parse(raw or "", "BR")
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhone
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def format_phone(value):
    """E.164 para exibição: +5511988887777 vira (11) 98888-7777."""
    try:
        parsed = phonenumbers.parse(value or "", "BR")
    except phonenumbers.NumberParseException:
        return "—"
    fmt = phonenumbers.PhoneNumberFormat.NATIONAL
    if parsed.country_code != 55:
        fmt = phonenumbers.PhoneNumberFormat.INTERNATIONAL
    return phonenumbers.format_number(parsed, fmt)


def search_clients(query, limit=None):
    """Busca por nome, sem diferenciar acentos, ou por dígitos do telefone."""
    queryset = Cliente.objects.filter(anonimizado_em__isnull=True)
    query = (query or "").strip()
    if query:
        condition = Q(nome__unaccent__icontains=query)
        digits = re.sub(r"\D", "", query)
        if digits:
            condition |= Q(telefone__contains=digits)
        queryset = queryset.filter(condition)
    return queryset[:limit] if limit else queryset


def find_or_create_client(estabelecimento, nome, telefone):
    """Devolve o cliente com esse telefone ou cria um novo. Um cliente existente mantém o nome."""
    cliente, _ = Cliente.all_tenants.get_or_create(
        estabelecimento=estabelecimento,
        telefone=normalize_phone(telefone),
        defaults={"nome": nome.strip()},
    )
    return cliente


@transaction.atomic
def anonymize_client(cliente):
    """LGPD: apaga os dados pessoais e mantém o histórico de reservas para os relatórios."""
    cliente.nome = ANONYMIZED_NAME
    cliente.telefone = f"anon-{cliente.pk}"
    cliente.email = ""
    cliente.observacoes = ""
    cliente.aceite_whatsapp = False
    cliente.anonimizado_em = timezone.now()
    cliente.save()
    Reserva.all_tenants.filter(cliente=cliente).update(observacoes="")
    from apps.whatsapp.models import Mensagem

    Mensagem.all_tenants.filter(cliente=cliente).update(corpo="", telefone=cliente.telefone, parametros=[])
