from django.urls import path

from .views import EstabelecimentoUpdateView, ReservasOnlineView, WhatsAppAjustesView

app_name = "estabelecimentos"

urlpatterns = [
    path("", EstabelecimentoUpdateView.as_view(), name="ajustes"),
    path("reservas-online/", ReservasOnlineView.as_view(), name="reservas_online"),
    path("whatsapp/", WhatsAppAjustesView.as_view(), name="whatsapp"),
]
