from datetime import datetime, time, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.agenda import mensalistas, services
from apps.agenda.models import Bloqueio, Mensalista, MensalistaAviso, Reserva
from apps.financeiro.models import ContaReceber
from apps.whatsapp.models import Mensagem
from conftest import TZ, make_cliente, make_espaco

D = Decimal


def today():
    return timezone.now().astimezone(TZ).date()


def make_mensalista(tenant, espaco, cliente, **fields):
    data = {
        "estabelecimento": tenant,
        "cliente": cliente,
        "espaco": espaco,
        "dia_semana": (today() + timedelta(days=2)).weekday(),
        "hora": time(19),
        "duracao_minutos": 60,
        "data_inicio": today(),
        "valor": D("90"),
        **fields,
    }
    return mensalistas.create_mensalista(Mensalista(**data))


def jogos(mensalista):
    return Reserva.all_tenants.filter(mensalista=mensalista).exclude(status="CANCELADA").order_by("inicio")


def test_creates_one_reservation_per_week_up_to_the_horizon(tenant, espaco, cliente):
    mensalista = make_mensalista(tenant, espaco, cliente)
    reservas = list(jogos(mensalista))
    assert len(reservas) == mensalistas.HORIZON_WEEKS
    assert {r.inicio.astimezone(TZ).weekday() for r in reservas} == {mensalista.dia_semana}
    assert all(r.origem == "MENSALISTA" and r.valor_total == D("90") for r in reservas)
    assert reservas[1].inicio - reservas[0].inicio == timedelta(weeks=1)
    assert mensalistas.generate_all(tenant) == 0  # já está tudo criado


def test_week_with_conflict_or_block_becomes_a_warning(tenant, espaco, cliente):
    dia = today() + timedelta(days=2)
    outro = make_cliente(tenant, "Outro", "+5511977770009")
    inicio = datetime.combine(dia, time(19), tzinfo=TZ)
    services.create_reservation(espaco, outro, inicio, inicio + timedelta(hours=1))
    semana_que_vem = inicio + timedelta(weeks=1)
    services.create_block(espaco, semana_que_vem, semana_que_vem + timedelta(hours=2), Bloqueio.Motivo.CHUVA)

    mensalista = make_mensalista(tenant, espaco, cliente)

    avisos = list(MensalistaAviso.all_tenants.filter(mensalista=mensalista).order_by("data"))
    assert [a.data for a in avisos] == [dia, dia + timedelta(weeks=1)]
    assert "reservado" in avisos[0].motivo and "bloqueado" in avisos[1].motivo
    assert jogos(mensalista).count() == mensalistas.HORIZON_WEEKS - 2
    assert mensalistas.generate_all(tenant) == 0  # semana com aviso não é tentada de novo


def test_monthly_billing_creates_a_recurring_receivable(tenant, espaco, cliente):
    mensalista = make_mensalista(
        tenant, espaco, cliente, cobranca="MENSAL", valor=D("320"), dia_vencimento=10
    )
    conta = mensalista.conta_mensal
    assert (conta.valor, conta.recorrencia, conta.categoria, conta.cliente) == (
        D("320"),
        "MENSAL",
        "MENSALIDADE",
        cliente,
    )
    assert conta.vencimento.day == 10 and conta.vencimento >= today()
    assert cliente.nome not in conta.descricao
    assert all(r.valor_total == 0 for r in jogos(mensalista))


def test_ending_cancels_later_games_and_stops_billing(tenant, espaco, cliente):
    mensalista = make_mensalista(tenant, espaco, cliente, cobranca="MENSAL")
    primeiro = jogos(mensalista).first()
    fim = primeiro.inicio.astimezone(TZ).date()

    cancelled = mensalistas.end_mensalista(mensalista, fim)

    assert cancelled == mensalistas.HORIZON_WEEKS - 1
    assert list(jogos(mensalista)) == [primeiro]
    assert ContaReceber.all_tenants.get(pk=mensalista.conta_mensal_id).recorrencia == "NENHUMA"
    assert mensalistas.generate_all(tenant) == 0


