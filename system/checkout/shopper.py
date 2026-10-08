"""Deterministic synthetic shoppers for the live storefront."""

from __future__ import annotations

import argparse
import random
import time
from typing import Any

import httpx

PRODUCTS: list[dict[str, Any]] = [
    {"product_id": 1, "price_cents": 1400},
    {"product_id": 2, "price_cents": 1800},
    {"product_id": 3, "price_cents": 2400},
    {"product_id": 4, "price_cents": 6800},
    {"product_id": 5, "price_cents": 7200},
    {"product_id": 6, "price_cents": 8900},
    {"product_id": 7, "price_cents": 12500},
    {"product_id": 8, "price_cents": 14900},
    {"product_id": 9, "price_cents": 5600},
]


def build_cart(rng: random.Random) -> dict[str, list[dict[str, int]]]:
    if rng.random() < 0.40:
        first = rng.choice(PRODUCTS[3:])
        second = rng.choice(PRODUCTS[3:])
        items = [{"product_id": int(first["product_id"]), "quantity": 1}]
        if second["product_id"] != first["product_id"]:
            items.append({"product_id": int(second["product_id"]), "quantity": 1})
        return {"items": items}
    items = [{"product_id": int(rng.choice(PRODUCTS[:4])["product_id"]), "quantity": 1}]
    if rng.random() < 0.25:
        items.append({"product_id": int(rng.choice(PRODUCTS[:3])["product_id"]), "quantity": 1})
    return {"items": items}


def run(
    url: str = "http://127.0.0.1:8000",
    rate: float = 4.0,
    seed: int = 20250214,
    duration: float | None = None,
    count: int | None = None,
) -> None:
    rng = random.Random(seed)
    interval = 1.0 / rate
    deadline = time.monotonic() + duration if duration is not None else None
    sent = 0
    succeeded = 0
    with httpx.Client(base_url=url, timeout=10) as client:
        while (deadline is None or time.monotonic() < deadline) and (
            count is None or sent < count
        ):
            started = time.monotonic()
            response = client.post("/api/checkout", json=build_cart(rng))
            response.raise_for_status()
            result = response.json()
            sent += 1
            succeeded += result["status"] == "succeeded"
            if sent % max(1, int(rate)) == 0:
                print(f"shopper attempts={sent} succeeded={succeeded} rate={succeeded / sent:.1%}")
            wait = interval - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic checkout traffic.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--rate", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=20250214)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--count", type=int)
    args = parser.parse_args()
    run(args.url, args.rate, args.seed, args.duration, args.count)


if __name__ == "__main__":
    main()
