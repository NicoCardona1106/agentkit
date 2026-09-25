# agentkit/voz.py — Notas de voz: transcripción (STT) y respuesta en voz (TTS)
#
# Entrada (audio → texto):
#   - OPENAI_API_KEY → OpenAI gpt-4o-mini-transcribe (~USD 0,003/min) — por defecto si hay key
#   - GROQ_API_KEY   → Groq whisper-large-v3 (capa gratis) — si no hay key de OpenAI
#   STT_PROVEEDOR=openai|groq fuerza uno (y solo ese; sin su key, el agente queda sin STT).
#   VOZ_MODELO cambia el modelo.
# Salida (texto → audio, siempre mp3). Decisión de Nicolas 2026-09-25 (prueba de oído a ciegas,
# muestra «O3»): el modelo conversacional gpt-audio-1.5 con la voz marin, por Chat Completions con
# audio (no /v1/audio/speech), la más humana de la prueba (~USD 0,08/min, ~5× el TTS barato).
#   - openai-audio → gpt-audio-1.5 (OPENAI_AUDIO_MODELO o TTS_MODELO, solo gpt-audio*). Es
#     conversacional y puede cambiar el texto: la guarda es_fiel compara su transcript con lo pedido
#     y, si no coincide (o cambia un número), descarta el audio y pasa al respaldo.
#   - openai → gpt-4o-mini-tts, mp3 directo (respaldo 1).
#   - gemini → gemini-2.5-flash-preview-tts, GEMINI_TTS_VOZ o TTS_VOZ (default Kore; respaldo 2).
#     Devuelve PCM: requiere ffmpeg para mp3. Usar una key con facturación activa: en el tier
#     gratis Google puede entrenar con los datos (choca con la Ley 1581 frente al cliente).
#   Las dos de OpenAI usan OPENAI_TTS_VOZ o TTS_VOZ (default marin).
#   TTS_PROVEEDOR elige el primero (default: el primero de _TTS con key); si falla, se intentan los
#   respaldos (_RESPALDOS) que tengan key. Forzar un proveedor sin su key deja al agente sin voz.
#   TTS_INSTRUCCIONES (tono, acento y ritmo) aplica a todos: gpt-audio la recibe en el mensaje
#   system (tras LECTOR_GPT_AUDIO), gpt-4o-mini-tts en `instructions` y Gemini antepuesta al
#   texto (ver _texto_gemini). Defaults: INSTRUCCIONES_FLUIDO (OpenAI) e INSTRUCCIONES_GEMINI.
# Cada proveedor valida modelo y voz: si un valor es de otro proveedor (un .env viejo con
# VOZ_MODELO=whisper-large-v3 o TTS_VOZ=Kore al pasar a OpenAI), usa su default y avisa una vez.
#   Otro proveedor (deepgram, elevenlabs…): escribir _sintetizar_<nombre>(texto, modelo) → mp3
#   y agregarlo a _TTS al final del archivo, con su variable de key y su modelo por defecto.
# Cada llamada queda registrada con su costo en uso_api (ver precios.py): gpt-audio con los
# tokens reales de su usage (también si la guarda descarta el audio); los demás, estimado.

import asyncio
import base64
import difflib
import logging
import os
import re
import unicodedata
from decimal import Decimal

import httpx

from agentkit import precios

logger = logging.getLogger("agentkit")

# Voces válidas verificadas el 2026-09-25 en la referencia de /v1/audio/speech de OpenAI y en
# ai.google.dev/gemini-api/docs/speech-generation.
VOCES_OPENAI = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage",
                "shimmer", "verse", "marin", "cedar"}
# gpt-audio (Chat Completions con audio) acepta las mismas voces: verificado 2026-09-25 con llamadas
# reales a gpt-audio-1.5 (nova, fable, onyx, verse y ballad respondieron OK).
VOCES_GPT_AUDIO = VOCES_OPENAI
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
    """Proveedor forzado por `variable` (None si no tiene key), o el primero de la tabla con key."""
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

