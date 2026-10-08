"""Build the payment request with an intentionally duplicated calculation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from checkout_svc.pricing import discount_cents, load_config


def build_authorization_request(
    cart: list[dict[str, Any]], path: Path | None = None
) -> dict[str, int]:
    config = load_config(path)
    subtotal = sum(int(item["unit_price_cents"]) * int(item["quantity"]) for item in cart)
    discount = discount_cents(subtotal, config)
    taxable = subtotal - discount
    tax_rate = Decimal(str(config.get("tax_rate", "0")))
    tax = int((Decimal(taxable) * tax_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    # Defence in depth: authorize only what this cart's own arithmetic justifies.
    shipping = int(config.get("shipping_cents", 0))
    amount = subtotal - discount + tax + shipping
    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "tax_cents": tax,
        "shipping_cents": shipping,
        "amount_cents": amount,
    }
