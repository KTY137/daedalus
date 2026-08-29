#!/usr/bin/env python3
"""Install and run the bounded Fourfold/Tensor gardener campaign.

This is an operator wrapper around the existing canonical ``daedalus.loop``.
It does not implement another picker, attempt engine, evaluator, budget ledger,
kill switch, merge path, or promotion path.

Every activation performs the same order:

1. resolve the current date in Europe/Berlin;
2. read and hash the adopted Master Plan;
3. before the campaign deadline, invoke one bounded ``daedalus.loop`` run;
4. on/after the deadline, invoke no candidate execution, stop the canonical
   kill switch, retain a final repository/branch/worktree inventory, and
   disable the Windows scheduled task.

The Windows installer uses one per-user, least-privilege Task Scheduler task.
It sets ``IgnoreNew`` and creates a distinct finalization trigger at the hard
cutoff. No Windows password, SYSTEM identity, shell interpolation, Git merge,
push, reset, promotion, or OwnerApproval command is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = ROOT / "docs" / "campaigns" / "FOURFOLD_TENSOR_GARDENER_20260929.json"
TASK_NAME = r"\Daedalus\FourfoldTensorGardener20260929"
CAMPAIGN_SCHEMA = "daedalus-gardener-campaign/1"
RECEIPT_SCHEMA = "daedalus-gardener-activation/1"
FINAL_SCHEMA = "daedalus-gardener-final-report/1"
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MASTER_PLAN_MARKERS = (
    "Status: adopted",
    "sole semantic authority",
    "Responsibility-led strangler boundary",
)


class CampaignError(RuntimeError):
    """The campaign configuration or runtime state is unsafe or invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CampaignError(f"duplicate campaign JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CampaignError(f"non-finite campaign JSON constant: {value}")


def _strict_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CampaignError(f"campaign file cannot be read: {path}") from exc
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise CampaignError("campaign file size is invalid")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise CampaignError("campaign file must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CampaignError("campaign file is malformed JSON") from exc
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise CampaignError("campaign JSON root must be an object")
    return value


def _positive_int(value: object, name: str, *, ceiling: int) -> int:
    if type(value) is not int or value <= 0 or value > ceiling:
        raise CampaignError(f"{name} must be an integer in 1..{ceiling}")
    return value


def _positive_float(value: object, name: str, *, ceiling: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignError(f"{name} must be numeric")
    result = float(value)
    if not 0.0 < result <= ceiling:
        raise CampaignError(f"{name} must be in (0, {ceiling}]")
    return result


def _date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise CampaignError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CampaignError(f"{name} must be an ISO date") from exc


def _confined_file(repo_root: Path, raw: object, name: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise CampaignError(f"{name} must be a repo-relative path")
    supplied = Path(raw)
    if supplied.is_absolute() or any(part in {".", ".."} for part in supplied.parts):
        raise CampaignError(f"{name} must be a canonical repo-relative path")
    root = repo_root.resolve()
    candidate = (root / supplied).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CampaignError(f"{name} escapes the repository") from exc
    return candidate


@dataclass(frozen=True)
class Bounds:
    max_iterations: int
    max_wall_clock_s: int
    max_spend_usd: float
    max_attempts_per_candidate: int
    queue_limit: int


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    timezone_name: str
    work_until_date_exclusive: date
    final_report_date: date
    interval_minutes: int
    master_plan: str
    derived_execution_plan: str
    bounds: Bounds
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path) -> "Campaign":
        value = _strict_json(path)
        if value.get("schema") != CAMPAIGN_SCHEMA:
            raise CampaignError("unsupported gardener campaign schema")
        campaign_id = value.get("campaign_id")
        if not isinstance(campaign_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,127}", campaign_id
        ):
            raise CampaignError("campaign_id is invalid")
        timezone_name = value.get("timezone")
        if timezone_name != "Europe/Berlin":
            raise CampaignError("this campaign must use Europe/Berlin")
        stop = _date(
            value.get("work_until_date_exclusive"),
            "work_until_date_exclusive",
        )
        final = _date(value.get("final_report_date"), "final_report_date")
        if final != stop:
            raise CampaignError(
                "final_report_date must equal the first non-working date"
            )
        schedule = value.get("schedule")
        if not isinstance(schedule, Mapping):
            raise CampaignError("schedule must be an object")
        if schedule.get("multiple_instances") != "IgnoreNew":
            raise CampaignError("schedule must refuse overlapping instances")
        if schedule.get("interactive_user_only") is not True:
            raise CampaignError("campaign must run only in the interactive user session")
        if schedule.get("least_privilege") is not True:
            raise CampaignError("campaign must run at least privilege")
        interval = _positive_int(
            schedule.get("interval_minutes"),
            "interval_minutes",
            ceiling=1440,
        )
        authority = value.get("authority")
        if not isinstance(authority, Mapping):
            raise CampaignError("authority must be an object")
        for forbidden_true in (
            "automatic_merge",
            "automatic_promotion",
            "may_mint_owner_approval",
            "may_change_gate_state",
        ):
            if authority.get(forbidden_true) is not False:
                raise CampaignError(f"authority.{forbidden_true} must be false")
        if authority.get("classification") != "ALIGNED":
            raise CampaignError("campaign must be classified ALIGNED")
        master_plan = authority.get("master_plan")
        execution_plan = authority.get("derived_execution_plan")
        if not isinstance(master_plan, str) or not isinstance(execution_plan, str):
            raise CampaignError("authority plan paths must be strings")
        bounds = value.get("activation_bounds")
        if not isinstance(bounds, Mapping):
            raise CampaignError("activation_bounds must be an object")
        return cls(
            campaign_id=campaign_id,
            timezone_name=timezone_name,
            work_until_date_exclusive=stop,
            final_report_date=final,
            interval_minutes=interval,
            master_plan=master_plan,
            derived_execution_plan=execution_plan,
            bounds=Bounds(
                max_iterations=_positive_int(
                    bounds.get("max_iterations"),
                    "max_iterations",
                    ceiling=20,
                ),
                max_wall_clock_s=_positive_int(
                    bounds.get("max_wall_clock_s"),
                    "max_wall_clock_s",
                    ceiling=7200,
                ),
                max_spend_usd=_positive_float(
                    bounds.get("max_spend_usd"),
                    "max_spend_usd",
                    ceiling=100.0,
                ),
                max_attempts_per_candidate=_positive_int(
                    bounds.get("max_attempts_per_candidate"),
                    "max_attempts_per_candidate",
                    ceiling=10,
                ),
                queue_limit=_positive_int(
                    bounds.get("queue_limit"),
                    "queue_limit",
                    ceiling=100,
                ),
            ),
            raw=value,
        )


def _berlin_now() -> tuple[datetime, str]:
    """Return Berlin time; use Windows local time only when IANA data is absent."""

    try:
        return datetime.now(ZoneInfo("Europe/Berlin")), "zoneinfo"
    except ZoneInfoNotFoundError:
        local = datetime.now().astimezone()
        if local.utcoffset() not in {timedelta(hours=1), timedelta(hours=2)}:
            raise CampaignError(
                "Europe/Berlin tzdata is unavailable and the system local UTC "
                "offset is not compatible with Berlin"
            )
        return local, "system-local-fallback"


def _iso_utc(value: datetime | None = None) -> str:
    instant = value or datetime.now(timezone.utc)
    return instant.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 60.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CampaignError(f"command could not complete: {argv[0]}") from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:1000]
        raise CampaignError(
            f"command failed ({completed.returncode}): {' '.join(argv)}: {detail}"
        )
    return completed


def _git(repo_root: Path, *args: str, timeout: float = 60.0) -> str:
    completed = _run(
        ("git", "-C", str(repo_root), *args),
        cwd=repo_root,
        timeout=timeout,
        check=True,
    )
    return completed.stdout.strip()


def _repo_state(repo_root: Path) -> dict[str, Any]:
    head = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "branch", "--show-current")
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    refs = _git(
        repo_root,
        "for-each-ref",
        "--format=%(refname:short)\t%(objectname)",
        "refs/heads",
        "refs/remotes/origin",
    )
    worktrees = _git(repo_root, "worktree", "list", "--porcelain")
    branches = []
    for line in refs.splitlines():
        if not line.strip():
            continue
        name, _, sha = line.partition("\t")
        branches.append({"name": name, "sha": sha})
    return {
        "head": head,
        "branch": branch or None,
        "dirty": bool(status),
        "dirty_paths": status.splitlines()[:500],
        "branch_count": len(branches),
        "branches": branches,
        "worktrees_porcelain": worktrees.splitlines(),
    }


