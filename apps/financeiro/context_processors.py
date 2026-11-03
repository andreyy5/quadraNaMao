from .services import current_register


def open_register(request):
    """Caixa aberto de quem está usando, para o menu e para o PDV saberem se dá para receber."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or getattr(request, "tenant", None) is None:
        return {}
    return {"caixa_aberto": current_register(user)}
