from django import forms

from .models import Estabelecimento


class StyledFormMixin:
    """Aplica as classes visuais do projeto a todos os campos do formulário."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "checkbox"
            elif isinstance(widget, forms.CheckboxSelectMultiple | forms.RadioSelect | forms.HiddenInput):
                continue
            else:
                css = "input"
            widget.attrs["class"] = f"{css} {widget.attrs.get('class', '')}".strip()


class EstabelecimentoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Estabelecimento
        fields = ["nome", "documento", "telefone", "endereco", "fuso_horario", "permite_estoque_negativo"]
        widgets = {"telefone": forms.TextInput(attrs={"inputmode": "tel", "data-mask": "phone"})}


class ReservasOnlineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Estabelecimento
        fields = [
            "reserva_online_ativa",
            "chave_pix",
            "pix_cidade",
            "prazo_sinal_minutos",
            "cancelamento_horas",
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("prazo_sinal_minutos") is not None and not 5 <= cleaned["prazo_sinal_minutos"] <= 1440:
            self.add_error("prazo_sinal_minutos", "Use de 5 minutos a 24 horas (1440).")
        return cleaned


class WhatsAppAjustesForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Estabelecimento
        fields = ["whatsapp_ativo", "whatsapp_phone_number_id", "lembrete_horas"]

    def clean_whatsapp_phone_number_id(self):
        value = self.cleaned_data["whatsapp_phone_number_id"].strip()
        if value and not value.isdigit():
            raise forms.ValidationError("O ID do número tem só dígitos. Copie do painel da Meta.")
        if (
            value
            and Estabelecimento.objects.filter(whatsapp_phone_number_id=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Esse número já está ligado a outro estabelecimento.")
        return value


class WhatsAppTestForm(StyledFormMixin, forms.Form):
    telefone = forms.CharField(
        label="Mandar um teste para",
        max_length=32,
        widget=forms.TextInput(
            attrs={"inputmode": "tel", "placeholder": "(11) 98888-7777", "data-mask": "phone"}
        ),
    )

    def clean_telefone(self):
        from apps.clientes.services import InvalidPhone, normalize_phone

        try:
            return normalize_phone(self.cleaned_data["telefone"])
        except InvalidPhone as exc:
            raise forms.ValidationError(str(exc)) from exc
