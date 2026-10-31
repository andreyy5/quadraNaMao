"""Cria um estabelecimento de demonstração. Apenas para desenvolvimento."""

import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.agenda.models import Reserva
from apps.agenda.services import create_block, create_reservation
from apps.clientes.services import find_or_create_client
from apps.espacos.models import DiaSemana, Espaco
from apps.espacos.services import save_price_rules, save_weekly_hours
from apps.estabelecimentos.models import Estabelecimento

SLUG = "arena-demo"
ESPACOS = [
    ("Areia 1", Espaco.Tipo.AREIA, "Beach tênis, futevôlei", Decimal("90")),
    ("Areia 2", Espaco.Tipo.AREIA, "Vôlei de praia", Decimal("90")),
    ("Society", Espaco.Tipo.CAMPO, "Fut7", Decimal("180")),
    ("Ginásio", Espaco.Tipo.QUADRA, "Futsal", Decimal("150")),
]
CLIENTES = [
    ("Marina Duarte", "11987650001"),
    ("João Pereira", "11987650002"),
    ("Carla Nogueira", "11987650003"),
    ("Rafael Lima", "11987650004"),
    ("Turma do Beto", "11987650005"),
]


class Command(BaseCommand):
    help = "Cria dados de demonstração com um dono, um atendente, espaços e reservas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", help="Apaga o estabelecimento de demonstração antes."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("O seed_demo só pode rodar em desenvolvimento.")

        existing = Estabelecimento.objects.filter(slug=SLUG).first()
        if existing and not options["reset"]:
            raise CommandError("A demonstração já existe. Use --reset para recriar.")
        if existing:
            self._delete(existing)

        tenant = Estabelecimento.objects.create(nome="Arena Demo", slug=SLUG, telefone="(11) 4000-0000")
        password = secrets.token_urlsafe(9)
        users = get_user_model()
        owner = users.objects.create_user(
            "dono@demo.local", password, nome="Andrea Souza", papel=users.Papel.DONO, estabelecimento=tenant
        )
        users.objects.create_user(
            "atendente@demo.local",
            password,
            nome="Bruno Costa",
            papel=users.Papel.ATENDENTE,
            estabelecimento=tenant,
        )

        espacos = []
        for ordem, (nome, tipo, modalidades, valor) in enumerate(ESPACOS):
            espaco = Espaco.all_tenants.create(
                estabelecimento=tenant, nome=nome, tipo=tipo, modalidades=modalidades, ordem=ordem
            )
            rows = [
                {"dia_semana": dia, "aberto": True, "abre": time(8), "fecha": time(23)}
                for dia in DiaSemana.values
            ]
            save_weekly_hours(espaco, rows)
            save_price_rules(espaco, DiaSemana.values, time(8), time(18), 60, valor)
            save_price_rules(espaco, DiaSemana.values, time(18), time(23), 60, valor + Decimal("30"))
            espacos.append(espaco)

        clientes = [find_or_create_client(tenant, nome, telefone) for nome, telefone in CLIENTES]
        tz = tenant.timezone
        today = timezone.now().astimezone(tz).date()
        agenda = [
            (0, 0, 9, 60),
            (0, 1, 18, 60),
            (0, 2, 19, 90),
            (1, 3, 10, 60),
            (1, 4, 20, 120),
            (2, 4, 19, 60),
            (2, 0, 21, 60),
            (3, 1, 16, 60),
        ]
        for espaco_idx, cliente_idx, hour, minutes in agenda:
            for offset in (0, 1):
                start = datetime.combine(today + timedelta(days=offset), time(hour), tzinfo=tz)
                create_reservation(
                    espacos[espaco_idx],
                    clientes[(cliente_idx + offset) % len(clientes)],
                    start,
                    start + timedelta(minutes=minutes),
                    usuario=owner,
                )

        rain = datetime.combine(today + timedelta(days=2), time(14), tzinfo=tz)
        create_block(espacos[1], rain, rain + timedelta(hours=3), "CHUVA", "Previsão de chuva forte", owner)

        self.stdout.write(self.style.SUCCESS("Demonstração criada."))
        self.stdout.write("  Dono:      dono@demo.local")
        self.stdout.write("  Atendente: atendente@demo.local")
        self.stdout.write(f"  Senha:     {password}")

    def _delete(self, tenant):
        Reserva.all_tenants.filter(estabelecimento=tenant).delete()
        tenant.delete()
