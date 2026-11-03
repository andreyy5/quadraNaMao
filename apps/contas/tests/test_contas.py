import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from conftest import make_user

Usuario = get_user_model()

OWNER_ONLY = [
    "espacos:list",
    "espacos:create",
    "estabelecimentos:ajustes",
    "contas:equipe",
    "contas:equipe_create",
]
ALL_ROLES = [
    "relatorios:dashboard",
    "agenda:day",
    "agenda:week",
    "clientes:list",
    "agenda:bloqueio_list",
    "contas:senha",
]


def test_login_with_email_case_insensitive_and_shows_brand(client, owner):
    page = client.get(reverse("contas:login"))
    assert "QuadraNaMão!" in page.content.decode()
    response = client.post(
        reverse("contas:login"), {"username": "DONO@a.test", "password": "senha-forte-123"}
    )
    assert response.status_code == 302
    assert response.url == reverse("relatorios:dashboard")


def test_wrong_password_shows_message(client, owner):
    response = client.post(reverse("contas:login"), {"username": owner.email, "password": "errada"})
    assert response.status_code == 200
    assert "E-mail ou senha incorretos" in response.content.decode()


@pytest.mark.parametrize("route", OWNER_ONLY + ALL_ROLES)
def test_anonymous_is_sent_to_login(client, db, route):
    response = client.get(reverse(route))
    assert response.status_code == 302
    assert response.url.startswith(reverse("contas:login"))


@pytest.mark.parametrize("papel", ["GERENTE", "ATENDENTE"])
@pytest.mark.parametrize("route", OWNER_ONLY)
def test_staff_cannot_open_owner_screens(client, tenant, papel, route):
    client.force_login(make_user(tenant, "pessoa@a.test", papel))
    assert client.get(reverse(route)).status_code == 403


@pytest.mark.parametrize("papel", ["DONO", "GERENTE", "ATENDENTE"])
@pytest.mark.parametrize("route", ALL_ROLES)
def test_every_role_opens_daily_screens(client, tenant, papel, route):
    client.force_login(make_user(tenant, "pessoa@a.test", papel))
    assert client.get(reverse(route)).status_code == 200


def test_owner_opens_owner_screens(owner_client):
    for route in OWNER_ONLY:
        assert owner_client.get(reverse(route)).status_code == 200


def test_attendant_does_not_see_owner_menu(client, attendant):
    client.force_login(attendant)
    assert reverse("espacos:list") not in client.get(reverse("relatorios:dashboard")).content.decode()


def test_superuser_without_tenant_goes_to_admin(client, db):
    client.force_login(Usuario.objects.create_superuser("admin@test.local", "senha-forte-123"))
    response = client.get(reverse("relatorios:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("admin:index")


def test_admin_pages_and_user_creation(client, tenant):
    client.force_login(Usuario.objects.create_superuser("admin@test.local", "senha-forte-123"))
    assert client.get(reverse("admin:contas_usuario_changelist")).status_code == 200
    assert client.get(reverse("admin:estabelecimentos_estabelecimento_changelist")).status_code == 200
    assert client.get(reverse("admin:contas_usuario_add")).status_code == 200
    data = {
        "email": "piloto@test.local",
        "nome": "Piloto",
        "papel": "DONO",
        "estabelecimento": tenant.pk,
        "password1": "uma-senha-boa-987",
        "password2": "uma-senha-boa-987",
    }
    response = client.post(reverse("admin:contas_usuario_add"), data)
    assert response.status_code == 302
    user = Usuario.objects.get(email="piloto@test.local")
    assert user.check_password("uma-senha-boa-987")
    assert client.get(reverse("admin:contas_usuario_change", args=[user.pk])).status_code == 200


def test_create_team_member_in_own_tenant(owner_client, tenant):
    data = {
        "nome": "Nova Pessoa",
        "email": "Nova@a.test",
        "papel": "ATENDENTE",
        "password": "uma-senha-boa-987",
    }
    assert owner_client.post(reverse("contas:equipe_create"), data).status_code == 302
    user = Usuario.objects.get(email="nova@a.test")
    assert user.estabelecimento == tenant
    assert user.check_password("uma-senha-boa-987")


def test_weak_team_password_is_rejected(owner_client):
    data = {"nome": "Nova", "email": "n@a.test", "papel": "ATENDENTE", "password": "123"}
    assert owner_client.post(reverse("contas:equipe_create"), data).status_code == 200
    assert not Usuario.objects.filter(email="n@a.test").exists()


def test_owner_cannot_lock_themselves_out(owner_client, owner):
    url = reverse("contas:equipe_update", args=[owner.pk])
    response = owner_client.post(url, {"nome": owner.nome, "papel": "ATENDENTE"})
    assert response.status_code == 200
    owner.refresh_from_db()
    assert owner.is_active
    assert owner.papel == "DONO"


def test_password_change_keeps_session(client, attendant):
    client.force_login(attendant)
    data = {
        "old_password": "senha-forte-123",
        "new_password1": "outra-senha-boa-55",
        "new_password2": "outra-senha-boa-55",
    }
    assert client.post(reverse("contas:senha"), data).status_code == 302
    assert client.get(reverse("relatorios:dashboard")).status_code == 200


def test_logout_requires_post(owner_client):
    assert owner_client.get(reverse("contas:logout")).status_code == 405
    assert owner_client.post(reverse("contas:logout")).status_code == 302


def test_login_is_blocked_after_repeated_failures(client, owner):
    url = reverse("contas:login")
    for _ in range(5):
        client.post(url, {"username": owner.email, "password": "errada"})
    blocked = client.post(url, {"username": owner.email, "password": "senha-forte-123"})
    assert blocked.status_code == 429
    assert "Muitas tentativas" in blocked.content.decode()
    assert "_auth_user_id" not in client.session


def test_failures_for_one_email_do_not_block_another(client, owner, attendant):
    url = reverse("contas:login")
    for _ in range(5):
        client.post(url, {"username": owner.email, "password": "errada"})
    response = client.post(url, {"username": attendant.email, "password": "senha-forte-123"})
    assert response.status_code == 302
