from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(email, password, **extra_fields)


class Usuario(AbstractUser):
    class Papel(models.TextChoices):
        DONO = "DONO", "Dono"
        GERENTE = "GERENTE", "Gerente"
        ATENDENTE = "ATENDENTE", "Atendente"

    username = None
    first_name = None
    last_name = None
    nome = models.CharField("nome", max_length=120)
    email = models.EmailField("e-mail", unique=True)
    papel = models.CharField("perfil", max_length=12, choices=Papel.choices, default=Papel.ATENDENTE)
    estabelecimento = models.ForeignKey(
        "estabelecimentos.Estabelecimento",
        on_delete=models.CASCADE,
        related_name="usuarios",
        null=True,
        blank=True,
        verbose_name="estabelecimento",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["nome"]

    def __str__(self):
        return self.nome or self.email

    def get_full_name(self):
        return self.nome

    def get_short_name(self):
        return self.nome.split(" ")[0] if self.nome else self.email

    @property
    def is_owner(self):
        return self.papel == self.Papel.DONO
