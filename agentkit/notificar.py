# agentkit/notificar.py — Avisos al equipo por WhatsApp (ADMIN_PHONE)

import logging
import os

from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")


async def notificar_equipo(proveedor: ProveedorWhatsApp, texto: str) -> bool:
    """Envía un aviso al número del equipo (ADMIN_PHONE). No-op si no está configurado."""
    admin = os.getenv("ADMIN_PHONE", "").replace("whatsapp:", "").strip()
    if not admin:
        logger.info(f"[notificación sin ADMIN_PHONE] {texto}")
        return False
    return await proveedor.enviar_mensaje(admin, texto)
