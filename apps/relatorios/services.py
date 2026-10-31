from django.urls import reverse

from apps.agenda.models import Reserva
from apps.espacos.models import Espaco, HorarioFuncionamento, TabelaPreco


def setup_checklist(estabelecimento):
    """Primeiros passos do dono. Devolve None quando tudo já foi feito."""
    espaco = Espaco.all_tenants.filter(estabelecimento=estabelecimento).first()
    has_hours = HorarioFuncionamento.all_tenants.filter(estabelecimento=estabelecimento).exists()
    has_prices = TabelaPreco.all_tenants.filter(estabelecimento=estabelecimento).exists()
    has_booking = Reserva.all_tenants.filter(estabelecimento=estabelecimento).exists()

    hours_url = reverse("espacos:horarios", args=[espaco.pk]) if espaco else reverse("espacos:create")
    prices_url = reverse("espacos:precos", args=[espaco.pk]) if espaco else reverse("espacos:create")
    steps = [
        {
            "label": "Cadastrar o primeiro espaço",
            "done": espaco is not None,
            "url": reverse("espacos:create"),
        },
        {"label": "Definir os horários de funcionamento", "done": has_hours, "url": hours_url},
        {"label": "Montar a tabela de preços", "done": has_prices, "url": prices_url},
        {"label": "Fazer a primeira reserva", "done": has_booking, "url": reverse("agenda:day")},
    ]
    return None if all(step["done"] for step in steps) else steps
