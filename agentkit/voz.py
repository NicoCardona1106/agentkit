# agentkit/voz.py — Notas de voz: transcripción (Whisper) y respuesta en voz (TTS)
#
# Entrada (audio → texto), Whisper:
#   - GROQ_API_KEY   → Groq (GRATIS, rápido) — recomendado. console.groq.com
#   - OPENAI_API_KEY → OpenAI (~USD $0.006/min)
# Salida (texto → audio), TTS:
#   - OPENAI_API_KEY → OpenAI gpt-4o-mini-tts (~USD $0.015/min, mp3 directo)
#   - GEMINI_API_KEY → Gemini TTS (capa GRATIS en AI Studio; devuelve PCM,
#     requiere ffmpeg instalado para convertir a mp3)

import asyncio
import base64
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
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY"))


def texto_para_voz(texto: str) -> str:
    """Versión hablable de una respuesta: sin URLs, markdown ni saltos de línea."""
    texto = re.sub(r"https?://\S+", "el link que te dejo aquí en el chat", texto)
    texto = re.sub(r"[*_#`~]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def sintetizar(texto: str) -> bytes | None:
    """Convierte texto en audio MP3. OpenAI si hay key; si no, Gemini. None si falla."""
    texto = texto[:2000]  # ponytail: tope duro, una nota de voz no debe durar minutos
    if os.getenv("OPENAI_API_KEY"):
        return await _sintetizar_openai(texto)
    if os.getenv("GEMINI_API_KEY"):
        return await _sintetizar_gemini(texto)
    return None


async def _sintetizar_openai(texto: str) -> bytes | None:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json={
                "model": os.getenv("TTS_MODELO", "gpt-4o-mini-tts"),
                "voice": os.getenv("TTS_VOZ", "nova"),
                "input": texto,
                "response_format": "mp3",
            },
        )
        if r.status_code != 200:
            logger.error(f"Error TTS OpenAI: {r.status_code} — {r.text}")
            return None
        return r.content


async def _sintetizar_gemini(texto: str) -> bytes | None:
    """Gemini TTS devuelve PCM crudo (24kHz, 16-bit, mono) — se convierte a mp3 con ffmpeg."""
    modelo = os.getenv("TTS_MODELO", "gemini-2.5-flash-preview-tts")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY")},
            json={
                "contents": [{"parts": [{"text": texto}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                        "voiceName": os.getenv("TTS_VOZ", "Kore")}}},
                },
            },
        )
        if r.status_code != 200:
            logger.error(f"Error TTS Gemini: {r.status_code} — {r.text}")
            return None
    try:
        data = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    except (KeyError, IndexError):
        logger.error(f"Respuesta TTS Gemini sin audio: {r.text[:300]}")
        return None
    return await _pcm_a_mp3(base64.b64decode(data))


async def _pcm_a_mp3(pcm: bytes) -> bytes | None:
    """PCM s16le 24kHz mono → mp3, vía ffmpeg (debe estar instalado)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
            "-f", "mp3", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.error("ffmpeg no está instalado — necesario para la voz con Gemini")
        return None
    mp3, _ = await proc.communicate(pcm)
    return mp3 if proc.returncode == 0 and mp3 else None
