from django.urls import path

from . import public_views as views

app_name = "publico"

urlpatterns = [
    path("<slug:slug>/", views.ReservarView.as_view(), name="reservar"),
    path("<slug:slug>/confirmada/", views.ConfirmadaView.as_view(), name="confirmada"),
    path("<slug:slug>/pagamento/<str:token>/", views.PagamentoView.as_view(), name="pagamento"),
    path("<slug:slug>/pagamento/<str:token>/simular/", views.SimularPagamentoView.as_view(), name="simular"),
]
