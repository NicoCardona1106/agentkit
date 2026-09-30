# agentkit/instagram_comentarios.py — Comentario con palabra clave → respuesta privada (DM) por Instagram
#
# El texto del comentario solo se compara con las reglas y se guarda en ig_comentarios:
# nunca llega al modelo (este módulo no importa brain).

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx
import yaml

from agentkit import instagram_cuenta, memory, notificar

logger = logging.getLogger("agentkit")

RUTA_REGLAS = "config/instagram.yaml"
LIMITE_HORA = 750  # respuestas privadas por hora y por cuenta (límite de Meta)
ESPERAS = (2, 5)  # segundos antes de cada reintento si Meta falla (5xx o red)
DIAS_PLAZO = 7  # Meta solo deja responder en privado dentro de 7 días

_reglas: list[dict] | None = None
_cupo = {"hora": "", "n": 0, "avisada": False}  # ponytail: en memoria; al reiniciar se cuenta desde cero
_errores_seguidos = 0


def normalizar(texto: str) -> str:
    """Sin tildes y en mayúsculas."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))
    return sin_tildes.upper()


# ── Reglas ────────────────────────────────────────────────────

def cargar_reglas(ruta: str = RUTA_REGLAS) -> list[dict]:
    """Lee las reglas del archivo y las deja en memoria. Archivo ausente o inválido: log y cero reglas."""
    global _reglas
    _reglas = []
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            datos = yaml.safe_load(archivo) or {}
        reglas = []
        for regla in datos["reglas"]:
            palabras = regla["palabras"]
            palabras = [palabras] if isinstance(palabras, str) else list(palabras)
            publicaciones = regla.get("publicaciones", "todas")
            if publicaciones != "todas":
                if isinstance(publicaciones, str):
                    raise ValueError("publicaciones debe ser 'todas' o una lista de media_id")
                publicaciones = {str(m) for m in publicaciones}
            palabras = [normalizar(str(p)).strip() for p in palabras]
            mensaje = str(regla["mensaje"]).strip()
            if not mensaje or not all(palabras) or not palabras:
                raise ValueError("regla sin palabras o sin mensaje")
            reglas.append({"palabras": palabras, "mensaje": mensaje, "publicaciones": publicaciones,
                           "respuesta_publica": str(regla.get("respuesta_publica") or "").strip()})
        _reglas = reglas
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError) as error:
        logger.error("Reglas de comentarios de Instagram no disponibles (%s): %s; sin reglas",
                     ruta, type(error).__name__)
    return _reglas


def buscar_regla(texto: str, media_id: str = "") -> dict | None:
    """Primera regla cuya palabra aparece COMPLETA en el texto (RF-07). Devuelve la regla + `palabra`."""
    if _reglas is None:
        cargar_reglas()
    normal = normalizar(texto)
    for regla in _reglas:
        if regla["publicaciones"] != "todas" and str(media_id) not in regla["publicaciones"]:
            continue
        for palabra in regla["palabras"]:
            if re.search(rf"(?<!\w){re.escape(palabra)}(?!\w)", normal):
                return {**regla, "palabra": palabra}
    return None


# ── Límite por hora y avisos ──────────────────────────────────

def _reservar_cupo() -> bool:
    hora = datetime.utcnow().strftime("%Y%m%d%H")
    if _cupo["hora"] != hora:
        _cupo.update(hora=hora, n=0, avisada=False)
    if _cupo["n"] >= LIMITE_HORA:
        return False
    _cupo["n"] += 1
    return True


async def _avisar(texto: str):
    from agentkit.providers import obtener_proveedor  # aquí: providers.instagram importa instagram_cuenta
    await notificar.notificar_equipo(obtener_proveedor(), texto)


# ── Llamadas a Meta ───────────────────────────────────────────

async def _post(url: str, token: str, **kwargs) -> tuple[bool, str]:
    """POST con 2 reintentos (5xx o red). Devuelve (ok, motivo). Un 4xx no se reintenta."""
    motivo = ""
    for espera in (0, *ESPERAS):
        if espera:
            await asyncio.sleep(espera)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except httpx.HTTPError as error:
            motivo = f"red_{type(error).__name__}"
            continue
        if r.status_code < 300:
            return True, ""
        motivo = f"http_{r.status_code}"
        if r.status_code < 500:
            break
    return False, motivo


async def _cerrar(comment_id: str, resultado: str, motivo: str, regla: str | None = None):
    await memory.actualizar_comentario(comment_id, resultado, motivo, regla)


async def _fallar(comment_id: str, motivo: str, regla: str):
    global _errores_seguidos
    await _cerrar(comment_id, "error", motivo, regla)
    _errores_seguidos += 1
    if _errores_seguidos >= 3:
        _errores_seguidos = 0
        await _avisar(f"Instagram: 3 respuestas privadas seguidas fallaron ({motivo}). Revisa la conexión.")


# ── Procesamiento ─────────────────────────────────────────────

async def procesar_comentario(evento: dict):
    """`evento` = `value` del cambio `comments` más `entry_id` y `entry_time` del entry."""
    try:
        comment_id = str(evento.get("id") or "")
        if not comment_id:
            return
        autor = evento.get("from") or {}
        igsid, usuario = str(autor.get("id") or ""), str(autor.get("username") or "")
        try:
            creado_en = datetime.fromtimestamp(int(evento["entry_time"]), timezone.utc).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            creado_en = datetime.utcnow()
        fila = {"comment_id": comment_id, "media_id": str((evento.get("media") or {}).get("id") or ""),
                "igsid": igsid, "usuario": usuario, "texto": str(evento.get("text") or ""), "creado_en": creado_en}

        if not await memory.insertar_comentario(**fila):  # webhook repetido: no se hace nada (RNF-04)
            return
        if igsid and igsid in (str(evento.get("entry_id") or ""), *await _cuenta_propia()):
            return await _cerrar(comment_id, "omitido", "propio")
        if evento.get("parent_id"):
            return await _cerrar(comment_id, "omitido", "respuesta_a_comentario")
        await _entregar(fila)
    except Exception:
        logger.exception("Falló el procesamiento de un comentario de Instagram")


async def _cuenta_propia() -> list[str]:
    cuenta = await memory.estado_cuenta_instagram()  # sin descifrar el token
    return [cuenta["ig_user_id"]] if cuenta else []


async def _entregar(fila: dict):
    """Regla, cupo, respuesta privada y extras. Sirve para el comentario nuevo y para los en_cola."""
    comment_id = fila["comment_id"]
    if fila["creado_en"] < datetime.utcnow() - timedelta(days=DIAS_PLAZO):
        return await _cerrar(comment_id, "omitido", "mas_de_7_dias")
    regla = buscar_regla(fila["texto"], fila["media_id"])
    if not regla:
        return await _cerrar(comment_id, "omitido", "sin_regla")
    palabra = regla["palabra"]

    try:
        cuenta = await instagram_cuenta.token_activo()
    except (RuntimeError, ValueError):
        cuenta = None
    if not cuenta:
        return await _fallar(comment_id, "sin_cuenta_o_token", palabra)
    ig_user_id, token = cuenta

    if not _reservar_cupo():
        await _cerrar(comment_id, "en_cola", "limite_750_hora", palabra)
        if not _cupo["avisada"]:
            _cupo["avisada"] = True
            await _avisar("Instagram: se llegó al límite de 750 respuestas privadas por hora; "
                          "los comentarios nuevos quedan en cola.")
        return

    # La respuesta privada es la apertura: no pasa por ProveedorInstagram.enviar_mensaje (ventana de 24 h)
    # VERIFICAR: Meta documenta /me/messages; aquí /{ig_user_id}/messages, igual que en A1.
    ok, motivo = await _post(instagram_cuenta._graph_url(f"{ig_user_id}/messages"), token,
                             json={"recipient": {"comment_id": comment_id}, "message": {"text": regla["mensaje"]}})
    if not ok:
        return await _fallar(comment_id, motivo, palabra)
    global _errores_seguidos
    _errores_seguidos = 0
    await _cerrar(comment_id, "enviado", "", palabra)

    try:  # el DM ya salió: un fallo de los extras no lo deshace
        await memory.guardar_mensaje(fila["igsid"], "assistant", regla["mensaje"])
        if regla["respuesta_publica"]:
            # VERIFICAR: Meta muestra `message` como parámetro de la URL; confirmar que acepta también cuerpo JSON.
            ok_publico, _ = await _post(instagram_cuenta._graph_url(f"{comment_id}/replies"), token,
                                        params={"message": regla["respuesta_publica"]})
            if not ok_publico:
                logger.warning("No se pudo publicar la respuesta pública al comentario %s", comment_id)
        # VERIFICAR: el webhook no trae el permalink de la publicación; se usa el media_id.
        await memory.guardar_dato_cliente(fila["igsid"], nombre=fila["usuario"],
                                          nota=f"Llegó por el comentario «{palabra}» en {fila['media_id']}")
        await memory.crear_lead(fila["igsid"], nombre=fila["usuario"],
                                interes=f"Comentó {palabra} [instagram:comentario:{palabra}]",
                                contacto=f"instagram:@{fila['usuario']}")
        await _avisar(f"Instagram: @{fila['usuario']} comentó {palabra} y recibió el DM.")
    except Exception:
        logger.exception("Falló un paso posterior al DM de un comentario de Instagram")


# ── Segundo plano ─────────────────────────────────────────────

async def reprocesar_cola():
    for fila in await memory.comentarios_en_cola():
        await _entregar(fila)


async def bucle_comentarios():
    """Cada 5 min reprocesa los en_cola; una vez al día borra lo de más de 12 meses (RNF-07)."""
    ultimo_borrado = None
    while True:
        try:
            await reprocesar_cola()
            if ultimo_borrado != datetime.utcnow().date():
                await memory.borrar_comentarios_antiguos(datetime.utcnow() - timedelta(days=365))
                ultimo_borrado = datetime.utcnow().date()
        except Exception:
            logger.exception("Falló el ciclo de comentarios de Instagram")
        await asyncio.sleep(300)
