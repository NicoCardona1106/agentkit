# agentkit/voz.py — Transcripción de notas de voz (Whisper via Groq u OpenAI)
#
# Claude no acepta audio, así que se transcribe con Whisper:
#   - GROQ_API_KEY   → Groq (GRATIS, rápido) — recomendado. console.groq.com
#   - OPENAI_API_KEY → OpenAI (~USD $0.006/min)
# Ambos usan el mismo API compatible con OpenAI.

import logging
import os

import httpx

logger = logging.getLogger("agentkit")


def _config() -> tuple[str, str, str] | None:
    """(url, api_key, modelo) según la key disponible. Groq tiene prioridad (gratis)."""
    if os.getenv("GROQ_API_KEY"):
        return ("https://api.groq.com/openai/v1/audio/transcriptions",
                os.getenv("GROQ_API_KEY"), os.getenv("VOZ_MODELO", "whisper-large-v3"))
    if os.getenv("OPENAI_API_KEY"):
        return ("https://api.openai.com/v1/audio/transcriptions",
                os.getenv("OPENAI_API_KEY"), os.getenv("VOZ_MODELO", "whisper-1"))
    return None


def voz_configurada() -> bool:
    return _config() is not None


async def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg") -> str | None:
    """Transcribe un audio. Retorna None si no está configurado o falla."""
    config = _config()
    if not config:
        return None
    url, key, modelo = config
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (nombre_archivo, audio, "audio/ogg")},
            data={"model": modelo, "language": "es"},
        )
        if r.status_code != 200:
            logger.error(f"Error transcripción ({url}): {r.status_code} — {r.text}")
            return None
        return r.json().get("text", "").strip() or None
