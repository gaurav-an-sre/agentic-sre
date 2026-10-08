"""Read-only access to a frozen evidence bundle (SHA-256 sealed). Shared by v1 and v2."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = Path(os.environ.get("SRE_BUNDLE") or ROOT / "evidence" / "INC-2026-1009")


class Bundle:
    def __init__(self, path: Path = DEFAULT_BUNDLE) -> None:
        self.path = path
        self.manifest: dict[str, str] = json.loads((path / "manifest.json").read_text())
        self._logs: list[dict] | None = None

    def verify(self) -> dict[str, object]:
        bad = [rel for rel, digest in self.manifest.items()
               if not (self.path / rel).exists()
               or hashlib.sha256((self.path / rel).read_bytes()).hexdigest() != digest]
        return {"files": len(self.manifest), "ok": not bad, "tampered_or_missing": bad}

    def incident(self) -> dict:
        return json.loads((self.path / "incident.json").read_text())

    def metrics(self) -> list[dict]:
        return json.loads((self.path / "metrics.json").read_text())

    def logs(self) -> list[dict]:
        if self._logs is None:
            self._logs = [json.loads(l) for l in (self.path / "logs.jsonl").read_text().splitlines() if l]
        return self._logs

    def deployments(self) -> list[dict]:
        return json.loads((self.path / "deployments.json").read_text())

    def alerts(self) -> list[dict]:
        return json.loads((self.path / "alerts.json").read_text())

    def config(self, name: str) -> str:
        p = (self.path / "config" / name).resolve()
        if not str(p).startswith(str((self.path / "config").resolve())):
            raise ValueError("path escapes bundle")
        return p.read_text()

    def runbook(self, name: str) -> str:
        return (self.path / "runbooks" / name).read_text()

    def evidence_ids(self) -> set[str]:
        return ({e["id"] for e in self.logs()} | {d["id"] for d in self.deployments()}
                | {a["id"] for a in self.alerts()})
