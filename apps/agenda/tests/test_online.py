from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda import online, services
from apps.agenda.models import Reserva, ReservaEvento
from apps.espacos.models import TabelaPreco
from apps.financeiro import pix
from apps.financeiro.models import Caixa, ContaReceber, Lancamento, Pagamento
from apps.pdv import services as pdv_services
from conftest import TZ, cashier, make_cliente, make_espaco, with_register

D = Decimal


@pytest.fixture
def loja(tenant):
    tenant.reserva_online_ativa = True
    tenant.chave_pix = "pix@arena.test"
    tenant.pix_cidade = "São Paulo"
    tenant.save()
    return tenant


@pytest.fixture
def quadra(loja):
    espaco = make_espaco(loja, "Areia 1")
    TabelaPreco.all_tenants.filter(espaco=espaco).update(valor_sinal=D("30"))
    return espaco


def amanha(hour=10):
    day = timezone.now().astimezone(TZ).date() + timedelta(days=1)
    return datetime.combine(day, time(hour), tzinfo=TZ)


def book(loja, quadra, inicio=None, nome="Lia Souza", telefone="(11) 97777-1111", aceite=False):
    return online.book_online(loja, quadra, inicio or amanha(), nome, telefone, aceite)


# --- Pix


def test_crc16_matches_the_standard_check_value():
    assert pix.crc16("123456789") == "29B1"


def test_brcode_has_key_amount_txid_and_valid_crc():
    codigo = pix.brcode("pix@arena.test", "Arena Ação & Cia", "São Paulo", D("30"), "QNMTESTE123")
    assert codigo.startswith("000201")
    assert "0014br.gov.bcb.pix0114pix@arena.test" in codigo
    assert "540530.00" in codigo
    assert "5914ARENA ACAO CIA" in codigo
    assert "6009SAO PAULO" in codigo
    assert "0511QNMTESTE123" in codigo
    assert codigo[-4:] == pix.crc16(codigo[:-4])


def test_txid_and_qr_code():
    txid = pix.new_txid()
    assert len(txid) == 25 and txid.isalnum()
    assert "<svg" in pix.qr_svg(pix.brcode("chave", "Arena", "SP", D("1"), txid))


# --- Reserva pelo link


def test_booking_with_deposit_is_pending_and_holds_the_slot(loja, quadra):
    reserva, pagamento = book(loja, quadra)

    assert reserva.status == Reserva.Status.PENDENTE
    assert reserva.origem == Reserva.Origem.ONLINE
    assert reserva.valor_sinal == D("30")
    assert reserva.expira_em is not None
    assert pagamento.valor == D("30")
    assert pagamento.copia_e_cola.startswith("000201")
    assert ContaReceber.all_tenants.get(reserva=reserva).valor == D("100")
    assert amanha() not in online.public_starts(quadra, amanha().date())


def test_booking_without_deposit_or_pix_key_is_confirmed(loja, quadra):
    TabelaPreco.all_tenants.filter(espaco=quadra).update(valor_sinal=None)
    reserva, pagamento = book(loja, quadra)
    assert reserva.status == Reserva.Status.CONFIRMADA and pagamento is None

    TabelaPreco.all_tenants.filter(espaco=quadra).update(valor_sinal=D("30"))
    loja.chave_pix = ""
    loja.save()
    reserva, pagamento = book(loja, quadra, inicio=amanha(12), telefone="(11) 97777-2222")
    assert reserva.status == Reserva.Status.CONFIRMADA and pagamento is None


