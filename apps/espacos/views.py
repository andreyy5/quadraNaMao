from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, FormView, ListView, UpdateView, View

from apps.contas.mixins import OwnerRequiredMixin
from apps.estabelecimentos.mixins import TenantCreateMixin

from .forms import EspacoForm, HorarioSemanaFormSet, TabelaPrecoForm
from .models import DiaSemana, Espaco, HorarioFuncionamento, TabelaPreco
from .services import (
    PriceRuleOverlap,
    group_price_rules,
    price_rule_siblings,
    save_price_rules,
    save_weekly_hours,
)


class EspacoListView(OwnerRequiredMixin, ListView):
    model = Espaco
    template_name = "espacos/espaco_list.html"
    context_object_name = "espacos"


class EspacoCreateView(OwnerRequiredMixin, TenantCreateMixin, CreateView):
    model = Espaco
    form_class = EspacoForm
    template_name = "espacos/espaco_form.html"

    def get_success_url(self):
        messages.success(self.request, "Espaço criado. Agora defina os horários de funcionamento.")
        return reverse("espacos:horarios", args=[self.object.pk])


class EspacoUpdateView(OwnerRequiredMixin, UpdateView):
    model = Espaco
    form_class = EspacoForm
    template_name = "espacos/espaco_form.html"
    context_object_name = "espaco"
    success_url = reverse_lazy("espacos:list")

    def form_valid(self, form):
        messages.success(self.request, "Espaço salvo.")
        return super().form_valid(form)


class EspacoScopedMixin(OwnerRequiredMixin):
    """Carrega o espaço da URL, restrito ao estabelecimento atual."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.espaco = get_object_or_404(Espaco, pk=kwargs["espaco_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["espaco"] = self.espaco
        return context


class HorarioSemanaView(EspacoScopedMixin, FormView):
    form_class = HorarioSemanaFormSet
    template_name = "espacos/horario_form.html"

    def get_initial(self):
        saved = {h.dia_semana: h for h in HorarioFuncionamento.objects.filter(espaco=self.espaco)}
        initial = []
        for dia in DiaSemana.values:
            horario = saved.get(dia)
            initial.append(
                {
                    "dia_semana": dia,
                    "aberto": horario is not None,
                    "abre": horario.abre if horario else "08:00",
                    "fecha": horario.fecha if horario else "22:00",
                }
            )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formset"] = context.pop("form")
        return context

    def form_valid(self, form):
        # O dia vem da posição da linha, não do campo oculto enviado pelo navegador.
        rows = [{**row, "dia_semana": dia} for dia, row in enumerate(form.cleaned_data)]
        save_weekly_hours(self.espaco, rows)
        messages.success(self.request, "Horários salvos.")
        if not TabelaPreco.objects.filter(espaco=self.espaco).exists():
            return redirect("espacos:precos", self.espaco.pk)
        return redirect("espacos:horarios", self.espaco.pk)


class TabelaPrecoListView(EspacoScopedMixin, ListView):
    template_name = "espacos/preco_list.html"
    context_object_name = "precos"

    def get_queryset(self):
        return group_price_rules(TabelaPreco.objects.filter(espaco=self.espaco))


class TabelaPrecoFormMixin(EspacoScopedMixin):
    form_class = TabelaPrecoForm
    template_name = "espacos/preco_form.html"
    instance = None

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            save_price_rules(
                self.espaco,
                data["dias"],
                data["hora_inicio"],
                data["hora_fim"],
                data["duracao"],
                data["valor"],
                data["valor_sinal"],
                instance=self.instance,
            )
        except PriceRuleOverlap as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Tabela de preços salva.")
        return redirect("espacos:precos", self.espaco.pk)


class TabelaPrecoCreateView(TabelaPrecoFormMixin, FormView):
    initial = {"dias": DiaSemana.values, "hora_inicio": "08:00", "hora_fim": "22:00", "duracao": 60}


class TabelaPrecoUpdateView(TabelaPrecoFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            self.instance = get_object_or_404(TabelaPreco, pk=kwargs["pk"], espaco_id=kwargs["espaco_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        rule = self.instance
        return {
            "dias": list(price_rule_siblings(rule).values_list("dia_semana", flat=True)),
            "hora_inicio": rule.hora_inicio,
            "hora_fim": rule.hora_fim,
            "duracao": rule.duracao_slot_minutos,
            "valor": rule.valor,
            "valor_sinal": rule.valor_sinal,
        }


class TabelaPrecoDeleteView(OwnerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, espaco_pk, pk):
        price_rule_siblings(get_object_or_404(TabelaPreco, pk=pk, espaco_id=espaco_pk)).delete()
        messages.success(request, "Faixa de preço removida.")
        return redirect("espacos:precos", espaco_pk)