def _plan_state(repo_root: Path, campaign: Campaign) -> dict[str, Any]:
    plan = _confined_file(repo_root, campaign.master_plan, "master_plan")
    derived = _confined_file(
        repo_root,
        campaign.derived_execution_plan,
        "derived_execution_plan",
    )
    try:
        plan_bytes = plan.read_bytes()
        derived_bytes = derived.read_bytes()
    except OSError as exc:
        raise CampaignError("campaign authority documents cannot be read") from exc
    try:
        text = plan_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignError("Master Plan must be UTF-8") from exc
    missing = [marker for marker in MASTER_PLAN_MARKERS if marker not in text]
    if missing:
        raise CampaignError(
            "Master Plan authority markers are missing: " + ", ".join(missing)
        )
    revision_match = re.search(r"^Revision:\s*(\d+)\s*$", text, re.MULTILINE)
    version_match = re.search(r"^Version:\s*([^\s]+)\s*$", text, re.MULTILINE)
    gate_match = re.search(
        r"^Active delivery gate:\s*(.+?)\s*$",
        text,
        re.MULTILINE,
    )
    if revision_match is None or version_match is None or gate_match is None:
        raise CampaignError("Master Plan identity fields are incomplete")
    return {
        "master_plan_path": plan.relative_to(repo_root).as_posix(),
        "master_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "master_plan_revision": int(revision_match.group(1)),
        "master_plan_version": version_match.group(1),
        "active_delivery_gate": gate_match.group(1),
        "derived_execution_plan_path": derived.relative_to(repo_root).as_posix(),
        "derived_execution_plan_sha256": hashlib.sha256(derived_bytes).hexdigest(),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    _atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


def _write_capture(path: Path, text: str) -> dict[str, Any]:
    data = text.encode("utf-8", "replace")
    truncated = len(data) > MAX_CAPTURE_BYTES
    retained = data[:MAX_CAPTURE_BYTES]
    _atomic_write(path, retained)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(retained).hexdigest(),
        "byte_length": len(retained),
        "truncated": truncated,
    }


