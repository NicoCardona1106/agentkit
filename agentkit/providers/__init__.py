# agentkit/providers/__init__.py — Factory de proveedores de canal

import os

from agentkit.providers.base import MensajeEntrante, ProveedorWhatsApp

__all__ = ["MensajeEntrante", "ProveedorWhatsApp", "obtener_proveedor"]


def obtener_proveedor() -> ProveedorWhatsApp:
    """Retorna el proveedor del canal configurado en PROVIDER (.env).

    Valores: meta (WhatsApp Cloud API) | twilio (WhatsApp) | instagram (DMs).
    Se acepta WHATSAPP_PROVIDER como alias por compatibilidad.
    """
    proveedor = (os.getenv("PROVIDER") or os.getenv("WHATSAPP_PROVIDER", "")).lower()
    if proveedor == "meta":
        from agentkit.providers.meta import ProveedorMeta
        return ProveedorMeta()
    if proveedor == "twilio":
        from agentkit.providers.twilio import ProveedorTwilio
        return ProveedorTwilio()
    if proveedor == "instagram":
        from agentkit.providers.instagram import ProveedorInstagram
        return ProveedorInstagram()
    raise ValueError(f"PROVIDER no válido: '{proveedor}'. Usa: meta, twilio o instagram")
