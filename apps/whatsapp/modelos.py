"""Modelos de mensagem (templates) do WhatsApp.

Fora da janela de 24 horas depois da última mensagem do cliente, a Meta só entrega modelos aprovados.
O texto de cada um precisa ser cadastrado no painel da Meta exatamente como está aqui, na categoria
Utilidade e no idioma Português (BR). O passo a passo está em docs/whatsapp.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Modelo:
    name: str
    descricao: str
    corpo: str
    exemplo: tuple

    def render(self, params):
        text = self.corpo
        for index, value in enumerate(params, start=1):
            text = text.replace("{{" + str(index) + "}}", str(value))
        return text


MODELOS = {
    modelo.name: modelo
    for modelo in [
        Modelo(
            "reserva_confirmada",
            "Confirmação de reserva, também usada quando ela é remarcada.",
            "Olá, {{1}}! Sua reserva em {{2}} está confirmada: {{3}}, {{4}}, das {{5}}. Até lá!",
            ("João", "Arena Demo", "Areia 1", "qui., 05/11", "19:00 às 20:00"),
        ),
        Modelo(
            "sinal_pendente",
            "Pedido de reserva pelo link público, aguardando o sinal.",
            "Olá, {{1}}! Recebemos seu pedido de reserva em {{2}} para {{3}}, {{4}}. "
            "Para garantir o horário, pague o sinal de {{5}} até as {{6}} neste link: {{7}} . "
            "Qualquer dúvida, é só responder.",
            (
                "João",
                "Arena Demo",
                "qui., 05/11",
                "19:00",
                "R$ 30,00",
                "18:30",
                "https://exemplo.com/r/arena/p/abc",
            ),
        ),
        Modelo(
            "lembrete_reserva",
            "Lembrete algumas horas antes do jogo.",
            "Olá, {{1}}! Passando para lembrar do seu jogo hoje às {{2}} em {{3}}, na {{4}}. Bom jogo!",
            ("João", "19:00", "Areia 1", "Arena Demo"),
        ),
        Modelo(
            "reserva_cancelada",
            "Reserva cancelada pelo estabelecimento.",
            "Olá, {{1}}. Sua reserva em {{2}} de {{3}}, {{4}}, foi cancelada. "
            "Se quiser marcar outro horário, é só responder esta mensagem.",
            ("João", "Arena Demo", "qui., 05/11", "19:00"),
        ),
        Modelo(
            "reserva_expirada",
            "Pedido do link público cancelado porque o sinal não foi pago no prazo.",
            "Olá, {{1}}. O prazo para pagar o sinal da reserva em {{2}} de {{3}}, {{4}}, terminou "
            "e o horário foi liberado. Se ainda quiser jogar, faça um novo pedido.",
            ("João", "Arena Demo", "qui., 05/11", "19:00"),
        ),
        Modelo(
            "aviso_remarcacao",
            "Aviso de bloqueio (chuva, manutenção, evento) que atinge a reserva.",
            "Olá, {{1}}. Por causa de {{2}}, não vai dar para usar {{3}} em {{4}}, {{5}}. "
            "Responda esta mensagem para remarcarmos o seu horário.",
            ("João", "chuva", "Areia 1", "qui., 05/11", "19:00"),
        ),
    ]
}

# Modelo que a própria Meta cria em toda conta nova: serve para testar a ligação.
MODELO_TESTE = "hello_world"
