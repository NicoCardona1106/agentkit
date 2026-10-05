# agentkit/providers/base.py — Interfaz común de proveedores de WhatsApp

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import Request

logger = logging.getLogger("agentkit")


def aceptar_sin_firma(motivo: str) -> bool:
    """Qué hacer con un webhook cuando falta el secreto para validar su firma.

    En producción se RECHAZA (fallar cerrado: sin secreto, cualquiera podría mandar webhooks falsos).
    Fuera de producción se acepta con aviso, para probar en local. Se decide por petición y no al
    arrancar, para no apagar un agente que no recibe webhooks (p. ej. uno que solo atiende el chat web).
    """
    if os.getenv("ENVIRONMENT", "development") == "production":
        logger.error("%s — webhook RECHAZADO (ENVIRONMENT=production)", motivo)
        return False
    logger.warning("%s — firma NO validada (solo fuera de producción)", motivo)
    return True


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str            # Número del remitente
    texto: str               # Contenido del mensaje (vacío si es audio)
    mensaje_id: str          # ID único del mensaje
    audio_ref: str | None = None  # Referencia al audio (media id o URL, según proveedor)


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def validar_webhook(self, request: Request) -> str | None:
        """Verificación GET del webhook (solo Meta la requiere). Devuelve el hub.challenge o None."""
        return None

    async def validar_firma(self, request: Request) -> bool:
        """Valida la firma del webhook. Retorna False si es inválida."""
        return True

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """Descarga el audio de una nota de voz. None si no soporta audio."""
        return None

    async def enviar_audio_url(self, telefono: str, audio_url: str) -> bool:
        """Envía un audio desde una URL pública. False si el canal no lo soporta."""
        return False
