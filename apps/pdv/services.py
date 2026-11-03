"""Regras do PDV: venda direta, comanda na reserva e cancelamento.

O preço sempre vem do cadastro, nunca da tela. Tudo acontece em uma transação: se um item
não tiver estoque, nada é gravado. Usa `all_tenants` com filtro explícito, como os demais serviços.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from apps.agenda.models import Reserva
from apps.estabelecimentos.models import Estabelecimento
from apps.estoque.models import Produto
from apps.estoque.services import lock_products, record_sale_exit, record_sale_return
from apps.financeiro.models import ContaReceber
from apps.financeiro.services import receive_account, record_sale_income, reverse_sale_income

from .models import ItemVenda, Venda

MAX_ITEM_QUANTITY = 9999


class SaleError(Exception):
    """Regra de venda violada. A mensagem pode ser mostrada ao usuário."""


class EmptyCart(SaleError):
    def __init__(self):
        super().__init__("Adicione pelo menos um produto.")


class InvalidCartQuantity(SaleError):
    def __init__(self):
        super().__init__("Confira as quantidades do carrinho.")


class ProductUnavailable(SaleError):
    def __init__(self):
        super().__init__("Um dos produtos não está mais disponível. Confira o carrinho.")


class PriceChanged(SaleError):
    def __init__(self):
        super().__init__("Os preços mudaram enquanto você vendia. Confira o novo total e confirme de novo.")


class InsufficientPayment(SaleError):
    def __init__(self):
        super().__init__("O valor recebido é menor que o total.")


class InvalidReservation(SaleError):
    def __init__(self):
        super().__init__("Essa reserva não pode receber consumo.")


class SaleClosed(SaleError):
    def __init__(self, venda):
        super().__init__(f"A venda #{venda.numero} já está {venda.get_status_display().lower()}.")


def _next_number(estabelecimento):
    """Próximo número do estabelecimento. A trava enfileira quem está vendendo ao mesmo tempo."""
    Estabelecimento.objects.select_for_update().get(pk=estabelecimento.pk)
    last = Venda.all_tenants.filter(estabelecimento=estabelecimento).aggregate(last=Max("numero"))["last"]
    return (last or 0) + 1


def _load_cart(estabelecimento, items):
    """Trava os produtos do carrinho e devolve pares (produto, quantidade). `items` é {pk do produto: quantidade}."""
    items = {pk: quantidade for pk, quantidade in items.items() if quantidade > 0}
    if not items:
        raise EmptyCart
    if max(items.values()) > MAX_ITEM_QUANTITY:
        raise InvalidCartQuantity
    produtos = [
        produto
        for produto in lock_products(items)
        if produto.estabelecimento_id == estabelecimento.pk and produto.ativo
    ]
    if len(produtos) != len(items):
        raise ProductUnavailable
    return [(produto, items[produto.pk]) for produto in produtos]


def _check_total(cart, esperado):
    if esperado is not None and sum(p.preco_venda * q for p, q in cart) != esperado:
        raise PriceChanged


def _items(venda):
    return ItemVenda.all_tenants.filter(venda=venda)


def _add_items(venda, cart, usuario):
    for produto, quantidade in cart:
        if produto.controla_estoque:
            record_sale_exit(produto, quantidade, usuario, referencia=f"Venda #{venda.numero}")
        item = _items(venda).filter(produto=produto, preco_unitario=produto.preco_venda).first()
        if item:
            item.quantidade += quantidade
            item.save(update_fields=["quantidade", "atualizado_em"])
        else:
            ItemVenda.all_tenants.create(
                estabelecimento_id=venda.estabelecimento_id,
                venda=venda,
                produto=produto,
                quantidade=quantidade,
                preco_unitario=produto.preco_venda,
            )
    _refresh_total(venda)


def _refresh_total(venda):
    venda.total = sum((item.subtotal for item in _items(venda)), Decimal("0"))
    venda.save(update_fields=["total", "atualizado_em"])


@transaction.atomic
def complete_sale(estabelecimento, items, forma, usuario=None, recebido=None, total_esperado=None):
    """Venda paga na hora: baixa o estoque e fica concluída."""
    numero = _next_number(estabelecimento)
    cart = _load_cart(estabelecimento, items)
    _check_total(cart, total_esperado)
    venda = Venda.all_tenants.create(
        estabelecimento=estabelecimento,
        numero=numero,
        status=Venda.Status.CONCLUIDA,
        forma_pagamento=forma,
        criado_por=usuario,
        concluida_em=timezone.now(),
    )
    _add_items(venda, cart, usuario)
    _register_payment(venda, recebido)
    record_sale_income(venda, usuario)
    return venda


def _register_payment(venda, recebido):
    if venda.forma_pagamento != Venda.Forma.DINHEIRO or recebido is None:
        return
    if recebido < venda.total:
        raise InsufficientPayment
    venda.valor_recebido = recebido
    venda.save(update_fields=["valor_recebido", "atualizado_em"])


@transaction.atomic
def add_to_tab(estabelecimento, reserva, items, usuario=None, total_esperado=None):
    """Lança o consumo na comanda da reserva. O estoque baixa agora; o pagamento fica para o fechamento."""
    if reserva.estabelecimento_id != estabelecimento.pk or reserva.status == Reserva.Status.CANCELADA:
        raise InvalidReservation
    numero = _next_number(estabelecimento)
    venda = Venda.all_tenants.select_for_update().filter(reserva=reserva, status=Venda.Status.ABERTA).first()
    cart = _load_cart(estabelecimento, items)
    _check_total(cart, total_esperado)
    if venda is None:
        venda = Venda.all_tenants.create(
            estabelecimento=estabelecimento,
            numero=numero,
            status=Venda.Status.ABERTA,
            reserva=reserva,
            cliente=reserva.cliente,
            criado_por=usuario,
        )
    _add_items(venda, cart, usuario)
    return venda


def _lock_sale(venda):
    return Venda.all_tenants.select_for_update().get(pk=venda.pk)


@transaction.atomic
def close_tab(venda, forma, usuario, recebido=None):
    """Recebe o pagamento de uma comanda, com a entrada no caixa de quem recebeu."""
    venda = _lock_sale(venda)
    if not venda.is_tab:
        raise SaleClosed(venda)
    venda.status = Venda.Status.CONCLUIDA
    venda.forma_pagamento = forma
    venda.concluida_em = timezone.now()
    venda.save(update_fields=["status", "forma_pagamento", "concluida_em", "atualizado_em"])
    _register_payment(venda, recebido)
    record_sale_income(venda, usuario)
    return venda


class NothingToCharge(SaleError):
    def __init__(self):
        super().__init__("Não há nada para receber nesta reserva.")


@transaction.atomic
def charge_reservation(reserva, valor, forma, usuario, include_tab=True, recebido=None):
    """Recebe a reserva e, se pedido, a comanda dela de uma vez: cada uma gera o próprio lançamento."""
    comanda = None
    if include_tab:
        comanda = Venda.all_tenants.filter(reserva=reserva, status=Venda.Status.ABERTA).first()
    total = valor + (comanda.total if comanda else Decimal("0"))
    if total <= 0:
        raise NothingToCharge
    if forma == Venda.Forma.DINHEIRO and recebido is not None and recebido < total:
        raise InsufficientPayment
    if valor > 0:
        receive_account(ContaReceber.all_tenants.get(reserva=reserva), valor, forma, usuario)
    if comanda:
        close_tab(comanda, forma, usuario)
    troco = recebido - total if forma == Venda.Forma.DINHEIRO and recebido else Decimal("0")
    return {"total": total, "troco": troco, "comanda": comanda}


def _return_items(venda, itens, usuario):
    controlados = [item for item in itens if item.produto.controla_estoque]
    produtos = {produto.pk: produto for produto in lock_products([item.produto_id for item in controlados])}
    for item in controlados:
        record_sale_return(
            produtos[item.produto_id], item.quantidade, usuario, referencia=f"Venda #{venda.numero}"
        )


@transaction.atomic
def remove_tab_item(item, usuario=None):
    """Corrige uma comanda em aberto. Sem itens, ela deixa de existir como venda."""
    venda = _lock_sale(item.venda)
    if not venda.is_tab:
        raise SaleClosed(venda)
    _return_items(venda, [item], usuario)
    item.delete()
    if _items(venda).exists():
        _refresh_total(venda)
    else:
        _mark_cancelled(venda, usuario, "Comanda sem itens")
    return venda


def _mark_cancelled(venda, usuario, motivo):
    venda.status = Venda.Status.CANCELADA
    venda.cancelada_em = timezone.now()
    venda.cancelada_por = usuario
    venda.motivo_cancelamento = motivo
    venda.save(
        update_fields=["status", "cancelada_em", "cancelada_por", "motivo_cancelamento", "atualizado_em"]
    )


@transaction.atomic
def cancel_sale(venda, usuario=None, motivo=""):
    """Cancela, devolve os itens ao estoque e, se já estava paga, estorna no caixa de quem cancelou."""
    venda = _lock_sale(venda)
    if venda.is_cancelled:
        raise SaleClosed(venda)
    _return_items(venda, list(_items(venda).select_related("produto")), usuario)
    if not venda.is_tab:
        reverse_sale_income(venda, usuario, motivo)
    _mark_cancelled(venda, usuario, motivo)
    return venda


def day_summary(estabelecimento, day):
    """Vendas concluídas no dia, com o total por forma de pagamento, e comandas abertas agora."""
    tz = estabelecimento.timezone
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    vendas = Venda.all_tenants.filter(
        estabelecimento=estabelecimento,
        status=Venda.Status.CONCLUIDA,
        concluida_em__gte=start,
        concluida_em__lt=start + timedelta(days=1),
    )
    totals = vendas.aggregate(total=Sum("total"), count=Count("pk"))
    labels = dict(Venda.Forma.choices)
    por_forma = [
        {
            "forma": row["forma_pagamento"],
            "label": labels.get(row["forma_pagamento"], ""),
            "total": row["total"],
        }
        for row in vendas.values("forma_pagamento").annotate(total=Sum("total")).order_by("-total")
    ]
    abertas = Venda.all_tenants.filter(estabelecimento=estabelecimento, status=Venda.Status.ABERTA).aggregate(
        total=Sum("total"), count=Count("pk")
    )
    return {
        "total": totals["total"] or Decimal("0"),
        "count": totals["count"],
        "por_forma": por_forma,
        "tabs_total": abertas["total"] or Decimal("0"),
        "tabs_count": abertas["count"],
    }


def has_products(estabelecimento):
    return Produto.all_tenants.filter(estabelecimento=estabelecimento, ativo=True).exists()
