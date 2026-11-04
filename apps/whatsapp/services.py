"""Regras do WhatsApp: quando mandar, para quem e como tratar o que chega pelo webhook.

Só recebe mensagem automática quem aceitou (LGPD). Quem responde SAIR deixa de receber na hora.
Usa `all_tenants` com filtro explícito, porque roda em tarefas e no webhook, fora de uma requisição.
"""

import hashlib
import hmac
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.agenda.models import Reserva
from apps.clientes.models import Cliente
from apps.estabelecimentos.models import Estabelecimento
from apps.estabelecimentos.templatetags.ui import brl

from .modelos import MODELO_TESTE, MODELOS
from .models import Mensagem
from .provider import ProviderError, get_provider

WINDOW = timedelta(hours=24)
OPT_OUT_WORDS = {"sair", "parar", "stop", "descadastrar", "nao quero mais"}
OPT_IN_WORDS = {"voltar", "quero receber"}
STATUS_ORDER = [
    Mensagem.Status.PENDENTE,
    Mensagem.Status.ENVIADA,
    Mensagem.Status.ENTREGUE,
    Mensagem.Status.LIDA,
]
META_STATUS = {
    "sent": Mensagem.Status.ENVIADA,
    "delivered": Mensagem.Status.ENTREGUE,
    "read": Mensagem.Status.LIDA,
    "failed": Mensagem.Status.FALHOU,
}


class WhatsAppError(Exception):
    """Regra do WhatsApp violada. A mensagem pode ser mostrada ao usuário."""


def _plain(text):
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip(" .!")


def window_open(estabelecimento, telefone):
    """Dentro de 24 horas da última mensagem do cliente, dá para mandar texto livre."""
    return Mensagem.all_tenants.filter(
        estabelecimento=estabelecimento,
        telefone=telefone,
        direcao=Mensagem.Direcao.ENTRADA,
        criado_em__gte=timezone.now() - WINDOW,
    ).exists()


def _queue(
    estabelecimento,
    telefone,
    *,
    cliente=None,
    modelo=None,
    params=(),
    texto="",
    reserva=None,
    usuario=None,
    now=False,
):
    from .tasks import deliver_message

    mensagem = Mensagem.all_tenants.create(
        estabelecimento=estabelecimento,
        cliente=cliente,
        telefone=telefone,
        direcao=Mensagem.Direcao.SAIDA,
        tipo=Mensagem.Tipo.TEMPLATE if modelo else Mensagem.Tipo.TEXTO,
        template=modelo or "",
        parametros=list(params),
        corpo=MODELOS[modelo].render(params) if modelo in MODELOS else texto or modelo or "",
        reserva=reserva,
        enviada_por=usuario,
    )
    if now:
        deliver(mensagem.pk)
        mensagem.refresh_from_db()
    else:
        transaction.on_commit(lambda: deliver_message.delay(mensagem.pk))
    return mensagem


def deliver(mensagem_id):
    """Entrega uma mensagem da fila. Uma falha fica registrada no histórico, com o motivo."""
    mensagem = Mensagem.all_tenants.select_related("estabelecimento").filter(pk=mensagem_id).first()
    if mensagem is None or mensagem.status != Mensagem.Status.PENDENTE:
        return
    language = "en_US" if mensagem.template == MODELO_TESTE else "pt_BR"
    try:
        wa_id = get_provider().send(
            phone_number_id=mensagem.estabelecimento.whatsapp_phone_number_id,
            to=mensagem.telefone,
            template=mensagem.template or None,
            params=mensagem.parametros,
            language=language,
            text=mensagem.corpo if not mensagem.template else None,
        )
    except ProviderError as exc:
        mensagem.status = Mensagem.Status.FALHOU
        mensagem.erro = str(exc)[:300]
        mensagem.save(update_fields=["status", "erro", "atualizado_em"])
        return
    mensagem.status = Mensagem.Status.ENVIADA
    mensagem.wa_id = wa_id
    mensagem.save(update_fields=["status", "wa_id", "atualizado_em"])


def enabled(estabelecimento=None):
    """Módulo ligado no sistema (WHATSAPP_ENABLED) e, se informado, ligado no estabelecimento."""
    if not settings.WHATSAPP_ENABLED:
        return False
    return estabelecimento is None or estabelecimento.whatsapp_ativo


def can_message(cliente):
    return enabled(cliente.estabelecimento) and cliente.aceite_whatsapp and cliente.anonimizado_em is None