# Estilo con el que se generó la muestra Kore de Gemini (prueba de oído): no cambiar sin repetirla.
INSTRUCCIONES_GEMINI = (
    "Habla en español de Colombia, con tono cálido, cercano y conversacional, a ritmo natural, "
    "como una persona amable que atiende por WhatsApp; nada de locutor ni de robot."
)
# FLUIDO de herramientas/prueba-voces/ajuste_sage.py: con él se generó la muestra O3 (gpt-audio-1.5).
INSTRUCCIONES_FLUIDO = (
    "Habla en español de Colombia, con tono cálido y cercano, como una persona amable que atiende por "
    "WhatsApp. Habla de corrido y con soltura: une las frases sin pausas largas, no te detengas en las comas "
    "ni entre oraciones, y mantén un ritmo conversacional ágil y continuo. Nada de locutor ni de robot."
)
# gpt-audio es conversacional: con la cláusula de v0.7.1 («di palabra por palabra el mensaje del usuario»)
# a veces respondía en vez de leer («Claro, repetimos…») y la guarda caía al respaldo (2 de 8 en la prueba
# del 2026-09-25). Rol de lector + texto entre <leer></leer>: 8 de 8 fieles
# (herramientas/prueba-voces/fidelidad_gpt_audio.py). Las instrucciones de tono van después.
LECTOR_GPT_AUDIO = ("Eres un lector de voz, no un asistente: nunca conversas, nunca respondes, nunca comentas "
                    "ni confirmas. Recibes un texto entre <leer> y </leer> y lo dices en voz alta EXACTAMENTE como "
                    "está escrito, de la primera a la última palabra, sin agregar ni quitar nada (nada de «claro», "
                    "«listo», «repito» ni saludos extra). Cómo debe sonar:")

