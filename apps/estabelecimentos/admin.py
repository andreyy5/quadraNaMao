from django.contrib import admin

from .models import Estabelecimento


@admin.register(Estabelecimento)
class EstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ["nome", "slug", "telefone", "ativo", "criado_em"]
    list_filter = ["ativo"]
    search_fields = ["nome", "slug", "documento"]
    prepopulated_fields = {"slug": ["nome"]}
