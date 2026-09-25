# agentkit/precios.py — Precios de las APIs (USD) y registro del costo de cada llamada
#
# El dinero va SIEMPRE en Decimal (nunca float) y se guarda como texto en la tabla uso_api.
# Precios verificados en las páginas oficiales el 2026-09-25:
#   Anthropic: https://docs.anthropic.com/en/docs/about-claude/pricing
#   OpenAI:    https://platform.openai.com/docs/pricing
#   Groq:      https://console.groq.com/docs/models (mínimo facturado: docs/speech-to-text)
#   Gemini:    https://ai.google.dev/gemini-api/docs/pricing
#
# Override sin tocar código: un JSON en PRECIOS_ARCHIVO (default config/precios.json, en la
# carpeta del agente) con la misma forma que PRECIOS; solo hace falta poner lo que cambia:
#   {"claude-haiku-4-5": {"salida": "4.5"}, "otro-modelo": {"minuto": "0.01"}}

import json
import logging
import os
from decimal import Decimal

from agentkit import memory

logger = logging.getLogger("agentkit")

MILLON = Decimal(1_000_000)

# LLM: USD por millón de tokens. cache_escritura es la de 5 minutos (la que usa brain.py).
# Audio (STT y TTS): USD por "minuto" (o por "hora") de audio; minimo_segundos = lo mínimo
# que factura el proveedor por llamada. El modelo con fecha (claude-haiku-4-5-20251001) usa
# el precio de su alias por prefijo.
PRECIOS: dict[str, dict[str, str]] = {
    # Anthropic
    "claude-haiku-4-5": {"entrada": "1", "salida": "5", "cache_lectura": "0.10", "cache_escritura": "1.25"},
    "claude-sonnet-5": {"entrada": "2", "salida": "10", "cache_lectura": "0.20", "cache_escritura": "2.50"},
    # STT — OpenAI publica el costo estimado por minuto
    "gpt-4o-mini-transcribe": {"minuto": "0.003"},
    "whisper-1": {"minuto": "0.006"},
    # STT — Groq cobra por hora, mínimo 10 s por llamada
    "whisper-large-v3": {"hora": "0.111", "minimo_segundos": "10"},
    "whisper-large-v3-turbo": {"hora": "0.04", "minimo_segundos": "10"},
    # TTS — solo el audio de salida; el texto de entrada (USD 0,50-0,60/M tokens) es despreciable.
    # SIN VERIFICAR la equivalencia por minuto: la página de OpenAI hoy publica USD 12/M tokens de
    # audio de salida sin costo por minuto; 0.015/min es la estimación que OpenAI publicaba en 2025.
    "gpt-4o-mini-tts": {"minuto": "0.015"},
    # Gemini: USD 10/M tokens de audio (2.5 Flash) y 9/M (3.8 Flash, hasta 2026-12-31; 18/M desde
    # 2027-01-01), a 25 tokens por segundo de audio.
    "gemini-2.5-flash-preview-tts": {"minuto": "0.015"},
    "gemini-3.8-flash-tts": {"minuto": "0.0135"},
}


def _precio(modelo: str) -> dict | None:
    """Precio del modelo (tabla + override opcional). El prefijo más largo gana."""
    tabla = {m: dict(p) for m, p in PRECIOS.items()}
    ruta = os.getenv("PRECIOS_ARCHIVO", "config/precios.json")
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            for m, p in json.load(f).items():
                tabla.setdefault(m, {}).update(p)
    for clave in sorted(tabla, key=len, reverse=True):
        if modelo.startswith(clave):
            return tabla[clave]
    logger.warning(f"Sin precio para el modelo {modelo}: se registra con costo 0")
    return None


def _d(valor) -> Decimal:
    return Decimal(str(valor))  # str() primero: un float del JSON no arrastra su error binario


def costo_llm(modelo: str, tokens_entrada: int = 0, tokens_salida: int = 0,
              tokens_cache_lectura: int = 0, tokens_cache_escritura: int = 0) -> Decimal:
    p = _precio(modelo)
    if not p:
        return Decimal(0)
    return (tokens_entrada * _d(p["entrada"]) + tokens_salida * _d(p["salida"])
            + tokens_cache_lectura * _d(p["cache_lectura"])
            + tokens_cache_escritura * _d(p["cache_escritura"])) / MILLON


def costo_audio(modelo: str, segundos: Decimal) -> Decimal:
    p = _precio(modelo)
    if not p:
        return Decimal(0)
    segundos = max(_d(segundos), _d(p.get("minimo_segundos", 0)))
    por_minuto = _d(p["minuto"]) if "minuto" in p else _d(p["hora"]) / 60
    return por_minuto * segundos / 60


async def registrar(tipo: str, proveedor: str, modelo: str, *, usage=None,
                    segundos_audio: Decimal | None = None, caracteres: int = 0):
    """Guarda en uso_api una fila con el costo de una llamada (tipo: llm | stt | tts).
    llm: `usage` es el objeto usage de Anthropic. stt/tts: segundos de audio (y caracteres en tts).
    NUNCA lanza: un fallo aquí se loguea y la respuesta al cliente sigue su curso."""
    try:
        fila = {"tipo": tipo, "proveedor": proveedor, "modelo": modelo, "caracteres": caracteres}
        if tipo == "llm":
            tokens = {
                "tokens_entrada": usage.input_tokens or 0,
                "tokens_salida": usage.output_tokens or 0,
                "tokens_cache_lectura": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "tokens_cache_escritura": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            }
            fila.update(tokens)
            usd = costo_llm(modelo, **tokens)
        else:
            fila["segundos_audio"] = float(segundos_audio or 0)  # medida, no dinero
            usd = costo_audio(modelo, segundos_audio or 0)
        await memory.registrar_uso(**fila, usd=str(usd))
    except Exception as e:
        logger.error(f"No se pudo registrar el costo ({tipo} {modelo}): {e}")
