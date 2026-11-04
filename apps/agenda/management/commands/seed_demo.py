"""Cria um estabelecimento de demonstração. Apenas para desenvolvimento."""

import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.agenda import online
from apps.agenda.mensalistas import create_mensalista
from apps.agenda.models import Mensalista, Reserva
from apps.agenda.services import create_block, create_reservation
from apps.clientes.models import Cliente
from apps.clientes.services import find_or_create_client
from apps.espacos.models import DiaSemana, Espaco, TabelaPreco
from apps.espacos.services import save_price_rules, save_weekly_hours
from apps.estabelecimentos.models import Estabelecimento
from apps.estoque.models import MovimentacaoEstoque, Produto
from apps.estoque.services import register_entry
from apps.financeiro.models import Caixa, ContaPagar, ContaReceber, Lancamento, Pagamento
from apps.financeiro.services import current_register, open_register, receive_account
from apps.pdv.models import Venda
from apps.pdv.services import add_to_tab, complete_sale
from apps.whatsapp.models import Mensagem
from apps.whatsapp.services import notify_reservation

SLUG = "arena-demo"
ESPACOS = [
    # As duas areias atendem as mesmas modalidades: na reserva por modalidade, o sistema escolhe a melhor.
    ("Areia 1", Espaco.Tipo.AREIA, "Beach tênis, futevôlei, vôlei de praia", Decimal("90")),
    ("Areia 2", Espaco.Tipo.AREIA, "Beach tênis, futevôlei, vôlei de praia", Decimal("90")),
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
# Nome, categoria, preço, custo, estoque inicial (None: sem controle), estoque mínimo.
PRODUTOS = [
    ("Água 500 ml", Produto.Categoria.BEBIDA, "4.00", "1.50", 48, 12),
    ("Refrigerante lata", Produto.Categoria.BEBIDA, "6.00", "3.00", 36, 12),
    ("Isotônico", Produto.Categoria.BEBIDA, "9.00", "5.00", 8, 10),
    ("Cerveja long neck", Produto.Categoria.BEBIDA, "10.00", "5.50", 60, 24),
    ("Salgadinho", Produto.Categoria.COMIDA, "7.00", "3.50", 15, 5),
    ("Barra de cereal", Produto.Categoria.COMIDA, "5.00", "2.50", 0, 5),
    ("Aluguel de bola", Produto.Categoria.ALUGUEL, "10.00", None, None, 0),
    ("Aluguel de raquete", Produto.Categoria.ALUGUEL, "20.00", None, None, 0),
    ("Bola de beach tênis", Produto.Categoria.ACESSORIO, "35.00", "20.00", 10, 3),
]


def online_link(tenant):
    return settings.SITE_URL.rstrip("/") + reverse("publico:reservar", args=[tenant.slug])


class Command(BaseCommand):
    help = "Cria dados de demonstração com um dono, um atendente, espaços e reservas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", help="Apaga o estabelecimento de demonstração antes."
        )
        parser.add_argument(
            "--produtos",
            action="store_true",
            help="Só acrescenta produtos e vendas a uma demonstração já criada, sem mexer no resto.",
        )
        parser.add_argument(
            "--financeiro",
            action="store_true",
            help="Só acrescenta contas e recebimentos de exemplo a uma demonstração já criada.",
        )
        parser.add_argument(
            "--online",
            action="store_true",
            help="Só liga o link de reserva, o Pix, o WhatsApp e os mensalistas numa demonstração já criada.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("O seed_demo só pode rodar em desenvolvimento.")

        existing = Estabelecimento.objects.filter(slug=SLUG).first()
        if options["online"]:
            if not existing:
                raise CommandError("A demonstração ainda não existe. Rode o seed_demo sem opções.")
            if Mensalista.all_tenants.filter(estabelecimento=existing).exists():
                raise CommandError("A demonstração já tem mensalistas.")
            owner = get_user_model().objects.filter(estabelecimento=existing, papel="DONO").first()
            self._seed_online(existing, owner)
            self.stdout.write(self.style.SUCCESS("Link de reserva, WhatsApp e mensalistas prontos."))
            self.stdout.write(f"  Link público: {online_link(existing)}")
            return
        if options["financeiro"]:
            if not existing:
                raise CommandError("A demonstração ainda não existe. Rode o seed_demo sem opções.")
            if ContaPagar.all_tenants.filter(estabelecimento=existing).exists():
                raise CommandError("A demonstração já tem contas.")
            owner = get_user_model().objects.filter(estabelecimento=existing, papel="DONO").first()
            self._seed_finance(existing, owner)
            self.stdout.write(self.style.SUCCESS("Contas e recebimentos de demonstração criados."))
            return
        if options["produtos"]:
            if not existing:
                raise CommandError("A demonstração ainda não existe. Rode o seed_demo sem opções.")
            if Produto.all_tenants.filter(estabelecimento=existing).exists():
                raise CommandError("A demonstração já tem produtos.")
            owner = get_user_model().objects.filter(estabelecimento=existing, papel="DONO").first()
            self._seed_sales(existing, owner)
            self.stdout.write(self.style.SUCCESS("Produtos e vendas de demonstração criados."))
            return
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

        self._seed_sales(tenant, owner)
        self._seed_finance(tenant, owner)
        self._seed_online(tenant, owner)

        self.stdout.write(self.style.SUCCESS("Demonstração criada."))
        self.stdout.write("  Dono:      dono@demo.local")
        self.stdout.write("  Atendente: atendente@demo.local")
        self.stdout.write(f"  Senha:     {password}")
        self.stdout.write(f"  Link público: {online_link(tenant)}")

    def _register(self, owner):
        return current_register(owner) or open_register(owner, Decimal("100"))

    def _seed_finance(self, tenant, owner):
        self._register(owner)
        today = timezone.now().astimezone(tenant.timezone).date()
        contas = [
            (
                "Aluguel do ponto",
                "ALUGUEL",
                "2500.00",
                today.replace(day=10),
                "MENSAL",
                "Imobiliária Central",
            ),
            ("Energia", "ENERGIA", "640.00", today + timedelta(days=3), "MENSAL", "Distribuidora de energia"),
            ("Internet", "INTERNET", "120.00", today + timedelta(days=12), "MENSAL", "Provedor"),
            ("Areia nova para as quadras", "MANUTENCAO", "900.00", today - timedelta(days=4), "NENHUMA", ""),
        ]
        for descricao, categoria, valor, vencimento, recorrencia, fornecedor in contas:
            ContaPagar.all_tenants.create(
                estabelecimento=tenant,
                descricao=descricao,
                categoria=categoria,
                valor=Decimal(valor),
                vencimento=vencimento,
                recorrencia=recorrencia,
                fornecedor=fornecedor,
                criado_por=owner,
            )
        ContaReceber.all_tenants.create(
            estabelecimento=tenant,
            descricao="Aluguel da quadra para evento",
            categoria="EVENTO",
            valor=Decimal("400.00"),
            vencimento=today - timedelta(days=2),
            criado_por=owner,
        )
        # Algumas reservas de hoje já pagas, uma delas só com o sinal.
        contas_hoje = ContaReceber.all_tenants.filter(
            estabelecimento=tenant, reserva__isnull=False, vencimento=today, status="ABERTA"
        ).order_by("reserva__inicio")
        for index, conta in enumerate(contas_hoje[:3]):
            valor = conta.saldo if index < 2 else (conta.saldo / 2).quantize(Decimal("0.01"))
            if valor > 0:
                receive_account(conta, valor, "PIX" if index % 2 == 0 else "DINHEIRO", owner)

    def _seed_sales(self, tenant, owner):
        self._register(owner)
        produtos = {}
        for nome, categoria, preco, custo, estoque, minimo in PRODUTOS:
            produto = Produto.all_tenants.create(
                estabelecimento=tenant,
                nome=nome,
                categoria=categoria,
                preco_venda=Decimal(preco),
                custo=Decimal(custo) if custo else None,
                controla_estoque=estoque is not None,
                estoque_minimo=minimo,
            )
            if estoque:
                register_entry(produto, estoque, usuario=owner, observacao="Estoque inicial")
            produtos[nome] = produto.pk

        complete_sale(
            tenant,
            {produtos["Água 500 ml"]: 2, produtos["Salgadinho"]: 1},
            Venda.Forma.PIX,
            usuario=owner,
        )
        complete_sale(tenant, {produtos["Aluguel de bola"]: 1}, Venda.Forma.DINHEIRO, usuario=owner)
        today = timezone.now().astimezone(tenant.timezone).date()
        reserva = (
            Reserva.all_tenants.filter(estabelecimento=tenant, status=Reserva.Status.CONFIRMADA)
            .filter(inicio__date=today)
            .order_by("inicio")
            .first()
        )
        if reserva:
            add_to_tab(tenant, reserva, {produtos["Cerveja long neck"]: 4}, usuario=owner)

    def _seed_online(self, tenant, owner):
        """Fases 2 e 5: link público com sinal por Pix, mensalistas e, com o módulo ligado, WhatsApp."""
        tenant.reserva_online_ativa = True
        tenant.chave_pix = "pix@arena-demo.local"
        tenant.pix_cidade = "Sao Paulo"
        tenant.whatsapp_ativo = settings.WHATSAPP_ENABLED
        tenant.save()
        Espaco.all_tenants.filter(estabelecimento=tenant, tipo=Espaco.Tipo.AREIA).update(
            modalidades="Beach tênis, futevôlei, vôlei de praia"
        )
        # Sinal só no horário nobre, como costuma ser.
        TabelaPreco.all_tenants.filter(espaco__estabelecimento=tenant, hora_inicio=time(18)).update(
            valor_sinal=Decimal("30")
        )
        Cliente.all_tenants.filter(estabelecimento=tenant, nome__in=[c[0] for c in CLIENTES[:4]]).update(
            aceite_whatsapp=True
        )
        espacos = {e.nome: e for e in Espaco.all_tenants.filter(estabelecimento=tenant)}
        clientes = {c.nome: c for c in Cliente.all_tenants.filter(estabelecimento=tenant)}
        today = timezone.now().astimezone(tenant.timezone).date()
        amanha = (today.weekday() + 1) % 7
        mensalistas = [
            ("Turma do Beto", "Society", 3, time(20), 90, Mensalista.Cobranca.POR_JOGO, "210.00"),
            ("Carla Nogueira", "Areia 1", 1, time(8), 60, Mensalista.Cobranca.MENSAL, "320.00"),
            # Cai em cima de uma reserva avulsa de amanhã: aparece o aviso para o dono resolver.
            ("Rafael Lima", "Ginásio", amanha, time(16), 60, Mensalista.Cobranca.POR_JOGO, "150.00"),
        ]
        for cliente, espaco, dia, hora, minutos, cobranca, valor in mensalistas:
            mensalista = Mensalista(
                estabelecimento=tenant,
                cliente=clientes[cliente],
                espaco=espacos[espaco],
                dia_semana=dia,
                hora=hora,
                duracao_minutos=minutos,
                data_inicio=today,
                cobranca=cobranca,
                valor=Decimal(valor),
                dia_vencimento=10,
            )
            create_mensalista(mensalista, owner)
        if settings.WHATSAPP_ENABLED:
            self._seed_whatsapp(tenant, clientes, today)
        # Um pedido pelo link esperando o Pix do sinal: o sistema escolhe a areia.
        inicio = datetime.combine(today + timedelta(days=1), time(18), tzinfo=tenant.timezone)
        areias = [espacos["Areia 1"], espacos["Areia 2"]]
        try:
            online.book_online(
                tenant, areias, inicio, "Paula Mendes", "11987650006", modalidade="Beach tênis"
            )
        except online.OnlineBookingError:
            pass

    def _seed_whatsapp(self, tenant, clientes, today):
        # Confirmações que já saíram (no modo de teste, só ficam no histórico) e uma conversa aberta.
        reservas = Reserva.all_tenants.filter(
            estabelecimento=tenant,
            status=Reserva.Status.CONFIRMADA,
            mensalista__isnull=True,
            cliente__aceite_whatsapp=True,
            inicio__date=today + timedelta(days=1),
        )
        for reserva in reservas[:3]:
            notify_reservation(reserva.pk, "confirmada")
        marina = clientes["Marina Duarte"]
        Mensagem.all_tenants.create(
            estabelecimento=tenant,
            cliente=marina,
            telefone=marina.telefone,
            direcao=Mensagem.Direcao.ENTRADA,
            tipo=Mensagem.Tipo.TEXTO,
            corpo="Oi! Ainda tem horário no sábado de manhã para beach tênis?",
            status=Mensagem.Status.RECEBIDA,
            wa_id=f"demo-{secrets.token_hex(6)}",
        )

    def _delete(self, tenant):
        # Pagamento e lançamento primeiro: eles protegem a venda, a reserva e as contas a que se referem.
        Pagamento.all_tenants.filter(estabelecimento=tenant).delete()
        Mensagem.all_tenants.filter(estabelecimento=tenant).delete()
        Mensalista.all_tenants.filter(estabelecimento=tenant).delete()
        Lancamento.all_tenants.filter(estabelecimento=tenant, estorno_de__isnull=False).delete()
        Lancamento.all_tenants.filter(estabelecimento=tenant).delete()
        ContaReceber.all_tenants.filter(estabelecimento=tenant).delete()
        ContaPagar.all_tenants.filter(estabelecimento=tenant).delete()
        Venda.all_tenants.filter(estabelecimento=tenant).delete()
        Caixa.all_tenants.filter(estabelecimento=tenant).delete()
        MovimentacaoEstoque.all_tenants.filter(estabelecimento=tenant).delete()
        Produto.all_tenants.filter(estabelecimento=tenant).delete()
        Reserva.all_tenants.filter(estabelecimento=tenant).delete()
        tenant.delete()
