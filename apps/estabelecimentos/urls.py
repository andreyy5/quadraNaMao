from django.urls import path

from .views import EstabelecimentoUpdateView

app_name = "estabelecimentos"

urlpatterns = [
    path("", EstabelecimentoUpdateView.as_view(), name="ajustes"),
]
