from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("", views.ConversasView.as_view(), name="conversas"),
    path("webhook/", views.WebhookView.as_view(), name="webhook"),
    path("<str:telefone>/", views.ConversaView.as_view(), name="conversa"),
]