def test_changing_the_time_redoes_future_games(tenant, espaco, cliente):
    mensalista = make_mensalista(tenant, espaco, cliente)
    before = Mensalista.all_tenants.get(pk=mensalista.pk)
    mensalista.hora = time(20)
    mensalistas.update_mensalista(mensalista, before)
    horas = {r.inicio.astimezone(TZ).hour for r in jogos(mensalista)}
    assert horas == {20}
    assert jogos(mensalista).count() == mensalistas.HORIZON_WEEKS
    assert (
        Reserva.all_tenants.filter(status="CANCELADA", mensalista=None).count() == mensalistas.HORIZON_WEEKS
    )


def test_a_game_cancelled_by_staff_is_not_recreated(tenant, espaco, cliente):
    mensalista = make_mensalista(tenant, espaco, cliente)
    services.cancel_reservation(jogos(mensalista).first())
    assert mensalistas.generate_all(tenant) == 0
    assert jogos(mensalista).count() == mensalistas.HORIZON_WEEKS - 1


def test_mensalista_games_do_not_message_the_client(
    tenant, espaco, cliente, django_capture_on_commit_callbacks
):
    tenant.whatsapp_ativo = True
    tenant.save()
    cliente.aceite_whatsapp = True
    cliente.save()
    with django_capture_on_commit_callbacks(execute=True):
        make_mensalista(tenant, espaco, cliente)
    assert not Mensagem.all_tenants.filter(cliente=cliente).exists()


def form_data(espaco, cliente, **extra):
    return {
        "cliente": cliente.pk,
        "espaco": espaco.pk,
        "dia_semana": (today() + timedelta(days=2)).weekday(),
        "hora": "19:00",
        "duracao_minutos": 60,
        "data_inicio": today().isoformat(),
        "data_fim": "",
        "cobranca": "POR_JOGO",
        "valor": "90,00",
        "dia_vencimento": 10,
        "observacoes": "",
        **extra,
    }


def test_screens_create_show_and_end(owner_client, tenant, espaco, cliente):
    response = owner_client.post(reverse("agenda:mensalista_create"), form_data(espaco, cliente))
    mensalista = Mensalista.all_tenants.get()
    assert response.url == reverse("agenda:mensalista_detail", args=[mensalista.pk])
    assert cliente.nome in owner_client.get(reverse("agenda:mensalistas")).content.decode()
    detail = owner_client.get(response.url)
    assert len(detail.context["proximas"]) == mensalistas.HORIZON_WEEKS

    url = reverse("agenda:mensalista_encerrar", args=[mensalista.pk])
    data_fim = today().isoformat()
    assert owner_client.post(url, {"data_fim": data_fim}, headers={"HX-Request": "true"}).status_code == 204
    assert jogos(mensalista).count() == 0


def test_form_validates_dates_and_due_day(owner_client, espaco, cliente):
    data = form_data(espaco, cliente, data_fim=(today() - timedelta(days=1)).isoformat(), dia_vencimento=31)
    content = owner_client.post(reverse("agenda:mensalista_create"), data).content.decode()
    assert "precisa ser depois do início" in content
    assert "entre 1 e 28" in content


def test_mensalistas_are_isolated(owner_client, other_tenant):
    espaco = make_espaco(other_tenant, "Quadra alheia")
    alheio = make_mensalista(
        other_tenant, espaco, make_cliente(other_tenant, "Cliente Alheio", "+5511977770000")
    )
    assert owner_client.get(reverse("agenda:mensalista_detail", args=[alheio.pk])).status_code == 404
    assert "Cliente Alheio" not in owner_client.get(reverse("agenda:mensalistas")).content.decode()
    data = form_data(espaco, alheio.cliente)
    content = owner_client.post(reverse("agenda:mensalista_create"), data).content.decode()
    assert "Faça uma escolha válida" in content or "Escolha uma opção válida" in content