def _when(reserva):
    local = timezone.localtime(reserva.inicio, reserva.estabelecimento.timezone)
    fim = timezone.localtime(reserva.fim, reserva.estabelecimento.timezone)
    weekday = ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."][local.weekday()]
    return f"{weekday}, {local:%d/%m}", f"{local:%H:%M}", f"{local:%H:%M} às {fim:%H:%M}"


def notify_reservation(reserva_id, kind, payment_url=""):
    """Avisa o cliente sobre a reserva. Só para quem aceitou e só sobre jogos que ainda não começaram."""
    reserva = (
        Reserva.all_tenants.select_related("cliente", "espaco", "estabelecimento")
        .filter(pk=reserva_id)
        .first()
    )
    if reserva is None or not can_message(reserva.cliente) or reserva.inicio <= timezone.now():
        return None
    estabelecimento, cliente = reserva.estabelecimento, reserva.cliente
    nome = cliente.nome.split()[0]
    dia, hora, horario = _when(reserva)
    if kind in ("confirmada", "remarcada"):
        modelo, params = "reserva_confirmada", [nome, estabelecimento.nome, reserva.espaco.nome, dia, horario]
    elif kind == "pendente":
        prazo = timezone.localtime(reserva.expira_em, estabelecimento.timezone)
        modelo = "sinal_pendente"
        params = [
            nome,
            estabelecimento.nome,
            dia,
            hora,
            brl(reserva.valor_sinal),
            f"{prazo:%H:%M}",
            payment_url,
        ]
    elif kind == "lembrete":
        modelo, params = "lembrete_reserva", [nome, hora, reserva.espaco.nome, estabelecimento.nome]
    elif kind == "cancelada":
        modelo, params = "reserva_cancelada", [nome, estabelecimento.nome, dia, hora]
    elif kind == "expirada":
        modelo, params = "reserva_expirada", [nome, estabelecimento.nome, dia, hora]
    else:
        raise ValueError(kind)
    return _queue(
        estabelecimento, cliente.telefone, cliente=cliente, modelo=modelo, params=params, reserva=reserva
    )


def notify_block(bloqueio, reservas, usuario=None):
    """Aviso de chuva, manutenção ou evento para as reservas atingidas. Devolve quantas mensagens saíram."""
    sent = 0
    for reserva in reservas:
        if not can_message(reserva.cliente) or reserva.inicio <= timezone.now():
            continue
        dia, hora, _ = _when(reserva)
        motivo = bloqueio.get_motivo_display().lower()
        params = [reserva.cliente.nome.split()[0], motivo, reserva.espaco.nome, dia, hora]
        _queue(
            reserva.estabelecimento,
            reserva.cliente.telefone,
            cliente=reserva.cliente,
            modelo="aviso_remarcacao",
            params=params,
            reserva=reserva,
            usuario=usuario,
        )
        sent += 1
    return sent


def reply(estabelecimento, telefone, texto, usuario):
    """Resposta livre da equipe. A Meta só aceita dentro de 24 horas da última mensagem do cliente."""
    if not estabelecimento.whatsapp_ativo:
        raise WhatsAppError("O envio pelo WhatsApp está desligado em Ajustes.")
    if not window_open(estabelecimento, telefone):
        raise WhatsAppError(
            "Já passaram 24 horas da última mensagem do cliente. Agora o WhatsApp só aceita modelos aprovados."
        )
    cliente = Cliente.all_tenants.filter(estabelecimento=estabelecimento, telefone=telefone).first()
    return _queue(estabelecimento, telefone, cliente=cliente, texto=texto.strip(), usuario=usuario)


def send_test(estabelecimento, telefone, usuario):
    """Manda o modelo de teste da Meta na hora, para a tela já mostrar se a ligação funcionou."""
    return _queue(estabelecimento, telefone, modelo=MODELO_TESTE, usuario=usuario, now=True)


