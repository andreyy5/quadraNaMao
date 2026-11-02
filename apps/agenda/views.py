from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from apps.clientes.models import Cliente
from apps.clientes.services import find_or_create_client, format_phone
from apps.espacos.models import Espaco
from apps.espacos.services import load_schedule
from apps.estabelecimentos.mixins import ModalResponseMixin, TenantRequiredMixin

from . import services
from .forms import BloqueioForm, ReservaForm
from .models import Bloqueio, Reserva

AGENDA_URL = reverse_lazy("agenda:day")


def _parse_day(raw):
    try:
        return parse_date(raw or "") or timezone.localdate()
    except ValueError:
        return timezone.localdate()


class AgendaDayView(TenantRequiredMixin, TemplateView):
    template_name = "agenda/agenda_day.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        day = _parse_day(self.request.GET.get("data"))
        day_url = reverse("agenda:day")
        context.update(
            day=day,
            today=timezone.localdate(),
            previous_url=f"{day_url}?data={day - timedelta(days=1):%Y-%m-%d}",
            next_url=f"{day_url}?data={day + timedelta(days=1):%Y-%m-%d}",
            today_url=day_url,
            heading=date_format(day, "l, j \\d\\e F").lower(),
            heading_short=date_format(day, "j \\d\\e F").lower(),
            grid=services.build_day_agenda(self.request.tenant, day),
            day_strip=services.week_strip(self.request.tenant, day),
            agenda_mode="day",
            new_reserva_url=f"{reverse('agenda:reserva_create')}?data={day:%Y-%m-%d}",
        )
        return context


class AgendaWeekView(TenantRequiredMixin, TemplateView):
    template_name = "agenda/agenda_week.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        day = _parse_day(self.request.GET.get("data"))
        monday = day - timedelta(days=day.weekday())
        espacos = list(Espaco.objects.filter(ativo=True).select_related("estabelecimento"))
        selected = None
        if espacos:
            requested = self.request.GET.get("espaco", "")
            selected = next((e for e in espacos if str(e.pk) == requested), espacos[0])
        week_url = reverse("agenda:week")
        suffix = f"&espaco={selected.pk}" if selected else ""
        sunday = monday + timedelta(days=6)
        context.update(
            day=day,
            today=timezone.localdate(),
            previous_url=f"{week_url}?data={monday - timedelta(days=7):%Y-%m-%d}{suffix}",
            next_url=f"{week_url}?data={monday + timedelta(days=7):%Y-%m-%d}{suffix}",
            today_url=f"{week_url}?{suffix.lstrip('&')}",
            heading=f"{monday:%d/%m} a {sunday:%d/%m}",
            espacos=espacos,
            selected=selected,
            grid=services.build_week_agenda(selected, monday) if selected else None,
            agenda_mode="week",
            new_reserva_url=f"{reverse('agenda:reserva_create')}?data={day:%Y-%m-%d}{suffix}",
        )
        return context


class ReservaFormMixin(TenantRequiredMixin, ModalResponseMixin):
    form_class = ReservaForm
    modal_template_name = "agenda/_reserva_form.html"
    success_message = ""

    def persist(self, data, cliente):
        raise NotImplementedError

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            # Se a reserva falhar, um cliente recém-digitado também não fica salvo.
            with transaction.atomic():
                cliente = data["cliente"] or find_or_create_client(
                    self.request.tenant, data["cliente_nome"], data["cliente_telefone"]
                )
                self.persist(data, cliente)
        except services.ReservationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(self.success_message, AGENDA_URL)


