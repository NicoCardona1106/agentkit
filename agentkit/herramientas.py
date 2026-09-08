# agentkit/herramientas.py — Herramientas que Claude ejecuta solo (tool use)
#
# Incluye las herramientas base (knowledge, leads, tickets, memoria de cliente,
# derivar a humano, links de pago) y carga herramientas personalizadas desde el
# tools.py del agente (si existe en el directorio de trabajo).

import importlib.util
import inspect
import logging
import os
from pathlib import Path

from agentkit import memory, notificar, pagos
from agentkit.providers.base import ProveedorWhatsApp

logger = logging.getLogger("agentkit")

_obj = {"type": "object", "properties": {}, "required": []}


def _schema(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props, "required": required}}


ESQUEMAS_BASE = [
    _schema("buscar_conocimiento",
            "Busca información del negocio (productos, precios, políticas, FAQ) en los archivos de conocimiento. "
            "Úsala SIEMPRE que el cliente pregunte por productos, precios o detalles que no estén en tu prompt.",
            {"consulta": {"type": "string", "description": "Palabras clave a buscar"}}, ["consulta"]),
    _schema("registrar_lead",
            "Registra un cliente interesado en comprar. Úsala cuando el cliente muestre intención de compra "
            "y ya conozcas su nombre e interés.",
            {"nombre": {"type": "string"}, "interes": {"type": "string", "description": "Qué le interesa comprar"},
             "presupuesto": {"type": "string", "description": "Presupuesto aproximado si lo mencionó"}},
            ["nombre", "interes"]),
    _schema("crear_ticket",
            "Crea un ticket de soporte cuando el cliente reporta un problema con un producto o servicio.",
            {"problema": {"type": "string", "description": "Descripción del problema"}}, ["problema"]),
    _schema("recordar_cliente",
            "Guarda datos del cliente para recordarlos en futuras conversaciones (nombre, qué compró, qué le interesa). "
            "Úsala cuando el cliente diga su nombre o comparta algo relevante.",
            {"nombre": {"type": "string"}, "nota": {"type": "string", "description": "Dato a recordar"}}, []),
    _schema("derivar_a_humano",
            "Pausa el bot y avisa a un asesor humano. Úsala cuando el cliente esté listo para cerrar una compra, "
            "pida hablar con una persona, o esté molesto y no puedas resolver su caso.",
            {"motivo": {"type": "string", "description": "Por qué se deriva y contexto para el asesor"}}, ["motivo"]),
]

ESQUEMA_PAGO = _schema(
    "crear_link_pago",
    "Genera un link de pago para que el cliente pague sin salir de WhatsApp. "
    "Úsala SOLO cuando el cliente confirme la compra y el precio esté verificado en el conocimiento del negocio.",
    {"concepto": {"type": "string", "description": "Qué está pagando el cliente"},
     "monto": {"type": "integer", "description": "Monto en la moneda del negocio, sin decimales"}},
    ["concepto", "monto"])


def buscar_en_knowledge(consulta: str) -> str:
    """Búsqueda simple por coincidencia en los archivos de /knowledge."""
    directorio = Path("knowledge")
    if not directorio.exists():
        return "No hay archivos de conocimiento disponibles."
    resultados = []
    for archivo in directorio.iterdir():
        if archivo.name.startswith(".") or not archivo.is_file():
            continue
        try:
            contenido = archivo.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(palabra in contenido.lower() for palabra in consulta.lower().split()):
            resultados.append(f"[{archivo.name}]:\n{contenido[:1500]}")
    return "\n---\n".join(resultados) if resultados else "No encontré información sobre eso en los archivos del negocio."


def _cargar_herramientas_custom() -> list[dict]:
    """Carga HERRAMIENTAS desde el tools.py del agente: [{"schema": {...}, "funcion": callable}]."""
    ruta = Path("tools.py")
    if not ruta.exists():
        return []
    spec = importlib.util.spec_from_file_location("tools_agente", ruta)
    modulo = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(modulo)
        return getattr(modulo, "HERRAMIENTAS", [])
    except Exception as e:
        logger.error(f"Error cargando tools.py: {e}")
        return []


def obtener_herramientas(telefono: str, proveedor: ProveedorWhatsApp):
    """Retorna (esquemas, ejecutor) para el loop de tool use de brain.py."""
    custom = _cargar_herramientas_custom()
    esquemas = list(ESQUEMAS_BASE)
    if pagos.pagos_configurados():
        esquemas.append(ESQUEMA_PAGO)
    esquemas += [h["schema"] for h in custom]
    funciones_custom = {h["schema"]["name"]: h["funcion"] for h in custom}

    async def ejecutar(nombre: str, entrada: dict) -> str:
        try:
            if nombre == "buscar_conocimiento":
                return buscar_en_knowledge(entrada["consulta"])
            if nombre == "registrar_lead":
                lead_id = await memory.crear_lead(telefono, entrada["nombre"],
                                                 entrada["interes"], entrada.get("presupuesto", ""))
                await notificar.notificar_equipo(
                    proveedor, f"🔥 Lead #{lead_id}: {entrada['nombre']} ({telefono}) — {entrada['interes']}")
                return f"Lead #{lead_id} registrado. El equipo fue notificado."
            if nombre == "crear_ticket":
                ticket_id = await memory.crear_ticket(telefono, entrada["problema"])
                await notificar.notificar_equipo(
                    proveedor, f"🎫 Ticket #{ticket_id} de {telefono}: {entrada['problema']}")
                return f"Ticket #{ticket_id} creado. Dile al cliente su número de ticket."
            if nombre == "recordar_cliente":
                await memory.guardar_dato_cliente(telefono, entrada.get("nombre", ""), entrada.get("nota", ""))
                return "Dato guardado."
            if nombre == "derivar_a_humano":
                minutos = int(os.getenv("PAUSA_MINUTOS", "60"))
                await memory.pausar_conversacion(telefono, minutos)
                await notificar.notificar_equipo(
                    proveedor, f"🙋 Cliente {telefono} derivado a humano.\nContexto: {entrada['motivo']}")
                humano = os.getenv("NOMBRE_HUMANO", "un asesor")  # p. ej. "el barbero", "Carlos"
                return (f"Conversación derivada: {humano} fue notificado y el bot quedó en pausa. "
                        f"Despídete diciéndole al cliente que {humano} le escribirá por este mismo chat en breve.")
            if nombre == "crear_link_pago":
                link = await pagos.crear_link_pago(entrada["concepto"], entrada["monto"])
                if not link:
                    return "No se pudo generar el link de pago. Ofrece derivar a un asesor."
                await notificar.notificar_equipo(
                    proveedor, f"💰 Link de pago para {telefono}: {entrada['concepto']} — ${entrada['monto']:,}")
                return f"Link de pago generado: {link} — Compártelo con el cliente."
            if nombre in funciones_custom:
                resultado = funciones_custom[nombre](**entrada)
                if inspect.isawaitable(resultado):
                    resultado = await resultado
                return str(resultado)
            return f"Herramienta desconocida: {nombre}"
        except Exception as e:
            logger.error(f"Error ejecutando {nombre}: {e}")
            return f"Error ejecutando la herramienta: {e}"

    return esquemas, ejecutar
