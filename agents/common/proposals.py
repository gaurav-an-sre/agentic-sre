"""The proposal store: where remediation proposals and approval records live.

Two backends, same record shape - the agent gate, remediation-mcp and the human approve endpoint all
read and write the same store, so an approval made by a human in one place is honoured everywhere:

  local (default, offline/tests): files under proposals/ (or PROPOSALS_DIR) - P-*.json
  gcs   (PROPOSAL_STORE=gcs):     gs://PROPOSAL_BUCKET/proposals/P-*.json - shared by Agent Engine,
                                  remediation-mcp and the approve endpoint in the cloud deployment

The module has no intra-package imports so it can be copied standalone into the approve container.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

_PREFIX = "proposals"


def _mode() -> str:
    return os.environ.get("PROPOSAL_STORE", "local")


def _dir() -> Path:
    if os.environ.get("PROPOSALS_DIR"):
        return Path(os.environ["PROPOSALS_DIR"])
    try:  # when used inside the package, honour tools.PROPOSALS (tests monkeypatch it)
        from agents.common import tools
        return tools.PROPOSALS
    except ImportError:  # standalone copy (e.g. the approve container)
        return Path(__file__).resolve().parent / "proposals"


def _bucket():
    from google.cloud import storage  # lazy: offline installs never need it
    name = os.environ.get("PROPOSAL_BUCKET", "")
    return storage.Client().bucket(name.removeprefix("gs://"))


def load(proposal_id: str) -> dict | None:
    if _mode() == "gcs":
        blob = _bucket().blob(f"{_PREFIX}/{proposal_id}.json")
        return json.loads(blob.download_as_text()) if blob.exists() else None
    p = _dir() / f"{proposal_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def save(rec: dict) -> None:
    if _mode() == "gcs":
        _bucket().blob(f"{_PREFIX}/{rec['id']}.json").upload_from_string(
            json.dumps(rec, indent=1), content_type="application/json")
        return
    _dir().mkdir(exist_ok=True)
    (_dir() / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1))


def claim(proposal_id: str) -> dict | None:
    """Atomically move an approved proposal to 'applying'; returns the record, or None if it was
    already claimed/applied/unknown. Two concurrent callers cannot both win: GCS uses a
    metageneration precondition, local files an O_EXCL lock file."""
    if _mode() == "gcs":
        blob = _bucket().blob(f"{_PREFIX}/{proposal_id}.json")
        if not blob.exists():
            return None
        rec = json.loads(blob.download_as_text())
        if rec.get("status") != "approved":
            return None
        rec["status"] = "applying"
        try:
            from google.api_core.exceptions import PreconditionFailed
        except ImportError:
            PreconditionFailed = type(None)  # unreachable: gcs mode implies the lib is installed
        try:
            blob.upload_from_string(json.dumps(rec, indent=1),
                                    if_metageneration_match=blob.metageneration,
                                    content_type="application/json")
        except PreconditionFailed:
            return None  # lost the race: another caller already claimed it
        return rec
    lock = _dir() / f"{proposal_id}.claim"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return None
    rec = load(proposal_id)
    if rec is None or rec.get("status") != "approved":
        lock.unlink(missing_ok=True)
        return None
    rec["status"] = "applying"
    save(rec)
    return rec


def release(proposal_id: str) -> None:
    (_dir() / f"{proposal_id}.claim").unlink(missing_ok=True)


def iter_records() -> Iterator[dict]:
    if _mode() == "gcs":
        for blob in _bucket().list_blobs(prefix=f"{_PREFIX}/"):
            if blob.name.endswith(".json"):
                yield json.loads(blob.download_as_text())
        return
    for p in sorted(f for f in _dir().glob("P-*.json") if f.suffix == ".json"):
        yield json.loads(p.read_text())
