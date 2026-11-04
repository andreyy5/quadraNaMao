from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from apps.agenda.models import Reserva
from apps.contas.mixins import ManagerRequiredMixin
from apps.estabelecimentos.mixins import ModalResponseMixin, TenantCreateMixin, TenantRequiredMixin
from apps.estabelecimentos.templatetags.ui import brl
from apps.pdv import services as pdv_services
from apps.pdv.models import Venda

from . import services
from .forms import (
    CancelAccountForm,
    CashMovementForm,
    ChargeReservationForm,
    CloseRegisterForm,
    OpenRegisterForm,
    PayBillForm,
    ReceiveForm,
    ReverseEntryForm,
)
from .models import Caixa, ContaBase, ContaPagar, ContaReceber, FormaPagamento, Lancamento

CAIXA_URL = reverse_lazy("financeiro:caixa")


class CaixaView(TenantRequiredMixin, TemplateView):
    """O caixa de quem está usando: abre, acompanha e fecha."""

    template_name = "financeiro/caixa.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        caixa = services.current_register(self.request.user)
        context["caixa"] = caixa
        context["active_tab"] = "caixa"
        if caixa:
            context["summary"] = services.register_summary(caixa)
            context["lancamentos"] = caixa.lancamentos.select_related("usuario", "estorno")[:100]
        else:
            context["ultimo"] = Caixa.objects.filter(operador=self.request.user).first()
        return context


class AbrirCaixaView(TenantRequiredMixin, ModalResponseMixin, FormView):
    form_class = OpenRegisterForm
    modal_template_name = "financeiro/_abrir.html"

    def get_initial(self):
        ultimo = Caixa.objects.filter(operador=self.request.user, fechado_em__isnull=False).first()
        return {"saldo_inicial": ultimo.saldo_conferido if ultimo else 0}

    def form_valid(self, form):
        try:
            services.open_register(self.request.user, form.cleaned_data["saldo_inicial"])
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success("Caixa aberto.", CAIXA_URL)


class MovimentoCaixaView(TenantRequiredMixin, ModalResponseMixin, FormView):
    form_class = CashMovementForm
    modal_template_name = "financeiro/_movimento.html"

    def form_valid(self, form):
        data = form.cleaned_data
        entra = data["tipo"] == CashMovementForm.ENTRA
        try:
            services.move_cash(self.request.user, entra, data["valor"], data["descricao"])
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(
            f"{'Entrada' if entra else 'Retirada'} de {brl(data['valor'])} registrada.", CAIXA_URL
        )


class FecharCaixaView(TenantRequiredMixin, ModalResponseMixin, FormView):
    """Quem opera conta o dinheiro sem ver o esperado; dono e gerente acompanham a diferença na hora."""

    form_class = CloseRegisterForm
    modal_template_name = "financeiro/_fechar.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.caixa = get_object_or_404(Caixa.objects.select_related("operador"), pk=kwargs["pk"])
            if self.caixa.operador_id != request.user.pk and not request.user.is_manager:
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["online"] = self.caixa.tipo == Caixa.Tipo.ONLINE
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["caixa"] = self.caixa
        context["summary"] = services.register_summary(self.caixa)
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            caixa = services.close_register(
                self.caixa, data.get("saldo_conferido", services.ZERO), self.request.user, data["observacao"]
            )
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_redirect("Caixa fechado.", reverse("financeiro:caixa_detail", args=[caixa.pk]))


class CaixaListView(ManagerRequiredMixin, ListView):
    template_name = "financeiro/caixa_list.html"
    context_object_name = "caixas"
    paginate_by = 30

    def get_queryset(self):
        return Caixa.objects.select_related("operador", "fechado_por")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "historico"
        return context


class CaixaDetailView(TenantRequiredMixin, DetailView):
    template_name = "financeiro/caixa_detail.html"
    context_object_name = "caixa"

    def get_queryset(self):
        queryset = Caixa.objects.select_related("operador", "fechado_por")
        if not self.request.user.is_manager:
            queryset = queryset.filter(operador=self.request.user)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["summary"] = services.register_summary(self.object)
        context["lancamentos"] = self.object.lancamentos.select_related("usuario", "estorno")
        context["active_tab"] = "historico"
        return context


class EstornarView(ManagerRequiredMixin, ModalResponseMixin, FormView):
    form_class = ReverseEntryForm
    modal_template_name = "financeiro/_estornar.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.lancamento = get_object_or_404(Lancamento, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lancamento"] = self.lancamento
        return context

    def form_valid(self, form):
        try:
            services.reverse_entry(self.lancamento, self.request.user, form.cleaned_data["motivo"])
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(f"Estorno de {brl(self.lancamento.valor)} registrado.", CAIXA_URL)


