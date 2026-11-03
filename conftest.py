from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from apps.clientes.models import Cliente
from apps.espacos.models import DiaSemana, Espaco
from apps.espacos.services import save_price_rules, save_weekly_hours
from apps.estabelecimentos.models import Estabelecimento
from apps.estoque.models import MovimentacaoEstoque, Produto

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


def make_produto(
    tenant, nome="Água", preco=Decimal("4"), estoque=10, minimo=0, custo=None, codigo="", ativo=True
):
    """Produto com saldo inicial. Com estoque=None, fica sem controle de estoque."""
    produto = Produto.all_tenants.create(
        estabelecimento=tenant,
        nome=nome,
        preco_venda=preco,
        custo=custo,
        codigo=codigo,
        ativo=ativo,
        controla_estoque=estoque is not None,
        estoque_minimo=minimo,
        estoque_atual=estoque or 0,
    )
    if estoque:
        MovimentacaoEstoque.all_tenants.create(
            estabelecimento=tenant,
            produto=produto,
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            origem=MovimentacaoEstoque.Origem.COMPRA,
            quantidade=estoque,
            saldo_apos=estoque,
        )
    return produto


def with_register(usuario):
    """Abre o caixa do usuário, se ainda não estiver aberto, e devolve o usuário."""
    from apps.financeiro.services import current_register, open_register

    if current_register(usuario) is None:
        open_register(usuario)
    return usuario


def cashier(tenant):
    """Um atendente com caixa aberto, para os testes que só precisam registrar um pagamento."""
    email = f"caixa@{tenant.slug}.test"
    usuario = get_user_model().objects.filter(email=email).first() or make_user(tenant, email, "ATENDENTE")
    return with_register(usuario)


@pytest.fixture(autouse=True)
def _clear_cache():
    """O limite de tentativas usa o cache: cada teste começa com a contagem zerada."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


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
