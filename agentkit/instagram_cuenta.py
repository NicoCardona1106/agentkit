# agentkit/instagram_cuenta.py — OAuth y ciclo de vida del token de Instagram Login

import asyncio
import hashlib
import hmac
import html
import logging
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
import yaml
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from agentkit import memory, notificar

logger = logging.getLogger("agentkit")
router = APIRouter()


def _graph_url(ruta: str) -> str:
    version = os.getenv("IG_GRAPH_VERSION", "").strip().strip("/")
    prefijo = f"/{version}" if version else ""
    return f"https://graph.instagram.com{prefijo}/{ruta.lstrip('/')}"


def crear_state(ahora: int | None = None) -> str:
    timestamp = str(ahora if ahora is not None else int(time.time()))
    firma = hmac.new(os.environ["IG_APP_SECRET"].encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{firma}"


def state_valido(state: str, ahora: int | None = None) -> bool:
    try:
        timestamp, firma = state.split(".", 1)
        edad = (ahora if ahora is not None else int(time.time())) - int(timestamp)
        esperada = hmac.new(os.environ["IG_APP_SECRET"].encode(), timestamp.encode(), hashlib.sha256).hexdigest()
        return 0 <= edad <= 600 and hmac.compare_digest(firma, esperada)
    except (KeyError, ValueError):
        return False


def _nombre_negocio() -> str:
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as archivo:
            datos = yaml.safe_load(archivo) or {}
        negocio = datos.get("negocio") if isinstance(datos, dict) else None
        return str(negocio.get("nombre")) if isinstance(negocio, dict) and negocio.get("nombre") else "tu negocio"
    except (OSError, yaml.YAMLError):
        return "tu negocio"


def _pagina(titulo: str, mensaje: str, estado: int = 200) -> HTMLResponse:
    titulo, mensaje, negocio = map(html.escape, (titulo, mensaje, _nombre_negocio()))
    contenido = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo} · {negocio}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f6f4;color:#171717;font:16px/1.5 system-ui,sans-serif}}
main{{box-sizing:border-box;width:min(560px,calc(100% - 32px));padding:32px;border:1px solid #ddd;border-radius:16px;background:white;box-shadow:0 12px 36px #0001}}
h1{{margin:0 0 12px;font-size:clamp(24px,5vw,34px);line-height:1.15}}p{{margin:0;color:#555}}
</style></head><body><main><h1>{titulo}</h1><p>{mensaje}</p></main></body></html>"""
    return HTMLResponse(contenido, status_code=estado)


@router.get("/instagram/conectar")
async def conectar_instagram():
    redirect_uri = f"{os.getenv('PUBLIC_URL', '').rstrip('/')}/instagram/callback"
    parametros = {
        "client_id": os.environ["IG_APP_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments",
        "state": crear_state(),
    }
    return RedirectResponse(f"https://www.instagram.com/oauth/authorize?{urlencode(parametros)}")


@router.get("/instagram/callback")
async def callback_instagram(code: str = "", state: str = ""):
    if not state_valido(state):
        return _pagina("Conexión rechazada", "El enlace venció o no es válido. Inicia la conexión de nuevo.", 400)
    if not os.getenv("IG_TOKEN_KEY", "").strip():
        logger.error("Instagram Login no puede guardar el token: IG_TOKEN_KEY no configurada")
        return _pagina("Configuración incompleta", "Falta configurar la clave de cifrado del agente.", 503)
    if not code:
        return _pagina("Conexión incompleta", "Instagram no devolvió el código de autorización.", 400)

    redirect_uri = f"{os.getenv('PUBLIC_URL', '').rstrip('/')}/instagram/callback"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            corto = await client.post("https://api.instagram.com/oauth/access_token", data={
                "client_id": os.environ["IG_APP_ID"],
                "client_secret": os.environ["IG_APP_SECRET"],
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            })
            corto.raise_for_status()
            token_corto = corto.json()["access_token"]
            largo = await client.get(_graph_url("access_token"), params={
                "grant_type": "ig_exchange_token",
                "client_secret": os.environ["IG_APP_SECRET"],
                "access_token": token_corto,
            })
            largo.raise_for_status()
            datos_token = largo.json()
            token = datos_token["access_token"]
            vence_en = datetime.utcnow() + timedelta(seconds=int(datos_token["expires_in"]))
            perfil = await client.get(_graph_url("me"), params={"fields": "user_id,username"},
                                       headers={"Authorization": f"Bearer {token}"})
            perfil.raise_for_status()
            datos_perfil = perfil.json()
            # VERIFICAR: confirmar en el panel de Meta que `messages` se acepta junto a `comments` aquí.
            suscripcion = await client.post(_graph_url("me/subscribed_apps"),
                                             params={"subscribed_fields": "comments,messages"},
                                             headers={"Authorization": f"Bearer {token}"})
            suscripcion.raise_for_status()
        await memory.guardar_cuenta_instagram(str(datos_perfil["user_id"]), datos_perfil["username"],
                                              token, vence_en)
        return _pagina(f"Cuenta @{datos_perfil['username']} conectada",
                       f"Instagram quedó conectado con {_nombre_negocio()}.")
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        logger.error("Falló Instagram Login (%s); no se guardó ninguna cuenta", type(error).__name__)
        return _pagina("No pudimos conectar Instagram", "Inténtalo de nuevo en unos minutos.", 502)


async def token_activo() -> tuple[str, str] | None:
    cuenta = await memory.obtener_cuenta_instagram()
    return (cuenta["ig_user_id"], cuenta["token"]) if cuenta else None


async def renovar_tokens():
    limite = datetime.utcnow() + timedelta(days=10)
    cuentas = await memory.cuentas_instagram_por_renovar(limite)
    for cuenta in cuentas:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                respuesta = await client.get(_graph_url("refresh_access_token"), params={
                    "grant_type": "ig_refresh_token",
                    "access_token": cuenta["token"],
                })
                respuesta.raise_for_status()
            datos = respuesta.json()
            vence_en = datetime.utcnow() + timedelta(seconds=int(datos["expires_in"]))
            await memory.actualizar_token_instagram(cuenta["ig_user_id"], datos["access_token"], vence_en)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            logger.error("No se pudo renovar el token de Instagram de @%s (%s)",
                         cuenta["usuario"], type(error).__name__)
            from agentkit.providers import obtener_proveedor
            await notificar.notificar_equipo(
                obtener_proveedor(), f"No se pudo renovar la conexión de Instagram de @{cuenta['usuario']}.")


async def bucle_renovacion():
    while True:
        await asyncio.sleep(12 * 60 * 60)
        await renovar_tokens()
