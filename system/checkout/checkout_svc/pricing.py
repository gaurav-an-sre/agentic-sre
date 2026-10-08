"""Customer-facing pricing calculation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from .paths import pricing_path


@dataclass(frozen=True)
class Quote:
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    shipping_cents: int
    total_cents: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def load_config(path: Path | None = None) -> dict[str, Any]:
    config = yaml.safe_load((path or pricing_path()).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("pricing config must be a mapping")
    return config


def _discount_cents(subtotal_cents: int, config: dict[str, Any]) -> int:
    discount = 0
    for promo in config.get("promos") or []:
        if not isinstance(promo, dict) or subtotal_cents < int(promo.get("min_subtotal_cents", 0)):
            continue
        if promo.get("type") == "fixed":
            discount += int(promo.get("discount_cents", 0))
        elif promo.get("type") == "percentage":
            percent = Decimal(str(promo.get("percent", "0")))
            discount += int(
                (Decimal(subtotal_cents) * percent / Decimal(100)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
    return min(subtotal_cents, discount)


def discount_cents(subtotal_cents: int, config: dict[str, Any] | None = None) -> int:
    return _discount_cents(subtotal_cents, config or load_config())


def quote(cart: list[dict[str, Any]], path: Path | None = None) -> Quote:
    config = load_config(path)
    subtotal = sum(int(item["unit_price_cents"]) * int(item["quantity"]) for item in cart)
    discount = _discount_cents(subtotal, config)
    taxable = subtotal - discount
    tax_rate = Decimal(str(config.get("tax_rate", "0")))
    tax = int((Decimal(taxable) * tax_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    shipping = int(config.get("shipping_cents", 0))
    if any(
        isinstance(promo, dict)
        and promo.get("type") == "free_shipping"
        and subtotal >= int(promo.get("min_subtotal_cents", 0))
        for promo in config.get("promos") or []
    ):
        shipping = 0
    return Quote(
        subtotal_cents=subtotal,
        discount_cents=discount,
        tax_cents=tax,
        shipping_cents=shipping,
        total_cents=subtotal - discount + tax + shipping,
    )
