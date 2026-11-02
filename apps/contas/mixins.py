from apps.estabelecimentos.mixins import RoleRequiredMixin

from .models import Usuario


class OwnerRequiredMixin(RoleRequiredMixin):
    """Telas de configuração: espaços, preços, estabelecimento e equipe."""

    allowed_roles = (Usuario.Papel.DONO,)


class ManagerRequiredMixin(RoleRequiredMixin):
    """Telas de gestão do dia a dia, como o estoque."""

    allowed_roles = (Usuario.Papel.DONO, Usuario.Papel.GERENTE)
