"""The proposal store: where remediation proposals and approval records live.

Proposals are agent-writable; approvals are NOT. The gate trusts only separate approval objects
that the human approve path (sre-trigger, tokened POST /approve) or control_plane.approve writes -
a status field inside the proposal doc itself is ignored, so the agent cannot promote its own
proposal to 'approved'. Approvals snapshot the reviewed target at approve time, so the binding
survives any later edit of the (agent-writable) proposal.

    proposals/{id}.json   pending proposal (agent writes via propose_remediation)
    approvals/{id}.json   approval record, incl. approved_target snapshot (human path only)
    claims/{id}.json      atomic 'applying' marker - first creator wins
    applied/{id}.json     applied marker with applied_ts / apply_result
    control/{name}.json   operator control flags (e.g. red_button)

Backends, same semantics:

  local (default, offline/tests): files under proposals/ (or PROPOSALS_DIR)
  gcs   (PROPOSAL_STORE=gcs):     gs://PROPOSAL_BUCKET/<prefix>/... - shared by Agent Engine,
                                  remediation-mcp and the approve endpoint

The module has no intra-package imports so it can be copied standalone into the approve container.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

_PREFIX = "proposals"
_APPROVALS = "approvals"
_CLAIMS = "claims"
_APPLIED = "applied"
_CONTROL = "control"
_TARGET_KEYS = ("action", "service", "target_service", "target_revision", "percent", "target_percent")


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


def _path(prefix: str, name: str) -> Path:
    # proposals keep the historical flat layout (P-*.json); other prefixes use subdirs
    return _dir() / f"{name}.json" if prefix == _PREFIX else _dir() / prefix / f"{name}.json"


def _read(prefix: str, name: str) -> dict | None:
    if _mode() == "gcs":
        blob = _bucket().blob(f"{prefix}/{name}.json")
        return json.loads(blob.download_as_text()) if blob.exists() else None
    p = _path(prefix, name)
    return json.loads(p.read_text()) if p.exists() else None


def _write(prefix: str, name: str, rec: dict) -> None:
    if _mode() == "gcs":
        _bucket().blob(f"{prefix}/{name}.json").upload_from_string(
            json.dumps(rec, indent=1), content_type="application/json")
        return
    p = _path(prefix, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1))


def _load_with_status(proposal_id: str) -> dict | None:
    rec = _read(_PREFIX, proposal_id)
    if rec is None:
        return None
    rec = dict(rec)
    appr = _read(_APPROVALS, proposal_id)
    if appr:
        rec.update(status="approved", approved_by=appr["approved_by"], approved_ts=appr["approved_ts"],
                   approved_target=appr.get("approved_target"))
    else:
        rec["status"] = "pending_approval"  # agent-written docs can never set this
    if _read(_CLAIMS, proposal_id) is not None:
        rec["status"] = "applying"
    applied = _read(_APPLIED, proposal_id)
    if applied is not None:
        rec.update(status="applied", applied_ts=applied.get("applied_ts"),
                   apply_result=applied.get("apply_result"), incident_id=applied.get("incident_id"),
                   override_hold=applied.get("override_hold"))
    return rec


def load(proposal_id: str) -> dict | None:
    return _load_with_status(proposal_id)


def save(rec: dict) -> None:
    """Write a proposal. Agent-writable: status is forced to pending_approval and any
    approval fields are stripped - approval can only come from approve() (approvals/ objects)."""
    rec = {k: v for k, v in rec.items()
           if k not in ("approved_by", "approved_ts", "approved_target")}
    rec["status"] = "pending_approval"
    _write(_PREFIX, rec["id"], rec)


def approve(proposal_id: str, approver: str) -> dict | None:
    """Human-path approval: writes an approvals/ object that snapshots the reviewed target.
    Returns the merged record, or None if the proposal is unknown or not pending."""
    rec = _load_with_status(proposal_id)
    if rec is None or rec["status"] != "pending_approval":
        return None
    target = {k: rec[k] for k in _TARGET_KEYS if rec.get(k) is not None}
    appr = {"id": proposal_id, "approved_by": approver,
            "approved_ts": datetime.now(UTC).isoformat(), "approved_target": target}
    _write(_APPROVALS, proposal_id, appr)
    rec.update(status="approved", approved_by=approver, approved_ts=appr["approved_ts"],
               approved_target=target)
    return rec


def mark_applied(rec: dict) -> None:
    _write(_APPLIED, rec["id"], rec)


def claim(proposal_id: str) -> dict | None:
    """Atomically mark an approved proposal 'applying'; returns the record, or None if it was
    already claimed/applied/unknown. Two concurrent callers cannot both win: GCS uses a
    generation precondition on the claim object, local files an O_EXCL lock."""
    rec = _load_with_status(proposal_id)
    if rec is None or rec["status"] != "approved":
        return None
    marker = {"id": proposal_id, "claimed_ts": datetime.now(UTC).isoformat()}
    if _mode() == "gcs":
        try:
            from google.api_core.exceptions import PreconditionFailed
        except ImportError:
            PreconditionFailed = type(None)  # unreachable: gcs mode implies the lib is installed
        blob = _bucket().blob(f"{_CLAIMS}/{proposal_id}.json")
        try:
            blob.upload_from_string(json.dumps(marker), if_generation_match=0,
                                    content_type="application/json")
        except PreconditionFailed:
            return None  # lost the race: another caller already claimed it
        rec["status"] = "applying"
        return rec
    lock = _dir() / _CLAIMS / f"{proposal_id}.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, json.dumps(marker).encode())
        os.close(fd)
    except FileExistsError:
        return None
    rec["status"] = "applying"
    return rec


def release(proposal_id: str) -> None:
    if _mode() == "gcs":
        _bucket().blob(f"{_CLAIMS}/{proposal_id}.json").delete()
    else:
        (_dir() / _CLAIMS / f"{proposal_id}.json").unlink(missing_ok=True)


def control_get(name: str) -> dict | None:
    return _read(_CONTROL, name)


def control_set(name: str, rec: dict | None) -> None:
    if rec is None:
        if _mode() == "gcs":
            _bucket().blob(f"{_CONTROL}/{name}.json").delete()
        else:
            (_dir() / _CONTROL / f"{name}.json").unlink(missing_ok=True)
        return
    _write(_CONTROL, name, rec)


def iter_records() -> Iterator[dict]:
    ids: list[str] = []
    if _mode() == "gcs":
        ids = [b.name.split("/")[-1].removesuffix(".json")
               for b in _bucket().list_blobs(prefix=f"{_PREFIX}/") if b.name.endswith(".json")]
    else:
        ids = [p.stem for p in sorted(_dir().glob("P-*.json"))]
    for pid in ids:
        rec = _load_with_status(pid)
        if rec is not None:
            yield rec
