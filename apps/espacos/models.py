from django.core.validators import MinValueValidator
from django.db import models

from apps.estabelecimentos.models import TenantModel


class DiaSemana(models.IntegerChoices):
    """Mesma numeração de date.weekday(): segunda é 0."""

    SEGUNDA = 0, "Segunda"
    TERCA = 1, "Terça"
    QUARTA = 2, "Quarta"
    QUINTA = 3, "Quinta"
    SEXTA = 4, "Sexta"
    SABADO = 5, "Sábado"
    DOMINGO = 6, "Domingo"


class Espaco(TenantModel):
    class Tipo(models.TextChoices):
        CAMPO = "CAMPO", "Campo (Fut7 / society)"
        QUADRA = "QUADRA", "Quadra (futsal / poliesportiva)"
        AREIA = "AREIA", "Areia (beach tênis, vôlei, futevôlei)"

    nome = models.CharField("nome", max_length=80)
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices, default=Tipo.AREIA)
    modalidades = models.CharField(
        "modalidades", max_length=160, blank=True, help_text="Ex.: beach tênis, futevôlei"
    )
    capacidade = models.PositiveSmallIntegerField("capacidade", null=True, blank=True)
    ativo = models.BooleanField("ativo", default=True, help_text="Espaço inativo some da agenda.")
    ordem = models.PositiveSmallIntegerField("ordem de exibição", default=0)

    class Meta:
        verbose_name = "espaço"
        verbose_name_plural = "espaços"
        ordering = ["ordem", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["estabelecimento", "nome"], name="espaco_nome_unico_por_estabelecimento"
            ),
        ]

    def __str__(self):
        return self.nome

    @property
    def tema(self):
        """Valor do atributo data-theme usado pelo CSS."""
        return self.tipo.lower()


class HorarioFuncionamento(TenantModel):
    espaco = models.ForeignKey(
        Espaco, on_delete=models.CASCADE, related_name="horarios", verbose_name="espaço"
    )
    dia_semana = models.PositiveSmallIntegerField("dia da semana", choices=DiaSemana.choices)
    abre = models.TimeField("abre às")
    fecha = models.TimeField("fecha às", help_text="Se for menor ou igual à abertura, fecha no dia seguinte.")

    class Meta:
        verbose_name = "horário de funcionamento"
        verbose_name_plural = "horários de funcionamento"
        ordering = ["dia_semana"]
        constraints = [
            models.UniqueConstraint(fields=["espaco", "dia_semana"], name="horario_unico_por_dia"),
        ]

    def __str__(self):
        return f"{self.get_dia_semana_display()}: {self.abre:%H:%M}–{self.fecha:%H:%M}"


class TabelaPreco(TenantModel):
    espaco = models.ForeignKey(Espaco, on_delete=models.CASCADE, related_name="precos", verbose_name="espaço")
    dia_semana = models.PositiveSmallIntegerField("dia da semana", choices=DiaSemana.choices)
    hora_inicio = models.TimeField("das")
    hora_fim = models.TimeField("até")
    duracao_slot_minutos = models.PositiveSmallIntegerField(
        "duração do horário (min)", default=60, validators=[MinValueValidator(15)]
    )
    valor = models.DecimalField("valor", max_digits=9, decimal_places=2, validators=[MinValueValidator(0)])
    valor_sinal = models.DecimalField(
        "sinal", max_digits=9, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )

    class Meta:
        verbose_name = "faixa de preço"
        verbose_name_plural = "tabela de preços"
        ordering = ["dia_semana", "hora_inicio"]

    def __str__(self):
        return f"{self.get_dia_semana_display()} {self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}: {self.valor}"
