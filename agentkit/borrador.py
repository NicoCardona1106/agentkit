# agentkit/borrador.py — Modo borrador: el equipo aprueba cada respuesta antes de enviarla
# Se activa con MODO_BORRADOR=true. El bot redacta y avisa del borrador por los canales de
# BORRADOR_CANALES (whatsapp, telegram; sin la variable, solo whatsapp como en v0.8.11).
# WhatsApp: el admin responde ok N / no N / editar N <texto>. Telegram: botones (agentkit/telegram_borradores.py).
# Pensado para el primer mes de un agente nuevo: confianza antes que autonomía. Detalle en docs/BORRADORES.md.
# Sin decisión no se envía nada: gana la primera decisión y el borrador vence 23 h 45 min después del
# último mensaje del cliente (la ventana de respuesta de WhatsApp e Instagram es de 24 h).

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from agentkit import humanizar, memory
from agentkit.privacidad import ocultar
from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")

VIGENCIA = memory.VIGENCIA
HUERFANO_TRAS = timedelta(minutes=10)  # un envío no tarda tanto: pasado esto se da por perdido
MAX_TEXTO = {"whatsapp": 4096, "instagram": 1000}  # largo máximo de un mensaje por canal del cliente
CANALES_CONOCIDOS = ("whatsapp", "telegram")

_RESULTADOS = {
    "enviado": "✅ Borrador #{} enviado.",
    "descartado": "🗑 Borrador #{} descartado.",
    "fallo_envio": "⚠️ Borrador #{}: no se pudo enviar al cliente. Atiéndelo directamente.",
    "vencido": ("⌛ Borrador #{} vencido: venció la ventana de respuesta (23 h 45 min desde el último "
                "mensaje del cliente). No se envió nada."),
    "reemplazado": "🔁 Borrador #{} reemplazado por uno más reciente.",
    "sin_confirmar": ("⚠️ Borrador #{}: no se pudo confirmar el envío. Revisa si el cliente lo recibió y "
                      "atiéndelo directamente."),
}


def ahora() -> datetime:
    """UTC. Aparte para que las pruebas simulen el reloj."""
    return datetime.utcnow()


