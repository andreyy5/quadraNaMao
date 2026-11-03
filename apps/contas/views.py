from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.estabelecimentos.mixins import TenantRequiredMixin
from apps.estabelecimentos.ratelimit import client_ip, hit, is_limited

from .forms import LoginForm, MembroEquipeCreateForm, MembroEquipeUpdateForm, SenhaForm
from .mixins import OwnerRequiredMixin
from .models import Usuario

LOGIN_LIMIT = 5
LOGIN_IP_LIMIT = 30
LOGIN_WINDOW = 15 * 60


class LoginView(auth_views.LoginView):
    """Depois de 5 senhas erradas para o mesmo e-mail, ou 30 do mesmo endereço, espera 15 minutos."""

    template_name = "contas/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _keys(self):
        ip = client_ip(self.request)
        email = self.request.POST.get("username", "").strip().lower()
        return f"login:{ip}:{email}", f"login-ip:{ip}"

    def post(self, request, *args, **kwargs):
        user_key, ip_key = self._keys()
        if is_limited(user_key, LOGIN_LIMIT) or is_limited(ip_key, LOGIN_IP_LIMIT):
            form = self.get_form()
            form.add_error(None, "Muitas tentativas seguidas. Espere 15 minutos e tente de novo.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        user_key, ip_key = self._keys()
        hit(user_key, LOGIN_WINDOW)
        hit(ip_key, LOGIN_WINDOW)
        return super().form_invalid(form)


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
