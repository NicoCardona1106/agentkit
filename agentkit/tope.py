# agentkit/tope.py — Tope de gasto por agente (docs/TOPE-GASTO.md, decidido 2026-10-02)
#
# TOPE_USD_DIA: al 80 % el agente deja la voz (solo texto) y avisa; al 100 % deja de llamar a
# Claude y deriva cada conversación a un humano hasta la medianoche. TOPE_USD_MES: al pasarlo,
# solo texto hasta fin de mes. Sin las variables no hay tope (el core se comporta como antes).

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from agentkit import memory, notificar
from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")

UMBRAL_SIN_VOZ = Decimal("0.8")
MSG_DERIVAR = "Gracias por escribirnos 🙏 En un momento {humano} te responde por este mismo chat."
MSG_SIN_EQUIPO = "Gracias por escribirnos 🙏 Por hoy ya no puedo seguir la conversación; escríbenos mañana y te atendemos."


@dataclass(frozen=True)
class Topes:
    dia: Decimal | None
    mes: Decimal | None


@dataclass
class Estado:
    """Qué hacer con el mensaje que llega. `avisos`: umbrales cruzados ("dia80", "dia100", "mes")."""
    sin_voz: bool = False
    derivar: bool = False
    avisos: list[str] = field(default_factory=list)


def _tope(nombre: str) -> Decimal | None:
    valor = os.getenv(nombre, "").strip()
    if not valor:
        return None
    try:
        tope = Decimal(valor)
    except InvalidOperation:
        tope = Decimal(0)
    if not tope.is_finite() or tope <= 0:
        # Mal configurado: se avisa en el log y no se aplica (un tope de 0 apagaría el agente).
        logger.warning(f"{nombre}={valor!r} no es un monto en USD mayor que 0: se ignora")
        return None
    return tope


def topes() -> Topes:
    return Topes(dia=_tope("TOPE_USD_DIA"), mes=_tope("TOPE_USD_MES"))


def evaluar(gasto_dia: Decimal, gasto_mes: Decimal, t: Topes) -> Estado:
    """Regla pura: con el gasto de hoy y del mes, qué se permite."""
    estado = Estado()
    if t.dia is not None:
        if gasto_dia >= t.dia:
            estado.derivar = estado.sin_voz = True
            estado.avisos.append("dia100")
        elif gasto_dia >= t.dia * UMBRAL_SIN_VOZ:
            estado.sin_voz = True
            estado.avisos.append("dia80")
    if t.mes is not None and gasto_mes >= t.mes:
        estado.sin_voz = True
        estado.avisos.append("mes")
    return estado


# ponytail: memoria del proceso; si el servicio se reinicia, un aviso puede repetirse una vez.
_avisados: set[str] = set()


def _clave(aviso: str, ahora: datetime) -> str:
    return f"{aviso}:{ahora.strftime('%Y-%m') if aviso == 'mes' else ahora.strftime('%Y-%m-%d')}"


