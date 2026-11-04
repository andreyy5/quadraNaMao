from django.conf import settings


def product(request):
    return {"PRODUCT_NAME": settings.PRODUCT_NAME, "WHATSAPP_ENABLED": settings.WHATSAPP_ENABLED}
