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
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFT_DIR = ROOT / "runs" / "drafts"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 48) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:max_len] or "draft"


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
        "status": "pending",   # pending -> applied|dismissed (future)
    }, indent=2), encoding="utf-8")
    return path


def list_drafts() -> list[dict]:
    """Newest-first summaries of every stored draft."""
    if not DRAFT_DIR.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(DRAFT_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "id": d.get("id", p.stem),
            "created": d.get("created", ""),
            "agent": d.get("agent", ""),
            "objective": (d.get("objective") or "")[:100],
            "paths": d.get("paths", []),
            "status": d.get("status", "pending"),
        })
    return out


def get_draft(draft_id: str) -> dict | None:
    p = DRAFT_DIR / f"{draft_id}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def delete_draft(draft_id: str) -> bool:
    p = DRAFT_DIR / f"{draft_id}.json"
    if p.is_file():
        p.unlink()
        return True
    return False
