from django.urls import path

from . import views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.LoginView.as_view(), name="login"),
    path("sair/", views.LogoutView.as_view(), name="logout"),
    path("senha/", views.SenhaChangeView.as_view(), name="senha"),
    path("senha/esqueci/", views.SenhaEsqueciView.as_view(), name="senha_esqueci"),
    path("senha/esqueci/enviado/", views.SenhaEnviadaView.as_view(), name="senha_enviada"),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        views.SenhaRedefinirView.as_view(),
        name="senha_redefinir",
    ),
    path("equipe/", views.EquipeListView.as_view(), name="equipe"),
    path("equipe/nova/", views.EquipeCreateView.as_view(), name="equipe_create"),
    path("equipe/<int:pk>/", views.EquipeUpdateView.as_view(), name="equipe_update"),
]