CARACTERES_POR_SEGUNDO = 15  # habla conversacional en español (~150 palabras por minuto)
SIMILITUD_MINIMA = 0.9  # guarda de fidelidad de gpt-audio (difflib sobre palabras normalizadas)
SIMILITUD_MINIMA_LARGO = 0.95  # desde PALABRAS_LARGO palabras: un cambio pesa menos en la razón
PALABRAS_LARGO = 20
# Palabras que cambian el sentido o la fecha: deben coincidir exactas y en orden, como los números.
# Van normalizadas (sin tildes): "sí" → "si", "mañana" → "manana".
PALABRAS_CRITICAS = {"no", "si", "nunca", "ni", "sin", "tampoco", "jamas", "hoy", "manana", "ayer",
                     "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}
# Timeout de cada llamada TTS: conexión 5 s y lectura acotada (main.py pone además un tope total).
TIMEOUT_TTS = httpx.Timeout(30, connect=5)


def tts_configurada() -> bool:
    return _elegir(_TTS, "TTS_PROVEEDOR") is not None


def texto_para_voz(texto: str) -> str:
    """Versión hablable de una respuesta: sin URLs, markdown ni saltos de línea."""
    texto = re.sub(r"https?://\S+", "el link que te dejo aquí en el chat", texto)
    texto = re.sub(r"[*_#`~]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _palabras(texto: str) -> list[str]:
    """Palabras normalizadas: minúsculas, sin tildes ni puntuación ni `$`, y los separadores de
    miles unidos ($3.500 → 3500)."""
    texto = unicodedata.normalize("NFKD", texto.lower())  # NFKD también pasa el espacio duro a espacio
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"(?<=\d)[.,\s](?=\d{3}(?!\d))", "", texto)  # 30.000 / 30,000 / 30 000 → 30000
    texto = re.sub(r"(\d)\s*([ap])\.?\s?m\b\.?", r"\1 \2m", texto)  # 5pm / 5 p. m. → 5 pm
    texto = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", texto)  # a. m. / a.m. sueltos → am
    return re.findall(r"\w+", texto)


def es_fiel(pedido: str, dicho: str) -> bool:
    """¿Lo que dijo gpt-audio es lo pedido? Compara la transcripción que devuelve el propio modelo,
    NO un reconocimiento del mp3: si el audio se aparta de su transcript, la guarda no lo ve.
    Los números (precios, placas, horas) y PALABRAS_CRITICAS deben coincidir exactos y en orden;
    el resto, con similitud >= SIMILITUD_MINIMA (SIMILITUD_MINIMA_LARGO en textos largos).
    ponytail: un número dicho en letras ("tres mil quinientos") no coincide con "3.500" y manda al
    respaldo (más caro). Límite conocido: un sustantivo cambiado en un texto largo (carro → moto)
    puede pasar; subir el umbral o sumar palabras críticas si pasa en la práctica."""
    a, b = _palabras(pedido), _palabras(dicho)

    def criticas(palabras):
        return [p for p in palabras if p in PALABRAS_CRITICAS or any(c.isdigit() for c in p)]

    minima = SIMILITUD_MINIMA_LARGO if len(a) >= PALABRAS_LARGO else SIMILITUD_MINIMA
    return criticas(a) == criticas(b) and difflib.SequenceMatcher(None, a, b).ratio() >= minima


def _cadena_tts() -> list[str]:
    """Proveedores a intentar en orden: el elegido y luego los respaldos que tengan key."""
    primero = _elegir(_TTS, "TTS_PROVEEDOR")
    if not primero:
        return []
    return [primero] + [p for p in _RESPALDOS if p != primero and os.getenv(_TTS[p][0])]


async def sintetizar(texto: str) -> bytes | None:
    """Convierte texto en audio MP3: el proveedor elegido y, si falla, los respaldos.
    None si ninguno sirve. Nunca lanza: un fallo de voz no puede tumbar la respuesta de texto."""
    texto = texto[:2000]  # ponytail: tope duro, una nota de voz no debe durar minutos
    for proveedor in _cadena_tts():
        _, funcion, modelo_default, valido = _TTS[proveedor]
        variables = ("OPENAI_AUDIO_MODELO", "TTS_MODELO") if proveedor == "openai-audio" else ("TTS_MODELO",)
        modelo = _opcion(proveedor, variables, modelo_default, valido)
        try:
            audio = await funcion(texto, modelo)
        except Exception as e:
            logger.error(f"Error TTS {proveedor}: {e!r}")
            audio = None
        if audio:
            if proveedor != "openai-audio":  # gpt-audio ya registró su costo exacto desde usage
                # ponytail: duración ESTIMADA por caracteres; la exacta pediría decodificar el mp3
                await precios.registrar("tts", proveedor, modelo, caracteres=len(texto),
                                        segundos_audio=Decimal(len(texto)) / CARACTERES_POR_SEGUNDO)
            return audio
        logger.warning(f"TTS {proveedor} sin audio: pasa al siguiente respaldo, si hay")
    return None


def _voz_openai() -> str:
    # gpt-4o-mini-tts. OpenAI recomienda marin o cedar por calidad; marin es la voz de la muestra O3
    return _opcion("openai", ("OPENAI_TTS_VOZ", "TTS_VOZ"), "marin", VOCES_OPENAI.__contains__)


async def _sintetizar_openai_audio(texto: str, modelo: str) -> bytes | None:
    """gpt-audio por Chat Completions con audio, exactamente como la muestra O3: system =
    LECTOR_GPT_AUDIO + instrucciones, user = el texto entre <leer></leer>. Registra el costo con el usage real y descarta
    el audio (None → respaldo) si el transcript no pasa la guarda es_fiel."""
    instrucciones = os.getenv("TTS_INSTRUCCIONES", INSTRUCCIONES_FLUIDO).strip()
    payload = {
        "model": modelo,
        "modalities": ["text", "audio"],
        "audio": {"voice": _opcion("openai-audio", ("OPENAI_TTS_VOZ", "TTS_VOZ"), "marin",
                                   VOCES_GPT_AUDIO.__contains__), "format": "mp3"},
        "messages": [{"role": "system", "content": f"{LECTOR_GPT_AUDIO} {instrucciones}".strip()},
                     {"role": "user", "content": f"<leer>{texto}</leer>"}],
    }
    # Genera el audio completo antes de responder: la lectura crece con el texto, con tope de 45 s
    timeout = httpx.Timeout(min(10 + len(texto) / 40, 45), connect=5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=payload,
        )
    if r.status_code != 200:
        logger.error(f"Error TTS OpenAI gpt-audio: {r.status_code} — {r.text}")
        return None
    datos = r.json()
    # Antes de la guarda: un audio descartado también consumió tokens
    await precios.registrar("tts", "openai-audio", modelo, usage=datos.get("usage") or {},
                            caracteres=len(texto), segundos_audio=Decimal(len(texto)) / CARACTERES_POR_SEGUNDO)
    audio = datos["choices"][0]["message"]["audio"]
    dicho = audio.get("transcript", "")
    if not es_fiel(texto, dicho):
        logger.warning(f"gpt-audio cambió el texto, se descarta el audio. Pedido: {texto!r} — dijo: {dicho!r}")
        return None
    return base64.b64decode(audio["data"])


async def _sintetizar_openai(texto: str, modelo: str) -> bytes | None:
    payload = {
        "model": modelo,
        "voice": _voz_openai(),
        "input": texto,
        "response_format": "mp3",
    }
    if not modelo.startswith("tts-1"):  # tts-1 y tts-1-hd no aceptan instructions
        payload["instructions"] = os.getenv("TTS_INSTRUCCIONES", INSTRUCCIONES_FLUIDO)
    async with httpx.AsyncClient(timeout=TIMEOUT_TTS) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=payload,
        )
        if r.status_code != 200:
            logger.error(f"Error TTS OpenAI: {r.status_code} — {r.text}")
            return None
        return r.content


