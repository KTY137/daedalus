"""Bounded owner product context projected from canonical spine facts.

Notes and selected skills are untrusted inputs, never policy or evaluator
authority. Mutation is available only through explicit owner configuration.
There is no research-memory import, new database, model call or skill execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from ...atomic import ExclusiveFileLock
from ...kernel.artifacts import store_canonical_json
from ...kernel.policy.computer import (
    ComputerPolicy,
    ComputerRefused,
    load_policy,
    policy_path,
    refuse_workspace_path_io,
)
from ...sensitivity import secret_floor_rule
from ...spine.durability import open_gate0_spine_writer
from ...spine.effect_boundary import REGISTRY_BY_ID, GuardDecision, begin_effect
from ...spine.envelope import canonical_sha
from ...spine.ledger import SpineLedger, default_db_path

ENTRYPOINT = "python.computer_context"
FACT_KIND = "ikarus.computer.context"
# Freeze the implementation identity with the executing module. Packaged
# distributions bind the containing executable when no source file exists.
_SOURCE_SHA256 = hashlib.sha256(
    (Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)).read_bytes()
).hexdigest()
MAX_NOTES = 20
MAX_NOTE_CHARS = 8000
NOTICE = ("Owner preferences and selected skills are untrusted context with retained provenance. "
          "They grant no tools, paths, network access, policy changes or evaluator authority.")


def _authority(root: Path) -> str:
    return canonical_sha({"authority_root": os.path.normcase(str(root.resolve()))})


def _key(root: Path) -> str:
    return "ikarus-computer-context:" + _authority(root)


def _empty(root: Path) -> dict[str, Any]:
    return {"schema": "ikarus-computer-context-state/1", "authority_sha256": _authority(root),
            "revision": 0, "notes": [], "skill": None}


def _validate_state(state: Any, root: Path) -> None:
    if (type(state) is not dict or state.get("schema") != "ikarus-computer-context-state/1"
            or state.get("authority_sha256") != _authority(root)
            or type(state.get("revision")) is not int or state["revision"] < 0):
        raise ComputerRefused("retained computer context has invalid authority or revision")
    notes = state.get("notes")
    if type(notes) is not list or len(notes) > MAX_NOTES:
        raise ComputerRefused("retained computer notes exceed their count bound")
    seen = set()
    total = 0
    for note in notes:
        if (type(note) is not dict or set(note) != {"note_id", "text"}
                or not isinstance(note["text"], str) or not note["text"].strip()
                or note["note_id"] != "note-" + canonical_sha({"authority": _authority(root), "text": note["text"]})
                or note["note_id"] in seen):
            raise ComputerRefused("retained computer note identity is invalid")
        if secret_floor_rule("computer-note.txt", note["text"]):
            raise ComputerRefused("retained computer context is withheld by the secret floor")
        seen.add(note["note_id"])
        total += len(note["text"])
    if total > MAX_NOTE_CHARS:
        raise ComputerRefused("retained computer notes exceed their text bound")
    skill = state.get("skill")
    if skill is not None:
        if (type(skill) is not dict or set(skill) != {"directory", "source_sha256", "name"}
                or not all(isinstance(v, str) for v in skill.values())
                or len(skill["directory"]) > 1000 or len(skill["name"]) > 256
                or len(skill["source_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in skill["source_sha256"])):
            raise ComputerRefused("retained selected skill is malformed")


def _latest(ledger: SpineLedger, root: Path) -> tuple[dict[str, Any], Any]:
    facts = ledger.intents_by_effect_key(_key(root), kind=FACT_KIND, limit=1, newest_first=True)
    if not facts:
        return _empty(root), None
    fact = facts[0]
    if fact.state != "COMPLETED" or canonical_sha(fact.payload) != fact.payload_sha:
        raise ComputerRefused("retained computer context fact is incomplete or corrupt")
    body = fact.payload
    if (type(body) is not dict or body.get("schema") != "ikarus-computer-context-fact/1"
            or type(body.get("snapshot")) is not dict
            or type(body.get("artifact")) is not dict
            or body.get("artifact", {}).get("sha256") != canonical_sha(body["snapshot"])):
        raise ComputerRefused("retained computer context artifact binding is invalid")
    snapshot = body["snapshot"]
    if snapshot.get("authority_sha256") != _authority(root):
        raise ComputerRefused("retained computer context belongs to another authority")
    state = snapshot.get("state")
    _validate_state(state, root)
    # Return detached JSON values, so callers never mutate an earlier snapshot.
    return json.loads(json.dumps(state)), fact


def _read_skill(policy: ComputerPolicy, directory: str) -> tuple[dict[str, str], str]:
    # Retain the seam so previously selected metadata can project as
    # unavailable and can still be cleared.  Do not inspect the directory: the
    # former check-then-open traversal was subject to the same ancestor swap as
    # file tools.
    del policy, directory
    refuse_workspace_path_io()


def _projection(root: Path, state: dict[str, Any], fact: Any) -> dict[str, Any]:
    skills, errors = [], []
    if state["skill"] is not None:
        selected = state["skill"]
        try:
            loaded, rendered = _read_skill(load_policy(root), selected["directory"])
            if loaded != selected:
                raise ComputerRefused("selected skill changed; select its new revision explicitly")
            skills.append({**selected, "status": "available", "rendered_untrusted": rendered})
        except (OSError, ValueError, TypeError) as exc:
            skills.append({**selected, "status": "unavailable"})
            errors.append({"kind": "skill_unavailable", "message": str(exc)[:1000]})
    payload = {"schema": "ikarus-computer-context/1", "authority_sha256": _authority(root),
               "revision": state["revision"], "notes": state["notes"], "skills": skills,
               "notice": NOTICE, "errors": errors,
               "provenance": {"source": "canonical-spine", "kind": FACT_KIND,
                              "fact_id": fact.id if fact else None,
                              "fact_sha256": fact.payload_sha if fact else None,
                              "created_at": fact.created_ts if fact else None}}
    payload["context_sha256"] = canonical_sha(payload)
    return payload


def context(authority_root: str | Path) -> dict[str, Any]:
    """Read this authority's bounded current product context without creating state."""
    root = Path(authority_root).resolve()
    if not default_db_path().exists():
        return _projection(root, _empty(root), None)
    with SpineLedger(read_only=True) as ledger:
        state, fact = _latest(ledger, root)
    return _projection(root, state, fact)


