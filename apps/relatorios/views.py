import csv
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import TemplateView

from apps.agenda.models import MensalistaAviso, Reserva
from apps.agenda.services import day_summary
from apps.contas.mixins import ManagerRequiredMixin
from apps.estabelecimentos.mixins import TenantRequiredMixin
from apps.estoque.services import stock_overview
from apps.financeiro.models import Caixa, ContaPagar, ContaReceber, Pagamento
from apps.financeiro.services import accounts_overview, generate_recurring_accounts
from apps.pdv import services as pdv_services
from apps.whatsapp.models import Mensagem

from .services import (
    MAX_REPORT_DAYS,
    bookings_report,
    cashflow_report,
    clients_report,
    overview_report,
    registers_report,
    sales_report,
    setup_checklist,
)


class DashboardView(TenantRequiredMixin, TemplateView):
    template_name = "relatorios/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        summary = day_summary(self.request.tenant, timezone.localdate())
        upcoming = [reserva for reserva in summary["reservas"] if reserva.fim >= now and reserva.is_open]
        hour = timezone.localtime(now).hour
        context.update(
            today=timezone.localdate(),
            greeting="Bom dia" if hour < 12 else "Boa tarde" if hour < 18 else "Boa noite",
            summary=summary,
            next_game=upcoming[0] if upcoming else None,
            in_progress=bool(upcoming) and upcoming[0].inicio <= now,
            next_games=upcoming[1:6],
            # Quem não vende nada não precisa ver a seção de vendas.
            has_products=pdv_services.has_products(self.request.tenant),
            sales=pdv_services.day_summary(self.request.tenant, timezone.localdate()),
            stock=stock_overview(self.request.tenant),
            bills=self._bills(),
            avisos=self._avisos(),
            receivables=self._receivables(),
            checklist=setup_checklist(self.request.tenant) if self.request.user.is_owner else None,
        )
        return context

    def _avisos(self):
        today = timezone.localdate()
        avisos = {
            "mensalistas": MensalistaAviso.objects.filter(resolvido=False, data__gte=today).count(),
            "pendentes": Reserva.objects.filter(status=Reserva.Status.PENDENTE).count(),
            "whatsapp": (
                Mensagem.objects.filter(
                    status=Mensagem.Status.FALHOU, criado_em__gte=timezone.now() - timedelta(days=7)
                ).count()
                if settings.WHATSAPP_ENABLED
                else 0
            ),
            "pix_atrasado": Pagamento.objects.filter(status=Pagamento.Status.PAGO_ATRASADO).count(),
            # Caixa aberto desde outro dia mistura os dias e atrasa a conferência do dinheiro.
            "caixas_antigos": (
                Caixa.objects.filter(
                    fechado_em__isnull=True,
                    tipo=Caixa.Tipo.OPERADOR,
                    criado_em__lt=timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0),
                ).count()
                if self.request.user.is_manager
                else 0
            ),
        }
        return avisos if any(avisos.values()) else None

    def _bills(self):
        if not self.request.user.is_manager:
            return None
        generate_recurring_accounts(self.request.tenant)
        return accounts_overview(ContaPagar, self.request.tenant)

    def _receivables(self):
        if not self.request.user.is_manager:
            return None
        return accounts_overview(ContaReceber, self.request.tenant)


class ReportMixin(ManagerRequiredMixin):
    """Período, abas e exportação em CSV, iguais em todos os relatórios."""

    presets = [
        ("7", "7 dias"),
        ("30", "30 dias"),
        ("mes", "Este mês"),
        ("anterior", "Mês passado"),
        ("ano", "Este ano"),
    ]
    tab = ""
    csv_name = ""

    def period(self):
        params = self.request.GET
        today = timezone.localdate()
        try:
            first, last = parse_date(params.get("de") or ""), parse_date(params.get("ate") or "")
        except ValueError:
            first, last = None, None
        preset = params.get("periodo", "")
        if first and last:
            preset = ""
        elif preset == "7":
            first, last = today - timedelta(days=6), today
        elif preset == "30":
            first, last = today - timedelta(days=29), today
        elif preset == "anterior":
            last = today.replace(day=1) - timedelta(days=1)
            first = last.replace(day=1)
        elif preset == "ano":
            first, last = today.replace(month=1, day=1), today
        else:
            preset = "mes"
            first, last = today.replace(day=1), today
        if first > last:
            first, last = last, first
        first = max(first, last - timedelta(days=MAX_REPORT_DAYS - 1))
        return first, last, preset

    def build(self, first, last):
        raise NotImplementedError

    def csv_rows(self, report):
        """Cabeçalho e linhas da exportação."""
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        self.first, self.last, self.preset = self.period()
        self.report = self.build(self.first, self.last)
        if request.GET.get("formato") == "csv":
            return self.csv_response()
        return super().get(request, *args, **kwargs)

    def csv_response(self):
        header, rows = self.csv_rows(self.report)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"{self.csv_name}-{self.first:%Y-%m-%d}-a-{self.last:%Y-%m-%d}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        # BOM e ponto e vírgula: o Excel em português abre com acentos e colunas no lugar.
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(header)
        writer.writerows([[_csv_value(value) for value in row] for row in rows])
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("formato", None)
        context.update(
            first=self.first,
            last=self.last,
            preset=self.preset,
            presets=self.presets,
            report=self.report,
            tab=self.tab,
            tabs=REPORT_TABS,
            query=query.urlencode(),
        )
        return context


