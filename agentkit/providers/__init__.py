# agentkit/providers/__init__.py — Factory de proveedores

import os

from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp

__all__ = ["MensajeEntrante", "ProveedorWhatsApp", "obtener_proveedor"]


def obtener_proveedor() -> ProveedorWhatsApp:
    """Retorna el proveedor de WhatsApp configurado en WHATSAPP_PROVIDER (.env)."""
    proveedor = os.getenv("WHATSAPP_PROVIDER", "").lower()
    if proveedor == "meta":
        from agentkit.providers.meta import ProveedorMeta
        return ProveedorMeta()
    if proveedor == "twilio":
        from agentkit.providers.twilio import ProveedorTwilio
        return ProveedorTwilio()
    raise ValueError(f"WHATSAPP_PROVIDER no válido: '{proveedor}'. Usa: meta o twilio")
