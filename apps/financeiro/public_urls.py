from django.urls import path

from . import public_views as views

app_name = "cobranca"

urlpatterns = [
    path("<slug:slug>/conta/<str:token>/", views.ContaPublicaView.as_view(), name="conta"),
]
