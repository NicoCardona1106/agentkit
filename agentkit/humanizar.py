# agentkit/humanizar.py — Respuestas en burbujas cortas con pausas de escritura

import asyncio
import os

from agentkit.providers.base import ProveedorWhatsApp

MAX_BURBUJAS = 4
MAX_CHARS_BURBUJA = 400


def partir_en_burbujas(texto: str) -> list[str]:
    """Parte un texto en burbujas cortas (por párrafos), como escribe una persona."""
    parrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    if not parrafos:
        return []
    burbujas: list[str] = []
    for p in parrafos:
        # Une párrafos muy cortos con el anterior para no fragmentar de más
        if burbujas and len(burbujas[-1]) + len(p) < 120:
            burbujas[-1] += "\n" + p
        else:
            burbujas.append(p)
    if len(burbujas) > MAX_BURBUJAS:
        burbujas = burbujas[:MAX_BURBUJAS - 1] + ["\n\n".join(burbujas[MAX_BURBUJAS - 1:])]
    return burbujas


def pausa_escritura(texto: str) -> float:
    """Segundos de 'escribiendo…' proporcionales al largo del mensaje."""
    return min(len(texto) / 40, 3.0)


async def enviar_humanizado(proveedor: ProveedorWhatsApp, telefono: str, texto: str):
    """Envía la respuesta en burbujas con pausas. Con HUMANIZAR=false envía un solo mensaje."""
    if os.getenv("HUMANIZAR", "true").lower() != "true":
        await proveedor.enviar_mensaje(telefono, texto)
        return
    for i, burbuja in enumerate(partir_en_burbujas(texto)):
        if i > 0:
            await asyncio.sleep(pausa_escritura(burbuja))
        await proveedor.enviar_mensaje(telefono, burbuja)
