# agentkit/chat.py — Test local: chatea con tu agente en la terminal
# Uso: python -m agentkit.chat  (desde la carpeta del agente)

import asyncio

from agentkit import brain, memory
from agentkit.providers.base import ProveedorWhatsApp

TELEFONO_TEST = "test-local-001"


class ProveedorConsola(ProveedorWhatsApp):
    """Proveedor falso: imprime en la terminal en vez de enviar por WhatsApp."""

    async def parsear_webhook(self, request):
        return []

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        print(f"\n[→ {telefono}] {mensaje}")
        return True


async def main():
    await memory.inicializar_db()
    proveedor = ProveedorConsola()

    print("\n" + "=" * 55)
    print("   AgentKit — Test Local")
    print("=" * 55)
    print("\n  Escribe mensajes como si fueras un cliente.")
    print("  Comandos: 'limpiar' borra el historial, 'salir' termina.\n")
    print("-" * 55 + "\n")

    while True:
        try:
            mensaje = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest finalizado.")
            break
        if not mensaje:
            continue
        if mensaje.lower() == "salir":
            print("\nTest finalizado.")
            break
        if mensaje.lower() == "limpiar":
            await memory.limpiar_historial(TELEFONO_TEST)
            print("[Historial borrado]\n")
            continue

        historial = await memory.obtener_historial(TELEFONO_TEST)
        respuesta = await brain.generar_respuesta(TELEFONO_TEST, mensaje, historial, proveedor)
        print(f"\nAgente: {respuesta}\n")
        await memory.guardar_mensaje(TELEFONO_TEST, "user", mensaje)
        await memory.guardar_mensaje(TELEFONO_TEST, "assistant", respuesta)


if __name__ == "__main__":
    asyncio.run(main())
