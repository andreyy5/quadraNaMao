from datetime import datetime, time, timedelta

from django import forms
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.clientes.services import InvalidPhone, normalize_phone
from apps.espacos.forms import TIME_WIDGET, money_field
from apps.espacos.models import Espaco
from apps.estabelecimentos.forms import StyledFormMixin
from apps.estabelecimentos.mixins import TenantFormMixin

from .models import Bloqueio

DURATION_CHOICES = [
    (30, "30 min"),
    (45, "45 min"),
    (60, "1 hora"),
    (90, "1h30"),
    (120, "2 horas"),
    (150, "2h30"),
    (180, "3 horas"),
    (240, "4 horas"),
]


class ReservaForm(StyledFormMixin, TenantFormMixin, forms.Form):
    espaco = forms.ModelChoiceField(
        label="Espaço", queryset=Espaco.objects.none(), empty_label=None, widget=forms.RadioSelect
    )
    data = forms.DateField(label="Dia", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hora = forms.TimeField(label="Início", widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M"))
    duracao = forms.IntegerField(
        label="Duração",
        min_value=15,
        max_value=720,
        initial=60,
        widget=forms.RadioSelect(choices=DURATION_CHOICES),
    )
    valor_total = money_field(label="Valor", required=False)
    observacoes = forms.CharField(
        label="Observações",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Recados para a equipe"}),
    )
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.none(), required=False, widget=forms.HiddenInput
    )
    cliente_nome = forms.CharField(
        label="Cliente",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Nome ou telefone"}),
    )
    cliente_telefone = forms.CharField(
        label="WhatsApp",
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "tel",
                "autocomplete": "off",
                "placeholder": "(11) 98888-7777",
                "data-mask": "phone",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["espaco"].queryset = Espaco.objects.filter(ativo=True)
        duration = str(self["duracao"].value() or "")
        if duration.isdigit() and int(duration) not in dict(DURATION_CHOICES):
            self.fields["duracao"].widget.choices = sorted(
                [*DURATION_CHOICES, (int(duration), f"{duration} min")]
            )

        # Busca instantânea e estado do cliente, controlados pelo componente reservaForm (app.js).
        search = {
            "hx-get": reverse("clientes:search"),
            "hx-trigger": "input changed delay:200ms",
            "hx-target": "#cliente-results",
            "hx-swap": "innerHTML",
            "x-on:input": "clienteId = ''",
        }
        self.fields["cliente"].widget.attrs["x-model"] = "clienteId"
        self.fields["cliente_nome"].widget.attrs["data-autofocus"] = "true"
        self.fields["cliente_nome"].widget.attrs.update(search, **{"x-model": "nome"})
        self.fields["cliente_telefone"].widget.attrs.update(search, **{"x-model": "telefone"})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("data") and cleaned.get("hora") and cleaned.get("duracao"):
            inicio = datetime.combine(
                cleaned["data"], cleaned["hora"], tzinfo=timezone.get_current_timezone()
            )
            cleaned["inicio"] = inicio
            cleaned["fim"] = inicio + timedelta(minutes=cleaned["duracao"])

        if not cleaned.get("cliente"):
            if not cleaned.get("cliente_nome", "").strip():
                self.add_error("cliente_nome", "Informe o nome do cliente.")
            try:
                cleaned["cliente_telefone"] = normalize_phone(cleaned.get("cliente_telefone"))
            except InvalidPhone as exc:
                self.add_error("cliente_telefone", str(exc))
        return cleaned


class BloqueioForm(StyledFormMixin, TenantFormMixin, forms.Form):
    espacos = forms.ModelMultipleChoiceField(
        label="Espaços",
        queryset=Espaco.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Marque pelo menos um espaço."},
    )
    data = forms.DateField(label="Dia", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    dia_todo = forms.BooleanField(
        label="O dia todo", required=False, widget=forms.CheckboxInput(attrs={"x-model": "diaTodo"})
    )
    hora_inicio = forms.TimeField(
        label="Das", required=False, widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M")
    )
    hora_fim = forms.TimeField(
        label="Até", required=False, widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M")
    )
    motivo = forms.ChoiceField(label="Motivo", choices=Bloqueio.Motivo.choices, widget=forms.RadioSelect)
    descricao = forms.CharField(
        label="Observação",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: troca da rede"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["espacos"].queryset = Espaco.objects.filter(ativo=True)

    def clean(self):
        cleaned = super().clean()
        day = cleaned.get("data")
        if day is None:
            return cleaned
        tz = timezone.get_current_timezone()
        if cleaned.get("dia_todo"):
            cleaned["inicio"] = datetime.combine(day, time.min, tzinfo=tz)
            cleaned["fim"] = cleaned["inicio"] + timedelta(days=1)
            return cleaned

        start, end = cleaned.get("hora_inicio"), cleaned.get("hora_fim")
        if not start:
            self.add_error("hora_inicio", "Informe o horário ou marque o dia todo.")
        if not end:
            self.add_error("hora_fim", "Informe o horário ou marque o dia todo.")
        if start and end:
            cleaned["inicio"] = datetime.combine(day, start, tzinfo=tz)
            # "Das 22h até 01h" termina no dia seguinte.
            end_day = day if end > start else day + timedelta(days=1)
            cleaned["fim"] = datetime.combine(end_day, end, tzinfo=tz)
        return cleaned
