from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from apps.contas.mixins import OwnerRequiredMixin

from .forms import EstabelecimentoForm


class EstabelecimentoUpdateView(OwnerRequiredMixin, UpdateView):
    form_class = EstabelecimentoForm
    template_name = "estabelecimentos/estabelecimento_form.html"
    success_url = reverse_lazy("estabelecimentos:ajustes")

    def get_object(self, queryset=None):
        return self.request.tenant

    def form_valid(self, form):
        messages.success(self.request, "Dados do estabelecimento salvos.")
        return super().form_valid(form)
