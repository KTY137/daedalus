"""Read-only, authority-scoped computer task views over canonical spine and CAS.

Display pages never drive scheduling or replay. Open means pending or interrupted;
it does not establish that an executor is alive. Unscoped legacy state stays so.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ...kernel.artifacts import ArtifactRef
from ...kernel.contracts import MissionContract
from ...kernel.policy.computer import ComputerRefused
from ...sensitivity import secret_floor_rule
from ...spine.envelope import canonical_sha
from ...spine.killswitch import control_root
from ...spine.ledger import SpineLedger, default_db_path

MISSION_KIND = "ikarus.computer.mission"
STEP_KIND = "ikarus.computer.step"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _read_artifact(root: Path, value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"sha256", "locator"}:
        raise ComputerRefused("task artifact requires an exact digest and locator")
    ref = ArtifactRef(**value)
    path = control_root(root) / "ikarus-computer-artifacts" / f"{ref.sha256}.json"
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > MAX_ARTIFACT_BYTES:
        raise ComputerRefused("task evidence is linked or exceeds the display read bound")
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES or hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ComputerRefused("task evidence bytes differ from their artifact digest")
    body = json.loads(raw.decode("ascii"))
    if type(body) is not dict or canonical_sha(body) != ref.sha256:
        raise ComputerRefused("task evidence is not the declared canonical object")
    return body


def _checked_payload(root: Path, row: Any) -> tuple[dict, dict]:
    payload = row.payload
    if type(payload) is not dict or payload.get("authority_root") != str(root):
        raise ComputerRefused("task does not declare this authority root")
    if canonical_sha(payload) != row.payload_sha:
        raise ComputerRefused("task payload digest differs")
    body = _read_artifact(root, payload.get("artifact"))
    if body.get("authority_root") != str(root):
        raise ComputerRefused("mission artifact belongs to another authority")
    mission = MissionContract.from_dict(body["mission"])
    if (mission.digest != payload.get("mission_sha256")
            or mission.mission_id != payload.get("mission_id")
            or mission.objective != payload.get("objective")
            or mission.policy_sha256 != payload.get("policy_sha256")):
        raise ComputerRefused("task inputs differ from their canonical mission")
    return payload, body


def _project(root: Path, row: Any) -> dict:
    payload, _ = _checked_payload(root, row)
    result = {"mission_id": payload["mission_id"], "intent_id": row.id,
              "objective": payload["objective"], "created_at": row.created_ts,
              "mission_sha256": payload["mission_sha256"],
              "policy_sha256": payload["policy_sha256"],
              "state": "pending_or_interrupted", "task_success_verified": False,
              "worker_liveness": "unknown", "terminal": not row.is_open}
    if not row.is_open:
        if row.state != "COMPLETED" or type(row.result) is not dict:
            raise ComputerRefused("task has no retained terminal report")
        report = row.result
        stored = _read_artifact(root, report.get("report_artifact"))
        if (stored != {key: value for key, value in report.items() if key != "report_artifact"}
                or row.effect_id != report["report_artifact"]["locator"]
                or stored.get("authority_root") != str(root)
                or stored.get("mission_id") != payload["mission_id"]
                or stored.get("mission_sha256") != payload["mission_sha256"]
                or stored.get("mission_artifact") != payload["artifact"]):
            raise ComputerRefused("terminal report does not bind this mission")
        result.update(state=stored.get("state"), summary=str(stored.get("summary", ""))[:2000],
                      tool_steps=len(stored.get("steps", [])), elapsed_s=stored.get("elapsed_s"),
                      planner_calls=stored.get("planner_calls"), plan=stored.get("plan"),
                      report_artifact=report["report_artifact"])
    if secret_floor_rule("computer-history.json", json.dumps(result, ensure_ascii=False)):
        raise ComputerRefused("task display withheld by secret floor")
    return result


def _invalid(row: Any, exc: Exception) -> dict:
    # Do not repeat unvalidated payload content or arbitrary exception text.
    return {"intent_id": row.id, "state": "evidence_unavailable",
            "error_type": type(exc).__name__, "task_success_verified": False}


def list_computer_tasks(authority_root: str | Path, *, limit: int = 20,
                        before_id: int | None = None) -> dict:
    """Newest display page only; SQL pagination is explicit in the response."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ComputerRefused("task page limit must be between 1 and 100")
    if before_id is not None and (type(before_id) is not int or before_id < 1):
        raise ComputerRefused("task page cursor must be a positive intent ID")
    root = Path(authority_root).resolve()
    result = {"schema": "ikarus-computer-task-page/1", "authority_root": str(root),
              "items": [], "has_more": False, "next_cursor": None,
              "legacy_unscoped": "not included; exact ID lookup reports unscoped history"}
    if default_db_path().exists():
        with SpineLedger(read_only=True) as ledger:
            rows = ledger.intents_matching_payload("authority_root", (str(root),),
                         kind=MISSION_KIND, limit=limit + 1, before_id=before_id)
            result["has_more"] = len(rows) > limit
            for row in rows[:limit]:
                try:
                    result["items"].append(_project(root, row))
                except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                    result["items"].append(_invalid(row, exc))
            if result["has_more"]:
                result["next_cursor"] = rows[limit - 1].id
    result["returned_count"] = len(result["items"])
    return result


