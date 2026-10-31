from datetime import time
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.espacos.models import Espaco, HorarioFuncionamento, TabelaPreco
from apps.espacos.services import PriceRuleOverlap, save_price_rules


def week_payload(**overrides):
    data = {
        "form-TOTAL_FORMS": 7,
        "form-INITIAL_FORMS": 7,
        "form-MIN_NUM_FORMS": 7,
        "form-MAX_NUM_FORMS": 7,
    }
    for dia in range(7):
        data[f"form-{dia}-dia_semana"] = dia
        data[f"form-{dia}-abre"] = "08:00"
        data[f"form-{dia}-fecha"] = "22:00"
        if dia < 5:
            data[f"form-{dia}-aberto"] = "on"
    data.update(overrides)
    return data


def test_create_space_sets_tenant_and_goes_to_hours(owner_client, tenant):
    data = {"nome": "Areia 9", "tipo": "AREIA", "ordem": 0, "ativo": "on"}
    response = owner_client.post(reverse("espacos:create"), data)
    espaco = Espaco.all_tenants.get(nome="Areia 9")
    assert espaco.estabelecimento == tenant
    assert espaco.tema == "areia"
    assert response.url == reverse("espacos:horarios", args=[espaco.pk])


def test_weekly_hours_saves_only_open_days(owner_client, tenant):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome="Sem horários")
    url = reverse("espacos:horarios", args=[espaco.pk])
    assert owner_client.get(url).status_code == 200

    response = owner_client.post(url, week_payload())
    assert response.status_code == 302
    assert response.url == reverse("espacos:precos", args=[espaco.pk])
    saved = HorarioFuncionamento.all_tenants.filter(espaco=espaco)
    assert sorted(h.dia_semana for h in saved) == [0, 1, 2, 3, 4]


def test_weekly_hours_ignores_day_sent_by_browser(owner_client, tenant):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome="Espaço X")
    owner_client.post(reverse("espacos:horarios", args=[espaco.pk]), week_payload(**{"form-1-dia_semana": 0}))
    assert HorarioFuncionamento.all_tenants.filter(espaco=espaco).count() == 5


def test_open_day_without_time_shows_error(owner_client, tenant):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome="Espaço Y")
    url = reverse("espacos:horarios", args=[espaco.pk])
    response = owner_client.post(url, week_payload(**{"form-0-abre": ""}))
    assert response.status_code == 200
    assert "Informe os dois horários." in response.content.decode()
    assert not HorarioFuncionamento.all_tenants.filter(espaco=espaco).exists()


def test_price_form_creates_one_rule_per_day(owner_client, tenant):
    espaco = Espaco.all_tenants.create(estabelecimento=tenant, nome="Espaço Z")
    data = {"dias": [0, 1, 2], "hora_inicio": "08:00", "hora_fim": "18:00", "duracao": 60, "valor": "120,50"}
    assert owner_client.post(reverse("espacos:preco_create", args=[espaco.pk]), data).status_code == 302
    rules = TabelaPreco.all_tenants.filter(espaco=espaco)
    assert rules.count() == 3
    assert {rule.valor for rule in rules} == {Decimal("120.50")}
    assert owner_client.get(reverse("espacos:precos", args=[espaco.pk])).status_code == 200


def test_overlapping_price_rule_is_rejected(espaco):
    with pytest.raises(PriceRuleOverlap):
        save_price_rules(espaco, [0], time(10), time(12), 60, Decimal("10"))


def test_price_overlap_keeps_previous_rules_when_form_fails(owner_client, espaco):
    data = {"dias": [0, 1], "hora_inicio": "10:00", "hora_fim": "12:00", "duracao": 60, "valor": "10"}
    response = owner_client.post(reverse("espacos:preco_create", args=[espaco.pk]), data)
    assert response.status_code == 200
    assert "Já existe uma faixa" in response.content.decode()
    assert TabelaPreco.all_tenants.filter(espaco=espaco).count() == 7


def test_editing_rule_replaces_it_and_can_keep_its_own_range(owner_client, espaco):
    rule = TabelaPreco.all_tenants.filter(espaco=espaco, dia_semana=0).get()
    url = reverse("espacos:preco_update", args=[espaco.pk, rule.pk])
    assert owner_client.get(url).status_code == 200
    data = {"dias": [0], "hora_inicio": "08:00", "hora_fim": "22:00", "duracao": 90, "valor": "200"}
    assert owner_client.post(url, data).status_code == 302
    updated = TabelaPreco.all_tenants.get(espaco=espaco, dia_semana=0)
    assert updated.valor == Decimal("200")
    assert updated.duracao_slot_minutos == 90


def test_failed_edit_keeps_original_rules(owner_client, espaco):
    other = save_price_rules(espaco, [0], time(6), time(7), 60, Decimal("10"))[0]
    rule = TabelaPreco.all_tenants.filter(espaco=espaco, dia_semana=0).exclude(pk=other.pk).get()
    url = reverse("espacos:preco_update", args=[espaco.pk, rule.pk])
    data = {"dias": [0], "hora_inicio": "06:30", "hora_fim": "22:00", "duracao": 60, "valor": "200"}
    assert owner_client.post(url, data).status_code == 200
    assert TabelaPreco.all_tenants.filter(espaco=espaco).count() == 8


def test_price_list_groups_equal_rules(owner_client, espaco):
    save_price_rules(espaco, [0, 1, 2], time(6), time(7), 60, Decimal("10"))
    save_price_rules(espaco, [0, 2], time(7), time(8), 60, Decimal("10"))
    response = owner_client.get(reverse("espacos:precos", args=[espaco.pk]))
    labels = sorted(row["label"] for row in response.context["precos"])
    assert labels == ["Segunda a quarta", "Segunda, Quarta", "Todos os dias"]


def test_delete_removes_the_whole_group(owner_client, espaco):
    rule = TabelaPreco.all_tenants.filter(espaco=espaco).first()
    owner_client.post(reverse("espacos:preco_delete", args=[espaco.pk, rule.pk]))
    assert not TabelaPreco.all_tenants.filter(espaco=espaco).exists()


def test_edit_form_comes_with_all_days_of_the_group(owner_client, espaco):
    rule = TabelaPreco.all_tenants.filter(espaco=espaco).first()
    response = owner_client.get(reverse("espacos:preco_update", args=[espaco.pk, rule.pk]))
    assert sorted(response.context["form"].initial["dias"]) == list(range(7))


def test_delete_rule(owner_client, espaco):
    rule = TabelaPreco.all_tenants.filter(espaco=espaco).first()
    assert owner_client.post(reverse("espacos:preco_delete", args=[espaco.pk, rule.pk])).status_code == 302
    assert not TabelaPreco.all_tenants.filter(pk=rule.pk).exists()


def test_inactive_space_leaves_the_agenda(owner_client, espaco):
    espaco.ativo = False
    espaco.save()
    assert owner_client.get(reverse("agenda:day")).context["grid"] is None
