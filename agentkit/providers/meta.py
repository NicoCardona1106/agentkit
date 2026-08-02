# agentkit/providers/meta.py — Adaptador para Meta WhatsApp Cloud API

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import Request

from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp

logger = logging.getLogger("agentkit")


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.app_secret = os.getenv("META_APP_SECRET")
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == self.verify_token:
            return int(params.get("hub.challenge"))
        return None

    async def validar_firma(self, request: Request) -> bool:
        """Valida X-Hub-Signature-256 (HMAC-SHA256 del body con el App Secret)."""
        if not self.app_secret:
            logger.warning("META_APP_SECRET no configurado — firma de webhook NO validada")
            return True
        firma = request.headers.get("X-Hub-Signature-256", "")
        cuerpo = await request.body()
        esperada = "sha256=" + hmac.new(self.app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
        return hmac.compare_digest(firma, esperada)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        body = await request.json()
        mensajes = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    tipo = msg.get("type")
                    if tipo == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=msg.get("from", ""),
                            texto=msg.get("text", {}).get("body", ""),
                            mensaje_id=msg.get("id", ""),
                        ))
                    elif tipo == "audio":
                        mensajes.append(MensajeEntrante(
                            telefono=msg.get("from", ""),
                            texto="",
                            mensaje_id=msg.get("id", ""),
                            audio_ref=msg.get("audio", {}).get("id", ""),
                        ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        payload = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": mensaje}}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {self.access_token}"})
            if r.status_code != 200:
                logger.error(f"Error Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """En Meta el audio_ref es un media id: primero se resuelve la URL, luego se descarga."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(f"https://graph.facebook.com/{self.api_version}/{audio_ref}", headers=headers)
            if r.status_code != 200:
                logger.error(f"Error resolviendo media de Meta: {r.text}")
                return None
            media_url = r.json().get("url")
            r2 = await client.get(media_url, headers=headers)
            return r2.content if r2.status_code == 200 else None
