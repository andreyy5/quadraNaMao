from django import forms

from apps.estabelecimentos.forms import StyledFormMixin

from .models import DiaSemana, Espaco

TIME_WIDGET = {"type": "time", "step": "900"}


class MoneyField(forms.DecimalField):
    """Valor em reais. Aceita "1.500,00", "1500,00", "1500.00" e "R$ 1.500"."""

    def to_python(self, value):
        if isinstance(value, str):
            text = value.replace("R$", "").replace(" ", "").strip()
            if "," in text:
                text = text.replace(".", "").replace(",", ".")
            elif text.count(".") > 1 or (text.count(".") == 1 and len(text.split(".")[1]) == 3):
                text = text.replace(".", "")
            value = text
        return super().to_python(value)


def money_field(**kwargs):
    return MoneyField(
        max_digits=9,
        decimal_places=2,
        min_value=0,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00"}),
        **kwargs,
    )


class EspacoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Espaco
        fields = ["nome", "tipo", "modalidades", "capacidade", "ordem", "ativo"]
        widgets = {
            "tipo": forms.RadioSelect,
            "nome": forms.TextInput(attrs={"placeholder": "Ex.: Quadra 1"}),
        }


class HorarioDiaForm(StyledFormMixin, forms.Form):
    dia_semana = forms.IntegerField(widget=forms.HiddenInput)
    aberto = forms.BooleanField(required=False, label="Aberto")
    abre = forms.TimeField(
        required=False, label="Abre", widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M")
    )
    fecha = forms.TimeField(
        required=False, label="Fecha", widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M")
    )

    @property
    def dia_label(self):
        return DiaSemana(int(self["dia_semana"].value())).label

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("aberto") and (not cleaned.get("abre") or not cleaned.get("fecha")):
            raise forms.ValidationError("Informe os dois horários.")
        return cleaned


HorarioSemanaFormSet = forms.formset_factory(HorarioDiaForm, extra=0, min_num=7, max_num=7, validate_min=True)


class TabelaPrecoForm(StyledFormMixin, forms.Form):
    dias = forms.TypedMultipleChoiceField(
        label="Dias",
        choices=DiaSemana.choices,
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Marque pelo menos um dia."},
    )
    hora_inicio = forms.TimeField(label="Das", widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M"))
    hora_fim = forms.TimeField(label="Até", widget=forms.TimeInput(attrs=TIME_WIDGET, format="%H:%M"))
    duracao = forms.TypedChoiceField(
        label="Cada horário dura",
        coerce=int,
        initial=60,
        choices=[(30, "30 min"), (45, "45 min"), (60, "1 hora"), (90, "1h30"), (120, "2 horas")],
        widget=forms.RadioSelect,
    )
    valor = money_field(label="Valor do horário")
    valor_sinal = money_field(label="Sinal", required=False)