def _campaign_root(repo_root: Path, campaign: Campaign) -> Path:
    return repo_root / "runs" / "gardener" / campaign.campaign_id


def _loop_argv(repo_root: Path, campaign: Campaign) -> tuple[str, ...]:
    bounds = campaign.bounds
    return (
        sys.executable,
        "-m",
        "daedalus.loop",
        "--repo-root",
        str(repo_root),
        "--max-iterations",
        str(bounds.max_iterations),
        "--max-wall-clock-s",
        str(bounds.max_wall_clock_s),
        "--max-spend-usd",
        f"{bounds.max_spend_usd:.2f}",
        "--max-attempts-per-candidate",
        str(bounds.max_attempts_per_candidate),
        "--queue-limit",
        str(bounds.queue_limit),
        "--json",
        "--arm",
    )


def _killswitch(repo_root: Path, action: str, reason: str, *, force: bool = False) -> int:
    argv = [sys.executable, "-m", "daedalus.spine.killswitch", action]
    if action == "arm" and force:
        argv.append("--force")
    if reason:
        argv.append(reason)
    return _run(argv, cwd=repo_root, timeout=60.0).returncode


def _disable_task(repo_root: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"attempted": False, "reason": "not-windows"}
    completed = _run(
        ("schtasks.exe", "/Change", "/TN", TASK_NAME, "/Disable"),
        cwd=repo_root,
        timeout=60.0,
    )
    return {
        "attempted": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[:1000],
        "stderr": completed.stderr.strip()[:1000],
    }


