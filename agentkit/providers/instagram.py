# agentkit/providers/instagram.py — Adaptador para Instagram DM (Meta Messenger Platform)
#
# Requiere: cuenta de Instagram profesional vinculada a una página de Facebook,
# app de Meta con el permiso instagram_manage_messages y un Page Access Token.
# Nota: Instagram solo permite responder dentro de las 24h del último mensaje del usuario.

import logging
import os
from datetime import datetime, timedelta

import httpx
from fastapi import Request

from agentkit import instagram_cuenta, memory
from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp
from agentkit.providers.meta import firma_meta_valida

logger = logging.getLogger("agentkit")
_aviso_facebook_emitido = False


class ProveedorInstagram(ProveedorWhatsApp):
    """Proveedor de DMs de Instagram. El campo `telefono` es el IGSID del usuario."""

    def __init__(self):
        # Reusa las credenciales de Meta si el agente usa la misma app
        self.access_token = os.getenv("IG_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
        self.verify_token = os.getenv("IG_VERIFY_TOKEN") or os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.app_secret = os.getenv("IG_APP_SECRET") or os.getenv("META_APP_SECRET")
        self.api_version = os.getenv("IG_GRAPH_VERSION", "").strip().strip("/")
        # Hora del último mensaje recibido por webhook, por IGSID: cubre las respuestas que salen
        # antes de guardar el mensaje (p. ej. «no pude escuchar tu nota de voz» a alguien nuevo).
        self._ultimo_entrante: dict[str, datetime] = {}

    async def validar_webhook(self, request: Request) -> str | None:
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == self.verify_token:
            return params.get("hub.challenge", "")  # se devuelve tal cual: Meta lo compara como texto
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
                remitente = evento.get("sender", {}).get("id", "")
                if remitente:
                    self._ultimo_entrante[remitente] = datetime.utcnow()
                mensajes.append(MensajeEntrante(
                    telefono=remitente,
                    texto=msg.get("text", "") or "",
                    mensaje_id=msg.get("mid", ""),
                    audio_ref=audio_ref,
                ))
        return mensajes

    def parsear_comentarios(self, body: dict) -> list[dict]:
        """Cambios `comments` del webhook: el `value` más el ID de la cuenta y la hora del entry."""
        return [{**cambio["value"], "entry_id": entry.get("id"), "entry_time": entry.get("time")}
                for entry in body.get("entry", []) for cambio in entry.get("changes", [])
                if cambio.get("field") == "comments" and isinstance(cambio.get("value"), dict)]

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        guardado = await memory.ultimo_mensaje_usuario(telefono)
        ultimo = max(filter(None, (guardado, self._ultimo_entrante.get(telefono))), default=None)
        if not ultimo or ultimo < datetime.utcnow() - timedelta(hours=24):
            logger.warning("DM de Instagram omitido para %s: fuera de la ventana de 24 h", telefono)
            return False

        try:
            cuenta = await instagram_cuenta.token_activo()
        except (RuntimeError, ValueError):
            logger.error("No se pudo descifrar el token de Instagram; revisa IG_TOKEN_KEY")
            return False

        payload = {"recipient": {"id": telefono}, "message": {"text": mensaje}}
        async with httpx.AsyncClient() as client:
            if cuenta:
                ig_user_id, token = cuenta
                version = f"{self.api_version}/" if self.api_version else ""
                # VERIFICAR: Meta muestra /me/messages; el contrato A1 exige /{ig_user_id}/messages.
                url = f"https://graph.instagram.com/{version}{ig_user_id}/messages"
                r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            elif self.access_token:
                global _aviso_facebook_emitido
                if not _aviso_facebook_emitido:
                    logger.warning("Instagram usa la vía de Facebook: reconecta con /instagram/conectar")
                    _aviso_facebook_emitido = True
                url = "https://graph.facebook.com/v21.0/me/messages"
                r = await client.post(url, json=payload, params={"access_token": self.access_token})
            else:
                logger.warning("Instagram no tiene una cuenta conectada ni IG_ACCESS_TOKEN")
                return False
            if r.status_code != 200:
                logger.error("Error Instagram API: HTTP %s", r.status_code)
            return r.status_code == 200

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """En Instagram el audio_ref ya es una URL de CDN descargable."""
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(audio_ref)
            return r.content if r.status_code == 200 else None
