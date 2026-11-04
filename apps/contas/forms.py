from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.contrib.auth.password_validation import validate_password
from django.template import loader

from apps.estabelecimentos.forms import StyledFormMixin

from .models import Usuario


class LoginForm(StyledFormMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "E-mail ou senha incorretos. Confira e tente de novo.",
        "inactive": "Este acesso está inativo.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "E-mail"
        self.fields["username"].widget.attrs.update({"autocomplete": "email", "inputmode": "email"})

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class SenhaForm(StyledFormMixin, PasswordChangeForm):
    pass


class SenhaEsqueciForm(StyledFormMixin, PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "E-mail"
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "inputmode": "email", "data-autofocus": "true"}
        )

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        """Monta o e-mail aqui e deixa o envio para o Celery (ver tasks.send_email)."""
        from .tasks import send_email

        subject = "".join(loader.render_to_string(subject_template_name, context).splitlines())
        body = loader.render_to_string(email_template_name, context)
        html = (
            loader.render_to_string(html_email_template_name, context) if html_email_template_name else None
        )
        send_email.delay(subject, body, from_email, [to_email], html)


class SenhaNovaForm(StyledFormMixin, SetPasswordForm):
    pass


class MembroEquipeCreateForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(
        label="Senha inicial",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="A pessoa pode trocar depois de entrar.",
    )

    class Meta:
        model = Usuario
        fields = ["nome", "email", "papel"]
        widgets = {"papel": forms.RadioSelect}

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class MembroEquipeUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["nome", "papel", "is_active"]
        widgets = {"papel": forms.RadioSelect}
        labels = {"is_active": "Acesso ativo"}

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def clean(self):
        cleaned = super().clean()
        if self.instance == self.current_user:
            if not cleaned.get("is_active", True):
                self.add_error("is_active", "Você não pode desativar o próprio acesso.")
            if cleaned.get("papel") != Usuario.Papel.DONO:
                self.add_error("papel", "Você não pode retirar o próprio perfil de dono.")
        return cleaned