def computer_task(authority_root: str | Path, mission_id: str) -> dict:
    """Inspect one exact mission and a labelled bounded step page, without writes."""
    if not isinstance(mission_id, str) or not 1 <= len(mission_id) <= 120:
        raise ComputerRefused("task lookup requires a bounded mission ID")
    root = Path(authority_root).resolve()
    if not default_db_path().exists():
        return {"state": "not_found", "mission_id": mission_id}
    with SpineLedger(read_only=True) as ledger:
        rows = ledger.intents_by_effect_key("computer:" + mission_id, kind=MISSION_KIND, limit=2)
        if not rows:
            return {"state": "not_found", "mission_id": mission_id}
        if len(rows) != 1:
            return {"state": "evidence_unavailable", "mission_id": mission_id}
        row = rows[0]
        if type(row.payload) is not dict or "authority_root" not in row.payload:
            return {"state": "legacy_unscoped", "mission_id": mission_id,
                    "detail": "This historical row has no declared authority; no task content is exposed."}
        if row.payload["authority_root"] != str(root):
            return {"state": "not_found", "mission_id": mission_id}
        try:
            result = _project(root, row)
            steps = ledger.intents_matching_payload("mission_id", (mission_id,), kind=STEP_KIND, limit=51)
            projected = []
            for step in steps[:50]:
                payload = step.payload
                if (type(payload) is not dict or canonical_sha(payload) != step.payload_sha
                        or payload.get("authority_root") != str(root)
                        or payload.get("mission_id") != mission_id):
                    raise ComputerRefused("step authority differs from the requested mission")
                proposal = _read_artifact(root, ArtifactRef.from_sha256(payload["proposal_sha256"]).to_dict())
                if (proposal.get("authority_root") != str(root)
                        or proposal.get("mission_sha256") != result["mission_sha256"]
                        or proposal.get("attempt_id") != payload.get("attempt_id")):
                    raise ComputerRefused("step source differs from the requested mission")
                projected.append({"attempt_id": payload["attempt_id"], "state": step.state,
                                  "tool": proposal.get("proposal", {}).get("tool"),
                                  "pending_or_interrupted": step.is_open})
            result.update(recent_steps=projected, steps_has_more=len(steps) > 50,
                          steps_order="newest_first")
            if secret_floor_rule("computer-history.json", json.dumps(result, ensure_ascii=False)):
                raise ComputerRefused("task display withheld by secret floor")
            return result
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            return _invalid(row, exc)
