"""Owner-bounded computer queueing over the canonical event store and CAS.

The existing watcher owns ticking. A committed open claim never implies that
external effects did not happen; interrupted claims require reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from daedalus.atomic import ExclusiveFileLock
from daedalus.budget import process_guard_boundary_decision
from daedalus.kernel.artifacts import store_canonical_json
from daedalus.kernel.offload_lease import require_retained_effect_lease_terminal_record
from daedalus.kernel.policy.computer import ComputerRefused, load_policy
from daedalus.limit_policy import load_from_env
from daedalus.sensitivity import secret_floor_rule
from daedalus.spine.durability import open_gate0_spine_writer
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision, begin_effect
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.killswitch import KillSwitch, control_root
from daedalus.spine.ledger import IntentAlreadyResolved, SpineLedger, default_db_path

from .computer_loop import run_computer_task as _run_computer_task


SCHEDULE_KIND = "ikarus.computer.schedule"
CLAIM_KIND = "ikarus.computer.schedule.claim"
CANCEL_KIND = "ikarus.computer.schedule.cancel"
CONTINUATION_KIND = "ikarus.computer.schedule.continuation"
_MAX_INTERVAL = 365 * 24 * 60 * 60
_OBSERVATIONS = frozenset({"desktop.observe", "browser.navigate", "browser.read", "vision.inspect",
                           "vision.match", "vision.changes", "vision.ocr"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: str | datetime) -> datetime:
    try:
        if isinstance(value, str):
            if len(value) > 64:
                raise ValueError()
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ComputerRefused("schedule time must be an ISO timestamp with an explicit timezone") from exc


def _admit(entrypoint: str, evidence: str) -> Any:
    return begin_effect(entrypoint, REGISTRY_BY_ID[entrypoint].effects,
                        (process_guard_boundary_decision(), GuardDecision("computer.configuration", True, evidence)))


def _claim(ledger: SpineLedger, kind: str, key: str, payload: dict[str, Any]):
    indexes = {SCHEDULE_KIND: "ux_ikarus_computer_schedule", CLAIM_KIND: "ux_ikarus_computer_schedule_claim",
               CANCEL_KIND: "ux_ikarus_computer_schedule_cancel",
               CONTINUATION_KIND: "ux_ikarus_computer_schedule_continuation"}
    if kind not in indexes:
        raise ComputerRefused("unknown schedule intent kind")
    index = indexes[kind]
    with ledger._txn() as connection:
        connection.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index} ON intents(effect_key) WHERE kind='{kind}'")
    try:
        return ledger.record_intent(kind, payload, effect_key=key, trace_id=payload["schedule_id"]), True
    except sqlite3.IntegrityError:
        prior = ledger.intents_by_effect_key(key, kind=kind)
        same = len(prior) == 1 and prior[0].payload == payload
        if len(prior) == 1 and kind in {SCHEDULE_KIND, CANCEL_KIND}:
            same = ({k: v for k, v in prior[0].payload.items() if k != "admission"}
                    == {k: v for k, v in payload.items() if k != "admission"})
        if not same:
            raise ComputerRefused("schedule identity is already bound to different content")
        return prior[0], False


def _spec(root: Path, row: Any) -> dict[str, Any]:
    payload = row.payload
    if type(payload) is not dict or payload.get("authority_root") != str(root) or canonical_sha(payload) != row.payload_sha:
        raise ComputerRefused("schedule authority or payload digest differs")
    ref = payload.get("spec")
    digest = ref.get("sha256") if isinstance(ref, dict) else None
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or ref.get("locator") != "artifact-locator:sha256:" + digest:
        raise ComputerRefused("schedule artifact identity is invalid")
    artifact = control_root(root) / "computer-artifacts" / (digest + ".json")
    if artifact.is_symlink() or artifact.stat().st_size > 65536:
        raise ComputerRefused("schedule artifact is linked or oversized")
    raw = artifact.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ComputerRefused("schedule artifact bytes do not match their digest")
    data = json.loads(raw.decode("ascii"))
    if type(data) is not dict or canonical_sha(data) != digest or data.get("authority_root") != str(root) or data.get("schema") != "daedalus-computer-schedule/1":
        raise ComputerRefused("schedule artifact does not match its canonical identity")
    identity = canonical_sha({k: v for k, v in data.items() if k not in {"schedule_id", "mission_id"}})
    if data.get("schedule_id") != "computer-schedule-" + identity or payload.get("schedule_id") != data["schedule_id"]:
        raise ComputerRefused("schedule identity does not bind its frozen inputs")
    if data.get("mission_id") != "computer-scheduled-" + identity[:32]:
        raise ComputerRefused("scheduled mission identity differs")
    _instant(data["due_at"])
    if _instant(data["expires_at"]) != _instant(data["due_at"]) + timedelta(hours=24):
        raise ComputerRefused("schedule expiry differs from its frozen admission")
    _recurrence(data.get("repeat_every_s"), data.get("occurrences", 1))
    occurrence = data.get("occurrence", 1)
    if type(occurrence) is not int or not 1 <= occurrence <= data.get("occurrences", 1):
        raise ComputerRefused("schedule occurrence is outside its frozen bound")
    if occurrence > 1:
        for field in ("series_id", "previous_schedule_id"):
            if not _schedule_id(data.get(field)):
                raise ComputerRefused("recurring schedule lineage is invalid")
    elif "series_id" in data or "previous_schedule_id" in data:
        raise ComputerRefused("initial schedule cannot replace its series identity")
    admission = payload.get("admission")
    admitted_sha = admission.get("sha256") if isinstance(admission, dict) else None
    if (not isinstance(admitted_sha, str) or len(admitted_sha) != 64
            or any(c not in "0123456789abcdef" for c in admitted_sha)
            or admission.get("locator") != "artifact-locator:sha256:" + admitted_sha):
        raise ComputerRefused("schedule admission identity is invalid")
    admitted_path = control_root(root) / "computer-artifacts" / (admitted_sha + ".json")
    if admitted_path.is_symlink() or admitted_path.stat().st_size > 65536:
        raise ComputerRefused("schedule admission artifact is linked or oversized")
    admitted_raw = admitted_path.read_bytes()
    if hashlib.sha256(admitted_raw).hexdigest() != admitted_sha:
        raise ComputerRefused("schedule admission artifact differs")
    admitted = json.loads(admitted_raw.decode("ascii"))
    boundary = admitted.get("boundary") if isinstance(admitted, dict) else None
    if (not isinstance(admitted, dict) or admitted.get("schema") != "daedalus-computer-schedule-admission/1"
            or admitted.get("spec_sha256") != digest or not isinstance(boundary, dict)
            or boundary.get("entrypoint_id") != "python.computer_schedule"):
        raise ComputerRefused("schedule has no matching retained admission receipt")
    return data


def _recurrence(repeat_every_s: int | None, occurrences: int) -> None:
    if type(occurrences) is not int:
        raise ComputerRefused("occurrences must be an integer")
    if repeat_every_s is None and occurrences == 1:
        return
    if (type(repeat_every_s) is not int or not 60 <= repeat_every_s <= _MAX_INTERVAL
            or not 2 <= occurrences <= 1000):
        raise ComputerRefused("recurrence requires 2 to 1000 occurrences and an interval from 60 seconds to 365 days")


def _schedule_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("computer-schedule-") and _digest(value[18:])


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _identity(spec: dict[str, Any]) -> dict[str, Any]:
    spec = {k: v for k, v in spec.items() if k not in {"schedule_id", "mission_id"}}
    identity = canonical_sha(spec)
    return {**spec, "schedule_id": "computer-schedule-" + identity, "mission_id": "computer-scheduled-" + identity[:32]}


def _series(spec: dict[str, Any]) -> str:
    return spec.get("series_id", spec["schedule_id"])


def _new_spec(authority_root: Path, due: datetime, objective: str, owner_confirmed: bool,
              repeat_every_s: int | None, occurrences: int) -> tuple[Path, dict[str, Any]]:
    if owner_confirmed is not True:
        raise ComputerRefused("explicit owner scheduling is required")
    if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 8000:
        raise ComputerRefused("scheduled objective must contain 1 to 8000 characters")
    if secret_floor_rule("computer-objective.txt", objective):
        raise ComputerRefused("scheduled objective contains secret material and was not retained")
    _recurrence(repeat_every_s, occurrences)
    try:
        due + timedelta(seconds=(repeat_every_s or 0) * (occurrences - 1), hours=24)
    except OverflowError as exc:
        raise ComputerRefused("schedule horizon overflows a representable timestamp") from exc
    root = Path(authority_root).resolve()
    policy = load_policy(root)
    KillSwitch(repo_root=root, sweep_managed=False).checkpoint()
    spec = {"schema": "daedalus-computer-schedule/1", "authority_root": str(root),
            "objective": objective.strip(), "due_at": due.isoformat(),
            "expires_at": (due + timedelta(hours=24)).isoformat(), "policy_sha256": policy.digest,
            "execution_limit_policy_sha256": load_from_env().fingerprint_sha256}
    if repeat_every_s is not None:
        spec.update(repeat_every_s=repeat_every_s, occurrences=occurrences, occurrence=1)
    return root, _identity(spec)


def _persist(ledger: SpineLedger, root: Path, spec: dict[str, Any], receipt: Any) -> dict[str, Any]:
    artifact = store_canonical_json(control_root(root) / "computer-artifacts", spec)
    admission = store_canonical_json(control_root(root) / "computer-artifacts", {
        "schema": "daedalus-computer-schedule-admission/1", "spec_sha256": artifact.sha256,
        "boundary": receipt.to_dict(),
    })
    intent, created = _claim(ledger, SCHEDULE_KIND, spec["schedule_id"], {
        "authority_root": str(root), "schedule_id": spec["schedule_id"], "spec": artifact.to_dict(),
        "admission": admission.to_dict(),
    })
    if not created:
        _spec(root, intent)
    return {"ok": True, "created": created, "state": "scheduled" if intent.is_open else "resolved",
            "schedule_id": spec["schedule_id"], "mission_id": spec["mission_id"],
            "due_at": spec["due_at"], "expires_at": spec["expires_at"], "policy_sha256": spec["policy_sha256"],
            "series_id": _series(spec), "occurrence": spec.get("occurrence", 1),
            "occurrences": spec.get("occurrences", 1), "repeat_every_s": spec.get("repeat_every_s"),
            "artifact": intent.payload["spec"], "admission": intent.payload["admission"], "task_success_verified": False}


def schedule_computer(authority_root: Path, due_at: str, objective: str, *, owner_confirmed: bool = False,
                      repeat_every_s: int | None = None, occurrences: int = 1) -> dict[str, Any]:
    due = _instant(due_at)
    if due < _utcnow():
        raise ComputerRefused("scheduled due time must be in the future")
    root, spec = _new_spec(authority_root, due, objective, owner_confirmed, repeat_every_s, occurrences)
    receipt = _admit("python.computer_schedule", f"explicit owner bounded schedule; root={root}; spec={canonical_sha(spec)}")
    with open_gate0_spine_writer() as ledger:
        return _persist(ledger, root, spec, receipt)


def enqueue_computer(authority_root: Path, objective: str, *, owner_confirmed: bool = False) -> dict[str, Any]:
    root, spec = _new_spec(authority_root, _instant(_utcnow()), objective, owner_confirmed, None, 1)
    receipt = _admit("python.computer_schedule", f"explicit owner immediate queue; root={root}; spec={canonical_sha(spec)}")
    with open_gate0_spine_writer() as ledger:
        return _persist(ledger, root, spec, receipt)


def _schedule_row(ledger: SpineLedger, root: Path, schedule_id: str) -> Any:
    if not _schedule_id(schedule_id):
        raise ComputerRefused("schedule ID is invalid")
    rows = ledger.intents_by_effect_key(schedule_id, kind=SCHEDULE_KIND)
    if len(rows) != 1:
        raise ComputerRefused("scheduled intent identity is missing or ambiguous")
    _spec(root, rows[0])
    return rows[0]


def _series_cancelled(ledger: SpineLedger, root: Path, series_id: str) -> bool:
    rows = ledger.intents_by_effect_key(series_id, kind=CANCEL_KIND)
    if not rows:
        return False
    if (len(rows) != 1 or rows[0].payload.get("authority_root") != str(root)
            or rows[0].payload.get("series_id") != series_id or canonical_sha(rows[0].payload) != rows[0].payload_sha):
        raise ComputerRefused("schedule cancellation authority is invalid")
    # The committed request is sticky even if interruption prevented its terminal event.
    return True


def _complete_once(ledger: SpineLedger, row: Any, result: dict[str, Any], locator: str) -> None:
    try:
        ledger.mark_completed(row.id, effect_id=locator, result=result)
    except IntentAlreadyResolved:
        prior = ledger.intents_by_effect_key(row.effect_key, kind=row.kind)
        if len(prior) != 1 or prior[0].result != result or prior[0].effect_id != locator:
            raise ComputerRefused("schedule terminal evidence conflicts with retained completion")


def cancel_computer_schedule(authority_root: Path, schedule_id: str, *, owner_confirmed: bool = False) -> dict[str, Any]:
    if owner_confirmed is not True:
        raise ComputerRefused("explicit owner cancellation is required")
    root = Path(authority_root).resolve()
    if not default_db_path().exists():
        raise ComputerRefused("scheduled intent identity is missing")
    with SpineLedger(read_only=True) as ledger:
        spec = _spec(root, _schedule_row(ledger, root, schedule_id))
    series_id = _series(spec)
    receipt = _admit("python.computer_schedule", f"explicit owner durable cancellation; root={root}; series={series_id}")
    with open_gate0_spine_writer() as ledger:
        admission = store_canonical_json(control_root(root) / "computer-artifacts", {
            "schema": "daedalus-computer-schedule-cancellation/1", "authority_root": str(root),
            "series_id": series_id, "boundary": receipt.to_dict(),
        })
        intent, created = _claim(ledger, CANCEL_KIND, series_id, {
            "authority_root": str(root), "schedule_id": series_id, "series_id": series_id,
            "admission": admission.to_dict(),
        })
        result = {"ok": True, "state": "cancellation_requested", "series_id": series_id,
                  "cancel_requested": True, "task_success_verified": False}
        retained = store_canonical_json(control_root(root) / "computer-artifacts", result)
        _complete_once(ledger, intent, result, retained.locator)
        # Serialize cancellation cleanup with reservation and continuation
        # metadata. Existing claims retain their actual outcome and are never
        # relabelled as if cancellation had undone an effect.
        with ExclusiveFileLock(control_root(root) / "computer-schedule-claim.lock", timeout_s=5):
            with ExclusiveFileLock(control_root(root) / "computer-schedule-metadata.lock", timeout_s=5):
                for pending in _rows(ledger, root, open_only=True):
                    pending_spec = _spec(root, pending)
                    if _series(pending_spec) != series_id or ledger.intents_by_effect_key(pending.effect_key, kind=CLAIM_KIND):
                        continue
                    cancelled_result = {"ok": False, "state": "cancelled", "schedule_id": pending.effect_key,
                                        "mission_id": pending_spec["mission_id"], "series_id": series_id,
                                        "cancel_requested": True, "task_success_verified": False,
                                        "detail": "owner cancelled before any scheduled effect claim"}
                    artifact = store_canonical_json(control_root(root) / "computer-artifacts", cancelled_result)
                    _complete_once(ledger, pending, cancelled_result, artifact.locator)
    return {**result, "created": created, "schedule_id": schedule_id, "admission": intent.payload["admission"]}


def _rows(ledger: SpineLedger, root: Path, *, open_only: bool = False) -> list[Any]:
    return [row for row in ledger.intents_matching_payload("authority_root", (str(root),), kind=SCHEDULE_KIND, open_only=open_only)
            if isinstance(row.payload, dict) and row.payload.get("authority_root") == str(root)]


def _projection(ledger: SpineLedger, root: Path, row: Any) -> dict[str, Any]:
    spec = _spec(root, row)
    result = {"schedule_id": spec["schedule_id"], "mission_id": spec["mission_id"],
              "authority_root": str(root), "objective": spec["objective"], "due_at": spec["due_at"],
              "expires_at": spec["expires_at"], "policy_sha256": spec["policy_sha256"],
              "execution_limit_policy_sha256": spec["execution_limit_policy_sha256"],
              "series_id": _series(spec), "occurrence": spec.get("occurrence", 1),
              "occurrences": spec.get("occurrences", 1), "repeat_every_s": spec.get("repeat_every_s"),
              "state": "scheduled", "task_success_verified": False}
    if not row.is_open:
        result.update(row.result or {"state": "failed", "error": row.error})
    else:
        claims = ledger.intents_by_effect_key(spec["schedule_id"], kind=CLAIM_KIND)
        if claims:
            if len(claims) != 1:
                raise ComputerRefused("schedule claim identity is ambiguous")
            result.update({"state": "reconciliation_required", "detail": "claim is active or interrupted; never repeat it"}
                          if claims[0].is_open else claims[0].result or {"state": "failed", "error": claims[0].error})
    result["cancel_requested"] = _series_cancelled(ledger, root, _series(spec))
    if result["cancel_requested"]:
        if result["state"] == "scheduled":
            result["state"] = "cancelled"
        elif row.is_open and result["state"] == "reconciliation_required":
            result["state"] = "cancellation_requested"
    continuation = ledger.intents_by_effect_key(spec["schedule_id"], kind=CONTINUATION_KIND)
    if continuation:
        if len(continuation) != 1:
            raise ComputerRefused("schedule continuation identity is ambiguous")
        result["continuation"] = ({"state": "pending"} if continuation[0].is_open else continuation[0].result)
        if not continuation[0].is_open and isinstance(continuation[0].result, dict):
            result["next_schedule_id"] = continuation[0].result.get("next_schedule_id")
    return result


def _list_scheduled(authority_root: Path, *, open_only: bool = False) -> list[dict[str, Any]]:
    root = Path(authority_root).resolve()
    if not default_db_path().exists():
        return []
    with SpineLedger(read_only=True) as ledger:
        results = []
        for row in _rows(ledger, root, open_only=open_only):
            try:
                results.append(_projection(ledger, root, row))
            except (ComputerRefused, OSError, ValueError, KeyError, TypeError) as exc:
                results.append({"schedule_id": row.payload.get("schedule_id"), "state": "invalid", "error": str(exc)})
        return sorted(results, key=lambda x: (x.get("due_at", ""), x.get("schedule_id", "")))


def list_scheduled_computer(authority_root: Path) -> list[dict[str, Any]]:
    return _list_scheduled(authority_root)


def _read_artifact(root: Path, ref: Any) -> dict[str, Any]:
    digest = ref.get("sha256") if isinstance(ref, dict) else None
    if not _digest(digest) or ref.get("locator") != "artifact-locator:sha256:" + digest:
        raise ComputerRefused("continuation evidence has no canonical artifact identity")
    path = control_root(root) / "computer-artifacts" / (digest + ".json")
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ComputerRefused("continuation evidence is linked or oversized")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ComputerRefused("continuation artifact bytes differ from their digest")
    value = json.loads(raw.decode("ascii"))
    if type(value) is not dict or canonical_sha(value) != digest:
        raise ComputerRefused("continuation evidence is not a canonical object")
    return value


def _repeat_permission(root: Path, spec: dict[str, Any], report: dict[str, Any]) -> tuple[bool, str]:
    """Judge retained tool evidence, never the planner's finish/summary text."""
    if report.get("ok") is not True or report.get("state") != "completed":
        return False, "occurrence did not complete successfully"
    steps = report.get("steps")
    if type(steps) is not list or not steps:
        return False, "no terminal tool observation; a model finish alone cannot continue a series"
    try:
        for position, step in enumerate(steps, 1):
            outcome = step["outcome"]
            tool = step["tool"]
            if outcome.get("ok") is not True or outcome.get("state") != "completed":
                return False, "a tool failed or has an uncertain outcome"
            evidence = outcome["evidence"]
            if not all(_digest(evidence.get(key)) for key in ("lease_sha256", "start_sha256", "terminal_sha256")):
                return False, "tool has no retained terminal effect receipt"
            material = _read_artifact(root, evidence["artifact"])
            result = outcome["result"]
            if (material.get("schema") != "daedalus-computer-result/1" or material.get("tool") != tool
                    or material.get("result") != result or type(result) is not dict or result.get("withheld")):
                return False, "tool evidence differs from its retained result"
            binding = evidence["binding"]
            attempt_id = spec["mission_id"] + f"-step-{position:04d}"
            if (material.get("mission_id") != spec["mission_id"] or material.get("attempt_id") != attempt_id
                    or binding.get("attempt_id") != attempt_id or material.get("policy_sha256") != spec["policy_sha256"]
                    or material.get("operation_sha256") != binding.get("operation_sha256")):
                return False, "tool terminal evidence belongs to another occurrence or policy"
            terminal = require_retained_effect_lease_terminal_record(
                control_root(root) / "computer-effect-evidence",
                subject_record_sha256=binding["subject_record_sha256"],
                execution_record_sha256=binding["execution_record_sha256"],
                entrypoint_id="python.ikarus_computer", source_revision=binding["source_revision"],
                attempt_id=attempt_id, operation_sha256=binding["operation_sha256"],
                expected_lease_sha256=evidence["lease_sha256"], expected_execution_id=binding["execution_id"],
                expected_execution_request_sha256=binding["execution_request_sha256"],
                expected_terminal_state="completed", expected_output_digests=(evidence["artifact"]["sha256"],),
            )
            if (terminal.get("record_sha256") != binding.get("terminal_record_sha256")
                    or terminal.get("start_receipt_sha256") != evidence["start_sha256"]
                    or terminal.get("receipt_sha256") != evidence["terminal_sha256"]):
                return False, "tool terminal receipt differs from the retained kernel chain"
            if tool not in _OBSERVATIONS and not (result.get("postcondition_verified") is True
                                                   or tool == "browser.fill" and result.get("field_value_verified") is True):
                return False, "effect postcondition was not independently verified"
    except Exception:
        return False, "terminal tool evidence is missing or invalid"
    return True, "all tool effects have retained successful observations or verified postconditions"


