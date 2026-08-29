#!/usr/bin/env python3
"""Date/queue guard for the existing continuous Daedalus scheduler.

Windows task registration remains in ``tools/continuous_daedalus.ps1``. This
module only decides whether one bounded canonical ``daedalus.loop`` activation
is still admissible. It never merges, promotes, deletes refs, installs tasks, or
creates a second picker/evaluator/ledger.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = ROOT / "docs/campaigns/FOURFOLD_TENSOR_GARDENER_20260929.json"
CAMPAIGN_SCHEMA = "daedalus-gardener-campaign/1"
ACTIVATION_SCHEMA = "daedalus-gardener-activation/1"
WAITING_SCHEMA = "daedalus-gardener-waiting-owner/1"
FINAL_SCHEMA = "daedalus-gardener-final-report/1"
MAX_LOG_BYTES = 8 * 1024 * 1024


class CampaignError(RuntimeError):
    """The campaign configuration or observed state is not safe to execute."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise CampaignError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_campaign(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"campaign cannot be read: {path}") from exc
    if not raw or len(raw) > 2 * 1024 * 1024 or not isinstance(value, dict):
        raise CampaignError("campaign shape or size is invalid")
    if value.get("schema") != CAMPAIGN_SCHEMA:
        raise CampaignError("unsupported campaign schema")
    if value.get("timezone") != "Europe/Berlin":
        raise CampaignError("campaign timezone must be Europe/Berlin")
    try:
        cutoff = datetime.strptime(
            str(value["work_until_date_exclusive"]), "%Y-%m-%d"
        ).date()
        final = datetime.strptime(str(value["final_report_date"]), "%Y-%m-%d").date()
    except (KeyError, ValueError) as exc:
        raise CampaignError("campaign cutoff dates are invalid") from exc
    if cutoff != final:
        raise CampaignError("final report date must equal the first non-working date")
    authority = value.get("authority")
    bounds = value.get("activation_bounds")
    if not isinstance(authority, Mapping) or not isinstance(bounds, Mapping):
        raise CampaignError("campaign authority and bounds are required")
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
    limits = {
        "max_iterations": (1, 20),
        "max_wall_clock_s": (60, 7200),
        "max_attempts_per_candidate": (1, 10),
        "queue_limit": (1, 100),
    }
    for field, (low, high) in limits.items():
        current = bounds.get(field)
        if type(current) is not int or not low <= current <= high:
            raise CampaignError(f"{field} must be in {low}..{high}")
    spend = bounds.get("max_spend_usd")
    if isinstance(spend, bool) or not isinstance(spend, (int, float)):
        raise CampaignError("max_spend_usd must be numeric")
    if not 0.0 < float(spend) <= 100.0:
        raise CampaignError("max_spend_usd is outside the admitted range")
    value["_cutoff"] = cutoff
    return value


def berlin_now() -> tuple[datetime, str]:
    try:
        return datetime.now(ZoneInfo("Europe/Berlin")), "zoneinfo"
    except ZoneInfoNotFoundError:
        local = datetime.now().astimezone()
        if local.utcoffset() not in {timedelta(hours=1), timedelta(hours=2)}:
            raise CampaignError("Berlin tzdata is unavailable on a non-Berlin host")
        return local, "system-local-fallback"


