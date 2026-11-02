from django.urls import path

from . import views

app_name = "pdv"

urlpatterns = [
    path("", views.PdvView.as_view(), name="home"),
    path("finalizar/", views.FinalizarView.as_view(), name="finalizar"),
    path("vendas/", views.VendaListView.as_view(), name="vendas"),
    path("comandas/", views.ComandaListView.as_view(), name="comandas"),
    path("vendas/<int:pk>/", views.VendaDetailView.as_view(), name="venda_detail"),
    path("vendas/<int:pk>/receber/", views.ReceberComandaView.as_view(), name="receber"),
    path("vendas/<int:pk>/cancelar/", views.CancelarVendaView.as_view(), name="cancelar"),
    path("itens/<int:pk>/remover/", views.RemoverItemView.as_view(), name="remover_item"),
]
