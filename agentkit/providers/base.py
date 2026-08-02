# agentkit/providers/base.py — Interfaz común de proveedores de WhatsApp

from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import Request


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

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere)."""
        return None

    async def validar_firma(self, request: Request) -> bool:
        """Valida la firma del webhook. Retorna False si es inválida."""
        return True

    async def descargar_audio(self, audio_ref: str) -> bytes | None:
        """Descarga el audio de una nota de voz. None si no soporta audio."""
        return None
