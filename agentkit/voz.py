# agentkit/voz.py — Notas de voz: transcripción (STT) y respuesta en voz (TTS)
#
# Entrada (audio → texto):
#   - OPENAI_API_KEY → OpenAI gpt-4o-mini-transcribe (~USD 0,003/min) — por defecto si hay key
#   - GROQ_API_KEY   → Groq whisper-large-v3 (capa gratis) — si no hay key de OpenAI
#   STT_PROVEEDOR=openai|groq fuerza uno (y solo ese; sin su key, el agente queda sin STT).
#   VOZ_MODELO cambia el modelo.
# Salida (texto → audio, siempre mp3). Decisión 2026-09-25: OpenAI gpt-4o-mini-tts; Gemini
# queda solo como respaldo si no hay OPENAI_API_KEY. TTS_PROVEEDOR=openai|gemini fuerza uno.
#   - openai → gpt-4o-mini-tts, mp3 directo. OPENAI_TTS_VOZ o TTS_VOZ (default marin; en prueba
#     de oído contra coral y cedar) y TTS_INSTRUCCIONES (tono, acento y ritmo).
#   - gemini → Gemini TTS (capa gratis en AI Studio; devuelve PCM, requiere ffmpeg para mp3).
#     GEMINI_TTS_VOZ o TTS_VOZ (default Kore).
#   TTS_MODELO cambia el modelo. Forzar un proveedor sin su key deja al agente sin voz de salida.
# Cada proveedor valida modelo y voz: si un valor es de otro proveedor (un .env viejo con
# VOZ_MODELO=whisper-large-v3 o TTS_VOZ=Kore al pasar a OpenAI), usa su default y avisa una vez.
#   Otro proveedor (deepgram, elevenlabs…): escribir _sintetizar_<nombre>(texto, modelo) → mp3
#   y agregarlo a _TTS al final del archivo, con su variable de key y su modelo por defecto.
# Cada llamada exitosa queda registrada con su costo en uso_api (ver precios.py).

import asyncio
import base64
import logging
import os
import re
from decimal import Decimal

import httpx

from agentkit import precios

logger = logging.getLogger("agentkit")

# Voces válidas verificadas el 2026-09-25 en la referencia de /v1/audio/speech de OpenAI y en
# ai.google.dev/gemini-api/docs/speech-generation.
VOCES_OPENAI = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage",
                "shimmer", "verse", "marin", "cedar"}
VOCES_GEMINI = {"Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe",
                "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome",
                "Algenib", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux",
                "Pulcherrima", "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager",
                "Sulafat"}

# proveedor → (variable de la key, url, modelo por defecto, ¿el modelo es de este proveedor?).
# El orden es la prioridad.
_STT = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/audio/transcriptions", "gpt-4o-mini-transcribe",
               lambda m: m.startswith("gpt-") or m == "whisper-1"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3",
             lambda m: m.startswith(("whisper-large", "distil-whisper"))),
}

_avisados: set[str] = set()


def _opcion(proveedor: str, variables: tuple[str, ...], default: str, valido) -> str:
    """Primer valor definido en `variables` que sirva para el proveedor; si no hay, su default.
    Un valor de otro proveedor se ignora con un warning (una sola vez por proceso)."""
    for variable in variables:
        valor = os.getenv(variable)
        if not valor:
            continue
        if valido(valor):
            return valor
        aviso = f"{variable}={valor} no sirve para {proveedor}: se ignora (default {default})"
        if aviso not in _avisados:
            _avisados.add(aviso)
            logger.warning(aviso)
    return default


def _elegir(tabla: dict, variable: str) -> str | None:
    """Proveedor forzado por `variable` (solo ese), o el primero de la tabla con key."""
    forzado = os.getenv(variable, "").strip().lower()
    for nombre in ([forzado] if forzado else list(tabla)):
        if nombre in tabla and os.getenv(tabla[nombre][0]):
            return nombre
    return None


def _config() -> tuple[str, str, str, str] | None:
    """(proveedor, url, api_key, modelo) para transcribir, o None si no hay key."""
    nombre = _elegir(_STT, "STT_PROVEEDOR")
    if not nombre:
        return None
    variable, url, modelo, valido = _STT[nombre]
    return nombre, url, os.getenv(variable), _opcion(nombre, ("VOZ_MODELO",), modelo, valido)


def voz_configurada() -> bool:
    return _config() is not None


