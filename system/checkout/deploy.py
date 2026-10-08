"""Deploy and roll back the pricing configuration."""

from __future__ import annotations

import difflib
import shutil
import sys
import uuid
from datetime import UTC, datetime

from checkout_svc.evidence import append_jsonl
from checkout_svc.paths import config_dir


def deploy(mode: str) -> str:
    config = config_dir()
    live = config / "pricing.yaml"
    if mode not in {"promo", "rollback"}:
        raise ValueError("mode must be promo or rollback")
    target = config / ("pricing.promo.yaml" if mode == "promo" else "pricing.baseline.yaml")
    if not target.exists():
        raise FileNotFoundError(f"missing deployment config: {target}")
    before = live.read_text(encoding="utf-8")
    after = target.read_text(encoding="utf-8")
    shutil.copyfile(target, live)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="pricing.yaml (before)",
            tofile="pricing.yaml (after)",
        )
    )
    deploy_id = f"deploy-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    description = (
        "Enable free shipping for orders over $100"
        if mode == "promo"
        else "Roll back promotional pricing configuration"
    )
    append_jsonl(
        "deploys.jsonl",
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "deploy_id": deploy_id,
            "actor": "Maya Chen",
            "change_description": description,
            "diff": diff,
        },
    )
    return deploy_id


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tools.deploy promo|rollback")
    print(deploy(sys.argv[1]))


if __name__ == "__main__":
    main()
