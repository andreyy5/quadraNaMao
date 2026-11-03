from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("relatorios/", views.RelatorioView.as_view(), name="relatorio"),
]
