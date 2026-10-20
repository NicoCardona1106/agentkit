# agentkit/telegram_borradores.py — Canal Telegram del modo borrador (BORRADOR_CANALES=telegram)
# Avisa cada borrador a un chat de Telegram con botones Aprobar / Descartar y recibe las decisiones con
# getUpdates (espera larga): ningún puerto de entrada, ningún webhook. Un bot por agente y UN solo
# proceso lo sondea (un worker de uvicorn): dos procesos con el mismo token se quitan los updates (409).
# Lo que llega es hostil hasta probar lo contrario: solo decide un id de TELEGRAM_APROBADORES, dentro de
# TELEGRAM_CHAT_ID, y sobre un mensaje que AgentKit registró (chat + message_id → borrador).
# Los textos son de AgentKit, no de un negocio (RNF-21). Sin parse_mode: el texto del cliente va como texto plano.

import asyncio
import logging
import os
import re
import time

import httpx

from agentkit import borrador, memory
from agentkit.privacidad import ocultar

logger = logging.getLogger("agentkit")
# httpx registra la URL completa a nivel INFO y en Telegram esa URL lleva el token.
logging.getLogger("httpx").setLevel(logging.WARNING)

API = "https://api.telegram.org"
ACTUALIZACIONES = ["message", "callback_query"]  # lo único que se pide a getUpdates
MAX_TG = 4096        # largo máximo de un mensaje de Telegram
_PARTE = 4000        # margen bajo el tope al partir (el largo se mide en UTF-16, como lo cuenta Telegram)
_CLIENTE_MAX = 1500  # tope del bloque «el cliente escribió»; el borrador va siempre completo
_ULTIMO_LOG: dict = {}
_reloj = time.monotonic  # aparte para simular el tiempo en las pruebas


# ── Configuración (se lee del entorno en cada uso, como el resto del core) ──

def _token() -> str:
    return os.getenv("TELEGRAM_TOKEN", "").strip()


def _chat() -> int | None:
    try:
        return int(os.getenv("TELEGRAM_CHAT_ID", "").strip())
    except ValueError:
        return None


def _aprobadores() -> set[int]:
    """Ids de TELEGRAM_APROBADORES (separados por coma). Lista vacía = nadie decide."""
    return {int(p) for p in (x.strip() for x in os.getenv("TELEGRAM_APROBADORES", "").split(","))
            if re.fullmatch(r"\d+", p)}


def aprobadores_invalidos() -> list[str]:
    return [p for p in (x.strip() for x in os.getenv("TELEGRAM_APROBADORES", "").split(","))
            if p and not re.fullmatch(r"\d+", p)]


def configurado() -> bool:
    """El canal existe solo con bot, chat y al menos un aprobador."""
    return bool(_token() and _chat() is not None and _aprobadores())


# ── Llamadas a la API de Telegram ──

async def _llamar(metodo: str, datos: dict, espera: float = 10, tolerar: tuple = ()) -> tuple[int, dict | None]:
    """POST a la Bot API. Devuelve (HTTP, JSON); (0, None) si no hubo respuesta. Nada del cuerpo ni de
    str(e) va al log: la URL lleva el token y el cuerpo puede traer texto del cliente."""
    if metodo in ("sendMessage", "editMessageText"):
        # Sin vista previa de enlaces: el texto del cliente puede traer uno y Telegram lo abriría solo.
        # El enlace sigue siendo clicable; solo se omite la tarjeta con la página.
        datos = {**datos, "link_preview_options": {"is_disabled": True}}
    try:
        async with httpx.AsyncClient(timeout=espera) as client:
            r = await client.post(f"{API}/bot{_token()}/{metodo}", json=datos)
    except httpx.HTTPError as e:
        logger.warning(f"Telegram {metodo}: {type(e).__name__}")
        return 0, None
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = None
    if r.status_code != 200 and r.status_code not in tolerar:
        logger.warning(f"Telegram {metodo} respondió HTTP {r.status_code}")
    return r.status_code, cuerpo if isinstance(cuerpo, dict) else None