def _csv_value(value):
    """Valores no formato brasileiro: 1234,50 e 03/11/2026."""
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return "" if value is None else value


REPORT_TABS = [
    ("geral", "Visão geral", "relatorios:relatorio"),
    ("fluxo", "Fluxo de caixa", "relatorios:fluxo"),
    ("reservas", "Reservas", "relatorios:reservas"),
    ("clientes", "Clientes", "relatorios:clientes"),
    ("vendas", "Vendas", "relatorios:vendas"),
    ("caixas", "Caixas", "relatorios:caixas"),
]


class RelatorioView(ReportMixin, TemplateView):
    template_name = "relatorios/geral.html"
    tab = "geral"
    csv_name = "faturamento"

    def build(self, first, last):
        return overview_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        return ["Dia", "Faturamento"], [[point["day"], point["total"]] for point in report["series"]]


class FluxoView(ReportMixin, TemplateView):
    template_name = "relatorios/fluxo.html"
    tab = "fluxo"
    csv_name = "fluxo-de-caixa"

    def build(self, first, last):
        generate_recurring_accounts(self.request.tenant)
        return cashflow_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        rows = [[d["day"], d["entradas"], d["saidas"], d["saldo"], d["acumulado"]] for d in report["series"]]
        return ["Dia", "Entradas", "Saídas", "Saldo do dia", "Acumulado"], rows


class ReservasReportView(ReportMixin, TemplateView):
    template_name = "relatorios/reservas.html"
    tab = "reservas"
    csv_name = "ocupacao-por-horario"

    def build(self, first, last):
        return bookings_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        heat = report["heatmap"]
        rows = [[row["label"], *[cell["share"] for cell in row["cells"]]] for row in heat["rows"]]
        return ["Dia", *[f"{hour}h (%)" for hour in heat["hours"]]], rows


class ClientesReportView(ReportMixin, TemplateView):
    template_name = "relatorios/clientes.html"
    tab = "clientes"
    csv_name = "clientes"

    def build(self, first, last):
        return clients_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        rows = [
            [row["cliente"].nome, row["reservas"], row["horas"], row["valor"], row["ultima"]]
            for row in report["top"]
        ]
        return ["Cliente", "Reservas", "Horas", "Valor reservado", "Última reserva"], rows


class VendasReportView(ReportMixin, TemplateView):
    template_name = "relatorios/vendas.html"
    tab = "vendas"
    csv_name = "vendas-por-produto"

    def build(self, first, last):
        return sales_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        rows = [
            [p["nome"], p["categoria"], p["quantidade"], p["receita"], p["margem"]]
            for p in report["produtos"]
        ]
        return ["Produto", "Categoria", "Quantidade", "Vendido", "Margem estimada"], rows


class CaixasReportView(ReportMixin, TemplateView):
    template_name = "relatorios/caixas.html"
    tab = "caixas"
    csv_name = "fechamentos-de-caixa"

    def build(self, first, last):
        return registers_report(self.request.tenant, first, last)

    def csv_rows(self, report):
        rows = [
            [
                caixa.nome,
                caixa.criado_em,
                caixa.fechado_em,
                caixa.recebido,
                caixa.saldo_esperado,
                caixa.saldo_conferido,
                caixa.diferenca,
                caixa.observacao,
            ]
            for caixa in report["fechados"]
        ]
        header = ["Caixa", "Aberto em", "Fechado em", "Recebido", "Dinheiro esperado", "Dinheiro contado"]
        return [*header, "Diferença", "Observação"], rows
