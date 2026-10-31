from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q

from apps.estabelecimentos.models import TenantModel

CONFLICT_CONSTRAINT = "reserva_sem_sobreposicao"


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Reserva(TenantModel):
    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        CANCELADA = "CANCELADA", "Cancelada"
        CONCLUIDA = "CONCLUIDA", "Concluída"
        NAO_COMPARECEU = "NAO_COMPARECEU", "Não compareceu"

    class Origem(models.TextChoices):
        PAINEL = "PAINEL", "Painel"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        IA = "IA", "Agente de IA"
        MENSALISTA = "MENSALISTA", "Mensalista"

    espaco = models.ForeignKey(
        "espacos.Espaco", on_delete=models.PROTECT, related_name="reservas", verbose_name="espaço"
    )
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="reservas", verbose_name="cliente"
    )
    inicio = models.DateTimeField("início")
    fim = models.DateTimeField("fim")
    status = models.CharField("status", max_length=16, choices=Status.choices, default=Status.CONFIRMADA)
    origem = models.CharField("origem", max_length=12, choices=Origem.choices, default=Origem.PAINEL)
    valor_total = models.DecimalField("valor total", max_digits=9, decimal_places=2, default=0)
    valor_pago = models.DecimalField("valor pago", max_digits=9, decimal_places=2, default=0)
    observacoes = models.TextField("observações", blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="criada por",
    )

    class Meta:
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["inicio"]
        indexes = [models.Index(fields=["espaco", "inicio"], name="reserva_espaco_inicio_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(fim__gt=F("inicio")), name="reserva_fim_depois_do_inicio"),
            # A garantia contra reserva duplicada: [inicio, fim) não se sobrepõe no mesmo espaço.
            ExclusionConstraint(
                name=CONFLICT_CONSTRAINT,
                expressions=[
                    (TsTzRange("inicio", "fim", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("espaco", RangeOperators.EQUAL),
                ],
                condition=~Q(status="CANCELADA"),
            ),
        ]

    def __str__(self):
        return f"{self.espaco} · {self.inicio:%d/%m %H:%M}"

    @property
    def is_open(self):
        return self.status in (self.Status.PENDENTE, self.Status.CONFIRMADA)


class Bloqueio(TenantModel):
    class Motivo(models.TextChoices):
        CHUVA = "CHUVA", "Chuva"
        MANUTENCAO = "MANUTENCAO", "Manutenção"
        EVENTO = "EVENTO", "Evento"
        OUTRO = "OUTRO", "Outro"

    espaco = models.ForeignKey(
        "espacos.Espaco", on_delete=models.CASCADE, related_name="bloqueios", verbose_name="espaço"
    )
    inicio = models.DateTimeField("início")
    fim = models.DateTimeField("fim")
    motivo = models.CharField("motivo", max_length=12, choices=Motivo.choices, default=Motivo.CHUVA)
    descricao = models.CharField("observação", max_length=200, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="criado por",
    )

    class Meta:
        verbose_name = "bloqueio"
        verbose_name_plural = "bloqueios"
        ordering = ["inicio"]
        indexes = [models.Index(fields=["espaco", "inicio"], name="bloqueio_espaco_inicio_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(fim__gt=F("inicio")), name="bloqueio_fim_depois_do_inicio"),
        ]

    def __str__(self):
        return f"{self.espaco} · {self.get_motivo_display()}"


class ReservaEvento(TenantModel):
    """Auditoria: quem criou, alterou ou cancelou cada reserva."""

    class Acao(models.TextChoices):
        CRIADA = "CRIADA", "Criada"
        ALTERADA = "ALTERADA", "Alterada"
        CANCELADA = "CANCELADA", "Cancelada"
        CONCLUIDA = "CONCLUIDA", "Concluída"
        NAO_COMPARECEU = "NAO_COMPARECEU", "Não compareceu"

    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE, related_name="eventos", verbose_name="reserva"
    )
    acao = models.CharField("ação", max_length=16, choices=Acao.choices)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="usuário",
    )
    detalhes = models.CharField("detalhes", max_length=240, blank=True)

    class Meta:
        verbose_name = "evento da reserva"
        verbose_name_plural = "eventos da reserva"
        ordering = ["-criado_em", "-pk"]

    def __str__(self):
        return f"{self.reserva_id}: {self.get_acao_display()}"
