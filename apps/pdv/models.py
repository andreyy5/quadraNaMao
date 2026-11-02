from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.estabelecimentos.models import TenantModel


class Venda(TenantModel):
    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Comanda aberta"
        CONCLUIDA = "CONCLUIDA", "Concluída"
        CANCELADA = "CANCELADA", "Cancelada"

    class Forma(models.TextChoices):
        PIX = "PIX", "Pix"
        DINHEIRO = "DINHEIRO", "Dinheiro"
        CARTAO_DEBITO = "CARTAO_DEBITO", "Débito"
        CARTAO_CREDITO = "CARTAO_CREDITO", "Crédito"
        OUTRO = "OUTRO", "Outro"

    numero = models.PositiveIntegerField("número")
    status = models.CharField("status", max_length=10, choices=Status.choices, default=Status.CONCLUIDA)
    forma_pagamento = models.CharField("forma de pagamento", max_length=14, choices=Forma.choices, blank=True)
    total = models.DecimalField("total", max_digits=9, decimal_places=2, default=0)
    valor_recebido = models.DecimalField(
        "valor recebido", max_digits=9, decimal_places=2, null=True, blank=True
    )
    reserva = models.ForeignKey(
        "agenda.Reserva",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendas",
        verbose_name="reserva",
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendas",
        verbose_name="cliente",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="vendido por",
    )
    concluida_em = models.DateTimeField("concluída em", null=True, blank=True)
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True)
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="cancelada por",
    )
    motivo_cancelamento = models.CharField("motivo do cancelamento", max_length=200, blank=True)

    class Meta:
        verbose_name = "venda"
        verbose_name_plural = "vendas"
        ordering = ["-concluida_em", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["estabelecimento", "numero"], name="venda_numero_unico"),
            models.UniqueConstraint(
                fields=["reserva"], condition=Q(status="ABERTA"), name="uma_comanda_aberta_por_reserva"
            ),
        ]
        indexes = [models.Index(fields=["estabelecimento", "concluida_em"], name="venda_estab_conclusao")]

    def __str__(self):
        return f"Venda #{self.numero}"

    @property
    def is_tab(self):
        return self.status == self.Status.ABERTA

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELADA

    @property
    def troco(self):
        if self.valor_recebido is None or self.valor_recebido <= self.total:
            return None
        return self.valor_recebido - self.total


class ItemVenda(TenantModel):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="itens", verbose_name="venda")
    produto = models.ForeignKey(
        "estoque.Produto", on_delete=models.PROTECT, related_name="itens_venda", verbose_name="produto"
    )
    quantidade = models.PositiveIntegerField("quantidade")
    preco_unitario = models.DecimalField("preço unitário", max_digits=9, decimal_places=2)

    class Meta:
        verbose_name = "item de venda"
        verbose_name_plural = "itens de venda"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.quantidade}x {self.produto}"

    @property
    def subtotal(self):
        return self.quantidade * self.preco_unitario
