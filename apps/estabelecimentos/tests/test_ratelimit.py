from django.test import RequestFactory, override_settings

from apps.estabelecimentos.ratelimit import allow, client_ip


def request(forwarded=""):
    headers = {"HTTP_X_FORWARDED_FOR": forwarded} if forwarded else {}
    return RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", **headers)


def test_without_proxy_the_header_is_ignored():
    assert client_ip(request("1.2.3.4")) == "10.0.0.1"


@override_settings(NUM_PROXIES=1)
def test_behind_one_proxy_uses_the_address_it_saw():
    assert client_ip(request("6.6.6.6, 1.2.3.4")) == "1.2.3.4"  # o primeiro foi inventado pelo cliente
    assert client_ip(request()) == "10.0.0.1"


def test_allow_counts_within_the_window():
    assert [allow("teste", 2, 60) for _ in range(3)] == [True, True, False]
