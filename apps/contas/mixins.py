from apps.estabelecimentos.mixins import RoleRequiredMixin

from .models import Usuario


class OwnerRequiredMixin(RoleRequiredMixin):
    """Telas de configuração: espaços, preços, estabelecimento e equipe."""

    allowed_roles = (Usuario.Papel.DONO,)
