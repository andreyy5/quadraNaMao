from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.estabelecimentos.models import TenantModel


class FormaPagamento(models.TextChoices):
    PIX = "PIX", "Pix"
    DINHEIRO = "DINHEIRO", "Dinheiro"
    CARTAO_DEBITO = "CARTAO_DEBITO", "Débito"
    CARTAO_CREDITO = "CARTAO_CREDITO", "Crédito"
    OUTRO = "OUTRO", "Outro"


class Categoria(models.TextChoices):
    RESERVA = "RESERVA", "Reservas"
    VENDA = "VENDA", "Vendas"
    EVENTO = "EVENTO", "Evento"
    PATROCINIO = "PATROCINIO", "Patrocínio"
    ALUGUEL = "ALUGUEL", "Aluguel"
    ENERGIA = "ENERGIA", "Energia"
    AGUA = "AGUA", "Água"
    INTERNET = "INTERNET", "Internet"
    FORNECEDOR = "FORNECEDOR", "Fornecedor"
    SALARIO = "SALARIO", "Salários"
    MANUTENCAO = "MANUTENCAO", "Manutenção"
    IMPOSTO = "IMPOSTO", "Impostos"
    OUTRO = "OUTRO", "Outro"


CATEGORIAS_RECEBER = [Categoria.EVENTO, Categoria.PATROCINIO, Categoria.OUTRO]
CATEGORIAS_PAGAR = [
    Categoria.ALUGUEL,
    Categoria.ENERGIA,
    Categoria.AGUA,
    Categoria.INTERNET,
    Categoria.FORNECEDOR,
    Categoria.SALARIO,
    Categoria.MANUTENCAO,
    Categoria.IMPOSTO,
    Categoria.OUTRO,
]


class Caixa(TenantModel):
    """O caixa de um operador, da abertura ao fechamento com a conferência do dinheiro."""

    operador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="caixas", verbose_name="operador"
    )
    saldo_inicial = models.DecimalField("saldo inicial", max_digits=9, decimal_places=2, default=0)
    fechado_em = models.DateTimeField("fechado em", null=True, blank=True)
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="fechado por",
    )
    saldo_esperado = models.DecimalField(
        "saldo esperado", max_digits=9, decimal_places=2, null=True, blank=True
    )
    saldo_conferido = models.DecimalField(
        "saldo conferido", max_digits=9, decimal_places=2, null=True, blank=True
    )
    diferenca = models.DecimalField("diferença", max_digits=9, decimal_places=2, null=True, blank=True)
    observacao = models.CharField("observação", max_length=200, blank=True)

    class Meta:
        verbose_name = "caixa"
        verbose_name_plural = "caixas"
        ordering = ["-criado_em", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["estabelecimento", "operador"],
                condition=Q(fechado_em__isnull=True),
                name="um_caixa_aberto_por_operador",
            ),
            models.CheckConstraint(
                condition=Q(saldo_inicial__gte=0), name="caixa_saldo_inicial_nao_negativo"
            ),
        ]

    def __str__(self):
        return f"Caixa de {self.operador} em {self.criado_em:%d/%m}"

    @property
    def is_open(self):
        return self.fechado_em is None

    @property
    def is_from_another_day(self):
        return self.is_open and timezone.localtime(self.criado_em).date() != timezone.localdate()


