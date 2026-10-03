# agentkit/main.py — Servidor FastAPI + webhook de WhatsApp (provider-agnostic)

import asyncio
import logging
import os
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from agentkit import borrador, brain, estado, humanizar, memory, reporte, tope, voz, web
from agentkit.privacidad import ocultar
from agentkit.providers import MensajeEntrante, obtener_proveedor

load_dotenv(find_dotenv(usecwd=True))  # el .env vive en la carpeta del agente (cwd), no junto al paquete

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
# INFO por defecto aun en development: en DEBUG las librerías vuelcan teléfonos y conversaciones
# (Ley 1581; informe de seguridad 2026-10-03, hallazgo 5). DEBUG solo con LOG_LEVEL=DEBUG.
_nivel = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").strip().upper())
logging.basicConfig(level=_nivel if isinstance(_nivel, int) else logging.INFO)
for _ruidoso in ("anthropic", "openai", "aiosqlite", "httpcore", "sqlalchemy.engine"):
    logging.getLogger(_ruidoso).setLevel(logging.WARNING)
logger = logging.getLogger("agentkit")
logger.addHandler(estado.contador_errores)  # cuenta ERRORes para GET /estado

_iniciado: datetime | None = None  # marca de arranque (para /estado): UTC y monotónica
_arranque_monotonic: float | None = None

proveedor = obtener_proveedor()

# Dedup de webhooks reenviados (Meta/Twilio/Instagram reintentan si no respondemos rápido): la base
# manda (sobrevive a reinicios; con varios workers, usar PostgreSQL); esta lista corta es el respaldo si la base falla.
_procesados: deque[str] = deque(maxlen=500)

# Tope total de la respuesta en voz (proveedor principal + respaldos): si vence, sale el texto
VOZ_TIMEOUT_TOTAL = float(os.getenv("VOZ_TIMEOUT_TOTAL", "45"))

# Audios TTS generados, servidos en /audio/{id} para que el proveedor los descargue
# ponytail: en memoria con tope de 50 — si algún día hay varios workers, pasar a storage compartido
_audios: dict[str, bytes] = {}


def _guardar_audio(audio: bytes) -> str:
    aid = secrets.token_urlsafe(8)
    _audios[aid] = audio
    while len(_audios) > 50:
        _audios.pop(next(iter(_audios)))
    return aid


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _iniciado, _arranque_monotonic
    await memory.inicializar_db()
    _iniciado = datetime.utcnow()
    _arranque_monotonic = time.monotonic()
    logger.info(f"AgentKit listo — proveedor: {proveedor.__class__.__name__}")
    yield


from agentkit import __version__

