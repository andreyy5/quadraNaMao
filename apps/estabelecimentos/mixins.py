import json

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.forms import ModelChoiceField
from django.http import HttpResponse
from django.shortcuts import redirect

from .models import TenantModel


class TenantRequiredMixin(AccessMixin):
    """Exige login e um estabelecimento ativo. É a base de todas as telas do painel."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.tenant is None:
            if request.user.is_superuser:
                return redirect("admin:index")
            logout(request)
            messages.error(request, "Seu acesso está inativo. Fale com o responsável pelo estabelecimento.")
            return redirect("contas:login")
        return super().dispatch(request, *args, **kwargs)


class TenantFormMixin:
    """Refaz, a cada instância, as opções dos campos de relacionamento.

    Os campos são criados ao importar o módulo, quando ainda não há tenant, e o
    queryset daquele momento ficaria vazio. Aqui ele é recriado dentro da requisição.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, ModelChoiceField) and issubclass(field.queryset.model, TenantModel):
                field.queryset = field.queryset.model.objects.all()


class TenantCreateMixin:
    """Grava o estabelecimento atual em objetos criados por CreateView."""

    def form_valid(self, form):
        form.instance.estabelecimento = self.request.tenant
        return super().form_valid(form)


class ModalResponseMixin:
    """Tela que abre em painel via HTMX e também funciona como página comum.

    Com HTMX devolve só o conteúdo do painel; sem HTMX, o mesmo conteúdo dentro do layout.
    """

    modal_template_name = None
    page_template_name = "components/modal_page.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return [self.modal_template_name]
        return [self.page_template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modal_template"] = self.modal_template_name
        return context

    def modal_success(self, message, fallback_url, changed=True):
        """Fecha o painel e avisa a página. Sem HTMX, redireciona com a mesma mensagem."""
        if not self.request.headers.get("HX-Request"):
            messages.success(self.request, message)
            return redirect(fallback_url)
        # O fechamento vem por último: ele remove do DOM o elemento que dispara os eventos.
        events = {"toast": {"message": message}}
        if changed:
            events["data:changed"] = True
        events["modal:close"] = True
        return HttpResponse(status=204, headers={"HX-Trigger": json.dumps(events)})

    def modal_redirect(self, message, url):
        """Fecha o painel levando a outra página, com ou sem HTMX."""
        messages.success(self.request, message)
        if self.request.headers.get("HX-Request"):
            return HttpResponse(headers={"HX-Redirect": str(url)})
        return redirect(url)


class RoleRequiredMixin(TenantRequiredMixin):
    """Restringe a tela aos papéis listados em `allowed_roles`."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.tenant is not None:
            if request.user.papel not in self.allowed_roles:
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
