from django.utils import timezone
from django.views.generic import TemplateView

from apps.agenda.services import day_summary
from apps.estabelecimentos.mixins import TenantRequiredMixin

from .services import setup_checklist


class DashboardView(TenantRequiredMixin, TemplateView):
    template_name = "relatorios/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        summary = day_summary(self.request.tenant, timezone.localdate())
        context.update(
            today=timezone.localdate(),
            summary=summary,
            next_games=[reserva for reserva in summary["reservas"] if reserva.fim >= now and reserva.is_open][
                :6
            ],
            checklist=setup_checklist(self.request.tenant) if self.request.user.is_owner else None,
        )
        return context
