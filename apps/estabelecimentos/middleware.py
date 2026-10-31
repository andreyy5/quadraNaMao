from django.utils import timezone

from .tenancy import reset_current_tenant, set_current_tenant


class TenantMiddleware:
    """Define o estabelecimento e o fuso da requisição a partir do usuário logado."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None
        if request.user.is_authenticated:
            candidate = request.user.estabelecimento
            if candidate is not None and candidate.ativo:
                tenant = candidate
        request.tenant = tenant

        token = set_current_tenant(tenant)
        if tenant is not None:
            timezone.activate(tenant.timezone)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
            reset_current_tenant(token)
