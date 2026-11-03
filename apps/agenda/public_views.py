"""Link público de reserva: o cliente escolhe o horário sem login e paga o sinal por Pix.

Não há usuário nem tenant da sessão: o estabelecimento vem do endereço e as consultas usam
`all_tenants` com filtro explícito.
"""

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import TemplateView, View

from apps.espacos.models import Espaco
from apps.estabelecimentos.models import Estabelecimento
from apps.estabelecimentos.ratelimit import allow, client_ip
from apps.financeiro import pix

from . import online
from .forms import PublicBookingForm
from .models import Reserva

BOOKINGS_PER_HOUR = 10


class PublicMixin:
    def dispatch(self, request, *args, **kwargs):
        self.estabelecimento = get_object_or_404(Estabelecimento, slug=kwargs["slug"], ativo=True)
        timezone.activate(self.estabelecimento.timezone)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["estabelecimento"] = self.estabelecimento
        return context


class ReservarView(PublicMixin, TemplateView):
    template_name = "publico/reservar.html"

    def get_template_names(self):
        if not self.estabelecimento.reserva_online_ativa:
            return ["publico/indisponivel.html"]
        return [self.template_name]

    def _selection(self):
        espacos = online.public_spaces(self.estabelecimento)
        days = online.booking_days(self.estabelecimento)
        params = self.request.POST if self.request.method == "POST" else self.request.GET
        espaco = next(
            (e for e in espacos if str(e.pk) == params.get("espaco", "")), espacos[0] if espacos else None
        )
        try:
            day = parse_date(params.get("data") or "")
        except ValueError:
            day = None
        return espacos, days, espaco, day if day in days else days[0]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.estabelecimento.reserva_online_ativa:
            return context
        online.expire_pending_reservations(self.estabelecimento)
        espacos, days, espaco, day = self._selection()
        context.update(
            espacos=espacos,
            days=days,
            espaco=espaco,
            day=day,
            starts=online.public_starts(espaco, day) if espaco else [],
            form=kwargs.get("form") or PublicBookingForm(initial={"aceite_whatsapp": True}),
            hora=self.request.POST.get("hora", ""),
        )
        return context

    def get(self, request, *args, **kwargs):
        if request.headers.get("HX-Request") and self.estabelecimento.reserva_online_ativa:
            context = self.get_context_data(**kwargs)
            return self.response_class(request, "publico/_horarios.html", context)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not self.estabelecimento.reserva_online_ativa:
            raise Http404
        form = PublicBookingForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        if not allow(f"reserva-publica:{client_ip(request)}", BOOKINGS_PER_HOUR, 60 * 60):
            form.add_error(None, "Muitos pedidos seguidos deste aparelho. Tente de novo em uma hora.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        data = form.cleaned_data
        espaco = Espaco.all_tenants.filter(
            estabelecimento=self.estabelecimento, pk=data["espaco"], ativo=True
        ).first()
        if espaco is None:
            form.add_error(None, "Escolha um dos espaços da lista.")
            return self.render_to_response(self.get_context_data(form=form))
        try:
            reserva, pagamento = online.book_online(
                self.estabelecimento,
                espaco,
                online.parse_start(self.estabelecimento, data["data"], data["hora"]),
                data["nome"],
                data["telefone"],
                data["aceite_whatsapp"],
            )
        except online.OnlineBookingError as exc:
            form.add_error(None, str(exc))
            return self.render_to_response(self.get_context_data(form=form))
        if pagamento:
            return redirect(
                "publico:pagamento", slug=self.estabelecimento.slug, token=online.payment_token(pagamento)
            )
        request.session["reserva_publica"] = reserva.pk
        return redirect("publico:confirmada", slug=self.estabelecimento.slug)


class ConfirmadaView(PublicMixin, TemplateView):
    """Reserva sem sinal: confirmada na hora."""

    template_name = "publico/confirmada.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reserva_id = self.request.session.get("reserva_publica")
        context["reserva"] = (
            Reserva.all_tenants.filter(estabelecimento=self.estabelecimento, pk=reserva_id)
            .select_related("espaco")
            .first()
        )
        return context


class PagamentoView(PublicMixin, TemplateView):
    template_name = "publico/pagamento.html"

    def dispatch(self, request, *args, **kwargs):
        self.pagamento = online.payment_from_token(kwargs["token"])
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get_context_data(self, **kwargs):
        if self.pagamento is None or self.pagamento.estabelecimento_id != self.estabelecimento.pk:
            raise Http404
        online.expire_pending_reservations(self.estabelecimento)
        self.pagamento.refresh_from_db()
        context = super().get_context_data(**kwargs)
        context.update(
            pagamento=self.pagamento,
            reserva=self.pagamento.reserva,
            qr=pix.qr_svg(self.pagamento.copia_e_cola) if self.pagamento.is_pending else "",
            simulado=pix.get_provider().automatic and pix.get_provider().code == "simulado",
            token=self.kwargs["token"],
        )
        return context

    def get(self, request, *args, **kwargs):
        if request.headers.get("HX-Request"):
            return self.response_class(request, "publico/_status.html", self.get_context_data(**kwargs))
        return super().get(request, *args, **kwargs)


class SimularPagamentoView(PublicMixin, View):
    """Só com o provedor simulado: faz o papel do aviso do provedor de Pix, para testar o fluxo inteiro."""

    http_method_names = ["post"]

    def post(self, request, slug, token):
        provider = pix.get_provider()
        if provider.code != "simulado":
            raise Http404
        pagamento = online.payment_from_token(token)
        if pagamento is None or pagamento.estabelecimento_id != self.estabelecimento.pk:
            raise Http404
        online.confirm_pix_payment(pagamento)
        messages.success(request, "Pagamento simulado.")
        return redirect("publico:pagamento", slug=slug, token=token)


def robots(request):
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