def _usd(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.01")), "f")


async def _avisar(proveedor: ProveedorWhatsApp, texto: str) -> bool:
    """Aviso al equipo que nunca lanza: un fallo del canal no puede dejar al cliente sin respuesta."""
    try:
        return await notificar.notificar_equipo(proveedor, texto)
    except Exception as e:
        logger.error(f"No se pudo avisar al equipo del tope: {e!r}")
        return False


async def revisar(proveedor: ProveedorWhatsApp) -> Estado:
    """Antes de responder: mira el gasto, avisa al equipo (una vez por umbral) y devuelve qué
    se permite. Si no hay topes no consulta la base. Un fallo aquí NO frena al agente."""
    t = topes()
    if t.dia is None and t.mes is None:
        return Estado()
    try:
        # Sin tope mensual basta con lo de hoy: no se trae el mes entero en cada mensaje.
        dia, mes = await memory.costos_mensajeria(solo_hoy=t.mes is None)
    except Exception as e:
        logger.error(f"No se pudo leer el gasto para el tope: {e!r}")
        return Estado()
    estado = evaluar(dia, mes, t)
    ahora = datetime.now(memory.BOGOTA)
    vuelve = "" if "mes" in estado.avisos else " Mañana vuelve a la normalidad."
    textos = {
        "dia80": f"⚠️ El agente va en USD {_usd(dia)} de su tope diario de USD {_usd(t.dia or Decimal(0))} "
                 f"(80 %): desde ahora responde solo en texto, sin voz.{vuelve}",
        "dia100": f"🛑 El agente llegó a su tope diario (USD {_usd(dia)} de USD {_usd(t.dia or Decimal(0))}): "
                  f"hasta medianoche no responde con IA y cada cliente que escriba te llega aquí para atenderlo.",
        "mes": f"⚠️ El agente pasó su tope mensual: USD {_usd(mes)} de USD {_usd(t.mes or Decimal(0))}. "
               f"Responde solo en texto, sin voz, hasta fin de mes.",
    }
    for aviso in estado.avisos:
        clave = _clave(aviso, ahora)
        if clave not in _avisados:
            _avisados.add(clave)
            await _avisar(proveedor, textos[aviso])
    if estado.derivar:
        logger.warning(f"Tope diario alcanzado (USD {_usd(dia)} de {_usd(t.dia or Decimal(0))}): se deriva a humano")
    return estado


def minutos_hasta_medianoche(ahora: datetime) -> int:
    manana = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((manana - ahora).total_seconds() // 60) + 1)


def _pausa_minutos() -> int:
    try:
        return max(1, int(os.getenv("PAUSA_MINUTOS", "60")))
    except ValueError:
        return 60


# Un candado por teléfono: dos mensajes seguidos del mismo cliente no lo derivan dos veces.
_candados: dict[str, asyncio.Lock] = {}


async def derivar(proveedor: ProveedorWhatsApp, telefono: str, ahora: datetime | None = None) -> None:
    """Tope diario pasado: sin llamar a Claude, la conversación queda pausada hasta medianoche
    (o PAUSA_MINUTOS si es mayor). Si el equipo recibe el aviso, el cliente sabe que lo atiende una
    persona; si NO hay canal o falla, no se le promete nada: se le pide escribir mañana."""
    candado = _candados.setdefault(telefono, asyncio.Lock())
    try:
        async with candado:
            await _derivar(proveedor, telefono, ahora)
    finally:
        if not candado.locked():  # nadie más esperando: el diccionario no crece para siempre
            _candados.pop(telefono, None)


async def _derivar(proveedor: ProveedorWhatsApp, telefono: str, ahora: datetime | None) -> None:
    if await memory.conversacion_pausada(telefono):
        return
    ahora = ahora or datetime.now(memory.BOGOTA)
    await memory.pausar_conversacion(telefono, max(_pausa_minutos(), minutos_hasta_medianoche(ahora)))
    avisado = await _avisar(
        proveedor, f"🙋 Cliente {telefono} derivado a humano: el agente llegó a su tope de gasto del día. "
                   f"Atiéndelo por este mismo chat; el bot vuelve mañana.")
    if avisado:
        humano = os.getenv("NOMBRE_HUMANO", "un asesor")
        texto = os.getenv("TOPE_MSG_DERIVAR", "").strip() or MSG_DERIVAR.format(humano=humano)
    else:
        logger.error(f"Tope diario: no hay canal de avisos (ADMIN_PHONE/Telegram) o falló; "
                     f"{telefono} recibe el mensaje de «escríbenos mañana»")
        texto = os.getenv("TOPE_MSG_SIN_EQUIPO", "").strip() or MSG_SIN_EQUIPO
    await memory.guardar_mensaje(telefono, "assistant", texto)
    await proveedor.enviar_mensaje(telefono, texto)
