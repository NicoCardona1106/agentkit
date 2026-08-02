# agentkit/voz.py — Transcripción de notas de voz (Whisper de OpenAI, opcional)

import logging
import os

import httpx

logger = logging.getLogger("agentkit")


def voz_configurada() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


async def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg") -> str | None:
    """Transcribe un audio con Whisper. Retorna None si no está configurado o falla."""
    # ponytail: Claude API no acepta audio; Whisper es el camino estándar y barato
    if not voz_configurada():
        return None
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            files={"file": (nombre_archivo, audio, "audio/ogg")},
            data={"model": "whisper-1", "language": "es"},
        )
        if r.status_code != 200:
            logger.error(f"Error Whisper: {r.status_code} — {r.text}")
            return None
        return r.json().get("text", "").strip() or None
