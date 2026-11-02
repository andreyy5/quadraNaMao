from django.urls import path

from . import views

app_name = "estoque"

urlpatterns = [
    path("", views.ProdutoListView.as_view(), name="list"),
    path("novo/", views.ProdutoCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProdutoDetailView.as_view(), name="detail"),
    path("<int:pk>/editar/", views.ProdutoUpdateView.as_view(), name="update"),
    path("<int:pk>/movimentar/", views.MovimentarView.as_view(), name="movimentar"),
]
