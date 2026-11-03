from django import forms

from apps.espacos.forms import money_field
from apps.estabelecimentos.forms import StyledFormMixin

from .models import Produto


class ProdutoForm(StyledFormMixin, forms.ModelForm):
    preco_venda = money_field(label="Preço de venda")
    custo = money_field(label="Custo", required=False)
    estoque_inicial = forms.IntegerField(
        label="Estoque inicial",
        min_value=0,
        required=False,
        help_text="Quanto você tem agora. Depois, o saldo muda só pelas movimentações.",
    )

    class Meta:
        model = Produto
        fields = [
            "nome",
            "categoria",
            "preco_venda",
            "custo",
            "controla_estoque",
            "estoque_minimo",
            "codigo",
            "ativo",
        ]
        widgets = {
            "categoria": forms.RadioSelect,
            "nome": forms.TextInput(attrs={"placeholder": "Ex.: Água 500 ml", "autocomplete": "off"}),
            "codigo": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["estoque_inicial"]

    # O estabelecimento fica fora do form, então o Django não valida estas constraints sozinho.
    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip()
        if Produto.objects.filter(nome__iexact=nome).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe um produto com esse nome.")
        return nome

    def clean_codigo(self):
        codigo = self.cleaned_data["codigo"].strip()
        if codigo and Produto.objects.filter(codigo=codigo).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe um produto com esse código.")
        return codigo


class MovimentacaoForm(StyledFormMixin, forms.Form):
    ENTRADA, PERDA, CONTAGEM = "ENTRADA", "PERDA", "AJUSTE"

    tipo = forms.ChoiceField(
        label="O que aconteceu",
        choices=[(ENTRADA, "Comprei"), (PERDA, "Perdi"), (CONTAGEM, "Contei")],
        widget=forms.RadioSelect,
        initial=ENTRADA,
    )
    quantidade = forms.IntegerField(
        label="Quantidade",
        min_value=0,
        max_value=100000,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    custo = money_field(label="Custo por unidade", required=False)
    observacao = forms.CharField(
        label="Observação",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: nota 123, garrafa quebrada"}),
    )
    gerar_conta = forms.BooleanField(label="Lançar em contas a pagar", required=False)
    fornecedor = forms.CharField(label="Fornecedor", max_length=120, required=False)
    vencimento = forms.DateField(
        label="Vencimento",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("tipo") != self.CONTAGEM and cleaned.get("quantidade") == 0:
            self.add_error("quantidade", "Informe uma quantidade maior que zero.")
        if cleaned.get("tipo") == self.ENTRADA and cleaned.get("gerar_conta"):
            if not cleaned.get("custo"):
                self.add_error("custo", "Informe o custo para calcular o valor da conta.")
            if not cleaned.get("vencimento"):
                self.add_error("vencimento", "Informe quando a conta vence.")
        return cleaned
