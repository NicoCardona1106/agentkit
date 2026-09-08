# agentkit/brain.py — Cerebro del agente: Claude API con tool use loop

import logging
import os
from datetime import datetime

import yaml
from anthropic import AsyncAnthropic
from dotenv import find_dotenv, load_dotenv

from agentkit import herramientas, memory
from agentkit.providers.base import ProveedorWhatsApp

load_dotenv(find_dotenv(usecwd=True))  # el .env vive en la carpeta del agente (cwd), no junto al paquete
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODELO = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
MAX_ITERACIONES_TOOLS = 8


def cargar_config_prompts() -> dict:
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def obtener_mensaje_error() -> str:
    return cargar_config_prompts().get(
        "error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    return cargar_config_prompts().get(
        "fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


async def _system_prompt(telefono: str) -> list[dict]:
    """System prompt en dos bloques: el del negocio (estable, cacheado) y el contexto variable.

    El bloque base lleva cache_control: como el prefijo tools+system no cambia entre mensajes,
    Claude lo sirve desde caché (~10 % del precio). La fecha y la memoria del cliente van en
    un bloque aparte para no invalidar la caché en cada minuto.
    OJO: cada modelo exige un prefijo mínimo para cachear (Haiku 4.5: 4096 tokens; Sonnet 5:
    1024). Un agente pequeño (~2k tokens de tools+prompt) en Haiku no cachea y no falla:
    el log muestra "caché: 0 creados". Se activa solo cuando el conocimiento crece.
    """
    base = cargar_config_prompts().get("system_prompt", "Eres un asistente útil. Responde en español.")
    partes = [f"## Contexto actual\nFecha y hora (UTC): {datetime.utcnow():%A %Y-%m-%d %H:%M}"]
    cliente = await memory.obtener_cliente(telefono)
    if cliente["nombre"] or cliente["notas"]:
        partes.append("## Lo que sabes de este cliente (de conversaciones anteriores)\n"
                      f"Nombre: {cliente['nombre'] or 'desconocido'}\nNotas: {cliente['notas'] or 'ninguna'}")
    return [
        {"type": "text", "text": base, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "\n\n".join(partes)},
    ]


async def generar_respuesta(telefono: str, mensaje: str, historial: list[dict],
                            proveedor: ProveedorWhatsApp) -> str:
    """Genera la respuesta con Claude, ejecutando herramientas cuando el modelo las pida."""
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system = await _system_prompt(telefono)
    esquemas, ejecutar = herramientas.obtener_herramientas(telefono, proveedor)
    mensajes = list(historial) + [{"role": "user", "content": mensaje}]

    try:
        for _ in range(MAX_ITERACIONES_TOOLS):
            respuesta = await client.messages.create(
                model=MODELO, max_tokens=MAX_TOKENS, system=system,
                tools=esquemas, messages=mensajes,
            )
            if respuesta.stop_reason != "tool_use":
                break
            mensajes.append({"role": "assistant", "content": respuesta.content})
            resultados = []
            for bloque in respuesta.content:
                if bloque.type == "tool_use":
                    logger.info(f"Tool use: {bloque.name}({bloque.input})")
                    salida = await ejecutar(bloque.name, bloque.input)
                    resultados.append({"type": "tool_result", "tool_use_id": bloque.id, "content": salida})
            mensajes.append({"role": "user", "content": resultados})

        texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
        u = respuesta.usage
        logger.info(f"Respuesta generada ({u.input_tokens} in / {u.output_tokens} out / "
                    f"caché: {getattr(u, 'cache_read_input_tokens', 0) or 0} leídos, "
                    f"{getattr(u, 'cache_creation_input_tokens', 0) or 0} creados)")
        return texto or obtener_mensaje_fallback()
    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return obtener_mensaje_error()
