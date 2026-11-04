from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q

from apps.estabelecimentos.models import TenantModel

# Mesma numeração de date.weekday() e de espacos.DiaSemana: segunda é 0.
DIAS_SEMANA = [
    (0, "Segunda"),
    (1, "Terça"),
    (2, "Quarta"),
    (3, "Quinta"),
    (4, "Sexta"),
    (5, "Sábado"),
    (6, "Domingo"),
]

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
        ONLINE = "ONLINE", "Link público"

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
    valor_sinal = models.DecimalField("sinal", max_digits=9, decimal_places=2, default=0)
    expira_em = models.DateTimeField(
        "pagar o sinal até", null=True, blank=True, help_text="Só para reservas pendentes."
    )
    modalidade = models.CharField(
        "modalidade",
        max_length=60,
        blank=True,
        help_text="O que vai ser jogado, para a equipe preparar o espaço.",
    )
    mensalista = models.ForeignKey(
        "agenda.Mensalista",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas",
        verbose_name="mensalista",
    )
    lembrete_enviado_em = models.DateTimeField("lembrete enviado em", null=True, blank=True)
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

    @property
    def is_paid(self):
        return self.valor_total > 0 and self.valor_pago >= self.valor_total

    @property
    def is_pending(self):
        return self.status == self.Status.PENDENTE


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
        CONFIRMADA = "CONFIRMADA", "Sinal pago"
        EXPIRADA = "EXPIRADA", "Expirou sem pagamento"

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


class Mensalista(TenantModel):
    """Cliente com horário fixo toda semana. As reservas são geradas algumas semanas à frente."""

    class Cobranca(models.TextChoices):
        POR_JOGO = "POR_JOGO", "Por jogo"
        MENSAL = "MENSAL", "Mensalidade"

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="mensalidades", verbose_name="cliente"
    )
    espaco = models.ForeignKey(
        "espacos.Espaco", on_delete=models.PROTECT, related_name="mensalistas", verbose_name="espaço"
    )
    dia_semana = models.PositiveSmallIntegerField("dia da semana", choices=DIAS_SEMANA)
    hora = models.TimeField("início")
    duracao_minutos = models.PositiveSmallIntegerField("duração", default=60)
    data_inicio = models.DateField("a partir de")
    data_fim = models.DateField("até", null=True, blank=True)
    cobranca = models.CharField("cobrança", max_length=8, choices=Cobranca.choices, default=Cobranca.POR_JOGO)
    valor = models.DecimalField("valor", max_digits=9, decimal_places=2)
    dia_vencimento = models.PositiveSmallIntegerField("vencimento da mensalidade (dia)", default=10)
    conta_mensal = models.ForeignKey(
        "financeiro.ContaReceber",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="mensalidade",
    )
    gerado_ate = models.DateField("reservas geradas até", null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="criado por",
    )

    class Meta:
        verbose_name = "mensalista"
        verbose_name_plural = "mensalistas"
        ordering = ["dia_semana", "hora"]
        constraints = [
            models.CheckConstraint(
                condition=Q(dia_vencimento__gte=1) & Q(dia_vencimento__lte=28),
                name="mensalista_vencimento_valido",
            ),
        ]

    def __str__(self):
        return f"{self.cliente} · {self.get_dia_semana_display()} {self.hora:%H:%M}"

    @property
    def is_active(self):
        from django.utils import timezone

        return self.data_fim is None or self.data_fim >= timezone.localdate()


class MensalistaAviso(TenantModel):
    """Uma semana em que a reserva do mensalista não pôde ser criada. O dono precisa ver, não pode sumir."""

    mensalista = models.ForeignKey(
        Mensalista, on_delete=models.CASCADE, related_name="avisos", verbose_name="mensalista"
    )
    data = models.DateField("data")
    motivo = models.CharField("motivo", max_length=200)
    resolvido = models.BooleanField("resolvido", default=False)

    class Meta:
        verbose_name = "aviso de mensalista"
        verbose_name_plural = "avisos de mensalistas"
        ordering = ["data"]
        constraints = [
            models.UniqueConstraint(fields=["mensalista", "data"], name="um_aviso_por_semana"),
        ]

    def __str__(self):
        return f"{self.mensalista} · {self.data:%d/%m}"