def _repair_continuation(ledger: SpineLedger, root: Path, marker: Any) -> dict[str, Any] | None:
    # This lock covers metadata only. A running task never holds it, so owner
    # cancellation and other observers can progress during a long invocation.
    with ExclusiveFileLock(control_root(root) / "computer-schedule-metadata.lock", timeout_s=5):
        retained = ledger.intents_by_effect_key(marker.effect_key, kind=CONTINUATION_KIND)
        if len(retained) != 1:
            raise ComputerRefused("continuation marker identity differs")
        marker = retained[0]
        if not marker.is_open:
            return marker.result
        row = _schedule_row(ledger, root, marker.payload["schedule_id"])
        if (canonical_sha(marker.payload) != marker.payload_sha
                or marker.payload != {"authority_root": str(root), "schedule_id": row.effect_key, "spec": row.payload["spec"]}):
            raise ComputerRefused("continuation marker does not bind its original schedule")
        spec = _spec(root, row)
        claims = ledger.intents_by_effect_key(spec["schedule_id"], kind=CLAIM_KIND)
        if len(claims) != 1 or claims[0].is_open:
            return None  # Uncertain external effect: never replay it or create a successor.
        claim = claims[0]
        report = claim.result
        if (canonical_sha(claim.payload) != claim.payload_sha
                or claim.payload != {"authority_root": str(root), "schedule_id": spec["schedule_id"], "spec": row.payload["spec"]}):
            raise ComputerRefused("continuation claim does not bind its original schedule")
        if type(report) is not dict or not claim.effect_id:
            raise ComputerRefused("continuation predecessor has no terminal report")
        expected = {"schedule_id": spec["schedule_id"], "mission_id": spec["mission_id"], "series_id": _series(spec),
                    "occurrence": spec.get("occurrence", 1), "occurrences": spec.get("occurrences", 1)}
        if any(report.get(key) != value for key, value in expected.items()):
            raise ComputerRefused("continuation terminal report belongs to a different occurrence")
        digest = claim.effect_id.removeprefix("artifact-locator:sha256:")
        if _read_artifact(root, {"sha256": digest, "locator": claim.effect_id}) != report:
            raise ComputerRefused("continuation predecessor terminal report differs")
        _complete_once(ledger, row, report, claim.effect_id)
        permitted, reason = _repeat_permission(root, spec, report)
        if _series_cancelled(ledger, root, _series(spec)) or report.get("cancel_requested") is True:
            permitted, reason = False, "series cancellation was requested"
        elif load_policy(root).digest != spec["policy_sha256"]:
            permitted, reason = False, "computer policy changed; new owner scheduling required"
        elif load_from_env().fingerprint_sha256 != spec["execution_limit_policy_sha256"]:
            permitted, reason = False, "execution limit policy changed"
        occurrence = spec.get("occurrence", 1)
        if occurrence >= spec.get("occurrences", 1):
            raise ComputerRefused("continuation exceeds its finite occurrence bound")
        result = {"state": "stopped", "schedule_id": spec["schedule_id"], "series_id": _series(spec),
                  "reason": reason, "task_success_verified": False}
        if permitted:
            finished = _instant(report["finished_at"])
            due = finished + timedelta(seconds=spec["repeat_every_s"])
            child = _identity({**spec, "due_at": due.isoformat(), "expires_at": (due + timedelta(hours=24)).isoformat(),
                               "series_id": _series(spec), "previous_schedule_id": spec["schedule_id"],
                               "occurrence": occurrence + 1})
            receipt = _admit("python.computer_schedule", f"retained owner finite recurrence; root={root}; predecessor={spec['schedule_id']}; spec={canonical_sha(child)}")
            scheduled = _persist(ledger, root, child, receipt)
            result.update(state="scheduled", next_schedule_id=scheduled["schedule_id"], due_at=scheduled["due_at"],
                          artifact=scheduled["artifact"])
        artifact = store_canonical_json(control_root(root) / "computer-artifacts", result)
        _complete_once(ledger, marker, result, artifact.locator)
        return result