class ReceberReservaView(TenantRequiredMixin, ModalResponseMixin, FormView):
    """Recebe a reserva, a comanda dela ou as duas de uma vez."""

    form_class = ChargeReservationForm
    modal_template_name = "financeiro/_receber_reserva.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.reserva = get_object_or_404(
                Reserva.objects.select_related("espaco", "cliente", "conta").exclude(
                    status=Reserva.Status.CANCELADA
                ),
                pk=kwargs["pk"],
            )
            self.comanda = Venda.objects.filter(reserva=self.reserva, status=Venda.Status.ABERTA).first()
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        valor = self.reserva.conta.saldo
        if self.reserva.is_pending:
            valor = min(valor, max(self.reserva.valor_sinal - self.reserva.valor_pago, 0))
        return {"valor": valor, "incluir_comanda": True}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            reserva=self.reserva,
            conta=self.reserva.conta,
            comanda=self.comanda,
            caixa=services.current_register(self.request.user),
        )
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            result = pdv_services.charge_reservation(
                self.reserva,
                data["valor"] or 0,
                data["forma"],
                self.request.user,
                include_tab=data["incluir_comanda"],
                recebido=data["recebido"],
            )
        except (services.FinanceError, pdv_services.SaleError) as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        message = f"Recebido: {brl(result['total'])}."
        if result["troco"]:
            message += f" Troco: {brl(result['troco'])}."
        return self.modal_success(message, reverse("agenda:day"))


class ContaViewMixin:
    """O que muda entre contas a receber e a pagar. As telas são as mesmas."""

    model = None
    kind = ""

    @property
    def is_receivable(self):
        return self.kind == "receber"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            kind=self.kind,
            is_receivable=self.is_receivable,
            active_tab=self.kind,
            list_url=reverse(f"financeiro:{self.kind}"),
        )
        return context


class ContaListView(ContaViewMixin, ManagerRequiredMixin, ListView):
    template_name = "financeiro/conta_list.html"
    context_object_name = "contas"
    paginate_by = 30

    def get_queryset(self):
        # Garante as repetições mesmo em ambiente sem o agendador rodando; não duplica.
        services.generate_recurring_accounts(self.request.tenant)
        queryset = self.model.objects.all()
        if self.is_receivable:
            queryset = queryset.select_related("cliente", "reserva")
        filtro = self.request.GET.get("filtro", "")
        today = timezone.localdate()
        Status = ContaBase.Status
        if filtro == "atrasadas":
            return queryset.filter(status=Status.ABERTA, vencimento__lt=today)
        if filtro == "pagas":
            return queryset.filter(status=Status.PAGA).order_by("-pago_em", "-pk")
        if filtro == "canceladas":
            return queryset.filter(status=Status.CANCELADA).order_by("-vencimento", "-pk")
        return queryset.filter(status=Status.ABERTA)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filtro"] = self.request.GET.get("filtro", "")
        context["overview"] = services.accounts_overview(self.model, self.request.tenant)
        return context


class ContaEditMixin(ContaViewMixin, ManagerRequiredMixin):
    template_name = "financeiro/conta_form.html"
    context_object_name = "conta"


class ContaCreateView(ContaEditMixin, TenantCreateMixin, CreateView):
    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        messages.success(self.request, "Conta cadastrada.")
        return reverse(f"financeiro:{self.kind}")


class ContaUpdateView(ContaEditMixin, UpdateView):
    def get_queryset(self):
        # Conta paga já é histórico, e a da reserva muda junto com a reserva.
        queryset = self.model.objects.filter(status=ContaBase.Status.ABERTA, valor_pago=0)
        return queryset.filter(reserva__isnull=True) if self.is_receivable else queryset

    def get_success_url(self):
        messages.success(self.request, "Conta salva.")
        return reverse(f"financeiro:{self.kind}")


class ReceberContaView(ManagerRequiredMixin, ModalResponseMixin, FormView):
    form_class = ReceiveForm
    modal_template_name = "financeiro/_receber_conta.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.conta = get_object_or_404(ContaReceber.objects.select_related("cliente"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"valor": self.conta.saldo}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(conta=self.conta, caixa=services.current_register(self.request.user))
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        if data["recebido"] and data["forma"] == FormaPagamento.DINHEIRO and data["recebido"] < data["valor"]:
            form.add_error("recebido", "O valor recebido é menor que o valor da baixa.")
            return self.form_invalid(form)
        try:
            services.receive_account(self.conta, data["valor"], data["forma"], self.request.user)
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(f"Recebido: {brl(data['valor'])}.", reverse("financeiro:receber"))


class PagarContaView(ManagerRequiredMixin, ModalResponseMixin, FormView):
    form_class = PayBillForm
    modal_template_name = "financeiro/_pagar_conta.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.conta = get_object_or_404(ContaPagar, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"do_caixa": services.current_register(self.request.user) is not None}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(conta=self.conta, caixa=services.current_register(self.request.user))
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            services.pay_bill(self.conta, data["forma"], self.request.user, from_register=data["do_caixa"])
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(f"{self.conta.descricao} paga.", reverse("financeiro:pagar"))


class CancelarContaView(ContaViewMixin, ManagerRequiredMixin, ModalResponseMixin, FormView):
    form_class = CancelAccountForm
    modal_template_name = "financeiro/_cancelar_conta.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.conta = get_object_or_404(self.model, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["conta"] = self.conta
        return context

    def form_valid(self, form):
        try:
            services.cancel_account(self.conta, stop_repeating=form.cleaned_data["parar_repeticao"])
        except services.FinanceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success("Conta cancelada.", reverse(f"financeiro:{self.kind}"))
