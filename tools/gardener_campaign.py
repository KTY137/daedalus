#!/usr/bin/env python3
"""Run the bounded Fourfold/Tensor gardener through 2026-09-29.

This is a thin operator wrapper around the existing ``daedalus.loop``. It adds
no picker, worker protocol, evaluator, budget ledger, kill switch, merge path,
promotion path, or repository truth. Before the Europe/Berlin cutoff it may
launch one bounded canonical loop process. At or after the cutoff it launches
no candidate, stops the canonical kill switch, disables its Windows task, and
retains a final repository topology report.

The repo-local work queue is also the convergence boundary across activations:
a task definition is attempted at most once. Once every current definition has
an attempt in the canonical Spine ledger, later polls retain a waiting-for-owner
receipt rather than producing competing patches. A changed task definition or
candidate-base revision becomes eligible again through the existing picker
memory semantics.
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = ROOT / "docs/campaigns/FOURFOLD_TENSOR_GARDENER_20260929.json"
TASK_PATH = "\\Daedalus\\"
TASK_NAME = "FourfoldTensorGardener20260929"
FULL_TASK_NAME = TASK_PATH + TASK_NAME
CAMPAIGN_SCHEMA = "daedalus-gardener-campaign/1"
ACTIVATION_SCHEMA = "daedalus-gardener-activation/1"
WAITING_SCHEMA = "daedalus-gardener-waiting-owner/1"
FINAL_SCHEMA = "daedalus-gardener-final-report/1"
MAX_LOG_BYTES = 8 * 1024 * 1024


class CampaignError(RuntimeError):
    """Campaign configuration or runtime state is unsafe or invalid."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise CampaignError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise CampaignError(f"forbidden non-finite JSON constant: {value}")


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except OSError as exc:
        raise CampaignError(f"cannot read campaign file: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError("campaign file is not UTF-8 JSON") from exc
    if not raw or len(raw) > 2 * 1024 * 1024 or not isinstance(value, Mapping):
        raise CampaignError("campaign document shape or size is invalid")
    return value


def _iso_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise CampaignError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CampaignError(f"{name} must be an ISO date") from exc


def _integer(value: object, name: str, high: int) -> int:
    if type(value) is not int or not 1 <= value <= high:
        raise CampaignError(f"{name} must be in 1..{high}")
    return value


def _number(value: object, name: str, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignError(f"{name} must be numeric")
    result = float(value)
    if not 0.0 < result <= high:
        raise CampaignError(f"{name} must be in (0, {high}]")
    return result


@dataclass(frozen=True)
class Bounds:
    iterations: int
    wall_s: int
    spend_usd: float
    attempts: int
    queue_limit: int


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    timezone_name: str
    cutoff: date
    interval_minutes: int
    master_plan: str
    execution_plan: str
    bounds: Bounds

    @classmethod
    def load(cls, path: Path) -> "Campaign":
        raw = _read_json(path)
        if raw.get("schema") != CAMPAIGN_SCHEMA:
            raise CampaignError("unsupported campaign schema")
        campaign_id = raw.get("campaign_id")
        if not isinstance(campaign_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,127}", campaign_id
        ):
            raise CampaignError("invalid campaign_id")
        if raw.get("timezone") != "Europe/Berlin":
            raise CampaignError("campaign timezone must be Europe/Berlin")
        cutoff = _iso_date(raw.get("work_until_date_exclusive"), "cutoff")
        if _iso_date(raw.get("final_report_date"), "final_report_date") != cutoff:
            raise CampaignError("final report date must equal the cutoff")

        authority = raw.get("authority")
        schedule = raw.get("schedule")
        bounds = raw.get("activation_bounds")
        if not all(isinstance(item, Mapping) for item in (authority, schedule, bounds)):
            raise CampaignError("authority, schedule and activation_bounds are required")
        assert isinstance(authority, Mapping)
        assert isinstance(schedule, Mapping)
        assert isinstance(bounds, Mapping)
        if authority.get("classification") != "ALIGNED":
            raise CampaignError("campaign must be ALIGNED")
        for field in (
            "automatic_merge",
            "automatic_promotion",
            "may_mint_owner_approval",
            "may_change_gate_state",
        ):
            if authority.get(field) is not False:
                raise CampaignError(f"authority.{field} must be false")
        if schedule.get("multiple_instances") != "IgnoreNew":
            raise CampaignError("overlap policy must be IgnoreNew")
        if schedule.get("interactive_user_only") is not True:
            raise CampaignError("task must be interactive-user only")
        if schedule.get("least_privilege") is not True:
            raise CampaignError("task must use least privilege")
        master = authority.get("master_plan")
        execution = authority.get("derived_execution_plan")
        if not isinstance(master, str) or not isinstance(execution, str):
            raise CampaignError("authority plan paths must be strings")
        return cls(
            campaign_id=campaign_id,
            timezone_name="Europe/Berlin",
            cutoff=cutoff,
            interval_minutes=_integer(
                schedule.get("interval_minutes"), "interval_minutes", 1440
            ),
            master_plan=master,
            execution_plan=execution,
            bounds=Bounds(
                iterations=_integer(bounds.get("max_iterations"), "max_iterations", 20),
                wall_s=_integer(bounds.get("max_wall_clock_s"), "max_wall_clock_s", 7200),
                spend_usd=_number(bounds.get("max_spend_usd"), "max_spend_usd", 100.0),
                attempts=_integer(
                    bounds.get("max_attempts_per_candidate"),
                    "max_attempts_per_candidate",
                    10,
                ),
                queue_limit=_integer(bounds.get("queue_limit"), "queue_limit", 100),
            ),
        )


def berlin_now() -> tuple[datetime, str]:
    try:
        return datetime.now(ZoneInfo("Europe/Berlin")), "zoneinfo"
    except ZoneInfoNotFoundError:
        local = datetime.now().astimezone()
        if local.utcoffset() not in {timedelta(hours=1), timedelta(hours=2)}:
            raise CampaignError(
                "Berlin tzdata is missing and the system timezone is not Berlin-compatible"
            )
        return local, "system-local-fallback"


def _run(
    argv: Sequence[str],
    repo_root: Path,
    *,
    timeout: float = 60.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(argv),
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CampaignError(f"command did not complete: {argv[0]}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:1000]
        raise CampaignError(f"command failed ({result.returncode}): {detail}")
    return result


def _git(repo_root: Path, *args: str) -> str:
    return _run(
        ("git", "-C", str(repo_root), *args), repo_root, check=True
    ).stdout.strip()


def repo_state(repo_root: Path) -> dict[str, Any]:
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    refs = _git(
        repo_root,
        "for-each-ref",
        "--format=%(refname:short)\t%(objectname)",
        "refs/heads",
        "refs/remotes/origin",
    )
    branches = []
    for line in refs.splitlines():
        name, separator, sha = line.partition("\t")
        if separator:
            branches.append({"name": name, "sha": sha})
    return {
        "head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "branch", "--show-current") or None,
        "dirty": bool(status),
        "dirty_paths": status.splitlines()[:500],
        "branch_count": len(branches),
        "branches": branches,
        "worktrees": _git(repo_root, "worktree", "list", "--porcelain").splitlines(),
    }


def _repo_file(repo_root: Path, relative: str, label: str) -> Path:
    supplied = Path(relative)
    if supplied.is_absolute() or any(part in {".", ".."} for part in supplied.parts):
        raise CampaignError(f"{label} must be a canonical repo-relative path")
    root = repo_root.resolve()
    result = (root / supplied).resolve(strict=False)
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise CampaignError(f"{label} escapes the repository") from exc
    return result


def plan_state(repo_root: Path, campaign: Campaign) -> dict[str, Any]:
    master = _repo_file(repo_root, campaign.master_plan, "master_plan")
    execution = _repo_file(repo_root, campaign.execution_plan, "execution_plan")
    try:
        master_bytes = master.read_bytes()
        execution_bytes = execution.read_bytes()
        text = master_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CampaignError("authority documents cannot be read as UTF-8") from exc
    for marker in (
        "Status: adopted",
        "sole semantic authority",
        "## 5. The Project Twin",
        "## 10. Mandatory build and review chain",
    ):
        if marker not in text:
            raise CampaignError(f"Master Plan authority marker is missing: {marker}")
    revision = re.search(r"^Revision:\s*(\d+)\s*$", text, re.MULTILINE)
    version = re.search(r"^Version:\s*(\S+)\s*$", text, re.MULTILINE)
    gate = re.search(r"^Active delivery gate:\s*(.+?)\s*$", text, re.MULTILINE)
    if revision is None or version is None or gate is None:
        raise CampaignError("Master Plan identity fields are incomplete")
    return {
        "master_plan": master.relative_to(repo_root).as_posix(),
        "master_plan_sha256": hashlib.sha256(master_bytes).hexdigest(),
        "master_plan_revision": int(revision.group(1)),
        "master_plan_version": version.group(1),
        "active_delivery_gate": gate.group(1),
        "execution_plan": execution.relative_to(repo_root).as_posix(),
        "execution_plan_sha256": hashlib.sha256(execution_bytes).hexdigest(),
    }


def curated_queue_state(repo_root: Path) -> dict[str, Any]:
    """Describe current curated definitions and cross-run attempt convergence."""

    from daedalus.spine.picker import build_queue

    queue = build_queue(repo_root, limit=None)
    source = queue.sources.get("work_queue")
    if not isinstance(source, Mapping) or source.get("state") != "valid":
        raise CampaignError("curated work queue is unavailable or invalid")
    if source.get("policy_blocked"):
        raise CampaignError("curated work queue contains policy-blocked ready tasks")

    rows = []
    for candidate in queue.candidates:
        if candidate.source != "work_queue":
            continue
        raw_prior = candidate.evidence.get("prior_attempts_same_definition", 0)
        if type(raw_prior) is not int or raw_prior < 0:
            raise CampaignError(
                f"candidate {candidate.task_id} has invalid attempt-memory evidence"
            )
        rows.append(
            {
                "task_id": candidate.task_id,
                "score": candidate.score,
                "prior_attempts_same_definition": raw_prior,
                "attempted": raw_prior > 0,
                "target_paths": list(candidate.target_paths),
            }
        )
    unattempted = [row["task_id"] for row in rows if not row["attempted"]]
    return {
        "source": dict(source),
        "candidate_count": len(rows),
        "candidates": rows,
        "unattempted_task_ids": unattempted,
        "all_current_definitions_attempted": bool(rows) and not unattempted,
        "no_ready_candidates": not rows,
    }


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
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
    _atomic_bytes(path, data)
    return hashlib.sha256(data).hexdigest()


def _write_log(path: Path, text: str) -> dict[str, Any]:
    raw = text.encode("utf-8", "replace")
    retained = raw[:MAX_LOG_BYTES]
    _atomic_bytes(path, retained)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(retained).hexdigest(),
        "byte_length": len(retained),
        "truncated": len(raw) > len(retained),
    }


def _campaign_root(repo_root: Path, campaign: Campaign) -> Path:
    return repo_root / "runs" / "gardener" / campaign.campaign_id


def _killswitch(
    repo_root: Path, action: str, reason: str, *, force: bool = False
) -> int:
    argv = [sys.executable, "-m", "daedalus.spine.killswitch", action]
    if action == "arm" and force:
        argv.append("--force")
    if reason:
        argv.append(reason)
    return _run(argv, repo_root).returncode


def loop_argv(
    repo_root: Path,
    campaign: Campaign,
    *,
    max_iterations: int | None = None,
) -> tuple[str, ...]:
    bounds = campaign.bounds
    iterations = bounds.iterations
    if max_iterations is not None:
        if type(max_iterations) is not int or max_iterations < 1:
            raise CampaignError("max_iterations override must be a positive integer")
        iterations = min(iterations, max_iterations)
    return (
        sys.executable,
        "-m",
        "daedalus.loop",
        "--repo-root",
        str(repo_root),
        "--max-iterations",
        str(iterations),
        "--max-wall-clock-s",
        str(bounds.wall_s),
        "--max-spend-usd",
        f"{bounds.spend_usd:.2f}",
        "--max-attempts-per-candidate",
        str(bounds.attempts),
        "--queue-limit",
        str(bounds.queue_limit),
        "--json",
        "--arm",
    )


def _disable_windows_task(repo_root: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"attempted": False, "reason": "not-windows"}
    result = _run(
        ("schtasks.exe", "/Change", "/TN", FULL_TASK_NAME, "/Disable"),
        repo_root,
    )
    return {
        "attempted": True,
        "returncode": result.returncode,
        "stdout": result.stdout.strip()[:1000],
        "stderr": result.stderr.strip()[:1000],
    }


def finalize(repo_root: Path, campaign: Campaign, now: datetime, source: str) -> int:
    stop_code = _killswitch(
        repo_root,
        "stop",
        f"gardener campaign deadline reached {campaign.cutoff.isoformat()}",
    )
    report = {
        "schema": FINAL_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "berlin_time": now.isoformat(timespec="seconds"),
        "timezone_source": source,
        "cutoff": campaign.cutoff.isoformat(),
        "candidate_execution_performed": False,
        "kill_switch_stop_returncode": stop_code,
        "scheduled_task_disable": _disable_windows_task(repo_root),
        "plan": plan_state(repo_root, campaign),
        "repository": repo_state(repo_root),
        "claim_boundary": {
            "crewai_beaten": "unassessed_without_sealed_comparable_benchmark",
            "alphaevolve_beaten": "unassessed_without_directly_comparable_public_evidence",
            "automatic_merge": False,
            "automatic_promotion": False,
        },
    }
    digest = _write_json(_campaign_root(repo_root, campaign) / "final.json", report)
    print(json.dumps({**report, "report_sha256": digest}, indent=2))
    return 0 if stop_code == 0 else 2


def retain_waiting_owner(
    repo_root: Path,
    campaign: Campaign,
    now: datetime,
    source: str,
    queue_state: Mapping[str, Any],
) -> int:
    report = {
        "schema": WAITING_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "berlin_time": now.isoformat(timespec="seconds"),
        "timezone_source": source,
        "cutoff": campaign.cutoff.isoformat(),
        "candidate_execution_performed": False,
        "reason": (
            "all current task definitions have one retained attempt; waiting for "
            "owner integration or a revision-bound queue update"
            if queue_state.get("all_current_definitions_attempted")
            else "curated queue contains no ready candidates"
        ),
        "queue": dict(queue_state),
        "plan": plan_state(repo_root, campaign),
        "repository": repo_state(repo_root),
        "authority": {
            "automatic_merge": False,
            "automatic_promotion": False,
            "owner_approval_minted": False,
            "gate_state_changed": False,
        },
    }
    digest = _write_json(
        _campaign_root(repo_root, campaign) / "waiting-owner.json", report
    )
    print(json.dumps({**report, "receipt_sha256": digest}, indent=2))
    return 0


def activate(repo_root: Path, campaign_path: Path) -> int:
    campaign = Campaign.load(campaign_path)
    now, source = berlin_now()
    if now.date() >= campaign.cutoff:
        return finalize(repo_root, campaign, now, source)

    queue_state = curated_queue_state(repo_root)
    unattempted = list(queue_state["unattempted_task_ids"])
    if queue_state["all_current_definitions_attempted"] or queue_state["no_ready_candidates"]:
        return retain_waiting_owner(repo_root, campaign, now, source, queue_state)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    activation = _campaign_root(repo_root, campaign) / "activations" / stamp
    command = loop_argv(
        repo_root,
        campaign,
        max_iterations=min(campaign.bounds.iterations, len(unattempted)),
    )
    before = repo_state(repo_root)
    started = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    result = _run(
        command,
        repo_root,
        timeout=float(campaign.bounds.wall_s + 600),
    )
    receipt = {
        "schema": ACTIVATION_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "berlin_time_at_start": now.isoformat(timespec="seconds"),
        "timezone_source": source,
        "cutoff": campaign.cutoff.isoformat(),
        "candidate_execution_performed": True,
        "loop_returncode": result.returncode,
        "loop_arguments": list(command[1:]),
        "queue_before": queue_state,
        "plan": plan_state(repo_root, campaign),
        "repository_before": before,
        "repository_after": repo_state(repo_root),
        "stdout": _write_log(activation / "stdout.log", result.stdout),
        "stderr": _write_log(activation / "stderr.log", result.stderr),
        "authority": {
            "automatic_merge": False,
            "automatic_promotion": False,
            "owner_approval_minted": False,
            "gate_state_changed": False,
        },
    }
    digest = _write_json(activation / "receipt.json", receipt)
    print(json.dumps({**receipt, "receipt_sha256": digest}, indent=2))
    return result.returncode


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install(repo_root: Path, campaign_path: Path, *, force_rearm: bool) -> int:
    if os.name != "nt":
        raise CampaignError("Windows Task Scheduler installation requires Windows")
    campaign = Campaign.load(campaign_path)
    now, _ = berlin_now()
    if now.date() >= campaign.cutoff:
        raise CampaignError("campaign cutoff has already been reached")
    if _killswitch(
        repo_root,
        "arm",
        f"install gardener campaign {campaign.campaign_id}",
        force=force_rearm,
    ) != 0:
        raise CampaignError("kill switch did not arm; sticky human stop remains active")

    start = now + timedelta(minutes=2)
    cutoff = datetime.combine(campaign.cutoff, datetime.min.time(), tzinfo=now.tzinfo)
    duration = max(1, int((cutoff - start).total_seconds() // 60))
    arguments = (
        f'"{Path(__file__).resolve()}" run '
        f'--repo-root "{repo_root.resolve()}" '
        f'--campaign "{campaign_path.resolve()}"'
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps_literal(str(Path(sys.executable).resolve()))} -Argument {_ps_literal(arguments)} -WorkingDirectory {_ps_literal(str(repo_root.resolve()))}
$repeat = New-ScheduledTaskTrigger -Once -At ([datetimeoffset]{_ps_literal(start.isoformat(timespec='seconds'))}) -RepetitionInterval (New-TimeSpan -Minutes {campaign.interval_minutes}) -RepetitionDuration (New-TimeSpan -Minutes {duration})
$final = New-ScheduledTaskTrigger -Once -At ([datetimeoffset]{_ps_literal(cutoff.isoformat(timespec='seconds'))})
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds {campaign.bounds.wall_s + 600}) -MultipleInstances IgnoreNew
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath {_ps_literal(TASK_PATH)} -TaskName {_ps_literal(TASK_NAME)} -Action $action -Trigger @($repeat, $final) -Settings $settings -Principal $principal -Description 'Bounded Fourfold/Tensor gardener campaign; nomination only, never automatic merge or promotion.' -Force | Out-Null
""".strip()
    fd, name = tempfile.mkstemp(suffix=".ps1", prefix="daedalus-gardener-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(script)
        result = _run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(temporary),
            ),
            repo_root,
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if result.returncode != 0:
        raise CampaignError(
            "Task Scheduler registration failed: "
            + (result.stderr or result.stdout).strip()[:1000]
        )
    print(f"Installed {FULL_TASK_NAME}")
    print(f"First activation: {start.isoformat(timespec='seconds')}")
    print(f"Finalization: {cutoff.isoformat(timespec='seconds')}")
    print(f"Interval: {campaign.interval_minutes} minutes; overlap: IgnoreNew")
    return 0


def task_command(repo_root: Path, action: str) -> int:
    if os.name != "nt":
        raise CampaignError("Task Scheduler operation requires Windows")
    commands = {
        "start": ("schtasks.exe", "/Run", "/TN", FULL_TASK_NAME),
        "disable": ("schtasks.exe", "/Change", "/TN", FULL_TASK_NAME, "/Disable"),
        "delete": ("schtasks.exe", "/Delete", "/TN", FULL_TASK_NAME, "/F"),
        "status": (
            "schtasks.exe",
            "/Query",
            "/TN",
            FULL_TASK_NAME,
            "/V",
            "/FO",
            "LIST",
        ),
    }
    result = _run(commands[action], repo_root)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def repo_root(raw: str | None) -> Path:
    root = Path(raw).expanduser().resolve() if raw else ROOT
    if not (root / ".git").exists() or not (root / "daedalus/loop.py").is_file():
        raise CampaignError(f"not a Daedalus Git checkout: {root}")
    return root


def campaign_path(root: Path, raw: str | None) -> Path:
    path = Path(raw).expanduser().resolve() if raw else root / DEFAULT_CAMPAIGN.relative_to(ROOT)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CampaignError("campaign file must remain inside the repository") from exc
    return path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "action",
        choices=("install", "run", "run-once", "status", "start", "stop", "uninstall", "arm"),
    )
    result.add_argument("--repo-root", default=None)
    result.add_argument("--campaign", default=None)
    result.add_argument("--force-rearm", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repo_root(args.repo_root)
        spec = campaign_path(root, args.campaign)
        if args.action == "install":
            return install(root, spec, force_rearm=bool(args.force_rearm))
        if args.action in {"run", "run-once"}:
            return activate(root, spec)
        if args.action == "status":
            campaign = Campaign.load(spec)
            now, source = berlin_now()
            print(
                json.dumps(
                    {
                        "campaign_id": campaign.campaign_id,
                        "berlin_time": now.isoformat(timespec="seconds"),
                        "timezone_source": source,
                        "cutoff": campaign.cutoff.isoformat(),
                        "work_allowed_now": now.date() < campaign.cutoff,
                        "queue": curated_queue_state(root),
                        "plan": plan_state(root, campaign),
                        "repository": repo_state(root),
                    },
                    indent=2,
                )
            )
            return task_command(root, "status") if os.name == "nt" else 0
        if args.action == "start":
            return task_command(root, "start")
        if args.action == "stop":
            stop = _killswitch(root, "stop", "operator stop via gardener campaign")
            task = task_command(root, "disable") if os.name == "nt" else 0
            return 0 if stop == 0 and task == 0 else 2
        if args.action == "uninstall":
            stop = _killswitch(root, "stop", "gardener campaign uninstalled")
            task = task_command(root, "delete") if os.name == "nt" else 0
            return 0 if stop == 0 and task == 0 else 2
        if args.action == "arm":
            return _killswitch(
                root,
                "arm",
                "operator arm via gardener campaign",
                force=bool(args.force_rearm),
            )
        raise CampaignError(f"unsupported action: {args.action}")
    except CampaignError as exc:
        print(f"[gardener] REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
