"""Números da tela Hoje e dos relatórios, calculados na hora a partir dos registros.

Regras comuns a todos os relatórios:
- Período com as duas datas incluídas, no fuso do estabelecimento.
- Dinheiro pelo regime de caixa: vale a data em que entrou ou saiu. Um estorno conta na data dele.
- Faturamento é o que entrou por reservas, vendas e contas a receber, menos as devoluções dessas entradas.
  Dinheiro colocado ou retirado da gaveta é movimento interno, não faturamento nem despesa.
- Despesa é conta a pagar paga: pelo caixa, vale o lançamento; pelo banco, a data da baixa.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Exists, F, Max, Min, OuterRef, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Reserva
from apps.agenda.services import occupancy_by_space, occupancy_details
from apps.clientes.models import Cliente
from apps.espacos.models import Espaco, HorarioFuncionamento, TabelaPreco
from apps.estoque.models import Produto
from apps.financeiro.models import (
    Caixa,
    Categoria,
    ContaBase,
    ContaPagar,
    ContaReceber,
    FormaPagamento,
    Lancamento,
)
from apps.pdv.models import ItemVenda, Venda

ZERO = Decimal("0")
MAX_REPORT_DAYS = 366
# A ocupação monta a grade de cada dia de cada espaço: acima disso, olha só os últimos dias do período.
MAX_OCCUPANCY_DAYS = 92
FORECAST_DAYS = 30
INCOME_ORIGINS = [Lancamento.Origem.RESERVA, Lancamento.Origem.VENDA, Lancamento.Origem.CONTA_RECEBER]
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def setup_checklist(estabelecimento):
    """Primeiros passos do dono. Devolve None quando tudo já foi feito."""
    espaco = Espaco.all_tenants.filter(estabelecimento=estabelecimento).first()
    has_hours = HorarioFuncionamento.all_tenants.filter(estabelecimento=estabelecimento).exists()
    has_prices = TabelaPreco.all_tenants.filter(estabelecimento=estabelecimento).exists()
    has_booking = Reserva.all_tenants.filter(estabelecimento=estabelecimento).exists()

    hours_url = reverse("espacos:horarios", args=[espaco.pk]) if espaco else reverse("espacos:create")
    prices_url = reverse("espacos:precos", args=[espaco.pk]) if espaco else reverse("espacos:create")
    steps = [
        {
            "label": "Cadastrar o primeiro espaço",
            "done": espaco is not None,
            "url": reverse("espacos:create"),
        },
        {"label": "Definir os horários de funcionamento", "done": has_hours, "url": hours_url},
        {"label": "Montar a tabela de preços", "done": has_prices, "url": prices_url},
        {"label": "Fazer a primeira reserva", "done": has_booking, "url": reverse("agenda:day")},
    ]
    return None if all(step["done"] for step in steps) else steps


# --- Ferramentas comuns


def bounds(estabelecimento, first, last):
    """Início do primeiro dia e início do dia seguinte ao último, no fuso do estabelecimento."""
    tz = estabelecimento.timezone
    start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start, end


def previous_period(first, last):
    """O período de mesmo tamanho logo antes, para comparar."""
    length = (last - first).days + 1
    return first - timedelta(days=length), first - timedelta(days=1)


def days_between(first, last):
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _ranked(totals, labels=None):
    """Linhas ordenadas para as barras horizontais. `share` é a largura da barra, em texto para o CSS."""
    rows = [(key, total) for key, total in totals.items() if total > 0]
    rows.sort(key=lambda row: row[1], reverse=True)
    largest = rows[0][1] if rows else Decimal("1")
    return [
        {
            "label": labels.get(key, key) if labels else key,
            "total": total,
            "share": f"{total * 100 / largest:.2f}",
        }
        for key, total in rows
    ]


def _percent(part, whole):
    return round(part * 100 / whole) if whole else 0


def _delta(current, previous):
    """Variação em % sobre o período anterior. None quando não há base para comparar."""
    if not previous:
        return None
    return round((current - previous) * 100 / abs(previous))


def kpi(label, value, previous=None, up_is_good=True, kind="money", hint=""):
    delta = _delta(value, previous) if previous is not None else None
    return {
        "label": label,
        "value": value,
        "kind": kind,
        "hint": hint,
        "delta": delta,
        "good": None if not delta else (delta > 0) == up_is_good,
    }


def _local_date(moment, estabelecimento):
    return moment.astimezone(estabelecimento.timezone).date()


# --- Dinheiro: entradas e despesas


def _income_entries(estabelecimento, start, end):
    """Entradas de reservas, vendas e contas a receber, com os estornos delas."""
    return (
        Lancamento.all_tenants.filter(
            estabelecimento=estabelecimento, criado_em__gte=start, criado_em__lt=end
        )
        .filter(Q(origem__in=INCOME_ORIGINS) | Q(estorno_de__origem__in=INCOME_ORIGINS))
        .select_related("reserva__espaco", "estorno_de")
    )


def _bill_payments(estabelecimento, start, end):
    """(data, categoria, valor) de cada pagamento de conta no período. Estorno entra negativo, na data dele."""
    payments = []
    rows = (
        Lancamento.all_tenants.filter(
            estabelecimento=estabelecimento, criado_em__gte=start, criado_em__lt=end
        )
        .filter(Q(origem=Lancamento.Origem.CONTA_PAGAR) | Q(estorno_de__origem=Lancamento.Origem.CONTA_PAGAR))
        .values_list("criado_em", "categoria", "tipo", "valor")
    )
    for criado_em, categoria, tipo, valor in rows:
        payments.append((criado_em, categoria, valor if tipo == Lancamento.Tipo.SAIDA else -valor))
    # Pago no banco: a conta foi baixada sem lançamento de caixa em vigor.
    paid_in_register = Lancamento.all_tenants.filter(
        conta_pagar=OuterRef("pk"), origem=Lancamento.Origem.CONTA_PAGAR, estorno__isnull=True
    )
    banco = (
        ContaPagar.all_tenants.filter(
            estabelecimento=estabelecimento, status=ContaBase.Status.PAGA, pago_em__gte=start, pago_em__lt=end
        )
        .exclude(Exists(paid_in_register))
        .values_list("pago_em", "categoria", "valor_pago")
    )
    payments.extend(banco)
    return payments


def money_totals(estabelecimento, first, last):
    """Só os totais de dinheiro do período: para comparar com o período anterior sem montar o resto."""
    start, end = bounds(estabelecimento, first, last)
    faturamento = sum(
        (e.valor if e.is_income else -e.valor for e in _income_entries(estabelecimento, start, end)), ZERO
    )
    despesas = sum((valor for _, _, valor in _bill_payments(estabelecimento, start, end)), ZERO)
    return {"faturamento": faturamento, "despesas": despesas, "resultado": faturamento - despesas}


def _column_series(by_day, days):
    peak = max((by_day[day] for day in days), default=ZERO)
    series = [
        {
            "day": day,
            "total": by_day[day],
            "height": f"{max(by_day[day], ZERO) * 100 / peak:.2f}" if peak > 0 else "0",
            "is_peak": peak > 0 and by_day[day] == peak,
        }
        for day in days
    ]
    return series, peak


def overdue_receivables(estabelecimento, until):
    atrasadas = ContaReceber.all_tenants.filter(
        estabelecimento=estabelecimento, status=ContaBase.Status.ABERTA, vencimento__lt=until
    ).select_related("cliente")
    return sorted(atrasadas, key=lambda conta: conta.vencimento)


def revenue_report(estabelecimento, first, last):
    """Faturamento, despesas e inadimplência de um período, com as duas datas incluídas."""
    start, end = bounds(estabelecimento, first, last)
    by_day = defaultdict(Decimal)
    by_form = defaultdict(Decimal)
    by_space = defaultdict(Decimal)
    by_source = defaultdict(Decimal)
    for lancamento in _income_entries(estabelecimento, start, end):
        signed = lancamento.valor if lancamento.is_income else -lancamento.valor
        by_day[_local_date(lancamento.criado_em, estabelecimento)] += signed
        by_form[lancamento.forma] += signed
        origem = lancamento.estorno_de.origem if lancamento.estorno_de_id else lancamento.origem
        by_source[origem] += signed
        if lancamento.reserva_id:
            by_space[lancamento.reserva.espaco.nome] += signed

    faturamento = sum(by_source.values(), ZERO)
    despesas = sum((valor for _, _, valor in _bill_payments(estabelecimento, start, end)), ZERO)
    series, peak = _column_series(by_day, days_between(first, last))
    atrasadas = overdue_receivables(estabelecimento, min(last, timezone.localdate()))
    return {
        "faturamento": faturamento,
        "despesas": despesas,
        "resultado": faturamento - despesas,
        "series": series,
        "peak": peak,
        "por_forma": _ranked(by_form, dict(FormaPagamento.choices)),
        "por_espaco": _ranked(by_space),
        "por_origem": _ranked(by_source, dict(Lancamento.Origem.choices)),
        "inadimplencia": sum((conta.saldo for conta in atrasadas), ZERO),
        "atrasadas": atrasadas[:10],
        "atrasadas_count": len(atrasadas),
    }


def _booking_numbers(estabelecimento, first, last):
    start, end = bounds(estabelecimento, first, last)
    validas = Reserva.all_tenants.filter(
        estabelecimento=estabelecimento, inicio__gte=start, inicio__lt=end
    ).exclude(status=Reserva.Status.CANCELADA)
    numbers = validas.aggregate(total=Count("pk"), valor=Sum("valor_total"))
    # Jogo de mensalista com cobrança mensal vale zero na reserva: fica fora da média.
    pagas = validas.filter(valor_total__gt=0).aggregate(n=Count("pk"), valor=Sum("valor_total"))
    medio = (pagas["valor"] / pagas["n"]).quantize(Decimal("0.01")) if pagas["n"] else ZERO
    return {"reservas": numbers["total"], "valor_reservado": numbers["valor"] or ZERO, "valor_medio": medio}


def overview_report(estabelecimento, first, last):
    """Visão geral: os números do período comparados com o período anterior de mesmo tamanho."""
    report = revenue_report(estabelecimento, first, last)
    prev_first, prev_last = previous_period(first, last)
    previous = money_totals(estabelecimento, prev_first, prev_last)
    bookings = _booking_numbers(estabelecimento, first, last)
    prev_bookings = _booking_numbers(estabelecimento, prev_first, prev_last)
    report["kpis"] = [
        kpi("Faturamento", report["faturamento"], previous["faturamento"]),
        kpi("Contas pagas", report["despesas"], previous["despesas"], up_is_good=False),
        kpi("Resultado", report["resultado"], previous["resultado"]),
        kpi("Reservas", bookings["reservas"], prev_bookings["reservas"], kind="int"),
        kpi("Valor médio da reserva", bookings["valor_medio"], prev_bookings["valor_medio"]),
        kpi("A receber em atraso", report["inadimplencia"], kind="money_alert"),
    ]
    report["previous"] = (prev_first, prev_last)
    return report


# --- Fluxo de caixa


def cashflow_report(estabelecimento, first, last, today=None):
    """Entradas e saídas de dinheiro por dia no período, e o que está previsto para os próximos 30 dias."""
    today = today or timezone.localdate()
    start, end = bounds(estabelecimento, first, last)
    entradas, saidas = defaultdict(Decimal), defaultdict(Decimal)
    por_origem, por_categoria = defaultdict(Decimal), defaultdict(Decimal)
    origem_labels = dict(Lancamento.Origem.choices)
    categoria_labels = dict(Categoria.choices)

    for lancamento in _income_entries(estabelecimento, start, end):
        day = _local_date(lancamento.criado_em, estabelecimento)
        if lancamento.estorno_de_id:
            saidas[day] += lancamento.valor
            por_categoria["Devoluções a clientes"] += lancamento.valor
        else:
            entradas[day] += lancamento.valor
            por_origem[origem_labels[lancamento.origem]] += lancamento.valor
    for moment, categoria, valor in _bill_payments(estabelecimento, start, end):
        saidas[_local_date(moment, estabelecimento)] += valor
        por_categoria[categoria_labels.get(categoria, categoria)] += valor

    days = days_between(first, last)
    peak = max([entradas[day] for day in days] + [saidas[day] for day in days] + [ZERO])
    acumulado = ZERO
    series = []
    for day in days:
        saldo = entradas[day] - saidas[day]
        acumulado += saldo
        series.append(
            {
                "day": day,
                "entradas": entradas[day],
                "saidas": saidas[day],
                "saldo": saldo,
                "acumulado": acumulado,
                "up": f"{entradas[day] * 100 / peak:.2f}" if peak else "0",
                "down": f"{max(saidas[day], ZERO) * 100 / peak:.2f}" if peak else "0",
            }
        )
    total_entradas = sum(entradas.values(), ZERO)
    total_saidas = sum(saidas.values(), ZERO)

    gaveta = Lancamento.all_tenants.filter(
        estabelecimento=estabelecimento,
        criado_em__gte=start,
        criado_em__lt=end,
        origem__in=[Lancamento.Origem.SUPRIMENTO, Lancamento.Origem.RETIRADA],
    ).aggregate(
        colocado=Sum("valor", filter=Q(origem=Lancamento.Origem.SUPRIMENTO)),
        retirado=Sum("valor", filter=Q(origem=Lancamento.Origem.RETIRADA)),
    )
    return {
        "entradas": total_entradas,
        "saidas": total_saidas,
        "saldo": total_entradas - total_saidas,
        "series": series,
        "peak": peak,
        "por_origem": _ranked(por_origem),
        "por_categoria": _ranked(por_categoria),
        "gaveta_colocado": gaveta["colocado"] or ZERO,
        "gaveta_retirado": gaveta["retirado"] or ZERO,
        "previsto": forecast(estabelecimento, today),
    }


def _open_balance(queryset):
    return queryset.aggregate(total=Sum(F("valor") - F("valor_pago")))["total"] or ZERO


def forecast(estabelecimento, today, days=FORECAST_DAYS):
    """Contas em aberto que vencem nos próximos dias, por semana, e o que já venceu.

    As reservas futuras entram pela conta a receber de cada uma; as contas que se repetem, pelas
    repetições já criadas (até 31 dias à frente).
    """
    last = today + timedelta(days=days - 1)
    receber = ContaReceber.all_tenants.filter(estabelecimento=estabelecimento, status=ContaBase.Status.ABERTA)
    pagar = ContaPagar.all_tenants.filter(estabelecimento=estabelecimento, status=ContaBase.Status.ABERTA)
    weeks = []
    acumulado = ZERO
    week_start = today
    while week_start <= last:
        week_end = min(week_start + timedelta(days=6), last)
        entra = _open_balance(receber.filter(vencimento__gte=week_start, vencimento__lte=week_end))
        sai = _open_balance(pagar.filter(vencimento__gte=week_start, vencimento__lte=week_end))
        acumulado += entra - sai
        weeks.append(
            {
                "first": week_start,
                "last": week_end,
                "receber": entra,
                "pagar": sai,
                "saldo": entra - sai,
                "acumulado": acumulado,
            }
        )
        week_start = week_end + timedelta(days=1)
    total_receber = sum((week["receber"] for week in weeks), ZERO)
    total_pagar = sum((week["pagar"] for week in weeks), ZERO)
    return {
        "first": today,
        "last": last,
        "semanas": weeks,
        "receber": total_receber,
        "pagar": total_pagar,
        "saldo": total_receber - total_pagar,
        "atrasado_receber": _open_balance(receber.filter(vencimento__lt=today)),
        "atrasado_pagar": _open_balance(pagar.filter(vencimento__lt=today)),
        "proximas_contas": list(
            pagar.filter(vencimento__gte=today, vencimento__lte=last).order_by("vencimento", "pk")[:8]
        ),
    }


# --- Reservas


def heatmap(details):
    """Ocupação por dia da semana × hora. `level` vai de 0 a 5 para a intensidade da cor."""
    open_slot, busy_slot = details["open_slot"], details["busy_slot"]
    hours = sorted({hour for _, hour in open_slot})
    rows = []
    for weekday, label in enumerate(WEEKDAYS):
        cells = []
        for hour in hours:
            available = open_slot.get((weekday, hour), 0)
            share = _percent(busy_slot.get((weekday, hour), 0), available) if available else None
            cells.append(
                {
                    "hour": hour % 24,
                    "share": share,
                    "level": 0 if share is None else min(5, share // 20 + 1) if share else 1,
                    "alpha": "0" if share is None else f"{0.1 + share * 0.85 / 100:.2f}",
                }
            )
        rows.append({"label": label, "cells": cells})
    scale = [f"{0.1 + share * 0.85 / 100:.2f}" for share in (0, 25, 50, 75, 100)]
    return {"hours": [hour % 24 for hour in hours], "rows": rows, "scale": scale}


def bookings_report(estabelecimento, first, last):
    start, end = bounds(estabelecimento, first, last)
    reservas = Reserva.all_tenants.filter(estabelecimento=estabelecimento, inicio__gte=start, inicio__lt=end)
    validas = reservas.exclude(status=Reserva.Status.CANCELADA)
    total = reservas.count()
    canceladas = reservas.filter(status=Reserva.Status.CANCELADA).count()
    nao_compareceu = validas.filter(status=Reserva.Status.NAO_COMPARECEU).count()
    numbers = _booking_numbers(estabelecimento, first, last)
    duracao = validas.aggregate(total=Sum(F("fim") - F("inicio")))["total"] or timedelta(0)
    avulsas = validas.exclude(origem=Reserva.Origem.MENSALISTA)
    antecedencia = avulsas.aggregate(media=Sum(F("inicio") - F("criado_em")), n=Count("pk"))

    occupancy_first = max(first, last - timedelta(days=MAX_OCCUPANCY_DAYS - 1))
    details = occupancy_details(estabelecimento, occupancy_first, last)
    busy = sum(details["busy_space"].values())
    available = sum(details["open_space"].values())

    origem_labels = dict(Reserva.Origem.choices)
    por_origem = Counter(origem_labels[origem] for origem in validas.values_list("origem", flat=True))
    por_modalidade = Counter(
        modalidade for modalidade in validas.values_list("modalidade", flat=True) if modalidade
    )
    por_espaco = Counter()
    for nome, minutos in validas.values_list("espaco__nome").annotate(d=Sum(F("fim") - F("inicio"))):
        por_espaco[nome] = Decimal(minutos.total_seconds() / 3600).quantize(Decimal("0.1"))
    media_dias = (
        Decimal(antecedencia["media"].total_seconds() / 86400 / antecedencia["n"]).quantize(Decimal("0.1"))
        if antecedencia["n"]
        else ZERO
    )
    return {
        "kpis": [
            kpi("Reservas", numbers["reservas"], kind="int"),
            kpi(
                "Horas vendidas",
                Decimal(duracao.total_seconds() / 3600).quantize(Decimal("0.1")),
                kind="hours",
            ),
            kpi("Ocupação", _percent(busy, available), kind="percent", hint="das horas abertas"),
            kpi("Valor médio", numbers["valor_medio"]),
            kpi(
                "Cancelamentos", _percent(canceladas, total), kind="percent", hint=f"{canceladas} de {total}"
            ),
            kpi(
                "Não compareceu",
                _percent(nao_compareceu, numbers["reservas"]),
                kind="percent",
                hint=f"{nao_compareceu} reserva{'s' if nao_compareceu != 1 else ''}",
            ),
        ],
        "antecedencia_dias": media_dias,
        "ocupacao": occupancy_by_space(estabelecimento, occupancy_first, last, details=details),
        "ocupacao_desde": occupancy_first if occupancy_first != first else None,
        "heatmap": heatmap(details),
        "por_origem": _ranked(por_origem),
        "por_modalidade": _ranked(por_modalidade),
        "horas_por_espaco": _ranked(por_espaco),
    }


# --- Clientes


def clients_report(estabelecimento, first, last, today=None, ausencia_dias=30):
    today = today or timezone.localdate()
    start, end = bounds(estabelecimento, first, last)
    base = Reserva.all_tenants.filter(
        estabelecimento=estabelecimento, cliente__anonimizado_em__isnull=True
    ).exclude(status=Reserva.Status.CANCELADA)
    no_periodo = (
        base.filter(inicio__gte=start, inicio__lt=end)
        .values("cliente")
        .annotate(
            reservas=Count("pk"),
            valor=Sum("valor_total"),
            duracao=Sum(F("fim") - F("inicio")),
            ultima=Max("inicio"),
        )
    )
    no_periodo = list(no_periodo)
    primeiras = dict(
        base.values("cliente").annotate(primeira=Min("inicio")).values_list("cliente", "primeira")
    )
    novos = sum(1 for row in no_periodo if start <= primeiras[row["cliente"]] < end)
    total_reservas = sum(row["reservas"] for row in no_periodo)
    recorrentes = sum(1 for row in no_periodo if row["reservas"] >= 2)

    top_rows = sorted(no_periodo, key=lambda row: (-row["reservas"], -(row["valor"] or 0)))[:15]
    clientes = Cliente.all_tenants.in_bulk([row["cliente"] for row in top_rows])
    top = [
        {
            "cliente": clientes[row["cliente"]],
            "reservas": row["reservas"],
            "horas": Decimal(row["duracao"].total_seconds() / 3600).quantize(Decimal("0.1")),
            "valor": row["valor"] or ZERO,
            "ultima": row["ultima"],
        }
        for row in top_rows
    ]

    # Quem jogava com frequência e parou: bom para chamar de volta.
    corte = datetime.combine(
        today - timedelta(days=ausencia_dias), datetime.min.time(), tzinfo=estabelecimento.timezone
    )
    habituais = (
        base.values("cliente")
        .annotate(reservas=Count("pk"), ultima=Max("inicio"))
        .filter(reservas__gte=3, ultima__lt=corte)
    )
    sumidos_rows = sorted(habituais, key=lambda row: row["ultima"], reverse=True)[:15]
    sumidos_clientes = Cliente.all_tenants.in_bulk([row["cliente"] for row in sumidos_rows])
    sumidos = [
        {"cliente": sumidos_clientes[row["cliente"]], "reservas": row["reservas"], "ultima": row["ultima"]}
        for row in sumidos_rows
    ]

    devem = defaultdict(Decimal)
    nomes = {}
    for conta in overdue_receivables(estabelecimento, today):
        if conta.cliente_id and conta.cliente.anonimizado_em is None:
            devem[conta.cliente_id] += conta.saldo
            nomes[conta.cliente_id] = conta.cliente
    devedores = [
        {"cliente": nomes[pk], "valor": valor}
        for pk, valor in sorted(devem.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    return {
        "kpis": [
            kpi("Clientes que jogaram", len(no_periodo), kind="int"),
            kpi("Clientes novos", novos, kind="int", hint="primeira reserva no período"),
            kpi("Voltaram mais de uma vez", recorrentes, kind="int"),
            kpi(
                "Reservas por cliente",
                (Decimal(total_reservas) / len(no_periodo)).quantize(Decimal("0.1")) if no_periodo else ZERO,
                kind="decimal",
            ),
        ],
        "top": top,
        "sumidos": sumidos,
        "ausencia_dias": ausencia_dias,
        "devedores": devedores,
    }


# --- Vendas do PDV


def sales_report(estabelecimento, first, last):
    start, end = bounds(estabelecimento, first, last)
    vendas = Venda.all_tenants.filter(
        estabelecimento=estabelecimento,
        status=Venda.Status.CONCLUIDA,
        concluida_em__gte=start,
        concluida_em__lt=end,
    )
    numbers = vendas.aggregate(n=Count("pk"), total=Sum("total"))
    canceladas = Venda.all_tenants.filter(
        estabelecimento=estabelecimento,
        status=Venda.Status.CANCELADA,
        cancelada_em__gte=start,
        cancelada_em__lt=end,
    ).aggregate(n=Count("pk"), total=Sum("total"))
    itens = (
        ItemVenda.all_tenants.filter(venda__in=vendas)
        .values("produto", "produto__nome", "produto__categoria", "produto__custo")
        .annotate(qtd=Sum("quantidade"), receita=Sum(F("quantidade") * F("preco_unitario")))
        .order_by("-receita")
    )
    categoria_labels = dict(Produto.Categoria.choices)
    produtos = []
    por_categoria = defaultdict(Decimal)
    margem_total = receita_com_custo = ZERO
    itens_vendidos = 0
    for row in itens:
        custo = row["produto__custo"]
        margem = row["receita"] - custo * row["qtd"] if custo is not None else None
        if margem is not None:
            margem_total += margem
            receita_com_custo += row["receita"]
        itens_vendidos += row["qtd"]
        por_categoria[categoria_labels.get(row["produto__categoria"], row["produto__categoria"])] += row[
            "receita"
        ]
        produtos.append(
            {
                "nome": row["produto__nome"],
                "categoria": categoria_labels.get(row["produto__categoria"], ""),
                "quantidade": row["qtd"],
                "receita": row["receita"],
                "margem": margem,
                "margem_pct": _percent(margem, row["receita"]) if margem is not None else None,
            }
        )
    total = numbers["total"] or ZERO
    por_forma = defaultdict(Decimal)
    for forma, valor in vendas.values_list("forma_pagamento").annotate(t=Sum("total")):
        por_forma[forma] += valor
    baixo = Produto.all_tenants.filter(
        estabelecimento=estabelecimento,
        ativo=True,
        controla_estoque=True,
        estoque_atual__lte=F("estoque_minimo"),
    ).order_by("estoque_atual", "nome")
    return {
        "kpis": [
            kpi("Vendido no PDV", total),
            kpi("Vendas", numbers["n"], kind="int"),
            kpi("Ticket médio", (total / numbers["n"]).quantize(Decimal("0.01")) if numbers["n"] else ZERO),
            kpi("Itens vendidos", itens_vendidos, kind="int"),
            kpi(
                "Margem estimada",
                margem_total,
                hint=(
                    f"{_percent(margem_total, receita_com_custo)}% do vendido com custo"
                    if receita_com_custo
                    else "cadastre o custo dos produtos"
                ),
            ),
            kpi(
                "Vendas canceladas",
                canceladas["total"] or ZERO,
                hint=f"{canceladas['n']} venda{'s' if canceladas['n'] != 1 else ''}",
            ),
        ],
        "produtos": produtos,
        "top": _ranked({row["nome"]: row["receita"] for row in produtos[:10]}),
        "por_categoria": _ranked(por_categoria),
        "por_forma": _ranked(por_forma, dict(FormaPagamento.choices)),
        "estoque_baixo": list(baixo[:12]),
    }


# --- Caixas e conferência


def registers_report(estabelecimento, first, last):
    """Fechamentos do período, com as diferenças de dinheiro por operador, e os caixas esquecidos abertos."""
    start, end = bounds(estabelecimento, first, last)
    fechados = list(
        Caixa.all_tenants.filter(estabelecimento=estabelecimento, fechado_em__gte=start, fechado_em__lt=end)
        .select_related("operador", "fechado_por")
        .order_by("-fechado_em")
    )
    recebido = defaultdict(Decimal)
    rows = (
        Lancamento.all_tenants.filter(caixa__in=fechados)
        .filter(Q(origem__in=INCOME_ORIGINS) | Q(estorno_de__origem__in=INCOME_ORIGINS))
        .values("caixa", "tipo")
        .annotate(total=Sum("valor"))
    )
    for row in rows:
        recebido[row["caixa"]] += row["total"] if row["tipo"] == Lancamento.Tipo.ENTRADA else -row["total"]

    por_operador = {}
    for caixa in fechados:
        caixa.recebido = recebido[caixa.pk]
        item = por_operador.setdefault(
            caixa.nome, {"nome": caixa.nome, "caixas": 0, "diferenca": ZERO, "recebido": ZERO}
        )
        item["caixas"] += 1
        item["diferenca"] += caixa.diferenca or ZERO
        item["recebido"] += caixa.recebido
    diferencas = [caixa.diferenca or ZERO for caixa in fechados]
    hoje = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    abertos = list(
        Caixa.all_tenants.filter(estabelecimento=estabelecimento, fechado_em__isnull=True)
        .select_related("operador")
        .order_by("criado_em")
    )
    for caixa in abertos:
        caixa.antigo = caixa.tipo == Caixa.Tipo.OPERADOR and caixa.criado_em < hoje
    return {
        "kpis": [
            kpi("Caixas fechados", len(fechados), kind="int"),
            kpi("Com diferença", sum(1 for valor in diferencas if valor), kind="int"),
            kpi("Sobras", sum((valor for valor in diferencas if valor > 0), ZERO)),
            kpi("Faltas", -sum((valor for valor in diferencas if valor < 0), ZERO), kind="money_alert"),
        ],
        "fechados": fechados,
        "por_operador": sorted(por_operador.values(), key=lambda item: item["diferenca"]),
        "abertos": abertos,
    }
