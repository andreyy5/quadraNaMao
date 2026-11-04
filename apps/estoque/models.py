from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.estabelecimentos.models import TenantModel


class Produto(TenantModel):
    class Categoria(models.TextChoices):
        BEBIDA = "BEBIDA", "Bebida"
        COMIDA = "COMIDA", "Comida"
        ALUGUEL = "ALUGUEL", "Aluguel"
        ACESSORIO = "ACESSORIO", "Acessório"
        OUTRO = "OUTRO", "Outro"

    nome = models.CharField("nome", max_length=80)
    categoria = models.CharField(
        "categoria", max_length=10, choices=Categoria.choices, default=Categoria.BEBIDA
    )
    codigo = models.CharField(
        "código de barras", max_length=40, blank=True, help_text="Opcional. Funciona com leitor de código."
    )
    preco_venda = models.DecimalField("preço de venda", max_digits=9, decimal_places=2)
    custo = models.DecimalField("custo", max_digits=9, decimal_places=2, null=True, blank=True)
    controla_estoque = models.BooleanField(
        "controlar estoque",
        default=True,
        help_text="Desligue para o que não acaba, como o aluguel de uma bola.",
    )
    estoque_atual = models.IntegerField("estoque atual", default=0, editable=False)
    estoque_minimo = models.PositiveIntegerField(
        "estoque mínimo", default=0, help_text="Abaixo disso, o sistema avisa que está na hora de comprar."
    )
    ativo = models.BooleanField("ativo", default=True, help_text="Produto inativo some do PDV.")

    class Meta:
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["estabelecimento", "nome"], name="produto_nome_unico_por_estabelecimento"
            ),
            models.UniqueConstraint(
                fields=["estabelecimento", "codigo"],
                condition=~Q(codigo=""),
                name="produto_codigo_unico_por_estabelecimento",
            ),
            models.CheckConstraint(condition=Q(preco_venda__gte=0), name="produto_preco_nao_negativo"),
        ]

    def __str__(self):
        return self.nome

    @property
    def is_out(self):
        return self.controla_estoque and self.estoque_atual <= 0

    @property
    def is_low(self):
        return self.controla_estoque and self.estoque_atual <= self.estoque_minimo

    @property
    def margem_percentual(self):
        """Quanto do preço sobra depois do custo, em %. Sem custo ou sem preço, não dá para saber."""
        if self.custo is None or not self.preco_venda:
            return None
        return round((self.preco_venda - self.custo) * 100 / self.preco_venda)

    @property
    def icone(self):
        """Nome do ícone da categoria em components/icon.html."""
        return self.categoria.lower()


class MovimentacaoEstoque(TenantModel):
    """Histórico imutável: o saldo do produto só muda por aqui."""

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SAIDA = "SAIDA", "Saída"
        AJUSTE = "AJUSTE", "Contagem"
        PERDA = "PERDA", "Perda"

    class Origem(models.TextChoices):
        COMPRA = "COMPRA", "Compra"
        VENDA = "VENDA", "Venda"
        CANCELAMENTO = "CANCELAMENTO", "Cancelamento de venda"
        MANUAL = "MANUAL", "Ajuste manual"

    produto = models.ForeignKey(
        Produto, on_delete=models.PROTECT, related_name="movimentacoes", verbose_name="produto"
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    origem = models.CharField("origem", max_length=14, choices=Origem.choices)
    quantidade = models.IntegerField("quantidade", help_text="Positiva quando entra, negativa quando sai.")
    saldo_apos = models.IntegerField("saldo após")
    referencia = models.CharField("referência", max_length=40, blank=True)
    observacao = models.CharField("observação", max_length=200, blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="usuário",
    )

    class Meta:
        verbose_name = "movimentação de estoque"
        verbose_name_plural = "movimentações de estoque"
        ordering = ["-criado_em", "-pk"]
        indexes = [models.Index(fields=["produto", "-criado_em"], name="movimentacao_produto_data")]

    def __str__(self):
        return f"{self.produto} {self.quantidade:+d}"