class Lancamento(TenantModel):
    """Entrada ou saída de um caixa. Imutável: uma correção é um estorno, nunca uma edição."""

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SAIDA = "SAIDA", "Saída"

    class Origem(models.TextChoices):
        RESERVA = "RESERVA", "Reserva"
        VENDA = "VENDA", "Venda"
        CONTA_RECEBER = "CONTA_RECEBER", "Conta a receber"
        CONTA_PAGAR = "CONTA_PAGAR", "Conta a pagar"
        SUPRIMENTO = "SUPRIMENTO", "Dinheiro colocado"
        RETIRADA = "RETIRADA", "Dinheiro retirado"
        ESTORNO = "ESTORNO", "Estorno"

    caixa = models.ForeignKey(
        Caixa, on_delete=models.PROTECT, related_name="lancamentos", verbose_name="caixa"
    )
    tipo = models.CharField("tipo", max_length=7, choices=Tipo.choices)
    origem = models.CharField("origem", max_length=13, choices=Origem.choices)
    categoria = models.CharField(
        "categoria", max_length=10, choices=Categoria.choices, default=Categoria.OUTRO
    )
    forma = models.CharField("forma de pagamento", max_length=14, choices=FormaPagamento.choices)
    valor = models.DecimalField("valor", max_digits=9, decimal_places=2)
    descricao = models.CharField("descrição", max_length=200, blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="usuário",
    )
    reserva = models.ForeignKey(
        "agenda.Reserva",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="reserva",
    )
    venda = models.ForeignKey(
        "pdv.Venda",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="venda",
    )
    conta_receber = models.ForeignKey(
        "financeiro.ContaReceber",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="conta a receber",
    )
    conta_pagar = models.ForeignKey(
        "financeiro.ContaPagar",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="conta a pagar",
    )
    estorno_de = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="estorno",
        verbose_name="estorno de",
    )

    class Meta:
        verbose_name = "lançamento"
        verbose_name_plural = "lançamentos"
        ordering = ["-criado_em", "-pk"]
        indexes = [models.Index(fields=["estabelecimento", "criado_em"], name="lancamento_estab_data")]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="lancamento_valor_positivo")]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.valor}"

    @property
    def is_income(self):
        return self.tipo == self.Tipo.ENTRADA

    @property
    def can_reverse(self):
        """Venda se desfaz cancelando a venda, que também devolve os itens ao estoque."""
        return self.origem not in (self.Origem.ESTORNO, self.Origem.VENDA) and not hasattr(self, "estorno")


class ContaBase(TenantModel):
    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Em aberto"
        PAGA = "PAGA", "Paga"
        CANCELADA = "CANCELADA", "Cancelada"

    class Recorrencia(models.TextChoices):
        NENHUMA = "NENHUMA", "Não repete"
        SEMANAL = "SEMANAL", "Toda semana"
        MENSAL = "MENSAL", "Todo mês"
        ANUAL = "ANUAL", "Todo ano"

    descricao = models.CharField("descrição", max_length=120)
    categoria = models.CharField(
        "categoria", max_length=10, choices=Categoria.choices, default=Categoria.OUTRO
    )
    valor = models.DecimalField("valor", max_digits=9, decimal_places=2)
    valor_pago = models.DecimalField("valor pago", max_digits=9, decimal_places=2, default=0)
    vencimento = models.DateField("vencimento")
    status = models.CharField("status", max_length=9, choices=Status.choices, default=Status.ABERTA)
    recorrencia = models.CharField(
        "repetição", max_length=7, choices=Recorrencia.choices, default=Recorrencia.NENHUMA
    )
    recorrencia_origem = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="repetição de",
    )
    forma_pagamento = models.CharField(
        "forma de pagamento", max_length=14, choices=FormaPagamento.choices, blank=True
    )
    pago_em = models.DateTimeField("pago em", null=True, blank=True)
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
        abstract = True
        ordering = ["vencimento", "pk"]
        indexes = [
            models.Index(fields=["estabelecimento", "status", "vencimento"], name="%(class)s_status_venc"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recorrencia_origem", "vencimento"],
                condition=Q(recorrencia_origem__isnull=False),
                name="%(class)s_uma_por_vencimento",
            ),
            models.CheckConstraint(condition=Q(valor__gte=0), name="%(class)s_valor_nao_negativo"),
        ]

    def __str__(self):
        return self.descricao

    @property
    def saldo(self):
        return max(self.valor - self.valor_pago, 0)

    @property
    def is_open(self):
        return self.status == self.Status.ABERTA

    @property
    def is_paid(self):
        return self.status == self.Status.PAGA

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELADA

    @property
    def is_overdue(self):
        """Atraso é calculado na hora: assim não depende de uma tarefa agendada para ficar certo."""
        return self.is_open and self.vencimento < timezone.localdate()

    @property
    def is_due_today(self):
        return self.is_open and self.vencimento == timezone.localdate()

    @property
    def situacao(self):
        return "Atrasada" if self.is_overdue else self.get_status_display()

    @property
    def is_recurring(self):
        return self.recorrencia != self.Recorrencia.NENHUMA or self.recorrencia_origem_id is not None


class ContaReceber(ContaBase):
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contas",
        verbose_name="cliente",
    )
    reserva = models.OneToOneField(
        "agenda.Reserva",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conta",
        verbose_name="reserva",
    )

    class Meta(ContaBase.Meta):
        verbose_name = "conta a receber"
        verbose_name_plural = "contas a receber"


class ContaPagar(ContaBase):
    fornecedor = models.CharField("fornecedor", max_length=120, blank=True)

    class Meta(ContaBase.Meta):
        verbose_name = "conta a pagar"
        verbose_name_plural = "contas a pagar"