def send_due_reminders(now=None):
    """Lembrete das reservas que começam dentro do prazo configurado em cada estabelecimento."""
    if not enabled():
        return 0
    now = now or timezone.now()
    sent = 0
    for estabelecimento in Estabelecimento.objects.filter(
        ativo=True, whatsapp_ativo=True, lembrete_horas__gt=0
    ):
        due = Reserva.all_tenants.filter(
            estabelecimento=estabelecimento,
            status=Reserva.Status.CONFIRMADA,
            lembrete_enviado_em__isnull=True,
            inicio__gt=now,
            inicio__lte=now + timedelta(hours=estabelecimento.lembrete_horas),
        )
        for reserva in due:
            # Marca antes de enviar: duas rotinas ao mesmo tempo não mandam o lembrete duas vezes.
            claimed = Reserva.all_tenants.filter(pk=reserva.pk, lembrete_enviado_em__isnull=True).update(
                lembrete_enviado_em=now
            )
            if claimed and notify_reservation(reserva.pk, "lembrete"):
                sent += 1
    return sent


# --- Webhook


def valid_signature(body, header):
    """Confere a assinatura X-Hub-Signature-256 que a Meta calcula com o segredo do aplicativo."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _apply_status(status):
    mensagem = Mensagem.all_tenants.filter(wa_id=status.get("id", "")).first()
    novo = META_STATUS.get(status.get("status"))
    if mensagem is None or novo is None:
        return
    if novo == Mensagem.Status.FALHOU:
        errors = status.get("errors") or [{}]
        mensagem.status = novo
        mensagem.erro = (errors[0].get("title") or errors[0].get("message") or "Falha na entrega")[:300]
        mensagem.save(update_fields=["status", "erro", "atualizado_em"])
        return
    # Os avisos podem chegar fora de ordem: "entregue" depois de "lida" não volta o status.
    if mensagem.status in STATUS_ORDER and STATUS_ORDER.index(novo) > STATUS_ORDER.index(mensagem.status):
        mensagem.status = novo
        mensagem.save(update_fields=["status", "atualizado_em"])


def _receive(estabelecimento, message):
    telefone = "+" + message.get("from", "").lstrip("+")
    wa_id = message.get("id", "")
    if not wa_id or Mensagem.all_tenants.filter(wa_id=wa_id).exists():
        return None
    texto = (message.get("text") or {}).get("body", "") or f"[{message.get('type', 'mensagem')}]"
    cliente = Cliente.all_tenants.filter(estabelecimento=estabelecimento, telefone=telefone).first()
    try:
        with transaction.atomic():
            mensagem = Mensagem.all_tenants.create(
                estabelecimento=estabelecimento,
                cliente=cliente,
                telefone=telefone,
                direcao=Mensagem.Direcao.ENTRADA,
                corpo=texto,
                status=Mensagem.Status.RECEBIDA,
                wa_id=wa_id,
            )
    except IntegrityError:
        return None

    comando = _plain(texto)
    if cliente and comando in OPT_OUT_WORDS:
        cliente.aceite_whatsapp = False
        cliente.save(update_fields=["aceite_whatsapp", "atualizado_em"])
        _queue(
            estabelecimento,
            telefone,
            cliente=cliente,
            texto=f"Pronto, você não vai mais receber mensagens automáticas da {estabelecimento.nome}. "
            "Se mudar de ideia, responda VOLTAR.",
        )
    elif cliente and comando in OPT_IN_WORDS:
        cliente.aceite_whatsapp = True
        cliente.save(update_fields=["aceite_whatsapp", "atualizado_em"])
        _queue(
            estabelecimento,
            telefone,
            cliente=cliente,
            texto=f"Combinado! Você volta a receber confirmações e lembretes da {estabelecimento.nome}.",
        )
    return mensagem


def handle_webhook(payload):
    """Status de entrega e mensagens recebidas. O número que recebeu diz de qual estabelecimento é."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for status in value.get("statuses", []):
                _apply_status(status)
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            if not phone_number_id or not value.get("messages"):
                continue
            estabelecimento = Estabelecimento.objects.filter(whatsapp_phone_number_id=phone_number_id).first()
            if estabelecimento is None:
                continue
            for message in value["messages"]:
                _receive(estabelecimento, message)


def conversations(estabelecimento):
    """Uma linha por telefone, da conversa mais recente para a mais antiga."""
    rows = (
        Mensagem.all_tenants.filter(estabelecimento=estabelecimento)
        .values("telefone")
        .annotate(ultima=Max("criado_em"))
        .order_by("-ultima")
    )
    telefones = [row["telefone"] for row in rows]
    last = {}
    for mensagem in (
        Mensagem.all_tenants.filter(estabelecimento=estabelecimento, telefone__in=telefones)
        .select_related("cliente")
        .order_by("criado_em")
    ):
        last[mensagem.telefone] = mensagem
    return [last[telefone] for telefone in telefones if telefone in last]
