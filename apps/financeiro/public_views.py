"""Página da cobrança que vai no WhatsApp. Sem login: o link assinado diz qual é a conta."""

from django.http import Http404
from django.views.generic import TemplateView

from apps.agenda.public_views import PublicMixin

from . import cobranca, pix


class ContaPublicaView(PublicMixin, TemplateView):
    template_name = "financeiro/conta_publica.html"

    def get_context_data(self, **kwargs):
        conta = cobranca.account_from_token(self.kwargs["token"])
        if conta is None or conta.estabelecimento_id != self.estabelecimento.pk:
            raise Http404
        context = super().get_context_data(**kwargs)
        codigo = cobranca.pix_code(conta)
        context.update(conta=conta, copia_e_cola=codigo, qr=pix.qr_svg(codigo) if codigo else "")
        return context