def _id_mensaje(estado: int, cuerpo: dict | None) -> int | None:
    resultado = (cuerpo or {}).get("result") if estado == 200 else None
    mid = resultado.get("message_id") if isinstance(resultado, dict) else None
    return mid if isinstance(mid, int) else None


def _teclado(*botones: tuple[str, str]) -> dict:
    """Una fila de botones. El callback_data lleva solo la acción: el borrador sale del mensaje."""
    return {"inline_keyboard": [[{"text": t, "callback_data": a} for t, a in botones]]}


async def _editar(chat_id: int, message_id: int, texto: str):
    """Cambia el texto del mensaje y le quita los botones. «No modificado» (400) no es un fallo."""
    await _llamar("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": texto,
                                      "reply_markup": {"inline_keyboard": []}}, tolerar=(400,))


# ── El aviso ──

def _bloque_cliente(mensajes: list[str]) -> str:
    """Lo que el cliente escribió sin respuesta, acotado: se quedan los más recientes."""
    lineas, total = [], 0
    for m in reversed(mensajes):
        linea = "• " + (m if len(m) <= 300 else m[:300] + "…")
        if lineas and total + len(linea) > _CLIENTE_MAX:
            lineas.insert(0, "• …")
            break
        lineas.insert(0, linea)
        total += len(linea) + 1
    return "El cliente escribió:\n" + "\n".join(lineas)


