from django.urls import path

from . import views

app_name = "espacos"

urlpatterns = [
    path("", views.EspacoListView.as_view(), name="list"),
    path("novo/", views.EspacoCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EspacoUpdateView.as_view(), name="update"),
    path("<int:espaco_pk>/horarios/", views.HorarioSemanaView.as_view(), name="horarios"),
    path("<int:espaco_pk>/precos/", views.TabelaPrecoListView.as_view(), name="precos"),
    path("<int:espaco_pk>/precos/novo/", views.TabelaPrecoCreateView.as_view(), name="preco_create"),
    path("<int:espaco_pk>/precos/<int:pk>/", views.TabelaPrecoUpdateView.as_view(), name="preco_update"),
    path(
        "<int:espaco_pk>/precos/<int:pk>/remover/", views.TabelaPrecoDeleteView.as_view(), name="preco_delete"
    ),
]
