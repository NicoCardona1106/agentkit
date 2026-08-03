# agentkit/providers/twilio.py — Adaptador para Twilio WhatsApp

import base64
import hashlib
import hmac
import logging
import os

import httpx
from fastapi import Request

from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp

logger = logging.getLogger("agentkit")


def firma_twilio(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Calcula la firma X-Twilio-Signature: HMAC-SHA1(token, url + params ordenados)."""
    datos = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(auth_token.encode(), datos.encode(), hashlib.sha1).digest()).decode()


class ProveedorTwilio(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Twilio."""

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")
        # URL pública del servidor (Railway) — necesaria para validar la firma detrás del proxy
        self.public_url = os.getenv("PUBLIC_URL", "").rstrip("/")

    async def validar_firma(self, request: Request) -> bool:
        if not self.auth_token:
            return True
        if not self.public_url:
            logger.warning("PUBLIC_URL no configurada — firma de Twilio NO validada")
            return True
        firma = request.headers.get("X-Twilio-Signature", "")
        url = self.public_url + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        form = await request.form()
        esperada = firma_twilio(self.auth_token, url, {k: str(v) for k, v in form.items()})
        return hmac.compare_digest(firma, esperada)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        form = await request.form()
        telefono = str(form.get("From", "")).replace("whatsapp:", "")
        mensaje_id = str(form.get("MessageSid", ""))
        audio_ref = None
        if int(form.get("NumMedia", 0) or 0) > 0 and "audio" in str(form.get("MediaContentType0", "")):
            audio_ref = str(form.get("MediaUrl0", ""))
        texto = str(form.get("Body", "") or "")
        if not texto and not audio_ref:
            return []
        return [MensajeEntrante(telefono=telefono, texto=texto, mensaje_id=mensaje_id, audio_ref=audio_ref)]

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        if not all([self.account_sid, self.auth_token, self.phone_number]):
            logger.warning("Variables de Twilio no configuradas")
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {"From": f"whatsapp:{self.phone_number}", "To": f"whatsapp:{telefono}", "Body": mensaje}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            if r.status_code != 201:
                logger.error(f"Error Twilio: {r.status_code} — {r.text}")
            return r.status_code == 201

    async def enviar_audio_url(self, telefono: str, audio_url: str) -> bool:
        if not all([self.account_sid, self.auth_token, self.phone_number]):
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {"From": f"whatsapp:{self.phone_number}", "To": f"whatsapp:{telefono}", "MediaUrl": audio_url}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            if r.status_code != 201:
                logger.error(f"Error Twilio (audio): {r.status_code} — {r.text}")
            return r.status_code == 201

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """En Twilio el audio_ref es la URL del media (requiere auth básica)."""
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(audio_ref, auth=(self.account_sid, self.auth_token))
            return r.content if r.status_code == 200 else None