def _utf16(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


def _partir(texto: str, tamano: int) -> list[str]:
    """Trozos de hasta `tamano` unidades UTF-16 (un emoji vale 2), cortando en salto de línea cuando se
    puede. Nada se pierde."""
    partes = []
    while _utf16(texto) > tamano:
        bajo, alto = 1, min(len(texto), tamano)  # mayor corte cuyo largo en UTF-16 cabe
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            bajo, alto = (medio, alto) if _utf16(texto[:medio]) <= tamano else (bajo, medio - 1)
        corte = texto.rfind("\n", 0, bajo)
        corte = corte + 1 if corte >= bajo // 2 else bajo
        partes.append(texto[:corte])
        texto = texto[corte:]
    return partes + [texto]


def armar_aviso(bid: int, quien: str, mensajes: list[str], respuesta: str) -> list[str]:
    """Texto del aviso. Si pasa de 4.096 caracteres se parte en varios mensajes: los del cliente se
    acotan, el borrador va completo y los botones van en la última parte."""
    return _partir(f"📝 Borrador #{bid} · {quien}\n\n{_bloque_cliente(mensajes)}\n\n"
                   f"Respuesta propuesta:\n{respuesta}\n\n"
                   f"Para cambiarlo, responde a este mensaje con tu versión.", _PARTE)


async def avisar(b: dict) -> bool:
    """Manda el borrador `b` al chat de aprobadores y guarda dónde quedó. True si llegó."""
    if not configurado():
        return False
    cliente = await memory.obtener_cliente(b["telefono"])
    # Nombre que dio el cliente + últimos 4 dígitos; nunca el número completo
    quien = f"{' '.join(cliente['nombre'].split()) or 'Cliente'} · {ocultar(b['telefono'])}"
    chat = _chat()
    partes = armar_aviso(b["id"], quien, b["mensajes"], b["texto"])
    mid = None
    for i, parte in enumerate(partes):
        datos = {"chat_id": chat, "text": parte}
        if i == len(partes) - 1:
            datos["reply_markup"] = _teclado(("✅ Aprobar", "aprobar"), ("🗑 Descartar", "descartar"))
        mid = _id_mensaje(*await _llamar("sendMessage", datos))
        if mid is None:
            return False
    await memory.guardar_aviso_telegram(b["id"], chat, mid)
    return True


async def reflejar(fila: dict, resultado: str):
    """Deja el aviso (y el mensaje de confirmación de una edición, si lo hay) con el resultado y sin botones."""
    if not (_token() and fila.get("tg_chat_id")):
        return
    texto = borrador.texto_resultado(fila["id"], resultado)
    for mid in (fila.get("tg_message_id"), fila.get("version_msg_id")):
        if mid:
            await _editar(fila["tg_chat_id"], mid, texto)


# ── Lo que llega ──

def _ignorar(clave, motivo: str):
    """Un rechazo se anota sin contenido y como máximo una línea por minuto para el mismo id."""
    ahora = _reloj()
    if ahora - _ULTIMO_LOG.get(clave, float("-inf")) >= 60:
        if len(_ULTIMO_LOG) > 500:
            _ULTIMO_LOG.clear()
        _ULTIMO_LOG[clave] = ahora
        logger.warning(f"Telegram: decisión ignorada de {motivo} ({clave[0]} {clave[1]})")


def _entero(valor) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _autorizado(usuario, chat, mensaje: dict) -> int | None:
    """Id del usuario si puede decidir; None (y rechazo anotado) si no. Bots, canales y chats ajenos no."""
    usuario, chat = usuario if isinstance(usuario, dict) else {}, chat if isinstance(chat, dict) else {}
    uid, cid = _entero(usuario.get("id")), _entero(chat.get("id"))
    if usuario.get("is_bot") or mensaje.get("sender_chat"):
        _ignorar(("remitente", uid), "un remitente que es un bot o un canal")
        return None
    if cid is None or cid != _chat():
        _ignorar(("chat", cid), "un chat no autorizado")
        return None
    if uid is None or uid not in _aprobadores():
        _ignorar(("usuario", uid), "un usuario no autorizado")
        return None
    return uid


async def manejar_update(proveedor, update: dict):
    """Un update de getUpdates. Solo `message` y `callback_query` hacen algo: editados, canales, medios
    y todo lo demás se ignoran."""
    if not isinstance(update, dict):
        return
    if isinstance(update.get("callback_query"), dict):
        await _callback(proveedor, update["callback_query"])
    elif isinstance(update.get("message"), dict):
        await _respuesta(update["message"])


async def _callback(proveedor, cq: dict):
    msg = cq.get("message")
    if not isinstance(msg, dict):  # callbacks sin mensaje (modo inline): no hay a qué borrador mapearlos
        return
    uid = _autorizado(cq.get("from"), msg.get("chat"), {})
    if uid is None:
        return
    hit = await memory.borrador_por_mensaje_tg(msg["chat"]["id"], msg.get("message_id"))
    if not hit:  # mensaje que AgentKit no registró (p. ej. uno falso con botones)
        return
    b, rol = hit
    await _llamar("answerCallbackQuery", {"callback_query_id": cq.get("id")})  # quita el relojito del botón
    accion, quien = cq.get("data"), f"telegram:{uid}"
    if rol == "aviso" and accion in ("aprobar", "descartar"):
        await borrador.decidir(proveedor, b["id"], "enviar" if accion == "aprobar" else "descartar",
                               canal="telegram", decidido_por=quien)
    elif rol == "version" and accion == "enviar_version" and b["version_texto"]:
        await borrador.decidir(proveedor, b["id"], "enviar", canal="telegram", decidido_por=quien,
                               texto=b["version_texto"])
    elif rol == "version" and accion == "cancelar_version":
        if await memory.limpiar_version(b["id"], msg["message_id"]):
            await _editar(msg["chat"]["id"], msg["message_id"],
                          f"Versión cancelada. El borrador #{b['id']} sigue pendiente.")


async def _avisar_en_chat(chat_id: int, texto: str, responde_a: int | None = None, teclado: dict | None = None):
    datos = {"chat_id": chat_id, "text": texto}
    if responde_a:
        datos["reply_to_message_id"] = responde_a
    if teclado:
        datos["reply_markup"] = teclado
    return await _llamar("sendMessage", datos)


async def _respuesta(msg: dict):
    """Editar = responder al mensaje del borrador con la versión nueva. No se envía: pide confirmación."""
    texto, reply = msg.get("text"), msg.get("reply_to_message")
    if not isinstance(texto, str) or not isinstance(reply, dict):  # medios, o un mensaje suelto del grupo
        return
    if _autorizado(msg.get("from"), msg.get("chat"), msg) is None:
        return
    chat_id = msg["chat"]["id"]
    hit = await memory.borrador_por_mensaje_tg(chat_id, reply.get("message_id"))
    if not hit or hit[1] != "aviso":
        return
    b, texto = hit[0], texto.strip()
    limite = borrador.limite_texto()
    if not texto:
        await _avisar_en_chat(chat_id, "La versión está vacía. Responde al borrador con el texto que quieres enviar.",
                              msg.get("message_id"))
        return
    if len(texto) > limite:
        await _avisar_en_chat(chat_id, f"La versión tiene {len(texto)} caracteres y el máximo es {limite}. "
                                       f"Acórtala y vuelve a responder.", msg.get("message_id"))
        return
    previo = await memory.guardar_version(b["id"], texto, borrador.ahora())
    if previo is None:  # ya no se puede editar: vencido, reemplazado o resuelto
        motivo, _ = await borrador.rechazar(b["id"])
        await _avisar_en_chat(chat_id, borrador.texto_resultado(b["id"], motivo), msg.get("message_id"))
        return
    mid = _id_mensaje(*await _avisar_en_chat(
        chat_id, f"✏️ Versión recibida para el borrador #{b['id']} ({len(texto)} caracteres). "
                 f"Hasta que la confirmes no se envía nada.", msg.get("message_id"),
        _teclado(("Enviar esta versión", "enviar_version"), ("Cancelar", "cancelar_version"))))
    if mid:
        await memory.guardar_msg_version(b["id"], mid)
    if previo["version_msg_id"]:
        await _editar(chat_id, previo["version_msg_id"], "Versión reemplazada por una más nueva.")


# ── El sondeo (getUpdates con espera larga) ──

async def _una_vuelta(proveedor, est: dict) -> float:
    """Una consulta a getUpdates y el proceso de lo que traiga. Devuelve los segundos a esperar antes de la siguiente."""
    datos = {"timeout": 30, "allowed_updates": ACTUALIZACIONES}
    if est["offset"] is not None:
        datos["offset"] = est["offset"]
    estado, cuerpo = await _llamar("getUpdates", datos, espera=40)
    if estado == 409:
        # Otro proceso sondea el mismo bot (o el bot tiene un webhook): sin arreglarlo no llega ninguna decisión
        est["conflictos"] += 1
        if est["conflictos"] % 12 == 3:
            logger.error("Telegram getUpdates responde 409 repetido: otro proceso usa el mismo bot o el bot "
                         "tiene un webhook activo (un solo worker por agente, un bot por agente)")
        return 5.0
    est["conflictos"] = 0
    if estado in (401, 404):
        # Token revocado o mal puesto: no es algo que se arregle solo
        est["rechazos"] += 1
        if est["rechazos"] % 10 == 3:
            logger.error(f"Telegram getUpdates responde {estado} repetido: el token del bot es inválido o fue "
                         f"revocado; no llegará ninguna decisión")
        return min(60.0, 5.0 * 2 ** (est["rechazos"] - 1))
    est["rechazos"] = 0
    if estado != 200 or not cuerpo or not cuerpo.get("ok"):
        est["caidas"] += 1  # sin red u otro fallo: se espera más cada vez, hasta 60 s
        return min(60.0, 5.0 * 2 ** (est["caidas"] - 1))
    est["caidas"] = 0
    for u in cuerpo.get("result") or []:
        if not isinstance(u, dict):
            continue
        if _entero(u.get("update_id")) is not None:
            est["offset"] = u["update_id"] + 1
        try:
            await manejar_update(proveedor, u)
        except Exception as e:  # un update raro no tumba el sondeo
            logger.error(f"Telegram: falló el proceso de una actualización ({type(e).__name__})")
    return 0.0


async def sondear(proveedor):
    est = {"offset": None, "conflictos": 0, "rechazos": 0, "caidas": 0}
    while True:
        try:
            espera = await _una_vuelta(proveedor, est)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Telegram: falló el sondeo ({type(e).__name__})")
            espera = 5.0
        if espera:
            await asyncio.sleep(espera)


_tarea: asyncio.Task | None = None


def iniciar(proveedor) -> asyncio.Task:
    """Arranca el sondeo. Uno solo por proceso."""
    global _tarea
    if _tarea is None or _tarea.done():
        _tarea = asyncio.create_task(sondear(proveedor))
    return _tarea