@pytest.mark.parametrize(
    ("ajuste", "mensagem"),
    [
        ("desligado", "não está recebendo"),
        ("ocupado", "acabou de ser ocupado"),
        ("passado", "acabou de ser ocupado"),
    ],
)
def test_booking_is_refused(loja, quadra, cliente, ajuste, mensagem):
    inicio = amanha()
    if ajuste == "desligado":
        loja.reserva_online_ativa = False
        loja.save()
    elif ajuste == "ocupado":
        services.create_reservation(quadra, cliente, inicio, inicio + timedelta(hours=1))
    else:
        inicio = timezone.now().astimezone(TZ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    with pytest.raises(online.OnlineBookingError, match=mensagem):
        book(loja, quadra, inicio=inicio)


def test_one_pending_booking_per_client(loja, quadra):
    book(loja, quadra)
    with pytest.raises(online.OnlineBookingError, match="aguardando o pagamento"):
        book(loja, quadra, inicio=amanha(12))


def test_provider_confirmation_goes_to_the_online_register(loja, quadra):
    reserva, pagamento = book(loja, quadra)

    online.confirm_pix_payment(pagamento)
    online.confirm_pix_payment(pagamento)  # aviso repetido do provedor não lança duas vezes

    reserva.refresh_from_db()
    pagamento.refresh_from_db()
    assert reserva.status == Reserva.Status.CONFIRMADA
    assert reserva.valor_pago == D("30")
    assert pagamento.status == Pagamento.Status.PAGO
    assert pagamento.lancamento.caixa.tipo == Caixa.Tipo.ONLINE
    assert Lancamento.all_tenants.filter(reserva=reserva).count() == 1


def test_unpaid_booking_expires_and_frees_the_slot(loja, quadra):
    reserva, pagamento = book(loja, quadra)
    assert services.expire_pending_reservations(loja, now=reserva.expira_em - timedelta(minutes=1)) == 0

    assert services.expire_pending_reservations(loja, now=reserva.expira_em + timedelta(minutes=1)) == 1

    reserva.refresh_from_db()
    pagamento.refresh_from_db()
    assert reserva.status == Reserva.Status.CANCELADA
    assert ReservaEvento.all_tenants.filter(reserva=reserva, acao="EXPIRADA").exists()
    assert pagamento.status == Pagamento.Status.EXPIRADO
    assert ContaReceber.all_tenants.get(reserva=reserva).status == "CANCELADA"
    assert amanha() in online.public_starts(quadra, amanha().date())


def test_late_payment_is_flagged_and_does_not_reopen_the_slot(loja, quadra):
    reserva, pagamento = book(loja, quadra)
    services.expire_pending_reservations(loja, now=reserva.expira_em + timedelta(minutes=1))

    pagamento = online.confirm_pix_payment(pagamento)

    assert pagamento.status == Pagamento.Status.PAGO_ATRASADO
    assert not Lancamento.all_tenants.exists()
    assert Reserva.all_tenants.get(pk=reserva.pk).status == Reserva.Status.CANCELADA


def test_staff_receiving_the_deposit_confirms_the_booking(loja, quadra, owner):
    reserva, pagamento = book(loja, quadra)
    with_register(owner)

    pdv_services.charge_reservation(reserva, D("30"), "PIX", owner)

    reserva.refresh_from_db()
    pagamento.refresh_from_db()
    assert reserva.status == Reserva.Status.CONFIRMADA
    assert pagamento.status == Pagamento.Status.PAGO
    assert pagamento.lancamento.caixa.operador == owner


def test_partial_deposit_keeps_the_booking_pending(loja, quadra):
    reserva, _ = book(loja, quadra)
    usuario = cashier(loja)
    pdv_services.charge_reservation(reserva, D("10"), "DINHEIRO", usuario)
    assert Reserva.all_tenants.get(pk=reserva.pk).status == Reserva.Status.PENDENTE


# --- Telas públicas


def test_public_page_lists_spaces_and_free_times(client, loja, quadra):
    response = client.get(
        reverse("publico:reservar", args=[loja.slug]), {"data": amanha().date().isoformat()}
    )
    assert response.status_code == 200
    assert "Areia 1" in response.content.decode()
    assert amanha() in response.context["starts"]


def test_public_page_when_online_booking_is_off(client, tenant):
    response = client.get(reverse("publico:reservar", args=[tenant.slug]))
    assert "indisponíveis" in response.content.decode()
    assert client.get(reverse("publico:reservar", args=["nao-existe"])).status_code == 404


def booking_post(client, loja, quadra, inicio=None, **extra):
    inicio = inicio or amanha()
    data = {
        "espaco": quadra.pk,
        "data": inicio.date().isoformat(),
        "hora": f"{inicio:%H:%M}",
        "nome": "Lia Souza",
        "telefone": "(11) 97777-1111",
        "aceite_whatsapp": "on",
        **extra,
    }
    return client.post(reverse("publico:reservar", args=[loja.slug]), data)


def test_public_booking_flow_until_payment_is_confirmed(client, loja, quadra):
    response = booking_post(client, loja, quadra)
    assert response.status_code == 302
    pagamento = Pagamento.all_tenants.get()
    assert pagamento.reserva.cliente.aceite_whatsapp is True

    page = client.get(response.url)
    assert "Copiar código Pix" in page.content.decode()
    assert "<svg" in page.content.decode()

    simulate = reverse("publico:simular", args=[loja.slug, online.payment_token(pagamento)])
    assert client.post(simulate).status_code == 302
    assert "Reserva confirmada" in client.get(response.url).content.decode()


def test_payment_token_cannot_be_forged_or_used_on_another_establishment(client, loja, quadra, other_tenant):
    book(loja, quadra)
    pagamento = Pagamento.all_tenants.get()
    token = online.payment_token(pagamento)
    assert client.get(reverse("publico:pagamento", args=[loja.slug, token + "x"])).status_code == 404
    assert client.get(reverse("publico:pagamento", args=[other_tenant.slug, token])).status_code == 404


def test_public_booking_refuses_another_establishments_space(client, loja, quadra, other_tenant):
    alheio = make_espaco(other_tenant, "Quadra alheia")
    response = booking_post(client, loja, alheio)
    assert "Escolha um dos espaços" in response.content.decode()
    assert not Reserva.all_tenants.exists()


def test_public_booking_is_rate_limited(client, loja, quadra):
    for hour in range(8, 18):
        booking_post(client, loja, quadra, inicio=amanha(hour), telefone=f"(11) 97777-{1000 + hour}")
    response = booking_post(client, loja, quadra, inicio=amanha(19), telefone="(11) 97777-3999")
    assert response.status_code == 429


def test_pending_booking_shows_on_the_staff_agenda(owner_client, loja, quadra):
    reserva, _ = book(loja, quadra)
    content = owner_client.get(
        reverse("agenda:reserva_detail", args=[reserva.pk]), headers={"HX-Request": "true"}
    )
    assert "Aguardando o sinal" in content.content.decode()
    grid = owner_client.get(reverse("agenda:day"), {"data": reserva.inicio.astimezone(TZ).date().isoformat()})
    assert "Aguardando sinal" in grid.content.decode()


def test_cancel_modal_explains_the_cancellation_policy(owner_client, loja, quadra, owner):
    reserva, _ = book(loja, quadra)
    with_register(owner)
    pdv_services.charge_reservation(reserva, D("30"), "PIX", owner)
    content = owner_client.get(
        reverse("agenda:reserva_cancel", args=[reserva.pk]), headers={"HX-Request": "true"}
    ).content.decode()
    assert "sinal fica com o estabelecimento" in content


def test_cliente_reuses_the_same_record(loja, quadra):
    existente = make_cliente(loja, "Lia", "+5511977771111")
    reserva, _ = book(loja, quadra)
    assert reserva.cliente == existente