def _solo_digitos(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")


def _admin() -> str:
    return os.getenv("ADMIN_PHONE", "").replace("whatsapp:", "").strip()


def es_instagram() -> bool:
    return (os.getenv("PROVIDER") or os.getenv("WHATSAPP_PROVIDER", "")).lower() == "instagram"


def limite_texto() -> int:
    """Largo máximo de una respuesta al cliente: 1.000 en Instagram, 4.096 en WhatsApp."""
    return MAX_TEXTO["instagram" if es_instagram() else "whatsapp"]


def activo() -> bool:
    # Falla cerrado: con MODO_BORRADOR=true nada sale sin aprobación aunque no quede ningún canal válido
    # (entonces el borrador queda pendiente como «sin aviso» y advertir_config deja un ERROR al arrancar).
    return os.getenv("MODO_BORRADOR", "").lower() == "true"


def es_admin(telefono: str) -> bool:
    """El ADMIN_PHONE es el aprobador del canal WhatsApp. En Instagram nunca: ahí ADMIN_PHONE no es un
    IGSID y el aviso no puede salir por el proveedor de Instagram (RF-56)."""
    if es_instagram():
        return False
    admin = _solo_digitos(_admin())
    return bool(admin) and _solo_digitos(telefono) == admin


def _canales_pedidos() -> list[str]:
    pedidos = [c.strip().lower() for c in os.getenv("BORRADOR_CANALES", "").split(",") if c.strip()]
    return list(dict.fromkeys(pedidos)) or ["whatsapp"]  # sin duplicados, en el orden dado


def _canal_valido(canal: str) -> bool:
    from agentkit import telegram_borradores  # aquí y no arriba: telegram_borradores importa este módulo
    if canal == "whatsapp":
        return bool(_admin()) and not es_instagram()
    if canal == "telegram":
        return telegram_borradores.configurado()
    return False


def canales() -> list[str]:
    """Canales por los que se avisa cada borrador: los de BORRADOR_CANALES que de verdad existen."""
    return [c for c in _canales_pedidos() if _canal_valido(c)]


def advertir_config():
    """Al arrancar: avisa de lo que se pidió en BORRADOR_CANALES y no existe (nunca se ignora en silencio)."""
    from agentkit import telegram_borradores
    for canal in _canales_pedidos():
        if canal not in CANALES_CONOCIDOS:
            logger.warning(f"BORRADOR_CANALES: «{canal}» no es un canal válido y se ignora")
        elif canal == "whatsapp" and es_instagram():
            logger.warning("BORRADOR_CANALES: «whatsapp» no es válido con PROVIDER=instagram (RF-56) y se ignora")
        elif canal == "whatsapp" and not _admin():
            logger.warning("BORRADOR_CANALES: «whatsapp» necesita ADMIN_PHONE y se ignora")
        elif canal == "telegram" and not telegram_borradores.configurado():
            logger.warning("BORRADOR_CANALES: «telegram» necesita TELEGRAM_TOKEN, TELEGRAM_CHAT_ID y "
                           "TELEGRAM_APROBADORES (con al menos un id): el canal no existe")
    if os.getenv("TELEGRAM_APROBADORES", "").strip() and telegram_borradores.aprobadores_invalidos():
        logger.warning("TELEGRAM_APROBADORES: hay valores que no son un id numérico y se ignoran")
    if not canales():
        logger.error("MODO_BORRADOR sin ningún canal de aviso válido: los borradores quedan pendientes, "
                     "salen en /estado como borradores_sin_aviso y no se envía nada al cliente")


def texto_resultado(bid: int, resultado: str) -> str:
    return _RESULTADOS.get(resultado, "El borrador #{} no existe o ya fue resuelto.").format(bid)


async def _reflejar(fila: dict | None, resultado: str):
    """Deja el aviso de Telegram con el resultado y sin botones (si ese borrador se avisó por ahí)."""
    if fila and fila.get("tg_chat_id"):
        from agentkit import telegram_borradores
        await telegram_borradores.reflejar(fila, resultado)


async def _avisar_whatsapp(proveedor: ProveedorWhatsApp, bid: int, telefono: str, mensajes: list[str],
                           respuesta: str) -> bool:
    return bool(await proveedor.enviar_mensaje(_admin(), (
        f"📝 *Borrador #{bid}* para {telefono}\n\n"
        f"Cliente: {chr(10).join(mensajes)}\n\n"
        f"Respuesta propuesta:\n{respuesta}\n\n"
        f"Responde: *ok {bid}* envía · *no {bid}* descarta · "
        f"*editar {bid} <texto>* envía tu versión"
    )))


async def proponer(proveedor: ProveedorWhatsApp, telefono: str,
                   respuesta: str, mensaje_cliente: str):
    """Guarda la respuesta como borrador y avisa por todos los canales válidos. Un solo borrador pendiente
    por conversación: el nuevo reemplaza al anterior y el aviso junta los mensajes sin responder."""
    from agentkit import telegram_borradores
    ahora_ = ahora()
    ultimo = await memory.ultimo_mensaje_cliente(telefono) or ahora_
    bid = await memory.crear_borrador(telefono, respuesta, mensaje_cliente,
                                      vence=ultimo + VIGENCIA, ahora=ahora_)
    for viejo in await memory.reemplazados_por(bid):
        await _reflejar(viejo, "reemplazado")
    b = await memory.obtener_borrador(bid)

    resultados: dict[str, bool] = {}
    for canal in canales():
        try:
            if canal == "whatsapp":
                resultados[canal] = await _avisar_whatsapp(proveedor, bid, telefono, b["mensajes"], respuesta)
            else:
                resultados[canal] = await telegram_borradores.avisar(b)
        except Exception as e:  # un canal caído no debe tumbar al otro ni al mensaje del cliente
            logger.warning(f"Borrador #{bid}: falló el aviso por {canal} ({type(e).__name__})")
            resultados[canal] = False
    for canal, ok in resultados.items():
        if not ok:
            logger.warning(f"Borrador #{bid}: no se pudo avisar por {canal}")
    if not any(resultados.values()):
        await memory.marcar_sin_aviso(bid)
        logger.error(f"Borrador #{bid} para {ocultar(telefono)}: no llegó por ningún canal "
                     f"(queda pendiente; sale en /estado como borradores_sin_aviso)")
        return
    logger.info(f"Borrador #{bid} para {ocultar(telefono)} pendiente de aprobación "
                f"({', '.join(c for c, ok in resultados.items() if ok)})")
    # Si lo reemplazaron mientras se avisaba, el aviso de Telegram no puede quedar con botones vivos
    actual = await memory.obtener_borrador(bid)
    if actual and actual["estado"] != "pendiente":
        await _reflejar(actual, actual["estado"])


async def rechazar(bid: int) -> tuple[str, dict | None]:
    """Por qué no se pudo decidir o editar un borrador: no_existe | vencido | reemplazado | resuelto.
    Deja el aviso de Telegram con su estado real, aunque el barrido de vencidos no haya corrido."""
    ahora_ = ahora()
    motivo, fila = await memory.motivo_no_resuelto(bid, ahora_)
    if motivo == "vencido":
        fila = await memory.vencer_borrador(bid, ahora_) or fila
        await _reflejar(fila, "vencido")
    elif fila and fila["estado"] in ("reemplazado", "enviado", "descartado", "fallo_envio"):
        await _reflejar(fila, fila["estado"])
    return motivo, fila


async def _enviar_al_cliente(proveedor: ProveedorWhatsApp, bid: int, telefono: str, texto: str) -> bool:
    try:
        return await humanizar.enviar_humanizado(proveedor, telefono, texto)
    except Exception as e:
        logger.error(f"Borrador #{bid}: falló el envío a {ocultar(telefono)} ({type(e).__name__})")
        return False


async def decidir(proveedor: ProveedorWhatsApp, bid: int, accion: str, *, canal: str, decidido_por: str,
                  texto: str = "") -> tuple[str, dict | None]:
    """Decisión de un canal sobre un borrador. `accion`: «enviar» (con `texto` si es una versión editada)
    o «descartar». Devuelve (resultado, borrador): enviado | descartado | fallo_envio, o el motivo del
    rechazo (no_existe | vencido | reemplazado | resuelto). Solo la primera decisión pasa (UPDATE atómico)."""
    descartar = accion == "descartar"
    r = await memory.resolver_borrador(bid, "descartado" if descartar else "enviando", texto=texto,
                                       decidido_por=decidido_por, canal=canal, ahora=ahora())
    if not r:
        return await rechazar(bid)
    if descartar:
        resultado = "descartado"
    else:
        try:
            ok = await _enviar_al_cliente(proveedor, bid, r["telefono"], r["texto"])
        except asyncio.CancelledError:  # deploy o cancelación a mitad del envío: no queda en «enviando»
            logger.error(f"Borrador #{bid}: envío cancelado a mitad (fallo_envio); revisar si el cliente lo recibió")
            await asyncio.shield(memory.cerrar_envio(bid, False))
            raise
        await memory.cerrar_envio(bid, ok)
        if ok:
            # El historial solo guarda lo que el cliente realmente recibió
            await memory.guardar_mensaje(r["telefono"], "assistant", r["texto"])
            resultado = "enviado"
        else:
            resultado = "fallo_envio"
            logger.error(f"Borrador #{bid}: no se pudo enviar a {ocultar(r['telefono'])} "
                         f"(fallo_envio; el equipo debe atender a esa persona)")
    await _reflejar(r, resultado)
    return resultado, r


async def barrer_vencidos() -> int:
    """Pasa a «vencido» los pendientes cuya ventana está por cerrar y lo muestra en Telegram. También da
    por perdidos (fallo_envio + ERROR) los que llevan más de 10 min «enviando»."""
    ahora_ = ahora()
    n = 0
    for fila in await memory.huerfanos_enviando(ahora_ - HUERFANO_TRAS):
        n += 1
        logger.error(f"Borrador #{fila['id']} quedó a mitad del envío ({ocultar(fila['telefono'])}): "
                     f"revisar si el cliente lo recibió")
        await _reflejar(fila, "sin_confirmar")
    for bid in await memory.ids_vencidos(ahora_):
        fila = await memory.vencer_borrador(bid, ahora_)
        if fila:
            n += 1
            await _reflejar(fila, "vencido")
    return n


async def vigilar():
    """Tarea de fondo: cada minuto barre los borradores vencidos."""
    while True:
        try:
            await barrer_vencidos()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Falló el barrido de borradores vencidos ({type(e).__name__})")
        await asyncio.sleep(60)


async def comando_admin(proveedor: ProveedorWhatsApp, texto: str):
    """Procesa la respuesta del admin por WhatsApp: ok N / no N / editar N <texto>.
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

    if accion == "editar" and not resto:
        await proveedor.enviar_mensaje(_admin(), f"Falta el texto: *editar {bid} <tu respuesta>*")
        return

    if accion == "editar" and len(resto) > limite_texto():
        await proveedor.enviar_mensaje(_admin(), (
            f"Tu versión tiene {len(resto)} caracteres y el máximo es {limite_texto()}. "
            f"Acórtala y vuelve a escribir *editar {bid} <texto>*."))
        return

    resultado, fila = await decidir(proveedor, bid, "descartar" if accion == "no" else "enviar",
                                    canal="whatsapp", decidido_por="admin",
                                    texto=resto if accion == "editar" else "")
    if resultado == "enviado":
        mensaje = f"✅ Borrador #{bid} enviado a {fila['telefono']}."
    else:
        mensaje = texto_resultado(bid, resultado)
    await proveedor.enviar_mensaje(_admin(), mensaje)
