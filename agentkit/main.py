# agentkit/main.py — Servidor FastAPI + webhook de WhatsApp (provider-agnostic)

import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agentkit import brain, humanizar, memory, reporte, voz
from agentkit.providers import MensajeEntrante, obtener_proveedor

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
logging.basicConfig(level=logging.DEBUG if ENVIRONMENT == "development" else logging.INFO)
logger = logging.getLogger("agentkit")

proveedor = obtener_proveedor()

# Dedup de webhooks reenviados (Meta/Twilio reintentan si no respondemos rápido)
_procesados: deque[str] = deque(maxlen=500)


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

        if await memory.conversacion_pausada(msg.telefono):
            # Derivado a humano: se guarda el mensaje pero el bot no responde
            await memory.guardar_mensaje(msg.telefono, "user", texto)
            logger.info(f"Conversación {msg.telefono} pausada — sin respuesta del bot")
            return

        historial = await memory.obtener_historial(msg.telefono)
        respuesta = await brain.generar_respuesta(msg.telefono, texto, historial, proveedor)

        await memory.guardar_mensaje(msg.telefono, "user", texto)
        await memory.guardar_mensaje(msg.telefono, "assistant", respuesta)
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


@app.get("/reporte")
async def reporte_diario(token: str = ""):
    """Genera y envía el reporte del día al equipo. Protegido con REPORTE_TOKEN (cron de Railway)."""
    esperado = os.getenv("REPORTE_TOKEN", "")
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token inválido")
    texto = await reporte.enviar_reporte(proveedor)
    return PlainTextResponse(texto)
