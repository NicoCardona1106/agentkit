# agentkit/pagos.py — Links de pago dentro del chat (Wompi, Colombia)

import logging
import os

import httpx

logger = logging.getLogger("agentkit")


def pagos_configurados() -> bool:
    return bool(os.getenv("WOMPI_PRIVATE_KEY"))


async def crear_link_pago(concepto: str, monto_cop: int) -> str | None:
    """Crea un link de pago en Wompi. Retorna la URL o None si falla."""
    # ponytail: solo Wompi por ahora; agregar Bold/MercadoPago cuando un cliente lo pida
    key = os.getenv("WOMPI_PRIVATE_KEY")
    base = "https://sandbox.wompi.co" if os.getenv("WOMPI_ENV", "production") == "sandbox" else "https://production.wompi.co"
    payload = {
        "name": concepto[:100],
        "description": concepto[:250],
        "single_use": True,
        "collect_shipping": False,
        "currency": "COP",
        "amount_in_cents": monto_cop * 100,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{base}/v1/payment_links", json=payload,
                              headers={"Authorization": f"Bearer {key}"})
        if r.status_code not in (200, 201):
            logger.error(f"Error Wompi: {r.status_code} — {r.text}")
            return None
        link_id = r.json().get("data", {}).get("id")
        return f"https://checkout.wompi.co/l/{link_id}" if link_id else None
