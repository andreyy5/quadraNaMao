import json
from datetime import datetime, timedelta

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.views.generic import DetailView, ListView, TemplateView, View

from apps.agenda.models import Reserva
from apps.estabelecimentos.mixins import ModalResponseMixin, TenantRequiredMixin
from apps.estabelecimentos.templatetags.ui import brl
from apps.estoque.models import Produto
from apps.estoque.services import StockError

from . import services
from .forms import CancelSaleForm, CheckoutForm, CloseTabForm
from .models import ItemVenda, Venda

PDV_URL = reverse_lazy("pdv:home")


def _reject(message):
    """Avisa o erro e recarrega a tela, para o carrinho conferir o estoque e os preços atuais."""
    events = {"toast": {"message": message, "level": "error"}, "data:changed": True}
    return HttpResponse(headers={"HX-Trigger": json.dumps(events), "HX-Reswap": "none"})


def _parse_cart(post):
    """Lê as listas de produtos e quantidades, somando produtos repetidos."""
    cart = {}
    for produto, quantidade in zip(post.getlist("produto"), post.getlist("quantidade"), strict=False):
        if produto.isdigit() and quantidade.isdigit():
            cart[int(produto)] = cart.get(int(produto), 0) + int(quantidade)
    return cart


class PdvView(TenantRequiredMixin, TemplateView):
    template_name = "pdv/pdv.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        today = timezone.localdate()
        start = datetime.combine(today, datetime.min.time(), tzinfo=tenant.timezone)
        reservas = (
            Reserva.objects.filter(inicio__gte=start, inicio__lt=start + timedelta(days=1))
            .exclude(status__in=[Reserva.Status.CANCELADA, Reserva.Status.NAO_COMPARECEU])
            .select_related("cliente", "espaco")
            .order_by("inicio")
        )
        reservas = list(reservas)

        # Reserva vinda do painel de detalhes, que pode ser de outro dia.
        requested = self.request.GET.get("reserva", "")
        selected = ""
        if requested.isdigit():
            reserva = (
                Reserva.objects.filter(pk=requested)
                .exclude(status=Reserva.Status.CANCELADA)
                .select_related("cliente", "espaco")
                .first()
            )
            if reserva:
                selected = reserva.pk
                if reserva not in reservas:
                    reservas.insert(0, reserva)

        produtos = list(Produto.objects.filter(ativo=True))
        context.update(
            produtos=produtos,
            # Só as categorias que têm produto: filtro vazio não ajuda ninguém.
            categorias=[
                choice
                for choice in Produto.Categoria.choices
                if any(produto.categoria == choice[0] for produto in produtos)
            ],
            formas=Venda.Forma.choices,
            pdv_data={
                "produtos": [
                    {
                        "id": produto.pk,
                        "nome": produto.nome,
                        "preco": str(produto.preco_venda),
                        "categoria": produto.categoria,
                        "codigo": produto.codigo,
                        "controla": produto.controla_estoque,
                        "estoque": produto.estoque_atual,
                        "baixo": produto.is_low,
                    }
                    for produto in produtos
                ],
                "permiteNegativo": tenant.permite_estoque_negativo,
                "reservas": [
                    {
                        "id": reserva.pk,
                        "cliente": reserva.cliente.nome,
                        "espaco": reserva.espaco.nome,
                        "tema": reserva.espaco.tema,
                        "hora": timezone.localtime(reserva.inicio).strftime("%H:%M"),
                    }
                    for reserva in reservas
                ],
                "reservaSelecionada": selected,
            },
            active_tab="vender",
            tabs_count=Venda.objects.filter(status=Venda.Status.ABERTA).count(),
        )
        return context


