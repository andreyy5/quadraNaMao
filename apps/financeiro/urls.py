from django.urls import path

from . import views
from .forms import ContaPagarForm, ContaReceberForm
from .models import ContaPagar, ContaReceber

app_name = "financeiro"

receber = {"model": ContaReceber, "kind": "receber"}
pagar = {"model": ContaPagar, "kind": "pagar"}
receber_form = {**receber, "form_class": ContaReceberForm}
pagar_form = {**pagar, "form_class": ContaPagarForm}

urlpatterns = [
    path("", views.CaixaView.as_view(), name="caixa"),
    path("abrir/", views.AbrirCaixaView.as_view(), name="abrir"),
    path("movimento/", views.MovimentoCaixaView.as_view(), name="movimento"),
    path("caixas/", views.CaixaListView.as_view(), name="caixas"),
    path("caixas/<int:pk>/", views.CaixaDetailView.as_view(), name="caixa_detail"),
    path("caixas/<int:pk>/fechar/", views.FecharCaixaView.as_view(), name="fechar"),
    path("lancamentos/<int:pk>/estornar/", views.EstornarView.as_view(), name="estornar"),
    path("reservas/<int:pk>/receber/", views.ReceberReservaView.as_view(), name="receber_reserva"),
    path("receber/", views.ContaListView.as_view(**receber), name="receber"),
    path("receber/nova/", views.ContaCreateView.as_view(**receber_form), name="receber_create"),
    path("receber/<int:pk>/editar/", views.ContaUpdateView.as_view(**receber_form), name="receber_update"),
    path("receber/<int:pk>/baixa/", views.ReceberContaView.as_view(), name="receber_baixa"),
    path("receber/<int:pk>/cancelar/", views.CancelarContaView.as_view(**receber), name="receber_cancel"),
    path("pagar/", views.ContaListView.as_view(**pagar), name="pagar"),
    path("pagar/nova/", views.ContaCreateView.as_view(**pagar_form), name="pagar_create"),
    path("pagar/<int:pk>/editar/", views.ContaUpdateView.as_view(**pagar_form), name="pagar_update"),
    path("pagar/<int:pk>/baixa/", views.PagarContaView.as_view(), name="pagar_baixa"),
    path("pagar/<int:pk>/cancelar/", views.CancelarContaView.as_view(**pagar), name="pagar_cancel"),
]
