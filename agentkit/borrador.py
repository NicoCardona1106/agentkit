# agentkit/borrador.py — Modo borrador: el equipo aprueba cada respuesta antes de enviarla
# Se activa con MODO_BORRADOR=true + ADMIN_PHONE en el .env. El bot redacta, el
# admin recibe el borrador por WhatsApp y responde: ok N / no N / editar N <texto>.
# Pensado para el primer mes de un agente nuevo: confianza antes que autonomía.

import logging
import os
import re

from agentkit import humanizar, memory
from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")


def _solo_digitos(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")


def _admin() -> str:
    return os.getenv("ADMIN_PHONE", "").replace("whatsapp:", "").strip()


def activo() -> bool:
    return os.getenv("MODO_BORRADOR", "").lower() == "true" and bool(_admin())


def es_admin(telefono: str) -> bool:
    admin = _solo_digitos(_admin())
    return bool(admin) and _solo_digitos(telefono) == admin


async def proponer(proveedor: ProveedorWhatsApp, telefono: str,
                   respuesta: str, mensaje_cliente: str):
    """Guarda la respuesta como borrador y se la muestra al admin para aprobar."""
    bid = await memory.crear_borrador(telefono, respuesta)
    await proveedor.enviar_mensaje(_admin(), (
        f"📝 *Borrador #{bid}* para {telefono}\n\n"
        f"Cliente: {mensaje_cliente}\n\n"
        f"Respuesta propuesta:\n{respuesta}\n\n"
        f"Responde: *ok {bid}* envía · *no {bid}* descarta · "
        f"*editar {bid} <texto>* envía tu versión"
    ))
    logger.info(f"Borrador #{bid} para {telefono} pendiente de aprobación")


async def comando_admin(proveedor: ProveedorWhatsApp, texto: str):
    """Procesa la respuesta del admin: ok N / no N / editar N <texto>.
    Cualquier otro mensaje devuelve la ayuda con los borradores pendientes."""
    m = re.match(r"(?is)^\s*(ok|no|editar)\s+#?(\d+)\s*(.*)$", texto or "")
    if not m:
        pendientes = await memory.borradores_pendientes()
        lista = "\n".join(
            f"#{b['id']} → {b['telefono']}: {b['texto'][:80]}" for b in pendientes
        ) or "(ninguno)"
        await proveedor.enviar_mensaje(_admin(), (
            "Modo borrador — comandos: *ok N* envía · *no N* descarta · "
            "*editar N texto* envía tu versión.\n\n"
            f"Pendientes:\n{lista}"))
        return
    accion, bid, resto = m.group(1).lower(), int(m.group(2)), m.group(3).strip()

    if accion == "no":
        r = await memory.resolver_borrador(bid, "descartado")
        await proveedor.enviar_mensaje(
            _admin(),
            f"🗑 Borrador #{bid} descartado." if r
            else f"El borrador #{bid} no existe o ya fue resuelto.")
        return

    if accion == "editar" and not resto:
        await proveedor.enviar_mensaje(_admin(), f"Falta el texto: *editar {bid} <tu respuesta>*")
        return

    r = await memory.resolver_borrador(bid, "enviado", texto=resto if accion == "editar" else "")
    if not r:
        await proveedor.enviar_mensaje(_admin(), f"El borrador #{bid} no existe o ya fue resuelto.")
        return
    await humanizar.enviar_humanizado(proveedor, r["telefono"], r["texto"])
    # El historial solo guarda lo que el cliente realmente recibió
    await memory.guardar_mensaje(r["telefono"], "assistant", r["texto"])
    await proveedor.enviar_mensaje(_admin(), f"✅ Borrador #{bid} enviado a {r['telefono']}.")
