# agentkit/voz.py — Notas de voz: transcripción (Whisper) y respuesta en voz (TTS)
#
# Entrada (audio → texto), Whisper:
#   - GROQ_API_KEY   → Groq (GRATIS, rápido) — recomendado. console.groq.com
#   - OPENAI_API_KEY → OpenAI (~USD $0.006/min)
# Salida (texto → audio), TTS:
#   - OPENAI_API_KEY → OpenAI gpt-4o-mini-tts (~USD $0.015/min, español natural)
# Ambos usan el mismo API compatible con OpenAI.

import logging
import os
import re

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


# --- Respuesta en voz (texto → audio) ---

def tts_configurada() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def texto_para_voz(texto: str) -> str:
    """Versión hablable de una respuesta: sin URLs, markdown ni saltos de línea."""
    texto = re.sub(r"https?://\S+", "el link que te dejo aquí en el chat", texto)
    texto = re.sub(r"[*_#`~]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def sintetizar(texto: str) -> bytes | None:
    """Convierte texto en audio MP3 (OpenAI TTS). None si no está configurado o falla."""
    if not tts_configurada():
        return None
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json={
                "model": os.getenv("TTS_MODELO", "gpt-4o-mini-tts"),
                "voice": os.getenv("TTS_VOZ", "nova"),
                "input": texto[:2000],  # ponytail: tope duro, una nota de voz no debe durar minutos
                "response_format": "mp3",
            },
        )
        if r.status_code != 200:
            logger.error(f"Error TTS: {r.status_code} — {r.text}")
            return None
        return r.content