class FinalizarView(TenantRequiredMixin, ModalResponseMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        form = CheckoutForm(request.POST)
        if not form.is_valid():
            return _reject("Confira a forma de pagamento e tente de novo.")
        data = form.cleaned_data
        cart = _parse_cart(request.POST)
        try:
            if data["reserva"]:
                venda = services.add_to_tab(
                    request.tenant, data["reserva"], cart, usuario=request.user, total_esperado=data["total"]
                )
                message = f"Lançado na comanda de {venda.cliente.nome}."
            else:
                venda = services.complete_sale(
                    request.tenant,
                    cart,
                    data["forma"],
                    usuario=request.user,
                    recebido=data["recebido"],
                    total_esperado=data["total"],
                )
                message = f"Venda #{venda.numero} concluída."
                if venda.troco:
                    message += f" Troco: {brl(venda.troco)}."
        except (services.SaleError, StockError) as exc:
            return _reject(str(exc))
        return self.modal_success(message, PDV_URL)


def _parse_day(raw):
    try:
        return parse_date(raw or "") or timezone.localdate()
    except ValueError:
        return timezone.localdate()


class VendaListView(TenantRequiredMixin, ListView):
    """Vendas de um dia, com o total por forma de pagamento."""

    template_name = "pdv/venda_list.html"
    context_object_name = "vendas"

    def get_queryset(self):
        self.day = _parse_day(self.request.GET.get("data"))
        start = datetime.combine(self.day, datetime.min.time(), tzinfo=self.request.tenant.timezone)
        return (
            Venda.objects.filter(concluida_em__gte=start, concluida_em__lt=start + timedelta(days=1))
            .select_related("criado_por", "reserva__cliente")
            .prefetch_related("itens__produto")
            .order_by("-concluida_em")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        url = reverse("pdv:vendas")
        context.update(
            day=self.day,
            heading=date_format(self.day, "l, j \\d\\e F").lower(),
            is_today=self.day == timezone.localdate(),
            previous_url=f"{url}?data={self.day - timedelta(days=1):%Y-%m-%d}",
            next_url=f"{url}?data={self.day + timedelta(days=1):%Y-%m-%d}",
            summary=services.day_summary(self.request.tenant, self.day),
            active_tab="vendas",
            tabs_count=Venda.objects.filter(status=Venda.Status.ABERTA).count(),
        )
        return context


class ComandaListView(TenantRequiredMixin, ListView):
    template_name = "pdv/comanda_list.html"
    context_object_name = "comandas"

    def get_queryset(self):
        return (
            Venda.objects.filter(status=Venda.Status.ABERTA)
            .select_related("reserva__espaco", "cliente")
            .prefetch_related("itens__produto")
            .order_by("reserva__inicio")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(active_tab="comandas", tabs_count=len(context["comandas"]))
        return context


class VendaDetailView(TenantRequiredMixin, ModalResponseMixin, DetailView):
    model = Venda
    modal_template_name = "pdv/_venda_detail.html"
    context_object_name = "venda"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("reserva__espaco", "reserva__cliente", "criado_por", "cancelada_por")
            .prefetch_related("itens__produto")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formas"] = Venda.Forma.choices
        context["can_cancel"] = self.object.is_tab or (
            not self.object.is_cancelled and self.request.user.is_manager
        )
        return context


class ReceberComandaView(TenantRequiredMixin, ModalResponseMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        venda = get_object_or_404(Venda, pk=pk)
        form = CloseTabForm(request.POST)
        if not form.is_valid():
            return _reject("Escolha a forma de pagamento.")
        try:
            venda = services.close_tab(venda, form.cleaned_data["forma"], form.cleaned_data["recebido"])
        except services.SaleError as exc:
            return _reject(str(exc))
        message = f"Comanda recebida: {brl(venda.total)}."
        if venda.troco:
            message += f" Troco: {brl(venda.troco)}."
        return self.modal_success(message, reverse("pdv:comandas"))


class RemoverItemView(TenantRequiredMixin, ModalResponseMixin, View):
    """Tira um item de uma comanda em aberto e devolve ao estoque."""

    http_method_names = ["post"]

    def post(self, request, pk):
        item = get_object_or_404(ItemVenda.objects.select_related("produto", "venda"), pk=pk)
        try:
            services.remove_tab_item(item, usuario=request.user)
        except services.SaleError as exc:
            return _reject(str(exc))
        return self.modal_success(f"{item.produto.nome} retirado da comanda.", reverse("pdv:comandas"))


class CancelarVendaView(TenantRequiredMixin, ModalResponseMixin, DetailView):
    """Comanda em aberto qualquer um corrige; venda já paga, só dono ou gerente cancela."""

    model = Venda
    modal_template_name = "pdv/_venda_cancel.html"
    context_object_name = "venda"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            venda = get_object_or_404(Venda, pk=kwargs["pk"])
            if not venda.is_tab and not request.user.is_manager:
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("form", CancelSaleForm())
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = CancelSaleForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        try:
            services.cancel_sale(self.object, usuario=request.user, motivo=form.cleaned_data["motivo"])
        except services.SaleError as exc:
            return self.render_to_response(self.get_context_data(form=form, error=str(exc)))
        return self.modal_success(
            f"Venda #{self.object.numero} cancelada. Os itens voltaram ao estoque.", reverse("pdv:vendas")
        )
