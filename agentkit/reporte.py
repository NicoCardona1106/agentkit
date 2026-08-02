# agentkit/reporte.py — Reporte diario al equipo (leads, tickets, conversaciones)

from agentkit import memory, notificar
from agentkit.providers.base import ProveedorWhatsApp


async def generar_reporte() -> str:
    datos = await memory.resumen_dia()
    lineas = ["📊 Reporte del día", f"Conversaciones atendidas: {datos['conversaciones']}",
              f"Leads nuevos: {len(datos['leads'])}"]
    for lead in datos["leads"]:
        lineas.append(f"  🔥 {lead['nombre']} ({lead['telefono']}) — {lead['interes']}")
    lineas.append(f"Tickets abiertos hoy: {len(datos['tickets'])}")
    for t in datos["tickets"]:
        lineas.append(f"  🎫 #{t['id']} ({t['telefono']}) — {t['problema'][:80]}")
    return "\n".join(lineas)


async def enviar_reporte(proveedor: ProveedorWhatsApp) -> str:
    texto = await generar_reporte()
    await notificar.notificar_equipo(proveedor, texto)
    return texto
