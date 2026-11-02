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