def _texto_gemini(texto: str, modelo: str) -> str:
    """Gemini 2.5 no tiene campo de instrucciones: el estilo va antepuesto al texto:
    las instrucciones, una línea en blanco y el texto (formato con el que se generó la muestra elegida en la prueba de
    oído, donde el modelo interpretó el estilo sin leerlo en voz alta).
    OJO: Gemini 3.8 TTS trata el texto como transcripción literal y LEERÍA el estilo en voz alta
    (pide `speech_metadata.style`, y además devuelve WAV y no PCM); por eso el prefijo solo va a los
    modelos anteriores y 3.8 no es un cambio de TTS_MODELO sin adaptar el código y probar de oído."""
    instrucciones = os.getenv("TTS_INSTRUCCIONES", INSTRUCCIONES_GEMINI).strip()
    if instrucciones and modelo.startswith(("gemini-2.", "gemini-3.1-")):
        return f"{instrucciones}\n\n{texto}"
    return texto


async def _sintetizar_gemini(texto: str, modelo: str) -> bytes | None:
    """Gemini TTS devuelve PCM crudo (24kHz, 16-bit, mono) — se convierte a mp3 con ffmpeg."""
    async with httpx.AsyncClient(timeout=TIMEOUT_TTS) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY")},
            json={
                "contents": [{"parts": [{"text": _texto_gemini(texto, modelo)}]}],
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
# El orden es la prioridad sin TTS_PROVEEDOR: gpt-audio (muestra O3), luego los respaldos.
# gemini-3.8-flash-tts existe y es la sucesora si el preview 2.5 se retira: no cambiar el default
# sin prueba de oído (ver _texto_gemini).
_TTS = {
    "openai-audio": ("OPENAI_API_KEY", _sintetizar_openai_audio, "gpt-audio-1.5",
                     lambda m: m.startswith("gpt-audio")),
    "openai": ("OPENAI_API_KEY", _sintetizar_openai, "gpt-4o-mini-tts",
               lambda m: m.startswith(("gpt-", "tts-")) and not m.startswith("gpt-audio")),
    "gemini": ("GEMINI_API_KEY", _sintetizar_gemini, "gemini-2.5-flash-preview-tts",
               lambda m: m.startswith("gemini-")),
}
# Respaldos, en orden, si el primero falla o gpt-audio no pasa la guarda. gpt-audio no es respaldo
# de nadie: si se fuerza otro proveedor es para no pagarlo.
_RESPALDOS = ("openai", "gemini")
