import json

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView, View

from apps.clientes.models import Cliente
from apps.estabelecimentos.mixins import TenantRequiredMixin
from apps.estabelecimentos.ratelimit import allow, client_ip

from . import services
from .models import Mensagem
from .tasks import process_webhook

WEBHOOK_LIMIT_PER_MINUTE = 600


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    """Endereço cadastrado no painel da Meta. A verificação usa o token; os avisos, a assinatura."""

    http_method_names = ["get", "post"]

    def get(self, request):
        params = request.GET
        token = settings.WHATSAPP_VERIFY_TOKEN
        if token and params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == token:
            return HttpResponse(params.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponseForbidden("Token de verificação inválido.")

    def post(self, request):
        if not allow(f"whatsapp-webhook:{client_ip(request)}", WEBHOOK_LIMIT_PER_MINUTE, 60):
            return HttpResponse(status=429)
        if not services.valid_signature(request.body, request.headers.get("X-Hub-Signature-256", "")):
            return HttpResponseForbidden("Assinatura inválida.")
        try:
            payload = json.loads(request.body)
        except ValueError:
            return HttpResponse(status=400)
        process_webhook.delay(payload)
        return HttpResponse("ok")


class ConversasView(TenantRequiredMixin, TemplateView):
    template_name = "whatsapp/conversas.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["conversas"] = services.conversations(self.request.tenant)
        context["ativo"] = self.request.tenant.whatsapp_ativo
        context["falhas"] = Mensagem.objects.filter(status=Mensagem.Status.FALHOU).count()
        return context


class ConversaView(TenantRequiredMixin, TemplateView):
    template_name = "whatsapp/conversa.html"

    def dispatch(self, request, *args, **kwargs):
        self.telefone = "+" + kwargs["telefone"]
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mensagens = Mensagem.objects.filter(telefone=self.telefone).select_related("enviada_por")
        if not mensagens.exists():
            raise Http404
        context.update(
            telefone=self.telefone,
            mensagens=mensagens,
            cliente=Cliente.objects.filter(telefone=self.telefone).first(),
            janela_aberta=services.window_open(self.request.tenant, self.telefone),
        )
        return context

    def post(self, request, *args, **kwargs):
        texto = request.POST.get("texto", "").strip()
        if texto:
            try:
                services.reply(request.tenant, self.telefone, texto[:1000], request.user)
            except services.WhatsAppError as exc:
                messages.error(request, str(exc))
        return redirect("whatsapp:conversa", telefone=kwargs["telefone"])