def _recover_continuations(root: Path) -> list[dict[str, Any]]:
    if not default_db_path().exists():
        return []
    with SpineLedger(read_only=True) as ledger:
        markers = ledger.intents_matching_payload("authority_root", (str(root),), kind=CONTINUATION_KIND, open_only=True)
    if not markers:
        return []
    _admit("python.computer_schedule", f"reconcile retained finite-series metadata only; root={root}")
    results = []
    with open_gate0_spine_writer() as ledger:
        for marker in markers:
            try:
                repaired = _repair_continuation(ledger, root, marker)
                if repaired is not None:
                    results.append({"schedule_id": marker.effect_key, "state": "continuation_reconciled",
                                    "continuation": repaired, "metadata_only": True, "task_success_verified": False})
            except (ComputerRefused, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
                results.append({"schedule_id": marker.effect_key, "state": "reconciliation_required",
                                "error": str(exc), "metadata_only": True, "task_success_verified": False})
    return results


def dispatch_due_computer(authority_root: Path, *, now: datetime | None = None,
                          cancelled: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
    root = Path(authority_root).resolve()
    instant = _instant(now if now is not None else _utcnow())
    recovered = _recover_continuations(root)
    available = _list_scheduled(root, open_only=True)
    # An existing open claim is shown by list/status, never selected again.
    due = [item for item in available if item["state"] == "scheduled" and _instant(item["due_at"]) <= instant]
    if not due:
        return recovered
    selected = due[0]
    _admit("python.computer_dispatch_due", f"resolve retained bounded schedule; root={root}; schedule={selected['schedule_id']}")
    with open_gate0_spine_writer() as ledger:
        rows = ledger.intents_by_effect_key(selected["schedule_id"], kind=SCHEDULE_KIND)
        if len(rows) != 1:
            raise ComputerRefused("scheduled intent identity is ambiguous")
        row = rows[0]
        spec = _spec(root, row)
        if not row.is_open:
            return []
        with ExclusiveFileLock(control_root(root) / "computer-schedule-claim.lock", timeout_s=5):
            row = _schedule_row(ledger, root, selected["schedule_id"])
            if not row.is_open:
                return recovered
            active = ledger.intents_matching_payload("authority_root", (str(root),), kind=CLAIM_KIND, open_only=True)
            if active:
                return [*recovered, {"schedule_id": selected["schedule_id"], "state": "waiting",
                                     "detail": "another scheduled claim is running or requires reconciliation",
                                     "task_success_verified": False}]
            claim, created = _claim(ledger, CLAIM_KIND, spec["schedule_id"], {
                "authority_root": str(root), "schedule_id": spec["schedule_id"], "spec": row.payload["spec"],
            })
        marker = None
        if created and spec.get("occurrence", 1) < spec.get("occurrences", 1):
            marker, _ = _claim(ledger, CONTINUATION_KIND, spec["schedule_id"], {
                "authority_root": str(root), "schedule_id": spec["schedule_id"], "spec": row.payload["spec"],
            })
        if not created:
            if not claim.is_open:
                return [{**(claim.result or {"ok": False, "state": "failed", "error": claim.error}),
                         "schedule_id": spec["schedule_id"], "replayed": True}]
            return [{"schedule_id": spec["schedule_id"], "state": "reconciliation_required",
                     "task_success_verified": False}]
        report: dict[str, Any]
        invoked = False
        def cancellation_requested() -> bool:
            return bool((cancelled and cancelled()) or _series_cancelled(ledger, root, _series(spec)))
        try:
            if cancellation_requested():
                raise ComputerRefused("scheduled task cancelled before execution")
            if instant > _instant(spec["expires_at"]):
                raise ComputerRefused("scheduled task expired without execution")
            if load_policy(root).digest != spec["policy_sha256"]:
                raise ComputerRefused("scheduled computer policy changed; new owner scheduling required")
            if load_from_env().fingerprint_sha256 != spec["execution_limit_policy_sha256"]:
                raise ComputerRefused("scheduled execution limit policy changed")
            KillSwitch(repo_root=root, sweep_managed=False).checkpoint()
            invoked = True
            report = _run_computer_task(root, spec["objective"], mission_id=spec["mission_id"], cancelled=cancellation_requested,
                                       expected_policy_sha256=spec["policy_sha256"],
                                       expected_execution_limit_policy_sha256=spec["execution_limit_policy_sha256"])
            if not isinstance(report, dict) or not isinstance(report.get("state"), str):
                raise ComputerRefused("scheduled mission returned no typed terminal report")
            report = json.loads(json.dumps(report, allow_nan=False))
        except Exception as exc:
            report = {"ok": False, "state": "reconciliation_required" if invoked else "blocked", "error": f"{type(exc).__name__}: {exc}"[:1000],
                      "task_success_verified": False}
        result = {**report, "schedule_id": spec["schedule_id"], "mission_id": spec["mission_id"],
                  "finished_at": max(instant, _utcnow()).isoformat(),
                  "cancel_requested": _series_cancelled(ledger, root, _series(spec)),
                  "series_id": _series(spec), "occurrence": spec.get("occurrence", 1),
                  "occurrences": spec.get("occurrences", 1)}
        artifact = store_canonical_json(control_root(root) / "computer-artifacts", result)
        ledger.mark_completed(claim.id, effect_id=artifact.locator, result=result)
        _complete_once(ledger, row, result, artifact.locator)
        continuation = _repair_continuation(ledger, root, marker) if marker else None
        return [*recovered, {**result, "report_artifact": artifact.to_dict(), "continuation": continuation}]
