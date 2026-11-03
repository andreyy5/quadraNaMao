from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import TemplateView

from apps.agenda.services import day_summary
from apps.contas.mixins import ManagerRequiredMixin
from apps.estabelecimentos.mixins import TenantRequiredMixin
from apps.estoque.services import stock_overview
from apps.financeiro.models import ContaPagar, ContaReceber
from apps.financeiro.services import accounts_overview, generate_recurring_accounts
from apps.pdv import services as pdv_services

from .services import MAX_REPORT_DAYS, revenue_report, setup_checklist


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
            receivables=self._receivables(),
            checklist=setup_checklist(self.request.tenant) if self.request.user.is_owner else None,
        )
        return context

    def _bills(self):
        if not self.request.user.is_manager:
            return None
        generate_recurring_accounts(self.request.tenant)
        return accounts_overview(ContaPagar, self.request.tenant)

    def _receivables(self):
        if not self.request.user.is_manager:
            return None
        return accounts_overview(ContaReceber, self.request.tenant)


class RelatorioView(ManagerRequiredMixin, TemplateView):
    template_name = "relatorios/relatorio.html"
    presets = [("7", "7 dias"), ("30", "30 dias"), ("mes", "Este mês"), ("anterior", "Mês passado")]

    def _period(self):
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
        elif preset == "anterior":
            last = today.replace(day=1) - timedelta(days=1)
            first = last.replace(day=1)
        elif preset == "30":
            first, last = today - timedelta(days=29), today
        else:
            preset = "mes"
            first, last = today.replace(day=1), today
        if first > last:
            first, last = last, first
        # O limite mantém a tela leve: a ocupação calcula a grade de cada dia.
        first = max(first, last - timedelta(days=MAX_REPORT_DAYS - 1))
        return first, last, preset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        first, last, preset = self._period()
        context.update(
            first=first,
            last=last,
            preset=preset,
            presets=self.presets,
            report=revenue_report(self.request.tenant, first, last),
            active_tab="relatorios",
        )
        return context
