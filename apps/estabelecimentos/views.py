from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import UpdateView

from apps.contas.mixins import OwnerRequiredMixin
from apps.estabelecimentos.ratelimit import allow
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.services import WhatsAppError

from .forms import EstabelecimentoForm, ReservasOnlineForm, WhatsAppAjustesForm, WhatsAppTestForm


class EstabelecimentoUpdateView(OwnerRequiredMixin, UpdateView):
    form_class = EstabelecimentoForm
    template_name = "estabelecimentos/estabelecimento_form.html"
    success_url = reverse_lazy("estabelecimentos:ajustes")

    def get_object(self, queryset=None):
        return self.request.tenant

    def form_valid(self, form):
        messages.success(self.request, "Dados do estabelecimento salvos.")
        return super().form_valid(form)


class ReservasOnlineView(EstabelecimentoUpdateView):
    form_class = ReservasOnlineForm
    template_name = "estabelecimentos/reservas_online_form.html"
    success_url = reverse_lazy("estabelecimentos:reservas_online")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["link_publico"] = self.request.build_absolute_uri(
            reverse("publico:reservar", args=[self.request.tenant.slug])
        )
        return context

    def form_valid(self, form):
        messages.success(self.request, "Reservas online salvas.")
        return super(EstabelecimentoUpdateView, self).form_valid(form)


class WhatsAppAjustesView(EstabelecimentoUpdateView):
    form_class = WhatsAppAjustesForm
    template_name = "estabelecimentos/whatsapp_form.html"
    success_url = reverse_lazy("estabelecimentos:whatsapp")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            test_form=kwargs.get("test_form") or WhatsAppTestForm(),
            provider=settings.WHATSAPP_PROVIDER,
            has_token=bool(settings.WHATSAPP_ACCESS_TOKEN),
            has_secret=bool(settings.WHATSAPP_APP_SECRET),
            has_verify=bool(settings.WHATSAPP_VERIFY_TOKEN),
            webhook_url=self.request.build_absolute_uri(reverse("whatsapp:webhook")),
            site_url=settings.SITE_URL,
        )
        return context

    def form_valid(self, form):
        messages.success(self.request, "Configuração do WhatsApp salva.")
        return super(EstabelecimentoUpdateView, self).form_valid(form)

    def post(self, request, *args, **kwargs):
        if "teste" not in request.POST:
            return super().post(request, *args, **kwargs)
        self.object = self.get_object()
        test_form = WhatsAppTestForm(request.POST)
        if not test_form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=self.get_form_class()(instance=self.object), test_form=test_form)
            )
        if not allow(f"whatsapp-teste:{request.tenant.pk}", 10, 60 * 60):
            messages.error(request, "Muitos testes seguidos. Tente de novo daqui a pouco.")
            return redirect("estabelecimentos:whatsapp")
        try:
            if not request.tenant.whatsapp_ativo:
                raise WhatsAppError("Ligue o envio pelo WhatsApp e salve antes de testar.")
            mensagem = whatsapp_services.send_test(
                request.tenant, test_form.cleaned_data["telefone"], request.user
            )
        except WhatsAppError as exc:
            messages.error(request, str(exc))
            return redirect("estabelecimentos:whatsapp")
        if mensagem.status == mensagem.Status.FALHOU:
            messages.error(request, f"O teste falhou: {mensagem.erro}")
        else:
            messages.success(request, "Mensagem de teste enviada. Confira no WhatsApp do número informado.")
        return redirect("estabelecimentos:whatsapp")
