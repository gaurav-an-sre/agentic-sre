"""Append-only evidence writers and per-second metric rollups."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from .paths import var_dir

_FILE_LOCK = threading.Lock()


def append_jsonl(name: str, record: dict[str, Any], directory: Path | None = None) -> None:
    target_dir = directory or var_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    with _FILE_LOCK:
        with (target_dir / name).open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, sort_keys=True) + "\n")


def read_jsonl(name: str, directory: Path | None = None) -> list[dict[str, Any]]:
    path = (directory or var_dir()) / name
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * 0.95) - 1)]


class MetricsRecorder:
    """Flushes one immutable rollup line for each second containing traffic."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self._second: int | None = None
        self._attempts = 0
        self._succeeded = 0
        self._declined = 0
        self._latencies: list[float] = []
        self._lock = threading.Lock()

    def _flush(self) -> None:
        if self._second is None or not self._attempts:
            return
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(self._second))
        append_jsonl(
            "metrics.jsonl",
            {
                "timestamp": timestamp,
                "second": self._second,
                "attempts": self._attempts,
                "succeeded": self._succeeded,
                "declined": self._declined,
                "success_rate": self._succeeded / self._attempts,
                "p95_latency_ms": _p95(self._latencies),
            },
            self.directory,
        )
        self._attempts = 0
        self._succeeded = 0
        self._declined = 0
        self._latencies = []

    def record(self, outcome: str, latency_ms: float, now: float | None = None) -> None:
        second = int(now if now is not None else time.time())
        with self._lock:
            if self._second is not None and second != self._second:
                self._flush()
            self._second = second
            self._attempts += 1
            if outcome == "succeeded":
                self._succeeded += 1
            else:
                self._declined += 1
            self._latencies.append(latency_ms)

    def flush(self) -> None:
        with self._lock:
            self._flush()
