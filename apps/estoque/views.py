from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.contas.mixins import ManagerRequiredMixin
from apps.estabelecimentos.mixins import ModalResponseMixin, TenantCreateMixin
from apps.financeiro.services import create_purchase_bill

from . import services
from .forms import MovimentacaoForm, ProdutoForm
from .models import Produto


class ProdutoListView(ManagerRequiredMixin, ListView):
    template_name = "estoque/produto_list.html"
    context_object_name = "produtos"

    def get_queryset(self):
        queryset = Produto.objects.all()
        filtro = self.request.GET.get("filtro", "")
        if filtro == "baixo":
            return queryset.filter(ativo=True, controla_estoque=True, estoque_atual__lte=F("estoque_minimo"))
        if filtro == "inativos":
            return queryset.filter(ativo=False)
        queryset = queryset.filter(ativo=True)
        query = self.request.GET.get("q", "").strip()
        return queryset.filter(nome__unaccent__icontains=query) if query else queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            filtro=self.request.GET.get("filtro", ""),
            q=self.request.GET.get("q", ""),
            overview=services.stock_overview(self.request.tenant),
        )
        return context


class ProdutoCreateView(ManagerRequiredMixin, TenantCreateMixin, CreateView):
    model = Produto
    form_class = ProdutoForm
    template_name = "estoque/produto_form.html"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            inicial = form.cleaned_data.get("estoque_inicial")
            if inicial and self.object.controla_estoque:
                services.register_entry(
                    self.object, inicial, usuario=self.request.user, observacao="Estoque inicial"
                )
        return response

    def get_success_url(self):
        messages.success(self.request, "Produto cadastrado.")
        return reverse("estoque:list")


class ProdutoUpdateView(ManagerRequiredMixin, UpdateView):
    model = Produto
    form_class = ProdutoForm
    template_name = "estoque/produto_form.html"
    context_object_name = "produto"

    def get_success_url(self):
        messages.success(self.request, "Produto salvo.")
        return reverse("estoque:detail", args=[self.object.pk])


class ProdutoDetailView(ManagerRequiredMixin, DetailView):
    model = Produto
    template_name = "estoque/produto_detail.html"
    context_object_name = "produto"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movimentacoes"] = self.object.movimentacoes.select_related("usuario")[:50]
        return context


class MovimentarView(ManagerRequiredMixin, ModalResponseMixin, FormView):
    """Registra uma compra, uma perda ou a contagem da prateleira."""

    form_class = MovimentacaoForm
    modal_template_name = "estoque/_movimentar.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.produto = get_object_or_404(Produto, pk=kwargs["pk"])
            if not self.produto.controla_estoque:
                raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        tipo = self.request.GET.get("tipo")
        valid = dict(MovimentacaoForm.base_fields["tipo"].choices)
        return {"tipo": tipo if tipo in valid else MovimentacaoForm.ENTRADA}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["produto"] = self.produto
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        kwargs = {"usuario": self.request.user, "observacao": data["observacao"]}
        try:
            if data["tipo"] == MovimentacaoForm.ENTRADA:
                with transaction.atomic():
                    services.register_entry(self.produto, data["quantidade"], custo=data["custo"], **kwargs)
                    message = f"Entrada registrada: {data['quantidade']} de {self.produto.nome}."
                    if data["gerar_conta"]:
                        create_purchase_bill(
                            self.produto,
                            data["quantidade"],
                            data["custo"],
                            data["vencimento"],
                            data["fornecedor"],
                            self.request.user,
                        )
                        message += " A conta foi lançada em contas a pagar."
            elif data["tipo"] == MovimentacaoForm.PERDA:
                services.register_loss(self.produto, data["quantidade"], **kwargs)
                message = f"Perda registrada: {data['quantidade']} de {self.produto.nome}."
            else:
                services.adjust_to_count(self.produto, data["quantidade"], **kwargs)
                message = f"Estoque de {self.produto.nome} acertado para {data['quantidade']}."
        except services.StockError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return self.modal_success(message, reverse("estoque:detail", args=[self.produto.pk]))
