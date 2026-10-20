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


async def enviar_humanizado(proveedor: ProveedorWhatsApp, telefono: str, texto: str) -> bool:
    """Envía la respuesta en burbujas con pausas. Con HUMANIZAR=false envía un solo mensaje.
    Devuelve True solo si TODAS las burbujas salieron; si una falla, no envía las que siguen."""
    if os.getenv("HUMANIZAR", "true").lower() != "true":
        return bool(await proveedor.enviar_mensaje(telefono, texto))
    burbujas = partir_en_burbujas(texto)
    for i, burbuja in enumerate(burbujas):
        if i > 0:
            await asyncio.sleep(pausa_escritura(burbuja))
        if not await proveedor.enviar_mensaje(telefono, burbuja):
            return False  # se corta: no sale un texto con huecos
    return bool(burbujas)  # un texto vacío no se envió
