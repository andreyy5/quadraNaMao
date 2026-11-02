from zoneinfo import ZoneInfo

from django.db import models

from .tenancy import TenantManager

FUSOS_HORARIOS = [
    ("America/Sao_Paulo", "Brasília (GMT-3)"),
    ("America/Manaus", "Amazonas (GMT-4)"),
    ("America/Cuiaba", "Mato Grosso (GMT-4)"),
    ("America/Campo_Grande", "Mato Grosso do Sul (GMT-4)"),
    ("America/Porto_Velho", "Rondônia (GMT-4)"),
    ("America/Boa_Vista", "Roraima (GMT-4)"),
    ("America/Rio_Branco", "Acre (GMT-5)"),
    ("America/Noronha", "Fernando de Noronha (GMT-2)"),
]


class Estabelecimento(models.Model):
    nome = models.CharField("nome", max_length=120)
    slug = models.SlugField("slug", max_length=120, unique=True)
    documento = models.CharField("CNPJ ou CPF", max_length=18, blank=True)
    telefone = models.CharField("telefone", max_length=20, blank=True)
    endereco = models.CharField("endereço", max_length=200, blank=True)
    fuso_horario = models.CharField(
        "fuso horário", max_length=40, choices=FUSOS_HORARIOS, default="America/Sao_Paulo"
    )
    permite_estoque_negativo = models.BooleanField(
        "vender mesmo sem estoque",
        default=False,
        help_text="Ligado, o PDV deixa vender o que está zerado no sistema. Bom se o estoque não for contado sempre.",
    )
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "estabelecimento"
        verbose_name_plural = "estabelecimentos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def timezone(self):
        return ZoneInfo(self.fuso_horario)


class TenantModel(models.Model):
    """Base de todo model de negócio.

    `objects` só enxerga o estabelecimento atual. `all_tenants` é a saída explícita para
    serviços, comandos e testes, que então precisam filtrar por conta própria.
    """

    estabelecimento = models.ForeignKey(
        Estabelecimento, on_delete=models.CASCADE, related_name="+", verbose_name="estabelecimento"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_tenants = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True