def _finalize(
    repo_root: Path,
    campaign: Campaign,
    *,
    now: datetime,
    timezone_source: str,
) -> int:
    stop_code = _killswitch(
        repo_root,
        "stop",
        f"gardener campaign deadline reached {campaign.final_report_date.isoformat()}",
    )
    report = {
        "schema": FINAL_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "finished_at": _iso_utc(),
        "berlin_time": now.isoformat(timespec="seconds"),
        "timezone_source": timezone_source,
        "deadline": campaign.work_until_date_exclusive.isoformat(),
        "candidate_execution_performed": False,
        "kill_switch_stop_returncode": stop_code,
        "scheduled_task_disable": _disable_task(repo_root),
        "plan": _plan_state(repo_root, campaign),
        "repository": _repo_state(repo_root),
        "claim_boundary": {
            "crewai_beaten": "unassessed_without_sealed_comparable_benchmark",
            "alphaevolve_beaten": "unassessed_without_directly_comparable_public_evidence",
            "automatic_merge": False,
            "automatic_promotion": False,
        },
    }
    root = _campaign_root(repo_root, campaign)
    digest = _write_json(root / "final.json", report)
    print(json.dumps({**report, "final_report_sha256": digest}, indent=2))
    return 0 if stop_code == 0 else 2


def run_activation(repo_root: Path, campaign_path: Path) -> int:
    campaign = Campaign.load(campaign_path)
    now, timezone_source = _berlin_now()
    if now.date() >= campaign.work_until_date_exclusive:
        return _finalize(
            repo_root,
            campaign,
            now=now,
            timezone_source=timezone_source,
        )

    plan = _plan_state(repo_root, campaign)
    repository_before = _repo_state(repo_root)
    started = _iso_utc()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    activation_dir = _campaign_root(repo_root, campaign) / "activations" / stamp
    completed = _run(
        _loop_argv(repo_root, campaign),
        cwd=repo_root,
        timeout=float(campaign.bounds.max_wall_clock_s + 600),
    )
    stdout_ref = _write_capture(activation_dir / "stdout.log", completed.stdout)
    stderr_ref = _write_capture(activation_dir / "stderr.log", completed.stderr)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "started_at": started,
        "finished_at": _iso_utc(),
        "berlin_time_at_start": now.isoformat(timespec="seconds"),
        "timezone_source": timezone_source,
        "deadline": campaign.work_until_date_exclusive.isoformat(),
        "candidate_execution_performed": True,
        "loop_returncode": completed.returncode,
        "loop_argv": list(_loop_argv(repo_root, campaign)[1:]),
        "bounds": {
            "max_iterations": campaign.bounds.max_iterations,
            "max_wall_clock_s": campaign.bounds.max_wall_clock_s,
            "max_spend_usd": campaign.bounds.max_spend_usd,
            "max_attempts_per_candidate": campaign.bounds.max_attempts_per_candidate,
            "queue_limit": campaign.bounds.queue_limit,
        },
        "plan": plan,
        "repository_before": repository_before,
        "repository_after": _repo_state(repo_root),
        "stdout": stdout_ref,
        "stderr": stderr_ref,
        "authority": {
            "automatic_merge": False,
            "automatic_promotion": False,
            "owner_approval_minted": False,
            "gate_state_changed": False,
        },
    }
    receipt_digest = _write_json(activation_dir / "receipt.json", receipt)
    print(json.dumps({**receipt, "receipt_sha256": receipt_digest}, indent=2))
    return completed.returncode


def _current_user(repo_root: Path) -> str:
    if os.name != "nt":
        raise CampaignError("Windows Task Scheduler installation requires Windows")
    completed = _run(("whoami.exe",), cwd=repo_root, timeout=30.0, check=True)
    user = completed.stdout.strip()
    if not user or any(ch in user for ch in "\r\n<>&\""):
        raise CampaignError("current Windows user identity is invalid")
    return user


def _xml_duration_minutes(minutes: int) -> str:
    if minutes <= 0:
        raise CampaignError("duration must be positive")
    hours, remaining = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = "P"
    if days:
        parts += f"{days}D"
    if hours or remaining or not days:
        parts += "T"
        if hours:
            parts += f"{hours}H"
        if remaining:
            parts += f"{remaining}M"
        if not hours and not remaining:
            parts += "1M"
    return parts


