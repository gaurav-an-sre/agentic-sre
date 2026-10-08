"""Small SQLite persistence layer using only the standard library."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .paths import database_path


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(path: Path | None = None) -> None:
    with connect(path) as connection:
        root = Path(__file__).resolve().parents[1]
        connection.executescript((root / "config" / "schema.sql").read_text(encoding="utf-8"))
        connection.executescript((root / "config" / "seed.sql").read_text(encoding="utf-8"))


def products(path: Path | None = None) -> list[dict[str, Any]]:
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT id, name, description, price_cents FROM products ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def product_map(path: Path | None = None) -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in products(path)}


def create_order(created_at: str, outcome: str, reason: str | None, total_cents: int) -> int:
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO orders (created_at, outcome, decline_reason, total_cents) "
            "VALUES (?, ?, ?, ?)",
            (created_at, outcome, reason, total_cents),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an order id")
        return int(cursor.lastrowid)