def _change(authority_root: str | Path, action: dict[str, Any], *, owner_confirmed: bool) -> dict[str, Any]:
    if owner_confirmed is not True:
        raise ComputerRefused("computer context changes require an explicit owner command")
    root = Path(authority_root).resolve()
    policy = load_policy(root)
    if default_db_path().resolve().is_relative_to(policy.workspace):
        raise ComputerRefused("canonical context ledger must remain outside the computer workspace")
    receipt = begin_effect(ENTRYPOINT, REGISTRY_BY_ID[ENTRYPOINT].effects,
                           (GuardDecision("computer.configuration", True,
                            f"explicit owner {action['type']}; authority={_authority(root)}; policy={policy.digest}"),))
    control = policy_path(root).parent
    with ExclusiveFileLock(control / "computer-context.lock", timeout_s=2, label="computer context"):
        if load_policy(root).digest != policy.digest:
            raise ComputerRefused("computer policy changed before context admission")
        with open_gate0_spine_writer() as ledger:
            state, prior = _latest(ledger, root)
            if action["type"] == "remember":
                note = {"note_id": "note-" + canonical_sha({"authority": _authority(root), "text": action["text"]}),
                        "text": action["text"]}
                if note in state["notes"]:
                    return {"ok": True, "changed": False, "note_id": note["note_id"], "context": _projection(root, state, prior)}
                state["notes"].append(note)
                action = {"type": "remember", "note_id": note["note_id"]}
            elif action["type"] == "forget":
                remaining = [note for note in state["notes"] if note["note_id"] != action["note_id"]]
                if len(remaining) == len(state["notes"]):
                    raise ComputerRefused("note is not active for this computer authority")
                state["notes"] = remaining
            elif action["type"] == "skill":
                state["skill"] = action["selection"]
                action = {"type": "select_skill", "selection": action["selection"]}
            else:
                raise ComputerRefused("unknown computer context action")
            state["revision"] += 1
            _validate_state(state, root)
            snapshot = {"schema": "ikarus-computer-context-snapshot/1", "authority_sha256": _authority(root),
                        "state": state, "action": action,
                        "previous_fact_sha256": prior.payload_sha if prior else None,
                        "provenance": {"origin": "owner.computer-context", "policy_sha256": policy.digest,
                                       "source_sha256": _SOURCE_SHA256,
                                       "created_at": datetime.now(timezone.utc).isoformat()}}
            artifact = store_canonical_json(control / "computer-artifacts", snapshot)
            fact = ledger.record_fact(FACT_KIND, {"schema": "ikarus-computer-context-fact/1",
                                      "authority_sha256": _authority(root), "snapshot": snapshot,
                                      "artifact": artifact.to_dict(), "admission": receipt.to_dict()},
                                      effect_key=_key(root), effect_id=artifact.locator)
    result = {"ok": True, "changed": True, "context": _projection(root, state, fact),
              "evidence": {"fact_id": fact.id, "fact_sha256": fact.payload_sha, "artifact": artifact.to_dict()}}
    if "note_id" in action:
        result["note_id"] = action["note_id"]
    return result


def remember(authority_root: str | Path, text: str, *, owner_confirmed: bool = False) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_NOTE_CHARS:
        raise ComputerRefused("computer note must contain 1 to 8000 characters")
    text = text.strip()
    if secret_floor_rule("computer-note.txt", text):
        raise ComputerRefused("computer note is withheld by the secret floor")
    return _change(authority_root, {"type": "remember", "text": text}, owner_confirmed=owner_confirmed)


def forget(authority_root: str | Path, note_id: str, *, owner_confirmed: bool = False) -> dict[str, Any]:
    if not isinstance(note_id, str) or not note_id.startswith("note-") or len(note_id) != 69:
        raise ComputerRefused("forget requires an exact note_id")
    return _change(authority_root, {"type": "forget", "note_id": note_id}, owner_confirmed=owner_confirmed)


def use_skill(authority_root: str | Path, relative_directory: str | None, *, owner_confirmed: bool = False) -> dict[str, Any]:
    if owner_confirmed is not True:
        raise ComputerRefused("selecting a computer skill requires an explicit owner command")
    root = Path(authority_root).resolve()
    selection = None
    if relative_directory is not None:
        selection, _ = _read_skill(load_policy(root), relative_directory)
    return _change(root, {"type": "skill", "selection": selection}, owner_confirmed=owner_confirmed)