def _task_xml(
    repo_root: Path,
    campaign_path: Path,
    campaign: Campaign,
    *,
    start: datetime,
    user: str,
) -> bytes:
    """Build one Task Scheduler 1.4 document with run and final triggers."""

    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)

    def element(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
        child = ET.SubElement(parent, f"{{{ns}}}{name}")
        if text is not None:
            child.text = text
        return child

    task = ET.Element(f"{{{ns}}}Task", {"version": "1.4"})
    registration = element(task, "RegistrationInfo")
    element(registration, "Date", start.isoformat(timespec="seconds"))
    element(registration, "Author", user)
    element(
        registration,
        "Description",
        "Bounded Masterplan-aligned Fourfold/Tensor gardener campaign. "
        "Nominates only; never auto-merges or promotes.",
    )

    triggers = element(task, "Triggers")
    repeated = element(triggers, "TimeTrigger")
    element(repeated, "StartBoundary", start.isoformat(timespec="seconds"))
    cutoff = datetime.combine(
        campaign.work_until_date_exclusive,
        datetime.min.time(),
        tzinfo=start.tzinfo,
    )
    element(repeated, "EndBoundary", cutoff.isoformat(timespec="seconds"))
    element(repeated, "Enabled", "true")
    repetition = element(repeated, "Repetition")
    element(repetition, "Interval", _xml_duration_minutes(campaign.interval_minutes))
    element(repetition, "Duration", _xml_duration_minutes(max(1, int((cutoff - start).total_seconds() // 60))))
    element(repetition, "StopAtDurationEnd", "true")

    final_trigger = element(triggers, "TimeTrigger")
    element(final_trigger, "StartBoundary", cutoff.isoformat(timespec="seconds"))
    element(final_trigger, "Enabled", "true")

    principals = element(task, "Principals")
    principal = ET.SubElement(principals, f"{{{ns}}}Principal", {"id": "Author"})
    element(principal, "UserId", user)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")

    settings = element(task, "Settings")
    element(settings, "MultipleInstancesPolicy", "IgnoreNew")
    element(settings, "DisallowStartIfOnBatteries", "false")
    element(settings, "StopIfGoingOnBatteries", "false")
    element(settings, "AllowHardTerminate", "true")
    element(settings, "StartWhenAvailable", "true")
    element(settings, "RunOnlyIfNetworkAvailable", "false")
    element(settings, "Enabled", "true")
    element(settings, "Hidden", "false")
    element(settings, "RunOnlyIfIdle", "false")
    element(settings, "WakeToRun", "false")
    element(settings, "ExecutionTimeLimit", "PT35M")
    element(settings, "Priority", "7")

    actions = ET.SubElement(task, f"{{{ns}}}Actions", {"Context": "Author"})
    execution = element(actions, "Exec")
    element(execution, "Command", str(Path(sys.executable).resolve()))
    arguments = (
        f'"{Path(__file__).resolve()}" run '
        f'--repo-root "{repo_root.resolve()}" '
        f'--campaign "{campaign_path.resolve()}"'
    )
    element(execution, "Arguments", arguments)
    element(execution, "WorkingDirectory", str(repo_root.resolve()))

    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def install_task(
    repo_root: Path,
    campaign_path: Path,
    *,
    force_rearm: bool,
) -> int:
    campaign = Campaign.load(campaign_path)
    now, _ = _berlin_now()
    if now.date() >= campaign.work_until_date_exclusive:
        raise CampaignError("campaign deadline has already been reached")
    if _killswitch(
        repo_root,
        "arm",
        f"install gardener campaign {campaign.campaign_id}",
        force=force_rearm,
    ) != 0:
        raise CampaignError(
            "kill switch did not arm; a sticky operator stop remains authoritative"
        )
    user = _current_user(repo_root)
    start = now + timedelta(minutes=2)
    xml = _task_xml(
        repo_root,
        campaign_path,
        campaign,
        start=start,
        user=user,
    )
    fd, temp_name = tempfile.mkstemp(suffix=".xml", prefix="daedalus-gardener-")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(xml)
        completed = _run(
            ("schtasks.exe", "/Create", "/TN", TASK_NAME, "/XML", str(temp), "/F"),
            cwd=repo_root,
            timeout=60.0,
        )
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    if completed.returncode != 0:
        raise CampaignError(
            "Task Scheduler registration failed: "
            + (completed.stderr or completed.stdout).strip()[:1000]
        )
    print(f"Installed {TASK_NAME}")
    print(f"First activation: {start.isoformat(timespec='seconds')}")
    print(f"Hard stop/finalization: {campaign.work_until_date_exclusive.isoformat()} 00:00 Europe/Berlin")
    print(f"Interval: {campaign.interval_minutes} minutes; overlap policy: IgnoreNew")
    return 0


def status_task(repo_root: Path, campaign_path: Path) -> int:
    campaign = Campaign.load(campaign_path)
    now, source = _berlin_now()
    result: dict[str, Any] = {
        "campaign_id": campaign.campaign_id,
        "berlin_time": now.isoformat(timespec="seconds"),
        "timezone_source": source,
        "deadline": campaign.work_until_date_exclusive.isoformat(),
        "work_allowed_now": now.date() < campaign.work_until_date_exclusive,
        "plan": _plan_state(repo_root, campaign),
        "repository": _repo_state(repo_root),
    }
    if os.name == "nt":
        completed = _run(
            ("schtasks.exe", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"),
            cwd=repo_root,
            timeout=60.0,
        )
        result["scheduled_task"] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    else:
        result["scheduled_task"] = {"available": False, "reason": "not-windows"}
    print(json.dumps(result, indent=2))
    return 0


def stop_task(repo_root: Path, *, delete: bool) -> int:
    stop_code = _killswitch(repo_root, "stop", "operator stop via gardener_campaign.py")
    task_code = 0
    if os.name == "nt":
        _run(("schtasks.exe", "/End", "/TN", TASK_NAME), cwd=repo_root, timeout=60.0)
        if delete:
            completed = _run(
                ("schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"),
                cwd=repo_root,
                timeout=60.0,
            )
            task_code = completed.returncode
        else:
            completed = _run(
                ("schtasks.exe", "/Change", "/TN", TASK_NAME, "/Disable"),
                cwd=repo_root,
                timeout=60.0,
            )
            task_code = completed.returncode
    return 0 if stop_code == 0 and task_code == 0 else 2


def _repo_root(raw: str | None) -> Path:
    root = Path(raw).expanduser() if raw else ROOT
    root = root.resolve()
    if not (root / ".git").exists() or not (root / "daedalus" / "loop.py").is_file():
        raise CampaignError(f"not a Daedalus Git checkout: {root}")
    return root


def _campaign_path(repo_root: Path, raw: str | None) -> Path:
    path = Path(raw).expanduser() if raw else repo_root / DEFAULT_CAMPAIGN.relative_to(ROOT)
    path = path.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise CampaignError("campaign path must remain inside the repository") from exc
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the deadline-bounded Daedalus gardener campaign."
    )
    parser.add_argument(
        "action",
        choices=("install", "run", "run-once", "status", "start", "stop", "uninstall", "arm"),
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--campaign", default=None)
    parser.add_argument("--force-rearm", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = _repo_root(args.repo_root)
        campaign_path = _campaign_path(repo_root, args.campaign)
        if args.action == "install":
            return install_task(
                repo_root,
                campaign_path,
                force_rearm=bool(args.force_rearm),
            )
        if args.action in {"run", "run-once"}:
            return run_activation(repo_root, campaign_path)
        if args.action == "status":
            return status_task(repo_root, campaign_path)
        if args.action == "start":
            if os.name != "nt":
                raise CampaignError("Task Scheduler start requires Windows")
            return _run(
                ("schtasks.exe", "/Run", "/TN", TASK_NAME),
                cwd=repo_root,
                timeout=60.0,
            ).returncode
        if args.action == "stop":
            return stop_task(repo_root, delete=False)
        if args.action == "uninstall":
            return stop_task(repo_root, delete=True)
        if args.action == "arm":
            return _killswitch(
                repo_root,
                "arm",
                "operator arm via gardener_campaign.py",
                force=bool(args.force_rearm),
            )
        raise CampaignError(f"unsupported action: {args.action}")
    except CampaignError as exc:
        print(f"[gardener] REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
