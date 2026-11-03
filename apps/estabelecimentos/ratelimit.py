"""Limite de tentativas por janela de tempo, guardado no cache do Django.

Em produção com mais de um processo, configure um cache compartilhado (Redis) em `CACHE_URL`:
com o cache em memória, cada processo conta separado.
"""

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    """IP de quem fez o pedido. Atrás de proxy, vem do X-Forwarded-For, contando só os proxies confiáveis.

    Cada proxy acrescenta à direita o IP de quem falou com ele; o que o cliente manda fica à esquerda e
    pode ser inventado. Por isso o IP certo é o que está `NUM_PROXIES` posições a partir da direita.
    """
    hops = getattr(settings, "NUM_PROXIES", 0)
    if hops:
        forwarded = [
            ip.strip() for ip in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if ip.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.META.get("REMOTE_ADDR", "")


def is_limited(key, limit):
    return (cache.get(key) or 0) >= limit


def hit(key, window):
    """Conta mais uma tentativa. A janela começa na primeira tentativa."""
    if cache.add(key, 1, window):
        return
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)


def allow(key, limit, window):
    """Conta a tentativa e diz se ela ainda está dentro do limite."""
    if is_limited(key, limit):
        return False
    hit(key, window)
    return True