class ReservaCreateView(ReservaFormMixin, FormView):
    success_message = "Reserva confirmada."

    def get_initial(self):
        params = self.request.GET
        espaco = None
        if params.get("espaco", "").isdigit():
            espaco = (
                Espaco.objects.filter(pk=params["espaco"], ativo=True)
                .select_related("estabelecimento")
                .first()
            )
        espaco = espaco or Espaco.objects.filter(ativo=True).select_related("estabelecimento").first()

        now = timezone.localtime()
        day = _parse_day(params.get("data"))
        try:
            hour = parse_time(params.get("hora") or "")
        except ValueError:
            hour = None
        hour = hour or (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).time()
        initial = {"espaco": espaco, "data": day, "hora": hour}

        if espaco:
            schedule = load_schedule(espaco)
            start = datetime.combine(day, hour, tzinfo=timezone.get_current_timezone())
            minutes = params.get("minutos", "")
            duration = (
                int(minutes)
                if minutes.isdigit() and 15 <= int(minutes) <= 720
                else schedule.slot_minutes(start)
            )
            initial["duracao"] = duration
            if not params.get("hora"):
                free = services.free_starts(espaco, day, duration)
                if free:
                    start = free[0]
                    initial["hora"] = start.time()
            quote = schedule.quote(start, start + timedelta(minutes=duration))
            if quote is not None:
                initial["valor_total"] = quote

        if params.get("cliente", "").isdigit():
            cliente = Cliente.objects.filter(pk=params["cliente"], anonimizado_em__isnull=True).first()
            if cliente:
                initial.update(
                    cliente=cliente,
                    cliente_nome=cliente.nome,
                    cliente_telefone=format_phone(cliente.telefone),
                )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Quem clicou em um horário livre já escolheu onde e quando: falta só dizer quem vai jogar.
        # Um erro no cliente não muda isso; um erro de horário precisa mostrar os campos de novo.
        request = self.request
        if request.method == "GET":
            context["slot_chosen"] = "hora" in request.GET
        else:
            form = context["form"]
            when_errors = form.non_field_errors() or any(
                name in form.errors for name in ("espaco", "data", "hora", "duracao")
            )
            context["slot_chosen"] = request.POST.get("compacto") == "1" and not when_errors
        return context

    def persist(self, data, cliente):
        return services.create_reservation(
            data["espaco"],
            cliente,
            data["inicio"],
            data["fim"],
            valor_total=data["valor_total"],
            observacoes=data["observacoes"],
            usuario=self.request.user,
        )


