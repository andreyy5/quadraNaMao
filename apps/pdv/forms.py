from django import forms

from apps.agenda.models import Reserva
from apps.estabelecimentos.forms import StyledFormMixin
from apps.estabelecimentos.mixins import TenantFormMixin

from .models import Venda


class CheckoutForm(TenantFormMixin, forms.Form):
    """Dados do fechamento enviados pela tela do PDV. Os itens chegam à parte, em listas."""

    forma = forms.ChoiceField(choices=Venda.Forma.choices, required=False)
    reserva = forms.ModelChoiceField(queryset=Reserva.objects.none(), required=False)
    recebido = forms.DecimalField(max_digits=9, decimal_places=2, min_value=0, required=False)
    total = forms.DecimalField(max_digits=9, decimal_places=2, min_value=0, required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("reserva") and not cleaned.get("forma"):
            raise forms.ValidationError("Escolha a forma de pagamento ou uma reserva.")
        return cleaned


class CloseTabForm(forms.Form):
    forma = forms.ChoiceField(choices=Venda.Forma.choices)
    recebido = forms.DecimalField(max_digits=9, decimal_places=2, min_value=0, required=False)


class CancelSaleForm(StyledFormMixin, forms.Form):
    motivo = forms.CharField(
        label="Motivo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: cobrado errado"}),
    )
