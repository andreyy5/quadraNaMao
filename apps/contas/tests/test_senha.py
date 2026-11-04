import re

from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from apps.contas.views import login_keys

URL = "/conta/senha/esqueci/"


def ask(client, email):
    return client.post(reverse("contas:senha_esqueci"), {"email": email})


def link_from(message):
    return re.search(r"https?://[^/\s]+(/conta/senha/redefinir/\S+/)", message.body).group(1)


def test_login_page_links_to_password_recovery(client):
    assert reverse("contas:senha_esqueci") == URL
    assert URL in client.get(reverse("contas:login")).content.decode()


def test_sends_a_link_that_resets_the_password(client, owner):
    response = ask(client, owner.email.upper())
    assert response.url == reverse("contas:senha_enviada")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [owner.email]
    assert "QuadraNaMão!" in message.subject
    assert "vale por 2 horas" in message.body
    assert message.alternatives and "Criar senha nova" in message.alternatives[0][0]

    form_page = client.get(link_from(message), follow=True)
    assert form_page.context["validlink"]
    done = client.post(
        form_page.redirect_chain[-1][0],
        {"new_password1": "outra-senha-forte-9", "new_password2": "outra-senha-forte-9"},
        follow=True,
    )
    assert "Senha redefinida" in done.content.decode()
    owner.refresh_from_db()
    assert owner.check_password("outra-senha-forte-9")

    # O link só funciona uma vez.
    again = client.get(link_from(message), follow=True)
    assert not again.context["validlink"]
    assert "Link vencido" in again.content.decode()


def test_unknown_or_inactive_email_gets_the_same_answer_and_no_message(client, attendant):
    attendant.is_active = False
    attendant.save()
    for email in ("ninguem@exemplo.com", attendant.email):
        response = ask(client, email)
        assert response.url == reverse("contas:senha_enviada")
    assert mail.outbox == []


def test_limits_messages_per_email_without_saying_so(client, owner):
    for _ in range(4):
        response = ask(client, owner.email)
        assert response.url == reverse("contas:senha_enviada")
    assert len(mail.outbox) == 3


def test_limits_requests_per_address(client, owner):
    for index in range(10):
        ask(client, f"pessoa{index}@exemplo.com")
    blocked = ask(client, owner.email)
    assert blocked.status_code == 429
    assert "Muitos pedidos" in blocked.content.decode()
    assert mail.outbox == []


def test_reset_clears_the_login_block(client, owner, rf):
    login = reverse("contas:login")
    for _ in range(5):
        client.post(login, {"username": owner.email, "password": "errada"})
    assert client.post(login, {"username": owner.email, "password": "x"}).status_code == 429

    ask(client, owner.email)
    page = client.get(link_from(mail.outbox[0]), follow=True)
    client.post(
        page.redirect_chain[-1][0],
        {"new_password1": "outra-senha-forte-9", "new_password2": "outra-senha-forte-9"},
    )
    response = client.post(login, {"username": owner.email, "password": "outra-senha-forte-9"})
    assert response.status_code == 302


def test_weak_password_is_refused(client, owner):
    ask(client, owner.email)
    page = client.get(link_from(mail.outbox[0]), follow=True)
    response = client.post(page.redirect_chain[-1][0], {"new_password1": "123", "new_password2": "123"})
    assert response.status_code == 200 and response.context["form"].errors
    owner.refresh_from_db()
    assert not owner.check_password("123")


def test_login_keys_are_case_insensitive(rf):
    request = rf.post("/", REMOTE_ADDR="10.0.0.1")
    assert login_keys(request, " Dono@Arena.TEST ")[0] == "login:10.0.0.1:dono@arena.test"
    assert cache.get(login_keys(request, "x")[0]) is None
