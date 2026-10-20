# agentkit/notificar.py — Avisos al equipo: Telegram (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID) y/o WhatsApp (ADMIN_PHONE)

import logging
import os

import httpx

from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")
# httpx registra la URL completa a nivel INFO y en Telegram esa URL lleva el token.
logging.getLogger("httpx").setLevel(logging.WARNING)


async def _telegram(texto: str) -> bool:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat):
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data={"chat_id": chat, "text": texto})
        if r.status_code != 200:
            logger.warning(f"Telegram respondió HTTP {r.status_code}")
        return r.status_code == 200
    except httpx.HTTPError as e:
        logger.warning(f"No se pudo avisar por Telegram: {type(e).__name__}")
        return False


def _telegram_configurado() -> bool:
    return bool(os.getenv("TELEGRAM_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def advertir_config():
    """Al arrancar: en Instagram ADMIN_PHONE no es un destino válido, así que sin Telegram no hay canal de avisos."""
    from agentkit import borrador  # aquí y no arriba: nada de este módulo debe depender del modo borrador
    if borrador.es_instagram() and os.getenv("ADMIN_PHONE", "").strip() and not _telegram_configurado():
        logger.warning("PROVIDER=instagram: ADMIN_PHONE no sirve para avisos (no es un IGSID) y no hay Telegram "
                       "configurado: los avisos al equipo no tienen canal")


async def notificar_equipo(proveedor: ProveedorWhatsApp, texto: str) -> bool:
    """Avisa al equipo por Telegram y/o por WhatsApp (ADMIN_PHONE), según lo configurado.

    Un agente solo web (sin número de WhatsApp) usa Telegram. Sin ningún canal, el aviso NO
    se escribe completo en el log: puede traer el contacto de un visitante (Ley 1581).
    """
    enviado = await _telegram(texto)
    from agentkit import borrador
    admin = os.getenv("ADMIN_PHONE", "").replace("whatsapp:", "").strip()
    if admin and not borrador.es_instagram():  # por Instagram el aviso nunca sale hacia ADMIN_PHONE (RF-56)
        enviado = await proveedor.enviar_mensaje(admin, texto) or enviado
    if not enviado:
        logger.info(f"[aviso sin canal configurado] texto omitido ({len(texto)} caracteres)")
    return enviado