def duracion_audio(audio: bytes) -> Decimal:
    """Segundos de audio. OGG/Opus (notas de voz de WhatsApp): exacto, del granule position de la
    última página (Opus siempre cuenta a 48 kHz). Otro formato (el mp4 de Instagram): ESTIMADO por
    tamaño a ~16 kbps (2.000 bytes/s)."""
    if audio[:4] == b"OggS":
        i = audio.rfind(b"OggS")
        granulo = int.from_bytes(audio[i + 6:i + 14], "little")
        if 0 < granulo < 2 ** 63:  # -1 (todo unos) = página sin granule
            return Decimal(granulo) / 48000
    return Decimal(len(audio)) / 2000


async def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg") -> str | None:
    """Transcribe un audio. Retorna None si no está configurado o falla."""
    config = _config()
    if not config:
        return None
    proveedor, url, key, modelo = config
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
    await precios.registrar("stt", proveedor, modelo, segundos_audio=duracion_audio(audio))
    return r.json().get("text", "").strip() or None


# --- Respuesta en voz (texto → audio) ---

INSTRUCCIONES_DEFAULT = (
    "Habla en español de Colombia, con tono cálido, cercano y conversacional, a ritmo natural, "
    "como una persona amable que atiende por WhatsApp; nada de locutor ni de robot."
)

CARACTERES_POR_SEGUNDO = 15  # habla conversacional en español (~150 palabras por minuto)


def tts_configurada() -> bool:
    return _elegir(_TTS, "TTS_PROVEEDOR") is not None


def texto_para_voz(texto: str) -> str:
    """Versión hablable de una respuesta: sin URLs, markdown ni saltos de línea."""
    texto = re.sub(r"https?://\S+", "el link que te dejo aquí en el chat", texto)
    texto = re.sub(r"[*_#`~]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def sintetizar(texto: str) -> bytes | None:
    """Convierte texto en audio MP3 con el proveedor elegido. None si no hay o si falla."""
    texto = texto[:2000]  # ponytail: tope duro, una nota de voz no debe durar minutos
    proveedor = _elegir(_TTS, "TTS_PROVEEDOR")
    if not proveedor:
        return None
    _, funcion, modelo_default, valido = _TTS[proveedor]
    modelo = _opcion(proveedor, ("TTS_MODELO",), modelo_default, valido)
    audio = await funcion(texto, modelo)
    if audio:
        # ponytail: duración ESTIMADA por caracteres; la exacta pediría decodificar el mp3
        await precios.registrar("tts", proveedor, modelo, caracteres=len(texto),
                                segundos_audio=Decimal(len(texto)) / CARACTERES_POR_SEGUNDO)
    return audio


async def _sintetizar_openai(texto: str, modelo: str) -> bytes | None:
    payload = {
        "model": modelo,
        # OpenAI recomienda marin o cedar por calidad
        "voice": _opcion("openai", ("OPENAI_TTS_VOZ", "TTS_VOZ"), "marin", VOCES_OPENAI.__contains__),
        "input": texto,
        "response_format": "mp3",
    }
    if not modelo.startswith("tts-1"):  # tts-1 y tts-1-hd no aceptan instructions
        payload["instructions"] = os.getenv("TTS_INSTRUCCIONES", INSTRUCCIONES_DEFAULT)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=payload,
        )
        if r.status_code != 200:
            logger.error(f"Error TTS OpenAI: {r.status_code} — {r.text}")
            return None
        return r.content


async def _sintetizar_gemini(texto: str, modelo: str) -> bytes | None:
    """Gemini TTS devuelve PCM crudo (24kHz, 16-bit, mono) — se convierte a mp3 con ffmpeg."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY")},
            json={
                "contents": [{"parts": [{"text": texto}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                        "voiceName": _opcion("gemini", ("GEMINI_TTS_VOZ", "TTS_VOZ"), "Kore",
                                             VOCES_GEMINI.__contains__)}}},
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


# proveedor → (variable de la key, función texto→mp3, modelo por defecto, ¿el modelo es suyo?).
# El orden es la prioridad.
_TTS = {
    "openai": ("OPENAI_API_KEY", _sintetizar_openai, "gpt-4o-mini-tts", lambda m: m.startswith(("gpt-", "tts-"))),
    "gemini": ("GEMINI_API_KEY", _sintetizar_gemini, "gemini-2.5-flash-preview-tts",
               lambda m: m.startswith("gemini-")),
}
