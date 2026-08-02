# agentkit/pagos.py — Links de pago dentro del chat
#
# El usuario elige su pasarela en la entrevista (según su país):
#   - wompi        → Colombia (WOMPI_PRIVATE_KEY)
#   - mercadopago  → Latinoamérica (MP_ACCESS_TOKEN)
#   - stripe       → Global / EE.UU. / Europa (STRIPE_SECRET_KEY)
# Se detecta por la llave presente en .env; PAGOS_PROVIDER la fuerza si hay varias.

import logging
import os

import httpx

logger = logging.getLogger("agentkit")

_MONEDA_DEFAULT = {"wompi": "COP", "mercadopago": "", "stripe": "usd"}


def proveedor_pago() -> str | None:
    forzado = os.getenv("PAGOS_PROVIDER", "").lower()
    if forzado:
        return forzado
    if os.getenv("WOMPI_PRIVATE_KEY"):
        return "wompi"
    if os.getenv("MP_ACCESS_TOKEN"):
        return "mercadopago"
    if os.getenv("STRIPE_SECRET_KEY"):
        return "stripe"
    return None


def pagos_configurados() -> bool:
    return proveedor_pago() is not None


async def crear_link_pago(concepto: str, monto: int) -> str | None:
    """Crea un link de pago con la pasarela configurada. `monto` sin decimales,
    en la moneda del negocio (PAGOS_MONEDA). Retorna la URL o None si falla."""
    pasarela = proveedor_pago()
    try:
        if pasarela == "wompi":
            return await _link_wompi(concepto, monto)
        if pasarela == "mercadopago":
            return await _link_mercadopago(concepto, monto)
        if pasarela == "stripe":
            return await _link_stripe(concepto, monto)
    except Exception as e:
        logger.error(f"Error creando link de pago ({pasarela}): {e}")
    return None


def _moneda(pasarela: str) -> str:
    return os.getenv("PAGOS_MONEDA", _MONEDA_DEFAULT[pasarela])


async def _link_wompi(concepto: str, monto: int) -> str | None:
    key = os.getenv("WOMPI_PRIVATE_KEY")
    base = "https://sandbox.wompi.co" if os.getenv("WOMPI_ENV") == "sandbox" else "https://production.wompi.co"
    payload = {"name": concepto[:100], "description": concepto[:250], "single_use": True,
               "collect_shipping": False, "currency": _moneda("wompi"), "amount_in_cents": monto * 100}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{base}/v1/payment_links", json=payload,
                              headers={"Authorization": f"Bearer {key}"})
        if r.status_code not in (200, 201):
            logger.error(f"Error Wompi: {r.status_code} — {r.text}")
            return None
        link_id = r.json().get("data", {}).get("id")
        return f"https://checkout.wompi.co/l/{link_id}" if link_id else None


async def _link_mercadopago(concepto: str, monto: int) -> str | None:
    token = os.getenv("MP_ACCESS_TOKEN")
    item = {"title": concepto[:250], "quantity": 1, "unit_price": monto}
    if _moneda("mercadopago"):
        item["currency_id"] = _moneda("mercadopago")  # opcional: MP usa la moneda de la cuenta
    async with httpx.AsyncClient() as client:
        r = await client.post("https://api.mercadopago.com/checkout/preferences",
                              json={"items": [item]},
                              headers={"Authorization": f"Bearer {token}"})
        if r.status_code not in (200, 201):
            logger.error(f"Error MercadoPago: {r.status_code} — {r.text}")
            return None
        return r.json().get("init_point")


async def _link_stripe(concepto: str, monto: int) -> str | None:
    key = os.getenv("STRIPE_SECRET_KEY")
    auth = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient() as client:
        # Stripe Payment Links necesita un price primero (API form-encoded)
        r1 = await client.post("https://api.stripe.com/v1/prices", headers=auth, data={
            "unit_amount": monto * 100, "currency": _moneda("stripe"),
            "product_data[name]": concepto[:250],
        })
        if r1.status_code != 200:
            logger.error(f"Error Stripe (price): {r1.status_code} — {r1.text}")
            return None
        r2 = await client.post("https://api.stripe.com/v1/payment_links", headers=auth, data={
            "line_items[0][price]": r1.json()["id"], "line_items[0][quantity]": 1,
        })
        if r2.status_code != 200:
            logger.error(f"Error Stripe (link): {r2.status_code} — {r2.text}")
            return None
        return r2.json().get("url")
