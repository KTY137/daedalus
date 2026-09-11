"""Persist advisory drafts -- the missing half of the FrugalGPT loop (Era 3 #1).

An advisory-mode task legitimately writes nothing: the free lane produces a
PROPOSAL that a write-capable, trusted lane (Claude / the user) applies later.
Until now that proposal lived only inside the offload result and evaporated
when the caller dropped it. Here every accepted advisory report is persisted
to ``runs/drafts/<ts>-<slug>.json`` so it can be listed, reviewed, applied,
and cleaned up later -- ``daedalus drafts list|show|rm``.

Apply is deliberately NOT automated: a draft is a proposal, and the safety
model says a free model may propose but never merge. Applying stays a human /
Claude action (Era-3 follow-up wires it into the webapp queue view).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

# This module moved one package level deeper. Runtime state remains at the
# repository root for backward compatibility with every existing draft.
ROOT = Path(__file__).resolve().parents[2]
DRAFT_DIR = ROOT / "runs" / "drafts"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# A draft id is our own timestamp-slug stem. It arrives from the CLI and from
# URL path segments (/api/drafts/<id>/apply), so it MUST NOT be trusted into a
# filesystem path -- reject anything that isn't a plain stem (no separators, no
# traversal). Closes the path-traversal gap Minos would have flagged.
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def _slug(text: str, max_len: int = 48) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:max_len] or "draft"


def _safe_path(draft_id: str) -> Path | None:
    """Resolve a draft id to its file ONLY if the id is a plain stem that stays
    inside DRAFT_DIR. Returns None for anything suspicious (``..``, separators,
    absolute paths, symlink escapes)."""
    if not isinstance(draft_id, str) or not _ID_RE.match(draft_id):
        return None
    p = (DRAFT_DIR / f"{draft_id}.json")
    try:
        p.resolve().relative_to(DRAFT_DIR.resolve())
    except (ValueError, OSError):
        return None
    return p


def save_draft(objective: str, paths: list[str], agent: str, provider: str,
               persona: str, report: dict, repo_root: str | None = None) -> Path:
    """Write one accepted advisory report to the drafts store; returns the path."""
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = DRAFT_DIR / f"{ts}-{_slug(objective)}.json"
    # never overwrite an existing draft from the same second
    n = 1
    while path.exists():
        path = DRAFT_DIR / f"{ts}-{_slug(objective)}-{n}.json"
        n += 1
    path.write_text(json.dumps({
        "id": path.stem,
        "created": ts,
        "objective": objective,
        "paths": list(paths or []),
        "agent": agent,
        "provider": provider,
        "persona": persona,
        "repo_root": repo_root or "",
        "report": dict(report or {}),
        "status": "pending",   # pending -> handed_off|dismissed
    }, indent=2), encoding="utf-8")
    return path


def same_repo(a: str, b: str) -> bool:
    """Whether two repo-root strings name the same tree.

    Compared as normalised, case-folded paths rather than as strings. The store
    keeps whatever the writer happened to hold, and on Windows the same
    repository arrives as ``C:\\Users\\...\\agent_env`` from the CLI and as
    ``c:/users/.../agent_env`` from a URL. Comparing raw strings would hide a
    project's own drafts from it -- the same class of lie as showing it
    someone else's, just in the other direction.
    """
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    except (TypeError, ValueError):
        return False


def list_drafts(repo_root: str | None = None) -> list[dict]:
    """Newest-first summaries of stored drafts; all of them, or one repo's.

    THE SUMMARY CARRIES ``repo_root``, AND THAT IS THE POINT. Every draft has
    recorded which repository it was written against since ``save_draft``
    gained the field, but this listing dropped it -- so ``/api/drafts`` had no
    way to scope, the cockpit's decision card counted every project's drafts
    under whichever project was selected, and a count of 427 under `agent_env`
    included proposals written against a garden-notes fixture. That is exactly
    the defect class design review has already caught twice on this surface:
    one project's data displayed under another project's name.

    A draft written before the field existed carries an empty root and belongs
    to no project. It appears only in the unfiltered listing, never scoped into
    a project that cannot be shown to own it.
    """
    if not DRAFT_DIR.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(DRAFT_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        root = d.get("repo_root", "")
        if repo_root and not same_repo(root, repo_root):
            continue
        out.append({
            "id": d.get("id", p.stem),
            "created": d.get("created", ""),
            "agent": d.get("agent", ""),
            "objective": (d.get("objective") or "")[:100],
            "paths": d.get("paths", []),
            "status": _public_status(d.get("status", "pending")),
            "repo_root": root,
        })
    return out


def get_draft(draft_id: str) -> dict | None:
    p = _safe_path(draft_id)
    if p is None or not p.is_file():
        return None
    try:
        stored = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Compatibility is deliberately a read projection. Older rows used the
    # word ``applied`` even though this module never touched the target
    # repository; rewriting them would alter retained history.
    if stored.get("status") == "applied":
        stored = dict(stored)
        stored["legacy_status"] = "applied"
        stored["status"] = "handed_off"
    return stored


def delete_draft(draft_id: str) -> bool:
    p = _safe_path(draft_id)
    if p is not None and p.is_file():
        p.unlink()
        return True
    return False


_STATUSES = ("pending", "handed_off", "dismissed")
_STATUS_ALIASES = {"applied": "handed_off"}


def _public_status(status: object) -> str:
    value = str(status or "pending")
    return _STATUS_ALIASES.get(value, value)


def set_status(draft_id: str, status: str) -> dict | None:
    """Transition a draft's lifecycle. Returns the updated draft, or None if the
    id is unknown; raises ValueError on an invalid status. This does NOT touch
    the filesystem of the target repo. ``applied`` is accepted only as a legacy
    caller alias and persisted as the honest ``handed_off`` state. Idempotent."""
    status = _STATUS_ALIASES.get(status, status)
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}, got {status!r}")
    p = _safe_path(draft_id)
    if p is None or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    d["status"] = status
    d["status_changed"] = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d


def handoff_payload(draft_id: str) -> dict | None:
    """Return the packet a trusted lane may review for later execution.

    This operation performs no repository write. Its only durable transition
    is ``pending -> handed_off``; execution, candidate production, integration
    and promotion remain separate evidence-bearing states.
    """
    d = get_draft(draft_id)
    if d is None:
        return None
    report = d.get("report") or {}
    packet = {
        "id": d.get("id", draft_id),
        "objective": d.get("objective", ""),
        "paths": d.get("paths", []),
        "repo_root": d.get("repo_root", ""),
        "agent": d.get("agent", ""),
        "proposal": report.get("summary", ""),
        "todos": report.get("todos", []),
        "risks": report.get("risks", []),
        "handoff": "Review this proposal and apply it via the trusted (Claude) lane; "
                   "the free bench may propose but never merges.",
    }
    set_status(draft_id, "handed_off")
    return packet


def apply_payload(draft_id: str) -> dict | None:
    """Deprecated compatibility alias for :func:`handoff_payload`."""
    return handoff_payload(draft_id)
