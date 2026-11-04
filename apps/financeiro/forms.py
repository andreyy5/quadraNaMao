from django import forms
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.espacos.forms import money_field
from apps.estabelecimentos.forms import StyledFormMixin
from apps.estabelecimentos.mixins import TenantFormMixin

from .models import CATEGORIAS_PAGAR, CATEGORIAS_RECEBER, ContaPagar, ContaReceber, FormaPagamento


def forma_field():
    return forms.ChoiceField(
        label="Forma de pagamento",
        choices=FormaPagamento.choices,
        widget=forms.RadioSelect,
        error_messages={"required": "Escolha a forma de pagamento."},
    )


class OpenRegisterForm(StyledFormMixin, forms.Form):
    saldo_inicial = money_field(label="Dinheiro na gaveta", help_text="O troco com que o caixa começa.")


class CashMovementForm(StyledFormMixin, forms.Form):
    ENTRA, SAI = "ENTRA", "SAI"

    tipo = forms.ChoiceField(
        label="O que aconteceu",
        choices=[(SAI, "Tirei dinheiro"), (ENTRA, "Coloquei dinheiro")],
        widget=forms.RadioSelect,
        initial=SAI,
    )
    valor = money_field(label="Valor")
    descricao = forms.CharField(
        label="Motivo",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: sangria, troco, compra de gelo"}),
        error_messages={"required": "Conte o motivo: é o que explica a diferença depois."},
    )


class CloseRegisterForm(StyledFormMixin, forms.Form):
    saldo_conferido = money_field(label="Dinheiro contado na gaveta")
    observacao = forms.CharField(
        label="Observação",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Se sobrou ou faltou, conte o que houve"}),
    )

    def __init__(self, *args, online=False, **kwargs):
        super().__init__(*args, **kwargs)
        if online:
            # O caixa online só recebe Pix: não há gaveta para contar, a conferência é com o extrato.
            del self.fields["saldo_conferido"]
            self.fields["observacao"].widget.attrs[
                "placeholder"
            ] = "Ex.: conferido com o extrato do dia 03/11"


class ReverseEntryForm(StyledFormMixin, forms.Form):
    motivo = forms.CharField(
        label="Motivo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: lançado errado, devolvido ao cliente"}),
    )


class ReceiveForm(StyledFormMixin, forms.Form):
    valor = money_field(label="Valor")
    forma = forma_field()
    recebido = money_field(label="Valor recebido", required=False)


class ChargeReservationForm(StyledFormMixin, forms.Form):
    valor = money_field(label="Valor da reserva", required=False)
    incluir_comanda = forms.BooleanField(label="Incluir a comanda", required=False)
    forma = forma_field()
    recebido = money_field(label="Valor recebido", required=False)


class PayBillForm(StyledFormMixin, forms.Form):
    forma = forma_field()
    do_caixa = forms.BooleanField(
        label="Saiu do meu caixa",
        required=False,
        help_text="Desligue se foi pago pelo banco: a conta baixa, mas não mexe no caixa.",
    )


class CancelAccountForm(StyledFormMixin, forms.Form):
    parar_repeticao = forms.BooleanField(label="Parar de repetir esta conta", required=False)


class ContaFormMixin(StyledFormMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vencimento"].widget = forms.DateInput(
            attrs={"type": "date", "class": "input"}, format="%Y-%m-%d"
        )
        if not self.instance.pk:
            self.fields["vencimento"].initial = timezone.localdate()
        # Repetição se define na conta que deu origem à série.
        if self.instance.recorrencia_origem_id:
            del self.fields["recorrencia"]


class ContaPagarForm(ContaFormMixin, forms.ModelForm):
    valor = money_field(label="Valor")
    categoria = forms.ChoiceField(label="Categoria", choices=[(c.value, c.label) for c in CATEGORIAS_PAGAR])

    class Meta:
        model = ContaPagar
        fields = ["descricao", "fornecedor", "categoria", "valor", "vencimento", "recorrencia", "observacoes"]
        widgets = {
            "descricao": forms.TextInput(
                attrs={"placeholder": "Ex.: Aluguel do ponto", "autocomplete": "off"}
            ),
            "recorrencia": forms.RadioSelect,
            "observacoes": forms.Textarea(attrs={"rows": 2}),
        }


class ContaReceberForm(ContaFormMixin, TenantFormMixin, forms.ModelForm):
    valor = money_field(label="Valor")
    categoria = forms.ChoiceField(label="Categoria", choices=[(c.value, c.label) for c in CATEGORIAS_RECEBER])
    cliente = forms.ModelChoiceField(
        label="Cliente", queryset=Cliente.objects.none(), required=False, empty_label="Sem cliente"
    )

    class Meta:
        model = ContaReceber
        fields = ["descricao", "cliente", "categoria", "valor", "vencimento", "recorrencia", "observacoes"]
        widgets = {
            "descricao": forms.TextInput(
                attrs={"placeholder": "Ex.: Aluguel para evento", "autocomplete": "off"}
            ),
            "recorrencia": forms.RadioSelect,
            "observacoes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(anonimizado_em__isnull=True)
