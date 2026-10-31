from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.estabelecimentos.mixins import TenantRequiredMixin

from .forms import LoginForm, MembroEquipeCreateForm, MembroEquipeUpdateForm, SenhaForm
from .mixins import OwnerRequiredMixin
from .models import Usuario


class LoginView(auth_views.LoginView):
    template_name = "contas/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


class SenhaChangeView(TenantRequiredMixin, auth_views.PasswordChangeView):
    template_name = "contas/senha_form.html"
    form_class = SenhaForm
    success_url = reverse_lazy("estabelecimentos:ajustes")

    def get_success_url(self):
        if self.request.user.is_owner:
            return super().get_success_url()
        return reverse_lazy("relatorios:dashboard")

    def form_valid(self, form):
        messages.success(self.request, "Senha alterada.")
        return super().form_valid(form)


class EquipeQuerysetMixin(OwnerRequiredMixin):
    """Usuario não é TenantModel: o filtro por estabelecimento é feito aqui."""

    model = Usuario

    def get_queryset(self):
        return Usuario.objects.filter(estabelecimento=self.request.tenant)


class EquipeListView(EquipeQuerysetMixin, ListView):
    template_name = "contas/equipe_list.html"
    context_object_name = "membros"


class EquipeCreateView(OwnerRequiredMixin, CreateView):
    form_class = MembroEquipeCreateForm
    template_name = "contas/equipe_form.html"
    success_url = reverse_lazy("contas:equipe")

    def form_valid(self, form):
        form.instance.estabelecimento = self.request.tenant
        messages.success(self.request, "Pessoa adicionada à equipe.")
        return super().form_valid(form)


class EquipeUpdateView(EquipeQuerysetMixin, UpdateView):
    form_class = MembroEquipeUpdateForm
    template_name = "contas/equipe_form.html"
    success_url = reverse_lazy("contas:equipe")
    context_object_name = "membro"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["current_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Dados salvos.")
        return super().form_valid(form)
