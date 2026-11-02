from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("conta/", include("apps.contas.urls")),
    path("ajustes/", include("apps.estabelecimentos.urls")),
    path("espacos/", include("apps.espacos.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("agenda/", include("apps.agenda.urls")),
    path("pdv/", include("apps.pdv.urls")),
    path("estoque/", include("apps.estoque.urls")),
    path("", include("apps.relatorios.urls")),
]

admin.site.site_header = "QuadraNaMão! — Administração"
admin.site.site_title = "QuadraNaMão!"
