from django.db import models

from apps.estabelecimentos.models import TenantModel


class Cliente(TenantModel):
    nome = models.CharField("nome", max_length=120)
    telefone = models.CharField("WhatsApp", max_length=32, help_text="Com DDD. Ex.: (11) 98888-7777")
    email = models.EmailField("e-mail", blank=True)
    observacoes = models.TextField("observações", blank=True)
    aceite_whatsapp = models.BooleanField("Aceita receber mensagens pelo WhatsApp", default=False)
    anonimizado_em = models.DateTimeField("anonimizado em", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["estabelecimento", "telefone"], name="cliente_telefone_unico_por_estabelecimento"
            ),
        ]

    def __str__(self):
        return self.nome
