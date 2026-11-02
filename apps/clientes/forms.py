from django import forms

from apps.estabelecimentos.forms import StyledFormMixin

from .models import Cliente
from .services import InvalidPhone, normalize_phone


class ClienteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "telefone", "email", "observacoes", "aceite_whatsapp"]
        help_texts = {"telefone": ""}
        widgets = {
            "nome": forms.TextInput(
                attrs={"placeholder": "Nome da pessoa ou do grupo", "autocomplete": "off"}
            ),
            "telefone": forms.TextInput(
                attrs={
                    "inputmode": "tel",
                    "autocomplete": "off",
                    "placeholder": "(11) 98888-7777",
                    "data-mask": "phone",
                }
            ),
            "email": forms.EmailInput(attrs={"placeholder": "nome@email.com", "autocomplete": "off"}),
            "observacoes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Preferências, combinados, recados"}
            ),
        }

    def clean_telefone(self):
        try:
            telefone = normalize_phone(self.cleaned_data["telefone"])
        except InvalidPhone as exc:
            raise forms.ValidationError(str(exc)) from exc
        # O estabelecimento fica fora do form, então o Django não valida essa constraint sozinho.
        if Cliente.objects.filter(telefone=telefone).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe um cliente com esse telefone.")
        return telefone
