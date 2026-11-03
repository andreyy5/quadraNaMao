from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.urls import reverse

from apps.agenda.models import Reserva
from apps.agenda.services import occupancy_by_space
from apps.espacos.models import Espaco, HorarioFuncionamento, TabelaPreco
from apps.financeiro.models import ContaBase, ContaPagar, ContaReceber, FormaPagamento, Lancamento

MAX_REPORT_DAYS = 92
INCOME_ORIGINS = [Lancamento.Origem.RESERVA, Lancamento.Origem.VENDA, Lancamento.Origem.CONTA_RECEBER]


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


def _ranked(totals, labels=None):
    """Linhas ordenadas para as barras horizontais. `share` é a largura da barra, em texto para o CSS."""
    rows = [(key, total) for key, total in totals.items() if total > 0]
    rows.sort(key=lambda row: row[1], reverse=True)
    largest = rows[0][1] if rows else Decimal("1")
    return [
        {"label": labels[key] if labels else key, "total": total, "share": f"{total * 100 / largest:.2f}"}
        for key, total in rows
    ]


def revenue_report(estabelecimento, first, last):
    """Faturamento, despesas, ocupação e inadimplência de um período, com as duas datas incluídas.

    Faturamento é o que entrou por reservas, vendas e contas, menos os estornos desses valores.
    Dinheiro colocado ou retirado da gaveta não é faturamento, e sim movimento de caixa.
    """
    tz = estabelecimento.timezone
    start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    lancamentos = (
        Lancamento.all_tenants.filter(
            estabelecimento=estabelecimento, criado_em__gte=start, criado_em__lt=end
        )
        .filter(Q(origem__in=INCOME_ORIGINS) | Q(estorno_de__origem__in=INCOME_ORIGINS))
        .select_related("reserva__espaco", "estorno_de")
    )

    by_day = defaultdict(Decimal)
    by_form = defaultdict(Decimal)
    by_space = defaultdict(Decimal)
    by_source = defaultdict(Decimal)
    for lancamento in lancamentos:
        signed = lancamento.valor if lancamento.is_income else -lancamento.valor
        by_day[lancamento.criado_em.astimezone(tz).date()] += signed
        by_form[lancamento.forma] += signed
        origem = lancamento.estorno_de.origem if lancamento.estorno_de_id else lancamento.origem
        by_source[origem] += signed
        if lancamento.reserva_id:
            by_space[lancamento.reserva.espaco.nome] += signed

    faturamento = sum(by_source.values(), Decimal("0"))
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    peak = max((by_day[day] for day in days), default=Decimal("0"))
    series = [
        {
            "day": day,
            "total": by_day[day],
            "height": f"{max(by_day[day], Decimal('0')) * 100 / peak:.2f}" if peak > 0 else "0",
            "is_peak": peak > 0 and by_day[day] == peak,
        }
        for day in days
    ]

    despesas = ContaPagar.all_tenants.filter(
        estabelecimento=estabelecimento, status=ContaBase.Status.PAGA, pago_em__gte=start, pago_em__lt=end
    ).aggregate(total=Sum("valor"))["total"] or Decimal("0")

    atrasadas = ContaReceber.all_tenants.filter(
        estabelecimento=estabelecimento, status=ContaBase.Status.ABERTA, vencimento__lt=last
    ).select_related("cliente")
    inadimplencia = sum((conta.saldo for conta in atrasadas), Decimal("0"))

    source_labels = dict(Lancamento.Origem.choices)
    return {
        "faturamento": faturamento,
        "despesas": despesas,
        "resultado": faturamento - despesas,
        "series": series,
        "peak": peak,
        "por_forma": _ranked(by_form, dict(FormaPagamento.choices)),
        "por_espaco": _ranked(by_space),
        "por_origem": _ranked(by_source, source_labels),
        "ocupacao": occupancy_by_space(estabelecimento, first, last),
        "inadimplencia": inadimplencia,
        "atrasadas": sorted(atrasadas, key=lambda conta: conta.vencimento)[:10],
        "atrasadas_count": len(atrasadas),
    }
