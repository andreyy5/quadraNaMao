from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("relatorios/", views.RelatorioView.as_view(), name="relatorio"),
    path("relatorios/fluxo-de-caixa/", views.FluxoView.as_view(), name="fluxo"),
    path("relatorios/reservas/", views.ReservasReportView.as_view(), name="reservas"),
    path("relatorios/clientes/", views.ClientesReportView.as_view(), name="clientes"),
    path("relatorios/vendas/", views.VendasReportView.as_view(), name="vendas"),
    path("relatorios/caixas/", views.CaixasReportView.as_view(), name="caixas"),
]
