from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.estabelecimentos.models import TenantModel


class Mensagem(TenantModel):
    """Histórico de tudo o que foi enviado e recebido, com o status de entrega de cada mensagem."""

    class Direcao(models.TextChoices):
        SAIDA = "SAIDA", "Enviada"
        ENTRADA = "ENTRADA", "Recebida"

    class Tipo(models.TextChoices):
        TEMPLATE = "TEMPLATE", "Modelo aprovado"
        TEXTO = "TEXTO", "Texto livre"

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Na fila"
        ENVIADA = "ENVIADA", "Enviada"
        ENTREGUE = "ENTREGUE", "Entregue"
        LIDA = "LIDA", "Lida"
        FALHOU = "FALHOU", "Falhou"
        RECEBIDA = "RECEBIDA", "Recebida"

    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensagens",
        verbose_name="cliente",
    )
    telefone = models.CharField("telefone", max_length=32)
    direcao = models.CharField("direção", max_length=7, choices=Direcao.choices)
    tipo = models.CharField("tipo", max_length=8, choices=Tipo.choices, default=Tipo.TEXTO)
    template = models.CharField("modelo", max_length=60, blank=True)
    corpo = models.TextField("texto", blank=True)
    parametros = models.JSONField("parâmetros do modelo", default=list, blank=True)
    status = models.CharField("status", max_length=8, choices=Status.choices, default=Status.PENDENTE)
    wa_id = models.CharField("identificador no WhatsApp", max_length=128, blank=True)
    erro = models.CharField("erro", max_length=300, blank=True)
    reserva = models.ForeignKey(
        "agenda.Reserva",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensagens",
        verbose_name="reserva",
    )
    enviada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="enviada por",
    )

    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["criado_em", "pk"]
        indexes = [
            models.Index(fields=["estabelecimento", "telefone", "criado_em"], name="mensagem_conversa")
        ]
        constraints = [
            # O webhook pode chegar repetido: a mesma mensagem não entra duas vezes.
            models.UniqueConstraint(fields=["wa_id"], condition=~Q(wa_id=""), name="mensagem_wa_id_unico"),
        ]

    def __str__(self):
        return f"{self.get_direcao_display()} {self.telefone}"

    @property
    def is_outgoing(self):
        return self.direcao == self.Direcao.SAIDA
