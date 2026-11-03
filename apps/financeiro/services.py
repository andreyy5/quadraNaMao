"""Regras do financeiro: caixa, lançamentos e contas.

Todo dinheiro que entra ou sai passa por um lançamento em um caixa aberto. Valores já lançados
não mudam: uma correção é um estorno. Usa `all_tenants` com filtro explícito, como os demais serviços.

Ordem das travas, para duas operações simultâneas não se bloquearem: reserva, conta, caixa.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.agenda.models import Reserva

from . import pix
from .models import (
    Caixa,
    Categoria,
    ContaBase,
    ContaPagar,
    ContaReceber,
    FormaPagamento,
    Lancamento,
    Pagamento,
)

ZERO = Decimal("0")
RECURRING_HORIZON_DAYS = 31


class FinanceError(Exception):
    """Regra financeira violada. A mensagem pode ser mostrada ao usuário."""


class RegisterClosed(FinanceError):
    def __init__(self):
        super().__init__("Abra o seu caixa para registrar esse valor.")


class RegisterAlreadyOpen(FinanceError):
    def __init__(self):
        super().__init__("Você já tem um caixa aberto.")


class RegisterAlreadyClosed(FinanceError):
    def __init__(self):
        super().__init__("Este caixa já foi fechado.")


class InvalidAmount(FinanceError):
    def __init__(self):
        super().__init__("Informe um valor maior que zero.")


class AmountAboveBalance(FinanceError):
    def __init__(self, saldo):
        valor = f"{saldo:.2f}".replace(".", ",")
        super().__init__(f"O valor é maior que o que falta receber (R$ {valor}).")


class NotEnoughCash(FinanceError):
    def __init__(self):
        super().__init__("Não há esse valor em dinheiro no caixa.")


class AccountNotOpen(FinanceError):
    def __init__(self, conta):
        super().__init__(f"Esta conta já está {conta.get_status_display().lower()}.")


class AccountLocked(FinanceError):
    """A conta tem um dono ou um histórico que impede a operação pedida."""


class CannotReverse(FinanceError):
    def __init__(self):
        super().__init__("Esse lançamento não pode ser estornado.")


# --- Caixa


def online_register(estabelecimento):
    """Caixa que recebe o que o provedor de Pix confirma sozinho. É criado na primeira vez que precisa."""
    caixa = Caixa.all_tenants.filter(
        estabelecimento=estabelecimento, tipo=Caixa.Tipo.ONLINE, fechado_em__isnull=True
    ).first()
    if caixa:
        return caixa
    try:
        with transaction.atomic():
            return Caixa.all_tenants.create(estabelecimento=estabelecimento, tipo=Caixa.Tipo.ONLINE)
    except IntegrityError:
        return Caixa.all_tenants.get(
            estabelecimento=estabelecimento, tipo=Caixa.Tipo.ONLINE, fechado_em__isnull=True
        )


def current_register(usuario):
    """Caixa aberto do operador, ou None."""
    return Caixa.all_tenants.filter(
        operador=usuario, estabelecimento_id=usuario.estabelecimento_id, fechado_em__isnull=True
    ).first()


def _lock_current_register(usuario):
    if usuario is None:
        raise RegisterClosed
    caixa = (
        Caixa.all_tenants.select_for_update()
        .filter(operador=usuario, estabelecimento_id=usuario.estabelecimento_id, fechado_em__isnull=True)
        .first()
    )
    if caixa is None:
        raise RegisterClosed
    return caixa


def open_register(usuario, saldo_inicial=ZERO):
    if saldo_inicial < 0:
        raise InvalidAmount
    try:
        with transaction.atomic():
            return Caixa.all_tenants.create(
                estabelecimento_id=usuario.estabelecimento_id, operador=usuario, saldo_inicial=saldo_inicial
            )
    except IntegrityError as exc:
        raise RegisterAlreadyOpen from exc


def _entry(caixa, tipo, origem, forma, valor, usuario, **fields):
    return Lancamento.all_tenants.create(
        estabelecimento_id=caixa.estabelecimento_id,
        caixa=caixa,
        tipo=tipo,
        origem=origem,
        forma=forma,
        valor=valor,
        usuario=usuario,
        **fields,
    )


def _cash_balance(caixa):
    entradas, saidas = ZERO, ZERO
    rows = (
        Lancamento.all_tenants.filter(caixa=caixa, forma=FormaPagamento.DINHEIRO)
        .values("tipo")
        .annotate(total=Sum("valor"))
    )
    for row in rows:
        if row["tipo"] == Lancamento.Tipo.ENTRADA:
            entradas = row["total"]
        else:
            saidas = row["total"]
    return caixa.saldo_inicial + entradas - saidas


def _ensure_cash_available(caixa, forma, valor):
    if forma == FormaPagamento.DINHEIRO and valor > _cash_balance(caixa):
        raise NotEnoughCash


@transaction.atomic
def move_cash(usuario, entra, valor, descricao=""):
    """Dinheiro colocado no caixa (troco, reforço) ou retirado dele (sangria, compra rápida)."""
    if valor <= 0:
        raise InvalidAmount
    caixa = _lock_current_register(usuario)
    if not entra:
        _ensure_cash_available(caixa, FormaPagamento.DINHEIRO, valor)
    return _entry(
        caixa,
        Lancamento.Tipo.ENTRADA if entra else Lancamento.Tipo.SAIDA,
        Lancamento.Origem.SUPRIMENTO if entra else Lancamento.Origem.RETIRADA,
        FormaPagamento.DINHEIRO,
        valor,
        usuario,
        descricao=descricao,
    )


def register_summary(caixa):
    """Tudo o que passou pelo caixa, por origem e por forma, e o dinheiro que deveria estar nele."""
    rows = (
        Lancamento.all_tenants.filter(caixa=caixa)
        .values("tipo", "origem", "forma", "estorno_de__origem")
        .annotate(total=Sum("valor"))
    )
    origens = {origem: ZERO for origem in Lancamento.Origem.values}
    formas = {forma: ZERO for forma in FormaPagamento.values}
    for row in rows:
        signed = row["total"] if row["tipo"] == Lancamento.Tipo.ENTRADA else -row["total"]
        # Um estorno abate da origem do lançamento estornado: a venda cancelada some das vendas.
        origens[row["estorno_de__origem"] or row["origem"]] += signed
        formas[row["forma"]] += signed

    Origem = Lancamento.Origem
    labels = dict(FormaPagamento.choices)
    return {
        "reservas": origens[Origem.RESERVA],
        "vendas": origens[Origem.VENDA],
        "contas_receber": origens[Origem.CONTA_RECEBER],
        "contas_pagar": origens[Origem.CONTA_PAGAR],
        "suprimentos": origens[Origem.SUPRIMENTO],
        "retiradas": origens[Origem.RETIRADA],
        "recebido": origens[Origem.RESERVA] + origens[Origem.VENDA] + origens[Origem.CONTA_RECEBER],
        "por_forma": [
            {"forma": forma, "label": labels[forma], "total": total}
            for forma, total in formas.items()
            if total
        ],
        "dinheiro_esperado": caixa.saldo_inicial + formas[FormaPagamento.DINHEIRO],
    }


@transaction.atomic
def close_register(caixa, saldo_conferido, fechado_por, observacao=""):
    """Fecha com a conferência do dinheiro. Pix e cartão são informados, mas não entram na contagem."""
    if saldo_conferido < 0:
        raise InvalidAmount
    caixa = Caixa.all_tenants.select_for_update().get(pk=caixa.pk)
    if not caixa.is_open:
        raise RegisterAlreadyClosed
    esperado = _cash_balance(caixa)
    caixa.saldo_esperado = esperado
    caixa.saldo_conferido = saldo_conferido
    caixa.diferenca = saldo_conferido - esperado
    caixa.observacao = observacao
    caixa.fechado_em = timezone.now()
    caixa.fechado_por = fechado_por
    caixa.save()
    return caixa


# --- Contas a receber


def _refresh_paid_state(conta):
    if conta.is_cancelled:
        return
    if conta.valor_pago >= conta.valor:
        conta.status = ContaBase.Status.PAGA
        conta.pago_em = conta.pago_em or timezone.now()
    else:
        conta.status = ContaBase.Status.ABERTA
        conta.pago_em = None


def sync_reservation_account(reserva):
    """Mantém a conta a receber igual à reserva. Toda reserva tem uma, criada junto com ela."""
    local = timezone.localtime(reserva.inicio, reserva.estabelecimento.timezone)
    descricao = f"Reserva {reserva.espaco.nome} · {local:%d/%m %H:%M}"
    conta = ContaReceber.all_tenants.select_for_update().filter(reserva=reserva).first()
    if conta is None:
        conta = ContaReceber(
            estabelecimento_id=reserva.estabelecimento_id,
            reserva=reserva,
            categoria=Categoria.RESERVA,
            criado_por=reserva.criado_por,
        )
    conta.descricao = descricao
    conta.cliente = reserva.cliente
    conta.valor = reserva.valor_total
    conta.vencimento = local.date()
    if reserva.status == Reserva.Status.CANCELADA:
        conta.status = ContaBase.Status.CANCELADA
    _refresh_paid_state(conta)
    conta.save()
    return conta


def _set_reservation_paid(conta):
    if conta.reserva_id:
        Reserva.all_tenants.filter(pk=conta.reserva_id).update(
            valor_pago=conta.valor_pago, atualizado_em=timezone.now()
        )


def _lock_account(model, conta):
    return model.all_tenants.select_for_update().get(pk=conta.pk)


@transaction.atomic
def receive_account(conta, valor, forma, usuario, caixa=None):
    """Baixa total ou parcial de uma conta a receber, com o lançamento no caixa do operador.

    Com `caixa`, o valor entra nele; é o caso do caixa online, que recebe o Pix confirmado pelo provedor.
    """
    if valor <= 0:
        raise InvalidAmount
    if conta.reserva_id:
        Reserva.all_tenants.select_for_update().get(pk=conta.reserva_id)
    conta = _lock_account(ContaReceber, conta)
    if not conta.is_open:
        raise AccountNotOpen(conta)
    if valor > conta.saldo:
        raise AmountAboveBalance(conta.saldo)
    if caixa is None:
        caixa = _lock_current_register(usuario)
    else:
        caixa = Caixa.all_tenants.select_for_update().get(pk=caixa.pk)
        if not caixa.is_open:
            raise RegisterAlreadyClosed
    lancamento = _entry(
        caixa,
        Lancamento.Tipo.ENTRADA,
        Lancamento.Origem.RESERVA if conta.reserva_id else Lancamento.Origem.CONTA_RECEBER,
        forma,
        valor,
        usuario,
        categoria=conta.categoria,
        descricao=conta.descricao,
        conta_receber=conta,
        reserva_id=conta.reserva_id,
    )
    conta.valor_pago += valor
    conta.forma_pagamento = forma
    _refresh_paid_state(conta)
    conta.save()
    _set_reservation_paid(conta)
    return lancamento


# --- Vendas do PDV


def record_sale_income(venda, usuario):
    """Entrada da venda no caixa do operador. Chamada de dentro da transação da venda."""
    caixa = _lock_current_register(usuario)
    venda.caixa = caixa
    venda.save(update_fields=["caixa", "atualizado_em"])
    if venda.total <= 0:
        return None
    return _entry(
        caixa,
        Lancamento.Tipo.ENTRADA,
        Lancamento.Origem.VENDA,
        venda.forma_pagamento,
        venda.total,
        usuario,
        categoria=Categoria.VENDA,
        descricao=f"Venda #{venda.numero}",
        venda=venda,
    )


def reverse_sale_income(venda, usuario, motivo=""):
    """Devolve o dinheiro de uma venda cancelada. Vendas de antes do caixa existir não têm lançamento."""
    lancamento = Lancamento.all_tenants.filter(
        venda=venda, origem=Lancamento.Origem.VENDA, estorno__isnull=True
    ).first()
    if lancamento is None:
        return None
    return _reverse(lancamento, usuario, motivo or f"Venda #{venda.numero} cancelada")


# --- Contas a pagar


@transaction.atomic
def pay_bill(conta, forma, usuario, from_register=True):
    """Dá baixa na conta. Só vira lançamento se o dinheiro saiu do caixa: boleto pago no banco não entra."""
    conta = _lock_account(ContaPagar, conta)
    if not conta.is_open:
        raise AccountNotOpen(conta)
    if from_register:
        caixa = _lock_current_register(usuario)
        _ensure_cash_available(caixa, forma, conta.valor)
        _entry(
            caixa,
            Lancamento.Tipo.SAIDA,
            Lancamento.Origem.CONTA_PAGAR,
            forma,
            conta.valor,
            usuario,
            categoria=conta.categoria,
            descricao=conta.descricao,
            conta_pagar=conta,
        )
    conta.valor_pago = conta.valor
    conta.forma_pagamento = forma
    _refresh_paid_state(conta)
    conta.save()
    return conta


def create_purchase_bill(produto, quantidade, custo, vencimento, fornecedor="", usuario=None):
    """Conta a pagar de uma entrada de estoque."""
    return ContaPagar.all_tenants.create(
        estabelecimento_id=produto.estabelecimento_id,
        descricao=f"Compra de {quantidade}x {produto.nome}"[:120],
        categoria=Categoria.FORNECEDOR,
        fornecedor=fornecedor,
        valor=quantidade * custo,
        vencimento=vencimento,
        criado_por=usuario,
    )


# --- Comuns às contas


@transaction.atomic
def cancel_account(conta, stop_repeating=False):
    """Cancela uma conta sem pagamentos. A da reserva acompanha a reserva."""
    model = type(conta)
    if getattr(conta, "reserva_id", None):
        raise AccountLocked("Essa conta é da reserva. Para cancelar, cancele a reserva.")
    conta = _lock_account(model, conta)
    if not conta.is_open:
        raise AccountNotOpen(conta)
    if conta.valor_pago > 0:
        raise AccountLocked("Essa conta já tem valores recebidos. Estorne os lançamentos antes de cancelar.")
    conta.status = ContaBase.Status.CANCELADA
    conta.save(update_fields=["status", "atualizado_em"])
    if stop_repeating:
        origem_id = conta.recorrencia_origem_id or conta.pk
        model.all_tenants.filter(pk=origem_id).update(recorrencia=ContaBase.Recorrencia.NENHUMA)
    return conta


# --- Estorno


def _reverse(lancamento, usuario, motivo):
    caixa = _lock_current_register(usuario)
    if lancamento.is_income:
        _ensure_cash_available(caixa, lancamento.forma, lancamento.valor)
    try:
        with transaction.atomic():
            return _entry(
                caixa,
                Lancamento.Tipo.SAIDA if lancamento.is_income else Lancamento.Tipo.ENTRADA,
                Lancamento.Origem.ESTORNO,
                lancamento.forma,
                lancamento.valor,
                usuario,
                categoria=lancamento.categoria,
                descricao=motivo or f"Estorno: {lancamento.descricao}"[:200],
                reserva_id=lancamento.reserva_id,
                venda_id=lancamento.venda_id,
                conta_receber_id=lancamento.conta_receber_id,
                conta_pagar_id=lancamento.conta_pagar_id,
                estorno_de=lancamento,
            )
    except IntegrityError as exc:
        raise CannotReverse from exc


@transaction.atomic
def reverse_entry(lancamento, usuario, motivo=""):
    """Desfaz um lançamento no caixa atual de quem estorna e reabre a conta ligada a ele."""
    if not lancamento.can_reverse:
        raise CannotReverse
    if lancamento.reserva_id:
        Reserva.all_tenants.select_for_update().get(pk=lancamento.reserva_id)
    conta_receber = conta_pagar = None
    if lancamento.conta_receber_id:
        conta_receber = ContaReceber.all_tenants.select_for_update().get(pk=lancamento.conta_receber_id)
    if lancamento.conta_pagar_id:
        conta_pagar = ContaPagar.all_tenants.select_for_update().get(pk=lancamento.conta_pagar_id)

    estorno = _reverse(lancamento, usuario, motivo)

    if conta_receber:
        conta_receber.valor_pago -= lancamento.valor
        _refresh_paid_state(conta_receber)
        conta_receber.save()
        _set_reservation_paid(conta_receber)
    if conta_pagar:
        conta_pagar.valor_pago = ZERO
        conta_pagar.forma_pagamento = ""
        _refresh_paid_state(conta_pagar)
        conta_pagar.save()
    return estorno


# --- Recorrência


def next_due_date(base, recorrencia, step):
    """A `step`-ésima repetição, sempre a partir da data original: dia 31 volta a 31 depois de fevereiro."""
    if recorrencia == ContaBase.Recorrencia.SEMANAL:
        return base + timedelta(weeks=step)
    months = step * (12 if recorrencia == ContaBase.Recorrencia.ANUAL else 1)
    index = base.month - 1 + months
    year, month = base.year + index // 12, index % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def _generate_for_model(model, estabelecimento, until):
    created = 0
    origens = model.all_tenants.filter(
        estabelecimento=estabelecimento, recorrencia_origem__isnull=True
    ).exclude(recorrencia=ContaBase.Recorrencia.NENHUMA)
    for origem in origens:
        existing = set(
            model.all_tenants.filter(recorrencia_origem=origem).values_list("vencimento", flat=True)
        )
        step = 1
        due = next_due_date(origem.vencimento, origem.recorrencia, step)
        while due <= until:
            if due not in existing:
                copied = {
                    name: getattr(origem, name)
                    for name in ("descricao", "categoria", "valor", "observacoes", "criado_por_id")
                }
                if model is ContaPagar:
                    copied["fornecedor"] = origem.fornecedor
                else:
                    copied["cliente_id"] = origem.cliente_id
                _, was_created = model.all_tenants.get_or_create(
                    recorrencia_origem=origem,
                    vencimento=due,
                    defaults={"estabelecimento": estabelecimento, **copied},
                )
                created += int(was_created)
            step += 1
            due = next_due_date(origem.vencimento, origem.recorrencia, step)
    return created


def generate_recurring_accounts(estabelecimento, today=None):
    """Cria as repetições que vencem no próximo mês. Pode rodar quantas vezes for: não duplica."""
    today = today or timezone.now().astimezone(estabelecimento.timezone).date()
    until = today + timedelta(days=RECURRING_HORIZON_DAYS)
    return _generate_for_model(ContaPagar, estabelecimento, until) + _generate_for_model(
        ContaReceber, estabelecimento, until
    )


# --- Alertas


def _summary(queryset):
    row = queryset.aggregate(total=Sum("valor"), pago=Sum("valor_pago"), count=Count("pk"))
    return {"total": (row["total"] or ZERO) - (row["pago"] or ZERO), "count": row["count"]}


def accounts_overview(model, estabelecimento, today=None):
    """Em atraso, vencendo hoje e nos próximos dias."""
    today = today or timezone.now().astimezone(estabelecimento.timezone).date()
    abertas = model.all_tenants.filter(estabelecimento=estabelecimento, status=ContaBase.Status.ABERTA)
    return {
        "overdue": _summary(abertas.filter(vencimento__lt=today)),
        "today": _summary(abertas.filter(vencimento=today)),
        "next_days": _summary(
            abertas.filter(vencimento__gt=today, vencimento__lte=today + timedelta(days=7))
        ),
    }


# --- Cobrança Pix


def create_pix_charge(reserva, valor, expira_em):
    """Gera o Pix copia e cola da reserva no provedor configurado."""
    provider = pix.get_provider()
    txid = pix.new_txid()
    data = provider.create_charge(reserva.estabelecimento, valor, txid, expira_em)
    return Pagamento.all_tenants.create(
        estabelecimento_id=reserva.estabelecimento_id,
        reserva=reserva,
        valor=valor,
        provedor=provider.code,
        txid=txid,
        id_externo=data.get("id_externo", ""),
        copia_e_cola=data["copia_e_cola"],
        expira_em=expira_em,
    )
