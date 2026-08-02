# agentkit/providers/instagram.py — Adaptador para Instagram DM (Meta Messenger Platform)
#
# Requiere: cuenta de Instagram profesional vinculada a una página de Facebook,
# app de Meta con el permiso instagram_manage_messages y un Page Access Token.
# Nota: Instagram solo permite responder dentro de las 24h del último mensaje del usuario.

import logging
import os

import httpx
from fastapi import Request

from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp
from agentkit.providers.meta import firma_meta_valida

logger = logging.getLogger("agentkit")


class ProveedorInstagram(ProveedorWhatsApp):
    """Proveedor de DMs de Instagram. El campo `telefono` es el IGSID del usuario."""

    def __init__(self):
        # Reusa las credenciales de Meta si el agente usa la misma app
        self.access_token = os.getenv("IG_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
        self.verify_token = os.getenv("IG_VERIFY_TOKEN") or os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.app_secret = os.getenv("IG_APP_SECRET") or os.getenv("META_APP_SECRET")
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == self.verify_token:
            return int(params.get("hub.challenge"))
        return None

    async def validar_firma(self, request: Request) -> bool:
        return firma_meta_valida(self.app_secret, request.headers.get("X-Hub-Signature-256", ""),
                                 await request.body())

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        body = await request.json()
        mensajes = []
        for entry in body.get("entry", []):
            for evento in entry.get("messaging", []):
                msg = evento.get("message", {})
                if not msg or msg.get("is_echo"):  # is_echo = mensajes enviados por el propio agente
                    continue
                audio_ref = None
                for adj in msg.get("attachments", []):
                    if adj.get("type") == "audio":
                        audio_ref = adj.get("payload", {}).get("url")
                mensajes.append(MensajeEntrante(
                    telefono=evento.get("sender", {}).get("id", ""),
                    texto=msg.get("text", "") or "",
                    mensaje_id=msg.get("mid", ""),
                    audio_ref=audio_ref,
                ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        if not self.access_token:
            logger.warning("IG_ACCESS_TOKEN no configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/me/messages"
        payload = {"recipient": {"id": telefono}, "message": {"text": mensaje}}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, params={"access_token": self.access_token})
            if r.status_code != 200:
                logger.error(f"Error Instagram API: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """En Instagram el audio_ref ya es una URL de CDN descargable."""
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(audio_ref)
            return r.content if r.status_code == 200 else None
