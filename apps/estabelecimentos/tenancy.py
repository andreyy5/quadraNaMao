"""Isolamento por linha: o estabelecimento atual vale para todo o ciclo da requisição."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_current_tenant = ContextVar("current_tenant", default=None)


def get_current_tenant():
    return _current_tenant.get()


def set_current_tenant(tenant):
    return _current_tenant.set(tenant)


def reset_current_tenant(token):
    _current_tenant.reset(token)


@contextmanager
def tenant_context(tenant):
    token = set_current_tenant(tenant)
    try:
        yield
    finally:
        reset_current_tenant(token)


class TenantManager(models.Manager):
    """Filtra pelo estabelecimento atual e falha fechado: sem tenant, não devolve nada."""

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is None:
            return queryset.none()
        return queryset.filter(estabelecimento=tenant)
