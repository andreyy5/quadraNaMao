from django.urls import path

from . import views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.LoginView.as_view(), name="login"),
    path("sair/", views.LogoutView.as_view(), name="logout"),
    path("senha/", views.SenhaChangeView.as_view(), name="senha"),
    path("equipe/", views.EquipeListView.as_view(), name="equipe"),
    path("equipe/nova/", views.EquipeCreateView.as_view(), name="equipe_create"),
    path("equipe/<int:pk>/", views.EquipeUpdateView.as_view(), name="equipe_update"),
]
