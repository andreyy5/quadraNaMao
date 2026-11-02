"""Regras de estoque. O saldo do produto só muda por aqui, sempre deixando uma movimentação.

Usa `all_tenants` com filtro explícito para funcionar fora de uma requisição, como os demais serviços.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from .models import MovimentacaoEstoque, Produto


class StockError(Exception):
    """Regra de estoque violada. A mensagem pode ser mostrada ao usuário."""


class InsufficientStock(StockError):
    def __init__(self, produto):
        self.produto = produto
        restam = max(produto.estoque_atual, 0)
        super().__init__(f"Estoque insuficiente de {produto.nome}: restam {restam}.")


class InvalidQuantity(StockError):
    def __init__(self):
        super().__init__("Informe uma quantidade válida.")


class NotStocked(StockError):
    def __init__(self, produto):
        super().__init__(f"{produto.nome} não tem controle de estoque.")


def lock_products(pks):
    """Trava os produtos sempre na mesma ordem, para duas vendas simultâneas não se bloquearem."""
    queryset = Produto.all_tenants.select_for_update(of=("self",)).select_related("estabelecimento")
    return list(queryset.filter(pk__in=pks).order_by("pk"))


def _record(produto, tipo, origem, delta, usuario=None, observacao="", referencia=""):
    """Aplica a variação em um produto já travado pela transação em andamento."""
    novo_saldo = produto.estoque_atual + delta
    if delta < 0 and novo_saldo < 0 and not produto.estabelecimento.permite_estoque_negativo:
        raise InsufficientStock(produto)
    produto.estoque_atual = novo_saldo
    produto.save(update_fields=["estoque_atual", "atualizado_em"])
    return MovimentacaoEstoque.all_tenants.create(
        estabelecimento_id=produto.estabelecimento_id,
        produto=produto,
        tipo=tipo,
        origem=origem,
        quantidade=delta,
        saldo_apos=novo_saldo,
        usuario=usuario,
        observacao=observacao,
        referencia=referencia,
    )


def _locked(produto):
    if not produto.controla_estoque:
        raise NotStocked(produto)
    return lock_products([produto.pk])[0]


@transaction.atomic
def register_entry(produto, quantidade, usuario=None, custo=None, observacao=""):
    """Entrada por compra. Um custo informado passa a ser o custo do produto."""
    if quantidade <= 0:
        raise InvalidQuantity
    locked = _locked(produto)
    if custo is not None:
        locked.custo = custo
        locked.save(update_fields=["custo", "atualizado_em"])
    return _record(
        locked,
        MovimentacaoEstoque.Tipo.ENTRADA,
        MovimentacaoEstoque.Origem.COMPRA,
        quantidade,
        usuario,
        observacao,
    )


@transaction.atomic
def register_loss(produto, quantidade, usuario=None, observacao=""):
    if quantidade <= 0:
        raise InvalidQuantity
    return _record(
        _locked(produto),
        MovimentacaoEstoque.Tipo.PERDA,
        MovimentacaoEstoque.Origem.MANUAL,
        -quantidade,
        usuario,
        observacao,
    )


@transaction.atomic
def adjust_to_count(produto, contagem, usuario=None, observacao=""):
    """Acerta o saldo pelo que foi contado na prateleira. Contagem igual ao saldo não gera registro."""
    if contagem < 0:
        raise InvalidQuantity
    locked = _locked(produto)
    delta = contagem - locked.estoque_atual
    if delta == 0:
        return None
    # A contagem é o saldo real: nunca é recusada por deixar o saldo baixo.
    locked.estoque_atual = contagem
    locked.save(update_fields=["estoque_atual", "atualizado_em"])
    return MovimentacaoEstoque.all_tenants.create(
        estabelecimento_id=locked.estabelecimento_id,
        produto=locked,
        tipo=MovimentacaoEstoque.Tipo.AJUSTE,
        origem=MovimentacaoEstoque.Origem.MANUAL,
        quantidade=delta,
        saldo_apos=contagem,
        usuario=usuario,
        observacao=observacao,
    )


def record_sale_exit(produto, quantidade, usuario=None, referencia=""):
    """Baixa de uma venda. Deve ser chamada com o produto já travado, dentro da transação da venda."""
    return _record(
        produto,
        MovimentacaoEstoque.Tipo.SAIDA,
        MovimentacaoEstoque.Origem.VENDA,
        -quantidade,
        usuario,
        referencia=referencia,
    )


def record_sale_return(produto, quantidade, usuario=None, referencia=""):
    """Devolve ao estoque o que saiu em uma venda cancelada ou em um item retirado da comanda."""
    return _record(
        produto,
        MovimentacaoEstoque.Tipo.ENTRADA,
        MovimentacaoEstoque.Origem.CANCELAMENTO,
        quantidade,
        usuario,
        referencia=referencia,
    )


def stock_overview(estabelecimento):
    """Números do topo da tela de estoque."""
    produtos = Produto.all_tenants.filter(estabelecimento=estabelecimento, ativo=True)
    controlados = produtos.filter(controla_estoque=True)
    valor = controlados.filter(estoque_atual__gt=0, custo__isnull=False).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("estoque_atual") * F("custo"), output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
    )["total"]
    return {
        "total": produtos.count(),
        "low": controlados.filter(estoque_atual__lte=F("estoque_minimo")).count(),
        "value": valor or Decimal("0"),
    }