def _run(
    argv: Sequence[str], repo_root: Path, *, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
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


def _git(repo_root: Path, *args: str) -> str:
    result = _run(("git", "-C", str(repo_root), *args), repo_root)
    if result.returncode != 0:
        raise CampaignError((result.stderr or result.stdout).strip()[:1000])
    return result.stdout.strip()


def repository_state(repo_root: Path) -> dict[str, Any]:
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    refs = _git(
        repo_root,
        "for-each-ref",
        "--format=%(refname:short)\t%(objectname)",
        "refs/heads",
        "refs/remotes/origin",
    )
    return {
        "head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "branch", "--show-current") or None,
        "dirty": bool(status),
        "dirty_paths": status.splitlines()[:500],
        "branches": [line.split("\t", 1) for line in refs.splitlines() if "\t" in line],
        "worktrees": _git(repo_root, "worktree", "list", "--porcelain").splitlines(),
    }


def _confined(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve()
    supplied = Path(relative)
    if supplied.is_absolute() or any(part in {".", ".."} for part in supplied.parts):
        raise CampaignError(f"non-canonical repo path: {relative}")
    result = (root / supplied).resolve(strict=False)
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise CampaignError(f"path escapes repository: {relative}") from exc
    return result


def plan_state(repo_root: Path, campaign: Mapping[str, Any]) -> dict[str, Any]:
    authority = campaign["authority"]
    master = _confined(repo_root, str(authority["master_plan"]))
    execution = _confined(repo_root, str(authority["derived_execution_plan"]))
    try:
        master_bytes = master.read_bytes()
        execution_bytes = execution.read_bytes()
        text = master_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CampaignError("authority documents cannot be read") from exc
    for marker in (
        "Status: adopted",
        "sole semantic authority",
        "## 5. The Project Twin",
        "## 10. Mandatory build and review chain",
    ):
        if marker not in text:
            raise CampaignError(f"Master Plan marker is missing: {marker}")
    revision = re.search(r"^Revision:\s*(\d+)\s*$", text, re.MULTILINE)
    version = re.search(r"^Version:\s*(\S+)\s*$", text, re.MULTILINE)
    gate = re.search(r"^Active delivery gate:\s*(.+?)\s*$", text, re.MULTILINE)
    if revision is None or version is None or gate is None:
        raise CampaignError("Master Plan identity is incomplete")
    return {
        "master_plan_sha256": hashlib.sha256(master_bytes).hexdigest(),
        "master_plan_revision": int(revision.group(1)),
        "master_plan_version": version.group(1),
        "active_delivery_gate": gate.group(1),
        "execution_plan_sha256": hashlib.sha256(execution_bytes).hexdigest(),
    }


def curated_queue_state(repo_root: Path) -> dict[str, Any]:
    from daedalus.spine.picker import build_queue

    queue = build_queue(repo_root, limit=None)
    source = queue.sources.get("work_queue")
    if not isinstance(source, Mapping) or source.get("state") != "valid":
        raise CampaignError("curated work queue is unavailable or invalid")
    if source.get("policy_blocked"):
        raise CampaignError("curated work queue contains policy-blocked tasks")
    candidates = []
    for item in queue.candidates:
        if item.source != "work_queue":
            continue
        prior = item.evidence.get("prior_attempts_same_definition", 0)
        if type(prior) is not int or prior < 0:
            raise CampaignError(f"invalid attempt memory for {item.task_id}")
        candidates.append(
            {
                "task_id": item.task_id,
                "definition_attempts": prior,
                "attempted": prior > 0,
                "target_paths": list(item.target_paths),
            }
        )
    pending = [row["task_id"] for row in candidates if not row["attempted"]]
    return {
        "source": dict(source),
        "candidates": candidates,
        "pending_task_ids": pending,
        "converged": bool(candidates) and not pending,
        "no_ready_candidates": not candidates,
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
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
    return hashlib.sha256(data).hexdigest()


def _campaign_root(repo_root: Path, campaign: Mapping[str, Any]) -> Path:
    return repo_root / "runs" / "gardener" / str(campaign["campaign_id"])


def _stop(repo_root: Path, reason: str) -> int:
    return _run(
        (sys.executable, "-m", "daedalus.spine.killswitch", "stop", reason),
        repo_root,
    ).returncode


def loop_argv(
    repo_root: Path, campaign: Mapping[str, Any], pending_count: int
) -> tuple[str, ...]:
    bounds = campaign["activation_bounds"]
    iterations = min(int(bounds["max_iterations"]), pending_count)
    if iterations < 1:
        raise CampaignError("loop requires at least one pending task")
    return (
        sys.executable,
        "-m",
        "daedalus.loop",
        "--repo-root",
        str(repo_root),
        "--max-iterations",
        str(iterations),
        "--max-wall-clock-s",
        str(bounds["max_wall_clock_s"]),
        "--max-spend-usd",
        f"{float(bounds['max_spend_usd']):.2f}",
        "--max-attempts-per-candidate",
        str(bounds["max_attempts_per_candidate"]),
        "--queue-limit",
        str(bounds["queue_limit"]),
        "--json",
        "--arm",
    )


def run_campaign(repo_root: Path, campaign_path: Path) -> int:
    campaign = load_campaign(campaign_path)
    now, timezone_source = berlin_now()
    common = {
        "campaign_id": campaign["campaign_id"],
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "berlin_time": now.isoformat(timespec="seconds"),
        "timezone_source": timezone_source,
        "cutoff": campaign["work_until_date_exclusive"],
        "plan": plan_state(repo_root, campaign),
        "repository": repository_state(repo_root),
    }
    root = _campaign_root(repo_root, campaign)
    if now.date() >= campaign["_cutoff"]:
        receipt = {
            **common,
            "schema": FINAL_SCHEMA,
            "candidate_execution_performed": False,
            "kill_switch_stop_returncode": _stop(
                repo_root, "Fourfold/Tensor gardener deadline reached"
            ),
            "claim_boundary": {
                "crewai_beaten": "unassessed_without_comparable_benchmark",
                "alphaevolve_beaten": "unassessed_without_comparable_public_evidence",
                "automatic_merge": False,
                "automatic_promotion": False,
            },
        }
        digest = _atomic_json(root / "final.json", receipt)
        print(json.dumps({**receipt, "receipt_sha256": digest}, indent=2))
        return 0

    queue = curated_queue_state(repo_root)
    if queue["converged"] or queue["no_ready_candidates"]:
        receipt = {
            **common,
            "schema": WAITING_SCHEMA,
            "candidate_execution_performed": False,
            "queue": queue,
            "reason": (
                "current task definitions were attempted; waiting for owner integration "
                "or a revision-bound queue update"
                if queue["converged"]
                else "curated queue contains no ready candidate"
            ),
        }
        digest = _atomic_json(root / "waiting-owner.json", receipt)
        print(json.dumps({**receipt, "receipt_sha256": digest}, indent=2))
        return 0

    argv = loop_argv(repo_root, campaign, len(queue["pending_task_ids"]))
    result = _run(
        argv,
        repo_root,
        timeout=float(campaign["activation_bounds"]["max_wall_clock_s"] + 600),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    activation = root / "activations" / stamp
    stdout = result.stdout.encode("utf-8", "replace")[:MAX_LOG_BYTES]
    stderr = result.stderr.encode("utf-8", "replace")[:MAX_LOG_BYTES]
    activation.mkdir(parents=True, exist_ok=True)
    (activation / "stdout.log").write_bytes(stdout)
    (activation / "stderr.log").write_bytes(stderr)
    receipt = {
        **common,
        "schema": ACTIVATION_SCHEMA,
        "candidate_execution_performed": True,
        "queue_before": queue,
        "loop_returncode": result.returncode,
        "loop_arguments": list(argv[1:]),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "authority": {
            "automatic_merge": False,
            "automatic_promotion": False,
            "owner_approval_minted": False,
            "gate_state_changed": False,
        },
    }
    digest = _atomic_json(activation / "receipt.json", receipt)
    print(json.dumps({**receipt, "receipt_sha256": digest}, indent=2))
    return result.returncode


def _root(value: str | None) -> Path:
    root = Path(value).expanduser().resolve() if value else ROOT
    if not (root / ".git").exists() or not (root / "daedalus/loop.py").is_file():
        raise CampaignError(f"not a Daedalus checkout: {root}")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "status"))
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--campaign", default=str(DEFAULT_CAMPAIGN))
    args = parser.parse_args(argv)
    try:
        root = _root(args.repo_root)
        campaign_path = _confined(root, str(Path(args.campaign).resolve().relative_to(root)))
        if args.action == "run":
            return run_campaign(root, campaign_path)
        campaign = load_campaign(campaign_path)
        now, source = berlin_now()
        print(
            json.dumps(
                {
                    "campaign_id": campaign["campaign_id"],
                    "berlin_time": now.isoformat(timespec="seconds"),
                    "timezone_source": source,
                    "work_allowed": now.date() < campaign["_cutoff"],
                    "queue": curated_queue_state(root),
                    "plan": plan_state(root, campaign),
                    "repository": repository_state(root),
                },
                indent=2,
            )
        )
        return 0
    except (CampaignError, ValueError) as exc:
        print(f"[gardener] REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
