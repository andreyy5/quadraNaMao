import unicodedata

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.agenda.models import Reserva
from apps.estabelecimentos.mixins import TenantCreateMixin, TenantRequiredMixin
from apps.financeiro.models import ContaBase, ContaReceber

from .forms import ClienteForm
from .models import Cliente
from .services import anonymize_client, search_clients


class ClienteListView(TenantRequiredMixin, ListView):
    template_name = "clientes/cliente_list.html"
    context_object_name = "clientes"
    paginate_by = 25

    def get_queryset(self):
        return search_clients(self.request.GET.get("q"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        return context


class ClienteSearchView(TenantRequiredMixin, TemplateView):
    """Sugestões enquanto o atendente digita nome ou telefone na reserva."""

    template_name = "clientes/_search_results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        query = (
            params.get("cliente_telefone") or params.get("cliente_nome") or params.get("q") or ""
        ).strip()
        context["clientes"] = search_clients(query, limit=6) if len(query) >= 2 else []
        return context


def _plain(text):
    """Minúsculas e sem acento, para comparar o que foi digitado com o nome de uma ação."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class PaletteView(TenantRequiredMixin, TemplateView):
    """Busca rápida (Ctrl+K): encontra clientes e leva direto a qualquer ação do sistema."""

    template_name = "clientes/_palette.html"

    def get_actions(self):
        actions = [
            {
                "label": "Nova reserva",
                "icon": "plus",
                "modal": reverse("agenda:reserva_create"),
                "terms": "agendar marcar",
            },
            {
                "label": "Bloquear horário",
                "icon": "lock",
                "modal": reverse("agenda:bloqueio_create"),
                "terms": "chuva manutencao evento fechar",
            },
            {"label": "Vender (PDV)", "icon": "cart", "url": reverse("pdv:home"), "terms": "caixa venda bar"},
            {
                "label": "Comandas abertas",
                "icon": "receipt",
                "url": reverse("pdv:comandas"),
                "terms": "consumo",
            },
            {"label": "Vendas do dia", "icon": "receipt", "url": reverse("pdv:vendas"), "terms": "historico"},
            {
                "label": "Meu caixa",
                "icon": "dinheiro",
                "url": reverse("financeiro:caixa"),
                "terms": "abrir fechar",
            },
            {"label": "Agenda do dia", "icon": "calendar", "url": reverse("agenda:day"), "terms": "hoje"},
            {"label": "Agenda da semana", "icon": "calendar", "url": reverse("agenda:week"), "terms": ""},
            {
                "label": "Mensalistas",
                "icon": "repeat",
                "url": reverse("agenda:mensalistas"),
                "terms": "fixo semanal",
            },
            {
                "label": "Novo mensalista",
                "icon": "repeat",
                "url": reverse("agenda:mensalista_create"),
                "terms": "horario fixo",
            },
            {
                "label": "WhatsApp",
                "icon": "message",
                "url": reverse("whatsapp:conversas"),
                "terms": "mensagens",
            },
            {
                "label": "Novo cliente",
                "icon": "users",
                "url": reverse("clientes:create"),
                "terms": "cadastrar",
            },
            {"label": "Clientes", "icon": "users", "url": reverse("clientes:list"), "terms": "lista"},
            {
                "label": "Bloqueios programados",
                "icon": "lock",
                "url": reverse("agenda:bloqueio_list"),
                "terms": "",
            },
        ]
        if self.request.user.is_manager:
            actions += [
                {
                    "label": "Contas a pagar",
                    "icon": "receipt",
                    "url": reverse("financeiro:pagar"),
                    "terms": "boleto despesa",
                },
                {
                    "label": "Contas a receber",
                    "icon": "receipt",
                    "url": reverse("financeiro:receber"),
                    "terms": "cobranca",
                },
                {
                    "label": "Relatórios",
                    "icon": "chart",
                    "url": reverse("relatorios:relatorio"),
                    "terms": "faturamento ocupacao",
                },
                {
                    "label": "Estoque",
                    "icon": "box",
                    "url": reverse("estoque:list"),
                    "terms": "produtos compra",
                },
                {
                    "label": "Novo produto",
                    "icon": "box",
                    "url": reverse("estoque:create"),
                    "terms": "cadastrar",
                },
            ]
        if self.request.user.is_owner:
            actions += [
                {
                    "label": "Espaços",
                    "icon": "court",
                    "url": reverse("espacos:list"),
                    "terms": "quadra campo areia",
                },
                {
                    "label": "Ajustes do estabelecimento",
                    "icon": "settings",
                    "url": reverse("estabelecimentos:ajustes"),
                    "terms": "configuracoes",
                },
                {
                    "label": "Equipe",
                    "icon": "users",
                    "url": reverse("contas:equipe"),
                    "terms": "atendente gerente",
                },
            ]
        return actions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        plain = _plain(query)
        context.update(
            q=query,
            clientes=search_clients(query, limit=6) if len(query) >= 2 else [],
            actions=[a for a in self.get_actions() if plain in _plain(f"{a['label']} {a['terms']}")],
        )
        return context


class ClienteCreateView(TenantRequiredMixin, TenantCreateMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/cliente_form.html"

    def get_success_url(self):
        messages.success(self.request, "Cliente cadastrado.")
        return reverse("clientes:detail", args=[self.object.pk])


class ClienteDetailView(TenantRequiredMixin, DetailView):
    model = Cliente
    template_name = "clientes/cliente_detail.html"
    context_object_name = "cliente"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reservas = Reserva.objects.filter(cliente=self.object).select_related("espaco")
        context["reservas"] = reservas.order_by("-inicio")[:30]
        contas = ContaReceber.objects.filter(cliente=self.object, status=ContaBase.Status.ABERTA)
        em_aberto = contas.aggregate(total=Sum("valor"), pago=Sum("valor_pago"))
        context["em_aberto"] = (em_aberto["total"] or 0) - (em_aberto["pago"] or 0)
        context["resumo"] = reservas.aggregate(
            total=Count("pk", filter=~Q(status=Reserva.Status.CANCELADA)),
            faltas=Count("pk", filter=Q(status=Reserva.Status.NAO_COMPARECEU)),
            canceladas=Count("pk", filter=Q(status=Reserva.Status.CANCELADA)),
        )
        return context


class ClienteUpdateView(TenantRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/cliente_form.html"
    context_object_name = "cliente"

    def get_queryset(self):
        return super().get_queryset().filter(anonimizado_em__isnull=True)

    def get_success_url(self):
        messages.success(self.request, "Cliente salvo.")
        return reverse("clientes:detail", args=[self.object.pk])


class ClienteAnonymizeView(TenantRequiredMixin, DetailView):
    model = Cliente
    template_name = "clientes/cliente_anonymize.html"
    context_object_name = "cliente"
    success_url = reverse_lazy("clientes:list")

    def get_queryset(self):
        return super().get_queryset().filter(anonimizado_em__isnull=True)

    def post(self, request, *args, **kwargs):
        anonymize_client(self.get_object())
        messages.success(request, "Dados pessoais do cliente apagados.")
        return redirect(self.success_url)
