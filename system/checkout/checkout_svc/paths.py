"""Filesystem locations for the demo, configurable for tests."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def config_dir() -> Path:
    return Path(os.getenv("CONFIG_DIR", str(ROOT / "config")))


def var_dir() -> Path:
    return Path(os.getenv("VAR_DIR", str(ROOT / "var")))


def incidents_dir() -> Path:
    return Path(os.getenv("INCIDENTS_DIR", str(ROOT / "incidents")))


def pricing_path() -> Path:
    return config_dir() / "pricing.yaml"


def database_path() -> Path:
    return Path(os.getenv("DB_PATH", str(var_dir() / "store.sqlite3")))
