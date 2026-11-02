from django.utils import timezone
from django.views.generic import TemplateView

from apps.agenda.services import day_summary
from apps.estabelecimentos.mixins import TenantRequiredMixin
from apps.estoque.services import stock_overview
from apps.pdv import services as pdv_services

from .services import setup_checklist


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
            checklist=setup_checklist(self.request.tenant) if self.request.user.is_owner else None,
        )
        return context