class ReservaUpdateView(ReservaFormMixin, FormView):
    success_message = "Reserva atualizada."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.reserva = get_object_or_404(
                Reserva.objects.select_related("espaco__estabelecimento", "cliente"),
                pk=kwargs["pk"],
            )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        reserva = self.reserva
        inicio = timezone.localtime(reserva.inicio)
        return {
            "espaco": reserva.espaco,
            "data": inicio.date(),
            "hora": inicio.time(),
            "duracao": int((reserva.fim - reserva.inicio).total_seconds() / 60),
            "valor_total": reserva.valor_total,
            "observacoes": reserva.observacoes,
            "cliente": reserva.cliente,
            "cliente_nome": reserva.cliente.nome,
            "cliente_telefone": format_phone(reserva.cliente.telefone),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["reserva"] = self.reserva
        return context

    def persist(self, data, cliente):
        valor = data["valor_total"]
        if valor is None:
            valor = services.quote_price(data["espaco"], data["inicio"], data["fim"]) or Decimal("0")
        return services.update_reservation(
            self.reserva,
            data["espaco"],
            cliente,
            data["inicio"],
            data["fim"],
            valor,
            observacoes=data["observacoes"],
            usuario=self.request.user,
        )


class ReservaQuoteView(TenantRequiredMixin, TemplateView):
    """Recalcula o valor quando o espaço, o horário ou a duração mudam no formulário."""

    template_name = "agenda/_valor_field.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        quote = None
        form = ReservaForm(params)
        form.is_valid()
        data = form.cleaned_data
        if data.get("espaco") and data.get("inicio"):
            quote = services.quote_price(data["espaco"], data["inicio"], data["fim"])
        context["field"] = ReservaForm(initial={"valor_total": quote})["valor_total"]
        return context


class ReservaSlotsView(TenantRequiredMixin, TemplateView):
    """Horários livres do dia e situação do horário escolhido, enquanto o formulário é preenchido."""

    template_name = "agenda/_slots.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        form = ReservaForm(params)
        form.is_valid()
        data = form.cleaned_data
        if not (data.get("espaco") and data.get("data") and data.get("duracao")):
            return context
        ignore = (
            Reserva.objects.filter(pk=params["reserva"]).first()
            if params.get("reserva", "").isdigit()
            else None
        )
        starts = services.free_starts(data["espaco"], data["data"], data["duracao"], ignore=ignore)
        context["ready"] = True
        context["hora"] = f"{data['hora']:%H:%M}" if data.get("hora") else ""
        context["slots"] = [f"{start:%H:%M}" for start in starts]
        if data.get("inicio"):
            context["problem"] = services.slot_problem(
                data["espaco"], data["inicio"], data["fim"], ignore=ignore
            )
        return context


class ReservaDetailView(TenantRequiredMixin, ModalResponseMixin, DetailView):
    model = Reserva
    modal_template_name = "agenda/_reserva_detail.html"
    context_object_name = "reserva"

    def get_queryset(self):
        return super().get_queryset().select_related("espaco", "cliente", "criado_por")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["eventos"] = self.object.eventos.select_related("usuario")
        return context


class ReservaCancelView(TenantRequiredMixin, ModalResponseMixin, DetailView):
    model = Reserva
    modal_template_name = "agenda/_reserva_cancel.html"
    context_object_name = "reserva"

    def get_queryset(self):
        return super().get_queryset().select_related("espaco", "cliente")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            services.cancel_reservation(self.object, usuario=request.user)
        except services.ReservationError as exc:
            return self.render_to_response(self.get_context_data(error=str(exc)))
        return self.modal_success("Reserva cancelada. O horário ficou livre.", AGENDA_URL)


class ReservaStatusView(TenantRequiredMixin, ModalResponseMixin, View):
    http_method_names = ["post"]
    actions = {
        "concluida": (services.mark_completed, "Reserva concluída."),
        "nao_compareceu": (services.mark_no_show, "Marcado como não compareceu."),
    }

    def post(self, request, pk):
        if request.POST.get("acao") not in self.actions:
            raise Http404
        action, message = self.actions[request.POST["acao"]]
        reserva = get_object_or_404(Reserva, pk=pk)
        try:
            action(reserva, usuario=request.user)
        except services.ReservationError as exc:
            message = str(exc)
        return self.modal_success(message, AGENDA_URL)


class BloqueioListView(TenantRequiredMixin, ListView):
    template_name = "agenda/bloqueio_list.html"
    context_object_name = "bloqueios"

    def get_queryset(self):
        return Bloqueio.objects.filter(fim__gte=timezone.now()).select_related("espaco")


class BloqueioCreateView(TenantRequiredMixin, ModalResponseMixin, FormView):
    form_class = BloqueioForm
    modal_template_name = "agenda/_bloqueio_form.html"

    def get_initial(self):
        return {
            "data": _parse_day(self.request.GET.get("data")),
            "motivo": Bloqueio.Motivo.CHUVA,
        }

    def form_valid(self, form):
        data = form.cleaned_data
        bloqueios, affected = [], 0
        with transaction.atomic():
            for espaco in data["espacos"]:
                bloqueio, reservas = services.create_block(
                    espaco, data["inicio"], data["fim"], data["motivo"], data["descricao"], self.request.user
                )
                bloqueios.append(bloqueio)
                affected += len(reservas)
        if not affected:
            return self.modal_success("Horário bloqueado.", AGENDA_URL)
        url = f"{reverse('agenda:bloqueio_impact')}?{urlencode({'ids': ','.join(str(b.pk) for b in bloqueios)})}"
        return self.modal_redirect(f"Horário bloqueado. Reservas afetadas: {affected}.", url)


class BloqueioImpactView(TenantRequiredMixin, TemplateView):
    """Mostra as reservas atingidas por um bloqueio para remarcar ou cancelar."""

    template_name = "agenda/bloqueio_impact.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ids = [value for value in self.request.GET.get("ids", "").split(",") if value.isdigit()]
        bloqueios = list(Bloqueio.objects.filter(pk__in=ids).select_related("espaco"))
        if not bloqueios:
            raise Http404
        context["bloqueios"] = bloqueios
        context["reservas"] = services.affected_reservations(bloqueios)
        return context


class BloqueioDeleteView(TenantRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        get_object_or_404(Bloqueio, pk=pk).delete()
        messages.success(request, "Bloqueio removido. O horário voltou a ficar livre.")
        return redirect("agenda:bloqueio_list")


class ReservaBulkCancelView(TenantRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        ids = [value for value in request.POST.getlist("reservas") if value.isdigit()]
        reservas = Reserva.objects.filter(
            pk__in=ids, status__in=[Reserva.Status.PENDENTE, Reserva.Status.CONFIRMADA]
        )
        with transaction.atomic():
            count = 0
            for reserva in reservas:
                services.cancel_reservation(
                    reserva, usuario=request.user, detalhes="Cancelada em lote por bloqueio"
                )
                count += 1
        messages.success(request, f"Reservas canceladas: {count}.")
        next_url = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect(AGENDA_URL)
