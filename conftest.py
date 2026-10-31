from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from apps.clientes.models import Cliente
from apps.espacos.models import DiaSemana, Espaco
from apps.espacos.services import save_price_rules, save_weekly_hours
from apps.estabelecimentos.models import Estabelecimento

TZ = ZoneInfo("America/Sao_Paulo")
# Uma terça-feira distante, para os testes não dependerem da data em que rodam.
DAY = datetime(2031, 3, 4).date()


def at(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def make_tenant(slug):
    return Estabelecimento.objects.create(nome=slug.title(), slug=slug)


def make_user(tenant, email, papel="DONO"):
    return get_user_model().objects.create_user(
        email, "senha-forte-123", nome=email, papel=papel, estabelecimento=tenant
    )


def make_espaco(tenant, nome="Areia 1", abre=time(8), fecha=time(22), valor=Decimal("100")):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome=nome, tipo=Espaco.Tipo.AREIA)
    rows = [{"dia_semana": dia, "aberto": True, "abre": abre, "fecha": fecha} for dia in DiaSemana.values]
    save_weekly_hours(espaco, rows)
    save_price_rules(espaco, DiaSemana.values, abre, fecha, 60, valor)
    return espaco


def make_cliente(tenant, nome="João Pereira", telefone="+5511987650001"):
    return Cliente.all_tenants.create(estabelecimento=tenant, nome=nome, telefone=telefone)


@pytest.fixture
def tenant(db):
    return make_tenant("arena-a")


@pytest.fixture
def other_tenant(db):
    return make_tenant("arena-b")


@pytest.fixture
def owner(tenant):
    return make_user(tenant, "dono@a.test")


@pytest.fixture
def attendant(tenant):
    return make_user(tenant, "atendente@a.test", "ATENDENTE")


@pytest.fixture
def espaco(tenant):
    return make_espaco(tenant)


@pytest.fixture
def cliente(tenant):
    return make_cliente(tenant)


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


HX = {"HX-Request": "true"}