# Sin /docs, /redoc ni /openapi.json públicos: no le dicen a nadie qué software corre (hallazgo 10).
app = FastAPI(title="AgentKit — WhatsApp AI Agent", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

# Tope de tamaño del cuerpo: un POST de cientos de MB no llena la memoria (hallazgo 8). Los webhooks
# de Meta/Twilio y el chat web pesan pocos KB; Caddy debería limitar también (request_body max_size).
def _max_cuerpo() -> int:
    valor = os.getenv("MAX_CUERPO_BYTES", "").strip()
    if re.fullmatch(r"[0-9]+", valor) and int(valor) > 0:
        return int(valor)
    if valor:
        logging.getLogger("agentkit").warning(f"MAX_CUERPO_BYTES={valor!r} no es válido: se usa 1 MB")
    return 1024 * 1024


MAX_CUERPO_BYTES = _max_cuerpo()


class LimiteCuerpo:
    """Middleware ASGI: 413 si el Content-Length declarado pasa el tope y, para cuerpos sin él
    (chunked), corta en cuanto lo recibido pasa el tope — antes de juntarlo entero en memoria."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limite = MAX_CUERPO_BYTES
        largo = dict(scope.get("headers") or []).get(b"content-length")
        if largo is not None:
            texto = largo.decode("latin-1").strip()
            if not re.fullmatch(r"[0-9]+", texto) or int(texto) > limite:
                return await PlainTextResponse("Cuerpo demasiado grande", status_code=413)(scope, receive, send)
        recibido = 0

        async def receive_limitado():
            nonlocal recibido
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibido += len(mensaje.get("body", b""))
                if recibido > limite:
                    raise HTTPException(status_code=413, detail="Cuerpo demasiado grande")
            return mensaje

        await self.app(scope, receive_limitado, send)


app.add_middleware(LimiteCuerpo)
app.include_router(web.router)  # /chat y /widget.js — canal de chat web (apagado sin WEB_CHAT_ORIGINS)


@app.get("/")
async def health_check():
    # Sin versión: /estado (con token) la trae para el panel.
    return {"status": "ok", "service": "agentkit"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    if request.query_params.get("hub.mode"):  # intento de verificación con token incorrecto
        raise HTTPException(status_code=403, detail="Verify token inválido")
    return {"status": "ok"}


async def procesar_mensaje(msg: MensajeEntrante):
    """Procesa un mensaje: voz → texto, memoria, Claude (con tools), respuesta humanizada."""
    try:
        texto = msg.texto
        if msg.audio_ref and not texto:
            audio = await proveedor.descargar_audio(msg.audio_ref)
            texto = await voz.transcribir(audio) if audio else None
            if not texto:
                await proveedor.enviar_mensaje(
                    msg.telefono, "Recibí tu nota de voz pero no pude escucharla. ¿Me lo escribes? 🙏")
                return

        logger.info(f"Mensaje de {ocultar(msg.telefono)} ({len(texto)} caracteres)")

        # MODO_BORRADOR: los mensajes del admin son comandos (ok/no/editar), no chat
        if borrador.activo() and borrador.es_admin(msg.telefono):
            await borrador.comando_admin(proveedor, texto)
            return

        if await memory.conversacion_pausada(msg.telefono):
            # Derivado a humano: se guarda el mensaje pero el bot no responde
            await memory.guardar_mensaje(msg.telefono, "user", texto)
            logger.info(f"Conversación {ocultar(msg.telefono)} pausada — sin respuesta del bot")
            return

        # Tope de gasto (docs/TOPE-GASTO.md): pasado el diario, un humano atiende sin llamar a
        # Claude; cerca del diario o pasado el mensual, solo texto.
        limite = await tope.revisar(proveedor)
        # El ADMIN_PHONE nunca queda derivado: es el equipo, no un cliente.
        if limite.derivar and not borrador.es_admin(msg.telefono):
            await memory.guardar_mensaje(msg.telefono, "user", texto)
            await tope.derivar(proveedor, msg.telefono)
            return

        # Si el cliente habló, el agente responde con voz (requiere TTS y PUBLIC_URL); el cerebro
        # lo sabe para escribir frases de corrido que suenen naturales.
        public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
        # En MODO_BORRADOR la respuesta va al admin como texto: sin voz ni instrucción de voz
        en_voz = bool(msg.audio_ref and public_url and voz.tts_configurada() and not borrador.activo()
                      and not limite.sin_voz)

        historial = await memory.obtener_historial(msg.telefono)
        respuesta = await brain.generar_respuesta(msg.telefono, texto, historial, proveedor, en_voz=en_voz)

        await memory.guardar_mensaje(msg.telefono, "user", texto)

        # MODO_BORRADOR: la respuesta espera aprobación del admin; el mensaje del
        # asistente se guarda al aprobarse, para que el historial refleje solo lo
        # que el cliente realmente recibió.
        # ponytail: si el cliente escribe de nuevo antes de la aprobación se genera
        # otro borrador sin ver el anterior — aceptable en el mes de supervisión
        if borrador.activo():
            await borrador.proponer(proveedor, msg.telefono, respuesta, texto)
            return

        await memory.guardar_mensaje(msg.telefono, "assistant", respuesta)

        # El texto solo se envía si la voz falló o si la respuesta trae un link
        # (la nota de voz no puede transmitirlo).
        respondido_en_voz = False
        if en_voz:
            try:  # un fallo de voz nunca se lleva la respuesta de texto
                audio_out = await asyncio.wait_for(voz.sintetizar(voz.texto_para_voz(respuesta)),
                                                   timeout=VOZ_TIMEOUT_TOTAL)
                if audio_out:
                    aid = _guardar_audio(audio_out)
                    respondido_en_voz = await proveedor.enviar_audio_url(
                        msg.telefono, f"{public_url}/audio/{aid}")
            except Exception as e:
                logger.error(f"Falló la respuesta en voz, sale en texto: {e!r}")

        if not respondido_en_voz or "http" in respuesta:
            await humanizar.enviar_humanizado(proveedor, msg.telefono, respuesta)
        logger.info(f"Respuesta a {ocultar(msg.telefono)} ({len(respuesta)} caracteres)")
    except Exception as e:
        logger.exception(f"Error procesando mensaje de {ocultar(msg.telefono)}: {e}")


async def _es_nuevo(mensaje_id: str) -> bool:
    """True si el mensaje no se ha atendido antes. Sin id no hay cómo reconocer un reintento: se
    atiende (antes, el primer id vacío hacía descartar todos los siguientes). Si la base falla, se
    decide con la lista en memoria: mejor un posible doble que dejar al cliente sin respuesta."""
    if not mensaje_id:
        return True
    if mensaje_id in _procesados:
        return False
    _procesados.append(mensaje_id)
    try:
        return await memory.marcar_procesado(mensaje_id)
    except Exception as e:
        logger.error(f"No se pudo registrar el mensaje en la base (dedup solo en memoria): {e!r}")
        return True


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Recibe mensajes de WhatsApp. Valida la firma, responde rápido y procesa en background."""
    if not await proveedor.validar_firma(request):
        raise HTTPException(status_code=403, detail="Firma inválida")
    mensajes = await proveedor.parsear_webhook(request)
    for msg in mensajes:
        if not (msg.texto or msg.audio_ref) or not await _es_nuevo(msg.mensaje_id):
            continue
        # Background: el proveedor reintenta el webhook si tardamos; Claude puede tardar >15s
        asyncio.create_task(procesar_mensaje(msg))
    return {"status": "ok"}


@app.get("/audio/{aid}")
async def servir_audio(aid: str):
    """Sirve un audio TTS generado, para que el proveedor de WhatsApp lo descargue."""
    audio = _audios.get(aid)
    if not audio:
        raise HTTPException(status_code=404, detail="Audio no encontrado")
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/reporte")
async def reporte_diario(request: Request, token: str = ""):
    """Genera y envía el reporte del día al equipo. Protegido con REPORTE_TOKEN (cron de Railway).
    Mejor por cabecera X-Reporte-Token (la URL con ?token= queda en los access logs); el ?token= se
    sigue aceptando para no romper los cron ya configurados. Comparación en tiempo constante."""
    esperado = os.getenv("REPORTE_TOKEN", "")
    recibido = request.headers.get("X-Reporte-Token") or token
    if not esperado or not secrets.compare_digest(recibido.encode(), esperado.encode()):
        raise HTTPException(status_code=403, detail="Token inválido")
    texto = await reporte.enviar_reporte(proveedor)
    return PlainTextResponse(texto)


@app.get("/estado")
async def estado_agente(request: Request, token: str = ""):
    """Estado del agente para que un panel externo lo consulte cada pocos minutos.
    Protegido con REPORTE_TOKEN (misma regla que /reporte): por query ?token= o, mejor,
    por cabecera X-Reporte-Token (no queda en los access logs). Nunca expone teléfonos ni mensajes."""
    esperado = os.getenv("REPORTE_TOKEN", "")
    recibido = request.headers.get("X-Reporte-Token") or token
    if not esperado or not secrets.compare_digest(recibido.encode(), esperado.encode()):
        raise HTTPException(status_code=403, detail="Token inválido")
    from agentkit import __version__
    resumen = await memory.resumen_estado()
    try:
        costo = await memory.resumen_costos()
    except Exception as e:  # el costo es un extra: si falla, el resto del estado sale igual
        logger.error(f"No se pudo calcular costo_usd para /estado: {e}")
        costo = None
    return {
        "service": "agentkit",
        "version": __version__,
        "nombre": estado.nombre_bot(),
        "proveedor": proveedor.__class__.__name__,
        "modelo": brain.MODELO,
        "uptime_s": round(time.monotonic() - _arranque_monotonic, 1) if _arranque_monotonic else 0.0,
        "iniciado": _iniciado.isoformat() + "Z" if _iniciado else None,
        "modo_borrador": borrador.activo(),
        **resumen,
        "errores_24h": estado.contador_errores.contar_24h(),
        "costo_usd": costo,  # {hoy, mes, desglose del mes, modelos_sin_precio} o null si falló
    }
