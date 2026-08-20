# agentkit/main.py — Servidor FastAPI + webhook de WhatsApp (provider-agnostic)

import asyncio
import logging
import os
import secrets
from collections import deque
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from agentkit import borrador, brain, humanizar, memory, reporte, voz
from agentkit.providers import MensajeEntrante, obtener_proveedor

load_dotenv(find_dotenv(usecwd=True))  # el .env vive en la carpeta del agente (cwd), no junto al paquete

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
logging.basicConfig(level=logging.DEBUG if ENVIRONMENT == "development" else logging.INFO)
logger = logging.getLogger("agentkit")

proveedor = obtener_proveedor()

# Dedup de webhooks reenviados (Meta/Twilio reintentan si no respondemos rápido)
_procesados: deque[str] = deque(maxlen=500)

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
    await memory.inicializar_db()
    logger.info(f"AgentKit listo — proveedor: {proveedor.__class__.__name__}")
    yield


app = FastAPI(title="AgentKit — WhatsApp AI Agent", version="1.0.0", lifespan=lifespan)


@app.get("/")
async def health_check():
    from agentkit import __version__
    return {"status": "ok", "service": "agentkit", "version": __version__}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
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

        logger.info(f"Mensaje de {msg.telefono}: {texto}")

        # MODO_BORRADOR: los mensajes del admin son comandos (ok/no/editar), no chat
        if borrador.activo() and borrador.es_admin(msg.telefono):
            await borrador.comando_admin(proveedor, texto)
            return

        if await memory.conversacion_pausada(msg.telefono):
            # Derivado a humano: se guarda el mensaje pero el bot no responde
            await memory.guardar_mensaje(msg.telefono, "user", texto)
            logger.info(f"Conversación {msg.telefono} pausada — sin respuesta del bot")
            return

        historial = await memory.obtener_historial(msg.telefono)
        respuesta = await brain.generar_respuesta(msg.telefono, texto, historial, proveedor)

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

        # Si el cliente habló, el agente responde con voz (requiere TTS y PUBLIC_URL).
        # El texto solo se envía si la voz falló o si la respuesta trae un link
        # (la nota de voz no puede transmitirlo).
        respondido_en_voz = False
        public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
        if msg.audio_ref and voz.tts_configurada() and public_url:
            audio_out = await voz.sintetizar(voz.texto_para_voz(respuesta))
            if audio_out:
                aid = _guardar_audio(audio_out)
                respondido_en_voz = await proveedor.enviar_audio_url(
                    msg.telefono, f"{public_url}/audio/{aid}")

        if not respondido_en_voz or "http" in respuesta:
            await humanizar.enviar_humanizado(proveedor, msg.telefono, respuesta)
        logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
    except Exception as e:
        logger.exception(f"Error procesando mensaje de {msg.telefono}: {e}")


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Recibe mensajes de WhatsApp. Valida la firma, responde rápido y procesa en background."""
    if not await proveedor.validar_firma(request):
        raise HTTPException(status_code=403, detail="Firma inválida")
    mensajes = await proveedor.parsear_webhook(request)
    for msg in mensajes:
        if not (msg.texto or msg.audio_ref) or msg.mensaje_id in _procesados:
            continue
        _procesados.append(msg.mensaje_id)
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
async def reporte_diario(token: str = ""):
    """Genera y envía el reporte del día al equipo. Protegido con REPORTE_TOKEN (cron de Railway)."""
    esperado = os.getenv("REPORTE_TOKEN", "")
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token inválido")
    texto = await reporte.enviar_reporte(proveedor)
    return PlainTextResponse(texto)
