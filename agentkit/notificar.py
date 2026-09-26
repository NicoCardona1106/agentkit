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


async def notificar_equipo(proveedor: ProveedorWhatsApp, texto: str) -> bool:
    """Avisa al equipo por Telegram y/o por WhatsApp (ADMIN_PHONE), según lo configurado.

    Un agente solo web (sin número de WhatsApp) usa Telegram. Sin ningún canal, el aviso NO
    se escribe completo en el log: puede traer el contacto de un visitante (Ley 1581).
    """
    enviado = await _telegram(texto)
    admin = os.getenv("ADMIN_PHONE", "").replace("whatsapp:", "").strip()
    if admin:
        enviado = await proveedor.enviar_mensaje(admin, texto) or enviado
    if not enviado:
        logger.info(f"[aviso sin canal configurado] texto omitido ({len(texto)} caracteres)")
    return enviado
