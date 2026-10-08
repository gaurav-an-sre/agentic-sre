"""Threshold alerting and immutable incident evidence bundles."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .evidence import append_jsonl, read_jsonl
from .paths import incidents_dir, var_dir


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class Watchdog:
    def __init__(
        self,
        directory: Path | None = None,
        incident_root: Path | None = None,
        threshold: float = 0.90,
        window_seconds: int = 30,
    ) -> None:
        self.directory = directory or var_dir()
        self.incident_root = incident_root or incidents_dir()
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.bad_windows = 0
        self._alerted = False
        self._lock = threading.Lock()

    def _window(self) -> tuple[dict[str, Any], datetime] | None:
        records = read_jsonl("metrics.jsonl", self.directory)
        if not records:
            return None
        parsed = [(record, _parse_timestamp(str(record["timestamp"]))) for record in records]
        end = max(timestamp for _, timestamp in parsed)
        start = end - timedelta(seconds=self.window_seconds)
        selected = [record for record, timestamp in parsed if start <= timestamp <= end]
        attempts = sum(int(record["attempts"]) for record in selected)
        if attempts == 0:
            return None
        succeeded = sum(int(record["succeeded"]) for record in selected)
        return (
            {
                "attempts": attempts,
                "succeeded": succeeded,
                "declined": sum(int(record["declined"]) for record in selected),
                "success_rate": succeeded / attempts,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
            },
            end,
        )

    def check_once(self) -> Path | None:
        with self._lock:
            window = self._window()
            if window is None:
                self.bad_windows = 0
                return None
            summary, _end = window
            if summary["success_rate"] >= self.threshold:
                self.bad_windows = 0
                self._alerted = False
                return None
            self.bad_windows += 1
            if self.bad_windows < 2 or self._alerted:
                return None
            self._alerted = True
            return self._fire(summary)

    def _fire(self, summary: dict[str, Any]) -> Path:
        timestamp = datetime.now(UTC)
        incident_id = f"inc-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        target = self.incident_root / incident_id
        target.mkdir(parents=True, exist_ok=False)
        alert = {
            "incident_id": incident_id,
            "timestamp": timestamp.isoformat(),
            "reason": "success rate below 90% for two consecutive 30s windows",
            **summary,
        }
        (target / "alert.json").write_text(json.dumps(alert, indent=2) + "\n", encoding="utf-8")
        start = _parse_timestamp(str(summary["window_start"]))
        end = _parse_timestamp(str(summary["window_end"]))
        files = ["orders.jsonl", "metrics.jsonl", "payments.jsonl", "deploys.jsonl"]
        manifest_files: dict[str, str] = {}
        for name in files:
            source_records = read_jsonl(name, self.directory)
            kept: list[str] = []
            for record in source_records:
                raw_timestamp = record.get("timestamp")
                if raw_timestamp is None:
                    continue
                record_time = _parse_timestamp(str(raw_timestamp))
                if start <= record_time <= end:
                    kept.append(json.dumps(record, sort_keys=True))
            destination = target / name
            destination.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
            manifest_files[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
        alert_path = target / "alert.json"
        manifest_files["alert.json"] = hashlib.sha256(alert_path.read_bytes()).hexdigest()
        bundle = {
            "incident_id": incident_id,
            "created_at": timestamp.isoformat(),
            "files": manifest_files,
        }
        (target / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        append_jsonl("alerts.jsonl", alert, self.directory)
        return target


class WatchdogThread:
    def __init__(self, watchdog: Watchdog) -> None:
        self.watchdog = watchdog
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="watchdog", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(1):
            self.watchdog.check_once()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)
