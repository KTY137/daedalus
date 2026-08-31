from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import metrics
from .claude_detect import detect_claude_crew
from .projects import PROJECT_DIR, list_projects, load_project, resolve_repo_root
from .providers import provider_health as _provider_health
from .router import load_agents
from .status import collect_status

ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "runs" / "processed"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

DEFAULT_SQUADS: dict[str, list[str]] = {
    "Core": ["generalist-dev", "reviewer", "qa-critic"],
    "UI": ["ui-ux-dev"],
    "Hardware": ["hardware-dev", "acquisition-dev"],
    "Docs": ["docs-dev"],
    "QA": ["qa-critic", "reviewer", "tests-dev"],
    "Research": ["researcher", "data-analysis-dev"],
}

SUGGESTED_MODELS = [
    {
        "name": "qwen2.5-coder:7b",
        "reason": "Current default local coding worker; good small-footprint baseline.",
        "command": "ollama pull qwen2.5-coder:7b",
    },
    {
        "name": "nomic-embed-text",
        "reason": "Useful for semantic routing and future memory search.",
        "command": "ollama pull nomic-embed-text",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(project: str | None, **payload: Any) -> dict[str, Any]:
    warnings = payload.pop("warnings", [])
    return {"ok": True, "generated_at": now_iso(), "project": project, "warnings": warnings, **payload}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _gb(n: int | float | None) -> float:
    return round(float(n or 0) / (1024 ** 3), 2)


def _safe_load_project(project: str | None) -> tuple[dict[str, Any], str]:
    """Load project config; degrade to {} + a warning instead of raising when the
    project is unknown or its config is malformed."""
    if not project:
        return {}, ""
    try:
        return load_project(project), ""
    except ValueError as exc:
        return {}, str(exc)


def _safe_collect_status(repo_root: str) -> tuple[dict[str, Any], str]:
    """Wrap status.collect_status: it shells out to git with `cwd=repo_root`
    (OSError when git is absent/repo_root missing) and also reads
    memory/events.jsonl via load_events, which can raise JSONDecodeError (a
    ValueError) on a truncated/concurrent line. Degrade on any of these."""
    if not repo_root:
        return {}, ""
    try:
        return collect_status(repo_root), ""
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"repo_root": repo_root}, f"Unable to read repo status for '{repo_root}': {exc}"


def team_config(project: str | None) -> dict[str, Any]:
    pdata, _ = _safe_load_project(project)
    team = pdata.get("team") or {}
    return {
        "max_workers": int(team.get("max_workers", 3) or 3),
        "default_lane": team.get("default_lane", "local_only"),
        "active_agents": [str(a) for a in team.get("active_agents", []) if str(a).strip()],
        "squads": team.get("squads") or DEFAULT_SQUADS,
        "model_assignments": team.get("model_assignments") or {},
        "semi_auto": team.get("semi_auto") or {
            "auto_review": True,
            "auto_docs": True,
            "auto_tests": False,
            "never_auto_write": True,
        },
    }


def provider_health(project: str | None = None) -> dict[str, Any]:
    rows = _provider_health()
    warnings = []
    if not any(row["name"] == "ollama" and row["available"] for row in rows):
        warnings.append("Ollama is not fully available; local bench work may fail.")
    if not any(row["name"] == "claude_cli" and row["available"] for row in rows):
        warnings.append("Claude CLI is not on PATH; Claude lane may be unavailable.")
    return envelope(project, providers=rows, warnings=warnings)


def model_resources(project: str | None = None, base_url: str = DEFAULT_OLLAMA) -> dict[str, Any]:
    cli = shutil.which("ollama")
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        server_ready = True
        error = ""
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        payload = {"models": []}
        server_ready = False
        error = str(exc)

    models = []
    total = 0
    for m in payload.get("models", []):
        size = int(m.get("size") or 0)
        total += size
        details = m.get("details") or {}
        models.append({
            "name": m.get("name") or m.get("model") or "",
            "model": m.get("model") or m.get("name") or "",
            "size_bytes": size,
            "size_gb": _gb(size),
            "parameter_size": details.get("parameter_size", ""),
            "quantization": details.get("quantization_level", ""),
            "context_length": details.get("context_length"),
            "capabilities": m.get("capabilities") or [],
            "modified_at": m.get("modified_at", ""),
        })

    usage = shutil.disk_usage(Path.home().anchor or Path.home())
    largest = max((m["size_bytes"] for m in models), default=0)
    worker_cap = max(1, min(8, int(usage.free // max(largest * 2, 1)))) if largest else 1
    warnings = []
    if not server_ready:
        warnings.append("Ollama server is offline or unreachable.")
    if not cli:
        warnings.append("Ollama CLI is not on PATH; model management commands must be run manually.")
    return envelope(
        project,
        ollama_cli_on_path=bool(cli),
        ollama_cli=cli or "",
        server_ready=server_ready,
        error=error,
        models=models,
        total_size_bytes=total,
        total_size_gb=_gb(total),
        disk={
            "root": Path.home().anchor or str(Path.home()),
            "free_bytes": usage.free,
            "free_gb": _gb(usage.free),
            "used_gb": _gb(usage.used),
            "total_gb": _gb(usage.total),
        },
        safe_parallel_workers_estimate=worker_cap,
        safe_parallel_workers_note=(
            "Disk-based estimate only — does not account for RAM/VRAM headroom, "
            "so it is not a safe hard concurrency ceiling."
        ),
        capabilities_note=(
            "Capability flags are declared by the model card, not verified. Small "
            "local coder models often fail to emit real tool calls; the full-file-"
            "rewrite path is the reliable write mechanism."
        ),
        suggested=SUGGESTED_MODELS,
        warnings=warnings,
    )


def _process_rows() -> list[dict[str, Any]]:
    if platform.system().lower() == "windows":
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"name like 'python%'\" | "
                    "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
                ],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            raw = completed.stdout.strip()
            if not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            return [{"pid": int(r.get("ProcessId") or 0), "command": str(r.get("CommandLine") or "")} for r in data]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            return []
    try:
        completed = subprocess.run(["ps", "-eo", "pid=,command="], text=True, capture_output=True, timeout=10, check=False)
        rows = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                rows.append({"pid": int(parts[0]), "command": parts[1]})
        return rows
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def watcher_status(project: str | None = None) -> dict[str, Any]:
    expected_repo = ""
    if project:
        try:
            expected_repo = str(load_project(project).get("repo_root", ""))
        except ValueError:
            expected_repo = ""
    watchers = []
    for row in _process_rows():
        cmd = row["command"]
        if "daedalus.file_bridge" not in cmd or "watch" not in cmd:
            continue
        stale = bool("--repo-root" in cmd and project and "--project" not in cmd)
        if expected_repo and expected_repo not in cmd and f"--project {project}" not in cmd:
            stale = True
        watchers.append({"pid": row["pid"], "command": cmd, "stale": stale})
    warnings = ["Stale watcher process detected. Stop it before queueing more work."] if any(w["stale"] for w in watchers) else []
    return envelope(
        project,
        running=bool(watchers),
        watchers=watchers,
        stale_count=sum(1 for w in watchers if w["stale"]),
        warnings=warnings,
    )


def _inner_local_summary(payload: dict[str, Any]) -> str:
    assignments = ((payload.get("result") or {}).get("assignments") or [])
    summaries = []
    for assignment in assignments:
        report = ((assignment.get("result") or {}).get("report") or {})
        if report.get("summary"):
            summaries.append(str(report["summary"]))
    return " ".join(summaries)[:300]


def _file_item(path: Path, kind: str) -> dict[str, Any]:
    payload = _read_json(path) if path.suffix == ".json" or path.name.endswith(".report.json") else {}
    summary = ((payload.get("report") or {}).get("summary") or _inner_local_summary(payload) or payload.get("error") or "")[:300]
    return {
        "kind": kind,
        "name": path.name,
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else "",
        "status": payload.get("bridge_status") or payload.get("status") or "",
        "lane": payload.get("lane") or (payload.get("request") or {}).get("lane") or "",
        "agent": payload.get("agent") or "",
        "summary": summary,
        "error": str(payload.get("error") or ""),
    }


def get_queue(project: str | None = None, limit: int = 30) -> dict[str, Any]:
    OUTBOX.mkdir(exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    pending = [_file_item(p, "pending") for p in sorted(OUTBOX.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]]
    reports = [_file_item(p, "report") for p in sorted(INBOX.glob("*.report.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]]
    processed = [_file_item(p, "processed") for p in sorted(ARCHIVE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]]
    latest_failed = next((r for r in reports if r["status"] == "failed" or r["error"]), None)
    warnings = []
    if latest_failed:
        warnings.append("Latest failed report needs review or rerun.")
    for report in reports[:5]:
        if report["status"] == "done" and not report["summary"]:
            warnings.append(f"Report {report['name']} has an empty summary.")
            break
    return envelope(project, pending=pending, reports=reports, processed=processed, latest_failed=latest_failed, warnings=warnings)


def get_squads(project: str | None = None) -> dict[str, Any]:
    pdata, load_warning = _safe_load_project(project)
    team = team_config(project)
    active = set(team["active_agents"])
    try:
        agents = load_agents(pdata.get("repo_root") if pdata else None)
    except (OSError, ValueError, json.JSONDecodeError):
        agents = []
    agent_by_name = {a.get("name"): a for a in agents}
    squad_rows = []
    for name, members in team["squads"].items():
        rows = []
        for member in members:
            a = agent_by_name.get(member, {"name": member})
            rows.append({
                "name": member,
                "call_name": a.get("call_name", ""),
                "model_tier": a.get("model_tier", ""),
                "external_ok": bool(a.get("external_ok", False)),
                "active": member in active if active else True,
                "assigned_model": team["model_assignments"].get(member, ""),
            })
        squad_rows.append({"name": name, "agents": rows})
    warnings = [load_warning] if load_warning else []
    return envelope(
        project,
        max_workers=team["max_workers"],
        default_lane=team["default_lane"],
        active_agents=team["active_agents"] or [a.get("name") for a in agents],
        model_assignments=team["model_assignments"],
        semi_auto=team["semi_auto"],
        squads=squad_rows,
        warnings=warnings,
    )


def enforcement_status(repo_root: str) -> dict[str, Any]:
    root = Path(repo_root)
    agents_md = root / "AGENTS.md"
    claude_md = root / "CLAUDE.md"
    state = root / ".agentenv" / "enforcement.json"

    def managed(p: Path) -> bool:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return False
        return "AGENT_ENV_ENFORCED:BEGIN" in text and "AGENT_ENV_ENFORCED:END" in text

    return {
        "enabled": managed(agents_md) and managed(claude_md) and state.exists(),
        "agents_md": managed(agents_md),
        "claude_md": managed(claude_md),
        "state_file": state.exists(),
    }


def _probe_local_only_fail_closed() -> bool:
    """Actually exercise the local_only branch (no bench) and confirm it does
    not reach Claude. Side-effect-free: _try_ikarus is stubbed out, so no
    doctor/network call happens."""
    # NOTE: not re-entrant — swaps a module global. Safe today because each
    # `dashboard --json` runs in its own subprocess; add a lock before reuse
    # in any long-lived/threaded process.
    g = globals()
    saved = g["_try_ikarus"]
    try:
        g["_try_ikarus"] = lambda payload, **_kwargs: None
        r = process_bridge_payload(
            {"lane": "local_only", "objective": "__gate_selftest__", "repo_root": "", "paths": [], "model": ""}
        )
        return r.get("lane") != "claude" and r.get("bridge_status") == "failed"
    except Exception:
        return False
    finally:
        g["_try_ikarus"] = saved


def _probe_schema_rejects_empty_summary() -> bool:
    """Confirm the schema gate rejects an empty summary — and that the summary
    rule itself is doing the rejecting, not merely other missing keys. Build an
    otherwise-valid report, verify it validates clean, then flip only summary."""
    try:
        from . import schemas

        valid = {"status": "done", "summary": "ok", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        validates_clean = schemas.validate_report(valid) == []
        rejects_empty = any("summary" in e for e in schemas.validate_report({**valid, "summary": ""}))
        return validates_clean and rejects_empty
    except Exception:
        return False


def get_quality(project: str | None = None) -> dict[str, Any]:
    watcher = watcher_status(project)
    m = metrics.summary()
    schema_gate = _probe_schema_rejects_empty_summary()
    local_only_gate = _probe_local_only_fail_closed()
    warnings = []
    if watcher["stale_count"]:
        warnings.append("Stale watcher detected.")
    if m.get("alarm"):
        warnings.append("Fallback-rate alarm is active.")
    if not local_only_gate:
        warnings.append("SAFETY: local_only fail-closed guard did not verify — investigate before queueing.")
    if not schema_gate:
        warnings.append("SAFETY: empty-report schema gate did not verify.")
    return envelope(
        project,
        schema_non_empty_summary=schema_gate,
        local_only_never_claude=local_only_gate,
        empty_reports_fail=schema_gate,
        stale_watchers=watcher["stale_count"],
        fallback_alarm=bool(m.get("alarm")),
        fallback_rate=m.get("fallback_rate", 0),
        recommendation="Use local_only until Claude quota recovers." if watcher["stale_count"] else "",
        warnings=warnings,
    )


def routing_summary(project: str | None, watcher: dict[str, Any], models: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    team = team_config(project)
    selected = team["default_lane"]
    if selected == "local_only":
        return {"selected_lane": selected, "recommended_lane": "local_only", "reason": "Project default is local_only."}
    if watcher.get("stale_count"):
        return {"selected_lane": selected, "recommended_lane": "local_only", "reason": "Stale watcher detected; avoid fallback ambiguity."}
    if quality.get("fallback_alarm"):
        return {"selected_lane": selected, "recommended_lane": "local_only", "reason": "Fallback alarm is active."}
    if models.get("server_ready"):
        return {"selected_lane": selected, "recommended_lane": selected, "reason": "Configured lane is compatible with current provider health."}
    return {
        "selected_lane": selected,
        "recommended_lane": "local_only",
        "reason": (
            "Ollama is unavailable; direct external fallback is disabled until "
            "the queue caller has canonical broker authority."
        ),
    }


# --------------------------------------------------------------------------- #
# governance: may this system promote anything right now, and WHY NOT?         #
# --------------------------------------------------------------------------- #
# Three mechanisms landed in this repo that no surface could show. An operator
# looking at any screen could not answer the one question that decides whether
# a candidate patch may be trusted. This block is that answer, and it is
# deliberately built to be UNABLE to say "green" by accident:
#
#   * Every gate carries one of FIVE states -- working / present / degraded /
#     absent / unknown -- and the aggregate is the WORST of them, never an
#     average and never a majority vote.
#   * Every value carries a provenance label (MEASURED / INHERITED / ASSUMED).
#     A receipt read off disk is INHERITED, not MEASURED, because it was
#     measured against a revision that may no longer be this one.
#   * The default for "I could not tell" is `unknown`, which renders as the
#     word "unknown" to the user. It is never coerced to a zero or a tick.
#
# `promotion_allowed` here is DERIVED from spine.bootstrap.gate_discrimination
# and nothing else, so this surface cannot drift into permitting something the
# shadow runner would refuse. tests/test_ui_governance.py pins that agreement.

GOVERNANCE_STATES = ("working", "present", "degraded", "absent", "unknown")
# Worst-first. Aggregation takes the minimum position in this order.
_GOVERNANCE_SEVERITY = ("unknown", "absent", "degraded", "present", "working")

# A path that is deliberately outside this repo's `write_allow` and is NOT on
# any generic denylist, so a block can only come from the confinement itself.
_CONFINEMENT_PROBE_DENIED = "z_governance_probe/probe.py"


def _worst_state(states: list[str]) -> str:
    """The aggregate is the WORST gate, never the average.

    Two working gates and one absent gate is an absent system. Averaging is how
    a dashboard turns a missing measurement into a passing grade.
    """
    if not states:
        return "unknown"
    return min(states, key=lambda s: _GOVERNANCE_SEVERITY.index(s)
               if s in _GOVERNANCE_SEVERITY else 0)


def _head_sha_safe(repo_root: str) -> str | None:
    if not repo_root:
        return None
    try:
        from .spine.picker import _head_sha

        return _head_sha(repo_root)
    except Exception:                            # noqa: BLE001
        return None


def _gov_discrimination(repo_root: str, head: str | None, *,
                        expected_gate: Mapping[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Has THIS candidate gate been shown to separate good patches from bad?

    A global boolean cannot safely authorise heterogeneous gates.  When no
    ``expected_gate`` is supplied this surface still reports the receipt, but
    promotion remains refused because no exact argv/scope/path binding was
    made.
    """
    gate = {
        "id": "discrimination",
        "question": "Has the test gate been shown to catch planted defects at THIS revision?",
        "state": "unknown",
        "headline": "could not be evaluated",
        "provenance": "ASSUMED",
        "detail": None,
    }
    if not repo_root:
        gate["headline"] = ("no repo_root is configured for this project, so no "
                            "receipt can be located")
        return gate
    try:
        from .spine.bootstrap import (DISCRIMINATION_REL_PATH, KILL_RATE_FLOOR,
                                      gate_discrimination)
    except Exception as e:                       # noqa: BLE001
        gate["headline"] = f"the discrimination module is unavailable ({type(e).__name__})"
        return gate
    receipt = Path(repo_root) / DISCRIMINATION_REL_PATH
    try:
        gd = gate_discrimination(
            repo_root, head=head, expected_gate=expected_gate,
            require_gate_binding=True)
    except Exception as e:                       # noqa: BLE001
        gate["headline"] = f"the discrimination gate raised {type(e).__name__}"
        return gate
    gate["detail"] = gd.to_dict()
    gate["reason"] = gd.reason
    gate["kill_rate_floor"] = KILL_RATE_FLOOR
    gate["receipt_path"] = DISCRIMINATION_REL_PATH
    if gd.proven:
        # MEASURED, and only here: proven means the receipt was tied to THIS
        # revision, so the number describes the tree in front of the operator.
        gate.update(state="working", provenance="MEASURED",
                    headline=gd.reason)
        return gate
    if not receipt.exists():
        gate.update(state="absent", provenance="MEASURED",
                    headline="no discrimination measurement exists at all, so a "
                             "green suite means only that pytest ran")
        return gate
    # A receipt exists and was refused. INHERITED: the number on disk was
    # measured, but against a tree that is not necessarily this one.
    gate.update(state="degraded", provenance="INHERITED", headline=gd.reason)
    return gate


def _gov_write_confinement(repo_root: str, project: str | None) -> dict[str, Any]:
    """Is the local write lane confined to a declared allow-list?

    This gate is MEASURED, not inspected. Reading `write_allow` out of the
    config proves only that somebody typed it; the repo learned that lesson the
    expensive way when a prose policy claimed to deny 12 paths and 8 of them
    were writable. So the check actually calls the predicate that guards live
    writes and confirms it refuses a path outside the list.

    Takes a project NAME rather than a pre-loaded config dict, deliberately:
    the whole point is to resolve the policy through the same call the live
    write path makes, and a caller that hands in an already-resolved dict can
    hand in one the write path would never have chosen.
    """
    gate = {
        "id": "write_confinement",
        "question": "Is the local write lane confined to a declared allow-list?",
        "state": "unknown",
        "headline": "could not be evaluated",
        "provenance": "ASSUMED",
        "write_allow": [],
        "detail": None,
    }
    try:
        from .sensitivity import load_policy, path_write_blocked
    except Exception as e:                       # noqa: BLE001
        gate["headline"] = f"the policy module is unavailable ({type(e).__name__})"
        return gate
    # ASK THE REAL RESOLVER; DO NOT RE-DERIVE THE POLICY HERE.
    #
    # This gate previously read the raw registry file and diffed it against the
    # raw repo-local file itself. That was wrong twice over. It reimplemented a
    # safety decision the safety core owns, and -- MEASURED -- it kept reporting
    # `degraded` for a bypass that commit 8e48783 had already CLOSED, because
    # the merge that closes it happens inside `config.resolve_project` and this
    # code never called it. A surface that cries degraded after the defect is
    # fixed teaches operators to ignore it, which is the same failure mode as a
    # control that always passes.
    #
    # So: resolve exactly the way the live write path does. `offload` does
    #     pdata = resolve_project(repo_root, project)
    #     pol   = load_policy(pdata) if pdata and pdata.get("policy") else None
    # and this mirrors it, with the SAME project name the operator is asking
    # about. Whatever the safety core decides about precedence, this gate now
    # inherits automatically instead of holding a stale second opinion.
    cfg = None
    repo_local = None
    if repo_root:
        try:
            from .config import resolve_project

            cfg = resolve_project(repo_root, project)
            # Still read the repo-local file separately, but ONLY to detect a
            # genuine disagreement below -- never to second-guess precedence.
            repo_local = resolve_project(repo_root, None)
        except Exception as e:                   # noqa: BLE001
            gate["headline"] = f"the project policy could not be resolved ({type(e).__name__})"
            return gate
    if not (cfg and cfg.get("policy")):
        cfg = repo_local or cfg
    if not (cfg and cfg.get("policy")):
        gate.update(state="absent", provenance="MEASURED",
                    headline="no policy is installed for this project, so the "
                             "local write lane is UNCONFINED")
        return gate
    try:
        pol = load_policy(cfg)
    except Exception as e:                       # noqa: BLE001
        gate["headline"] = f"the policy could not be parsed ({type(e).__name__})"
        return gate
    allow = list(pol.write_allow)
    gate["write_allow"] = allow
    gate["high_risk_paths"] = list(getattr(pol, "high_risk_path_substrings", ()))[:40]
    # THE PART OF THE OLD CHECK THAT IS STILL MEANINGFUL. The specific
    # "registry silently unconfines" case is closed (8e48783 intersects the
    # repo-local write_allow into the named entry). But two policy sources can
    # still disagree for other reasons, and a confinement that is WIDER for a
    # named project than for an unnamed one would be the same class of hole.
    # So the invariant is checked directly, against resolved policies:
    # naming a project must never grant MORE write permission than not naming
    # one. This is stated as a property, not as a diff of two files, so it
    # keeps holding however the safety core chooses to merge them.
    try:
        if project and repo_local is not None and cfg is not repo_local:
            local_allow = set(load_policy(repo_local).write_allow)
            named_allow = set(allow)
            widened = named_allow - local_allow if local_allow else set()
            if local_allow and widened:
                gate.update(
                    state="degraded", provenance="MEASURED",
                    headline=("naming this project WIDENS the write lane: "
                              + ", ".join(sorted(widened)) + " is writable under "
                              "--project " + str(project) + " but not under the "
                              "repo-local policy. Naming a project must never "
                              "grant more permission than not naming one."),
                    detail={"named_write_allow": sorted(named_allow),
                            "repo_local_write_allow": sorted(local_allow),
                            "widened_by_naming": sorted(widened)})
                return gate
    except Exception:                            # noqa: BLE001 - advisory only
        pass
    if not allow:
        gate.update(state="absent", provenance="MEASURED",
                    headline="a policy is installed but declares no write_allow, "
                             "so the local write lane is UNCONFINED -- the "
                             "egress allow-list does NOT gate writes")
        return gate
    # The live probe. Anything outside the list must be refused by the same
    # predicate that guards a real write.
    try:
        denied_blocked = bool(path_write_blocked(_CONFINEMENT_PROBE_DENIED, pol))
        entry = allow[0]
        permitted = entry + "z_governance_probe.md" if entry.endswith("/") else entry
        permitted_blocked = bool(path_write_blocked(permitted, pol))
    except Exception as e:                       # noqa: BLE001
        gate["headline"] = f"the confinement probe raised {type(e).__name__}"
        return gate
    gate["detail"] = {
        "probe_outside_allow": _CONFINEMENT_PROBE_DENIED,
        "probe_outside_allow_blocked": denied_blocked,
        "probe_inside_allow": permitted,
        "probe_inside_allow_blocked": permitted_blocked,
    }
    if not denied_blocked:
        gate.update(state="degraded", provenance="MEASURED",
                    headline=(f"write_allow declares {len(allow)} entr"
                              f"{'y' if len(allow) == 1 else 'ies'} but a path "
                              f"outside it was still writable -- the confinement "
                              f"does not hold"))
        return gate
    if permitted_blocked:
        # Confinement holds, but it is narrower than declared: an entry that
        # permits nothing reads as "I allowed this" while allowing nothing.
        gate.update(state="degraded", provenance="MEASURED",
                    headline=(f"writes are confined, but the declared entry "
                              f"{entry!r} is itself blocked -- the allow-list is "
                              f"narrower than it claims"))
        return gate
    gate.update(state="working", provenance="MEASURED",
                headline=("writes are confined to " + ", ".join(allow)
                          + " -- verified by probing the live write predicate"))
    return gate


def _gov_operability_drill(repo_root: str, head: str | None) -> dict[str, Any]:
    """Was every operability control tripped end-to-end, at this revision?"""
    gate = {
        "id": "operability_drill",
        "question": "Was every operability control tripped end-to-end at THIS revision?",
        "state": "unknown",
        "headline": "could not be evaluated",
        "provenance": "ASSUMED",
        "controls": [],
        "detail": None,
    }
    rel = "runs/spine/operability_drill.json"
    gate["receipt_path"] = rel
    if not repo_root:
        gate["headline"] = "no repo_root is configured, so no drill receipt can be located"
        return gate
    path = Path(repo_root) / rel
    if not path.exists():
        gate.update(state="absent", provenance="MEASURED",
                    headline="the operability drill has never been run in this "
                             "checkout, so no control is known to hold")
        return gate
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        gate["headline"] = f"the drill receipt is unreadable ({type(e).__name__})"
        return gate
    if not isinstance(doc, dict):
        gate["headline"] = "the drill receipt is not an object"
        return gate
    measured_head = str(doc.get("head") or "").strip() or None
    passed, failed = doc.get("passed"), doc.get("failed")
    incomplete = doc.get("incomplete")
    defensible = bool(doc.get("scheduling_defensible"))
    controls = doc.get("controls")
    if isinstance(controls, list):
        # Bounded on purpose: this payload rides along with every dashboard
        # poll. Names and effects, never the telemetry blobs.
        gate["controls"] = [
            {"name": str(c.get("name") or "")[:120],
             "status": str(c.get("status") or "UNKNOWN")[:20],
             "effect": str(c.get("effect") or "")[:240]}
            for c in controls if isinstance(c, dict)
        ][:40]
    gate["detail"] = {"head": measured_head, "passed": passed, "failed": failed,
                      "incomplete": incomplete,
                      "scheduling_defensible": defensible,
                      "measured_at": doc.get("measured_at")}
    stale = bool(head and measured_head and not head.startswith(measured_head[:12]))
    if stale:
        gate.update(state="degraded", provenance="INHERITED",
                    headline=(f"the last drill ran at {measured_head[:12]}, but "
                              f"HEAD is {head[:12]} -- these controls were shown "
                              f"to hold on a tree that is not this one"))
        return gate
    if not measured_head:
        gate.update(state="degraded", provenance="INHERITED",
                    headline="the drill receipt records no revision, so it cannot "
                            "be tied to this tree")
        return gate
    if failed:
        gate.update(state="degraded", provenance="INHERITED",
                    headline=f"{failed} operability control(s) did not hold")
        return gate
    if incomplete:
        # "skipped" is never "pass".
        gate.update(state="present", provenance="INHERITED",
                    headline=(f"{incomplete} control(s) could not be exercised, so "
                              f"the drill is INCOMPLETE, not passing"))
        return gate
    if defensible:
        gate.update(state="working", provenance="INHERITED",
                    headline=f"all {passed} operability controls were tripped and held")
        return gate
    gate.update(state="degraded", provenance="INHERITED",
                headline="the drill did not declare scheduling defensible")
    return gate


def get_governance(project: str | None = None, *,
                   expected_gate: Mapping[str, Any] | None = None
                   ) -> dict[str, Any]:
    """May this system promote anything right now, and why not?

    One payload, one shape, consumed identically by the HTTP API, the VS Code
    Mission Control webview and the web app. Adding a consumer must not add a
    second opinion, which is why this is computed here and not in any surface.
    """
    # RESOLVED THE SAME WAY get_dashboard RESOLVES IT, and that is not a
    # cosmetic detail. The first version took `project` literally while the
    # dashboard defaulted to the first registered project, so /api/governance
    # and dashboard["governance"] answered about DIFFERENT REPOSITORIES and
    # disagreed about whether writes were confined -- one said `degraded`, the
    # other `absent`, for the same machine at the same instant. Two surfaces,
    # two answers, which is the exact defect this whole payload exists to stop.
    # tests/test_ui_governance.py caught it and now pins it.
    try:
        names = list_projects()
    except OSError:
        names = []
    selected = project or (names[0] if names else None)
    pdata, load_warning = _safe_load_project(selected)
    repo_root = str(pdata.get("repo_root", "")) if pdata else ""
    if not repo_root:
        try:
            repo_root = str(ROOT)
        except Exception:                        # noqa: BLE001
            repo_root = ""
    head = _head_sha_safe(repo_root)
    gates = [
        _gov_discrimination(repo_root, head, expected_gate=expected_gate),
        _gov_write_confinement(repo_root, selected),
        _gov_operability_drill(repo_root, head),
    ]
    # The headline verdict is DERIVED from the discrimination gate alone,
    # matching spine.bootstrap.ShadowResult.promotion_allowed exactly. The other
    # gates inform the operator; they do not get a vote on promotion, because a
    # second opinion here is how an override sneaks in.
    disc = gates[0]
    promotion_allowed = disc["state"] == "working"
    blockers = [
        {"gate": g["id"], "state": g["state"], "why": g["headline"]}
        for g in gates if g["state"] != "working"
    ]
    if promotion_allowed:
        verdict = ("the gate has demonstrated discrimination at this revision; "
                   "promotion is still a human act")
    else:
        verdict = ("promotion is REFUSED: " + disc["headline"])
    warnings = [load_warning] if load_warning else []
    if head is None:
        warnings.append("The current revision could not be read, so every "
                        "revision-tied claim below is reported as unknown.")
    return envelope(
        project,
        promotion_allowed=promotion_allowed,
        verdict=verdict,
        state=_worst_state([g["state"] for g in gates]),
        head=head,
        repo_root=repo_root,
        gates=gates,
        blockers=blockers,
        states_vocabulary=list(GOVERNANCE_STATES),
        warnings=warnings,
    )


def get_dashboard(project: str | None = None) -> dict[str, Any]:
    try:
        names = list_projects()
    except OSError:
        names = []
    selected = project or (names[0] if names else None)
    pdata, load_warning = _safe_load_project(selected)
    repo_root = str(pdata.get("repo_root", "")) if pdata else ""
    watcher = watcher_status(selected)
    models = model_resources(selected)
    squads = get_squads(selected) if selected else envelope(None, squads=[])
    queue = get_queue(selected)
    quality = get_quality(selected)
    providers = provider_health(selected)
    status_payload, status_warning = _safe_collect_status(repo_root)
    warnings: list[str] = []
    if load_warning:
        warnings.append(load_warning)
    if status_warning:
        warnings.append(status_warning)
    for block in (watcher, models, squads, queue, quality, providers):
        warnings.extend(block.get("warnings") or [])
    if repo_root:
        enf = enforcement_status(repo_root)
        if not enf.get("enabled"):
            warnings.append("Harness enforcement is not active for this project.")
    else:
        enf = {}
    # Rides along with the dashboard ON PURPOSE. Both UI surfaces already poll
    # this one payload, and test_ui_contract.py pins its top-level keys across
    # both -- so shipping the promotion verdict here is what makes it
    # impossible for one surface to show it and the other to quietly not.
    try:
        governance = get_governance(selected)
    except Exception as e:                       # noqa: BLE001
        # Never let the promotion verdict take the whole dashboard down, and
        # never let its absence read as "nothing is wrong".
        governance = envelope(
            selected, promotion_allowed=False, state="unknown",
            verdict=(f"promotion status is UNKNOWN: the governance check itself "
                     f"failed ({type(e).__name__}). Treat this as unproven, not "
                     f"as permission."),
            head=None, repo_root=repo_root, gates=[], blockers=[],
            states_vocabulary=list(GOVERNANCE_STATES), warnings=[])
        warnings.append("The promotion verdict could not be computed; it is "
                        "shown as unknown.")
    return envelope(
        selected,
        selected_project=selected,
        projects=[{"name": p, "path": str(PROJECT_DIR / f"{p}.json")} for p in names],
        project_config=pdata,
        status=status_payload,
        watcher=watcher,
        models=models,
        provider_health=providers,
        squads=squads,
        queue=queue,
        metrics=metrics.summary(),
        quality=quality,
        routing=routing_summary(selected, watcher, models, quality),
        enforcement=enf,
        claude_crew=detect_claude_crew(repo_root),
        governance=governance,
        categories=get_categories(selected).get("categories", []),
        warnings=list(dict.fromkeys(warnings)),
    )


def get_categories(project: str | None = None) -> dict[str, Any]:
    from . import categories as cats

    pdata, load_warning = _safe_load_project(project)
    repo_root = pdata.get("repo_root") if pdata else None
    try:
        rows = cats.get_categories_joined(repo_root)
    except (OSError, ValueError, json.JSONDecodeError):
        rows = []
    warnings = [load_warning] if load_warning else []
    return envelope(project, categories=rows, warnings=warnings)


def queue_task(
    project: str,
    objective: str,
    lane: str,
    source: str = "unknown",
    strategy: str = "single",
    paths: list[str] | None = None,
) -> dict[str, Any]:
    from .file_bridge import enqueue
    from .router import route_task

    repo_root = resolve_repo_root(None, project)
    # Best-effort: tag the payload with the routed/owning agent's category so
    # the bus/reports carry it. This is metadata only -- it never changes
    # `lane`, which the caller/policy already decided.
    category = ""
    try:
        active = team_config(project).get("active_agents") or None
        owner = route_task(objective, paths or [], repo_root=repo_root, active_agents=active)
        category = owner.get("category", "") or ""
    except Exception:
        category = ""
    path = enqueue(objective, repo_root, paths or [], lane=lane, project=project,
                    source=source, strategy=strategy, category=category)
    return envelope(project, queued=str(path), lane=lane, source=source, strategy=strategy, category=category)


def review_diff(project: str, lane: str = "local_only") -> dict[str, Any]:
    objective = (
        "Review the current working-tree diff. Use git_status and git_diff before reporting. "
        "Advisory review only: do not write files. Return concrete findings with file-specific risks. "
        "If no concrete issue is found, say that and mention residual test gaps."
    )
    return queue_task(project, objective, lane=lane, source="codex", strategy="single", paths=[])


def plan_ikarus(project: str, objective: str) -> dict[str, Any]:
    from .kairos.scheduler import KairosScheduler

    repo_root = resolve_repo_root(None, project)
    plan = KairosScheduler(project=project).spawn(objective, repo_root, dry_run=True)
    return envelope(project, plan=plan)


def enforce_harness(project: str) -> dict[str, Any]:
    from .enforce import enforce_repo

    repo_root = resolve_repo_root(None, project)
    result = enforce_repo(repo_root, project)
    return envelope(project, enforcement=result)


def _availability_from_doctor() -> dict[str, bool]:
    from .doctor import check

    ready = check()
    return {
        "claude_cli": bool(ready.get("claude_cli")),
        "ollama": bool(ready.get("can_offload_local")),
        "deepseek": bool(ready.get("deepseek_key")),
        "codex_cli": bool(ready.get("codex_cli")),
    }


def _ikarus_availability(lane: str) -> dict[str, bool]:
    """Project provider health into the authority of one bridge lane.

    ``local_only`` is a confinement promise, not merely a preference.  It may
    expose the reachable Ollama bench only when the canonical host predicate
    says the configured endpoint is trusted; every external provider remains
    unavailable even when doctor found it.  ``auto``/``local`` keep the
    historical full availability map so the existing project policy and
    router continue to decide their provider.
    """
    availability = _availability_from_doctor()
    if lane != "local_only":
        return availability

    from .providers.ollama import DEFAULT_HOST
    from .sensitivity import lane_for_host

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    return {
        "claude_cli": False,
        "ollama": bool(
            availability.get("ollama") and lane_for_host(host) == "trusted"
        ),
        "deepseek": False,
        "codex_cli": False,
    }


def _one_task_session(payload: dict[str, Any], assignment: Any) -> Any:
    """Bind one bridge request to the existing Mission/WorkItem/Wave spine."""
    from .build import (
        FRONTIER_BUILDER,
        LOCAL_BUILDER,
        BuildSession,
        BuildTask,
        Wave,
    )
    from .spine.envelope import canonical_sha

    slug = "ikarus-queue-" + canonical_sha({
        "objective": payload["objective"],
        "repo_root": str(payload["repo_root"]),
        "paths": list(payload.get("paths") or []),
        "project": payload.get("project"),
        "trace_id": payload.get("trace_id"),
    })[:16]
    local = str(getattr(assignment, "lane", "")) == "ollama"
    task = BuildTask(
        objective=payload["objective"],
        agent=str(getattr(assignment, "owner", "") or "unknown"),
        category=str(payload.get("category") or ""),
        lane=str(getattr(assignment, "lane", "") or "local_only"),
        tier=str(payload.get("model") or "sonnet"),
        builder=LOCAL_BUILDER if local else FRONTIER_BUILDER,
        frontier=not local,
        paths=list(payload.get("paths") or []),
    )
    return BuildSession(
        feature=payload["objective"],
        repo_root=str(payload["repo_root"]),
        project=payload.get("project"),
        waves=[Wave(index=0, tasks=[task])],
        slug=slug,
        max_workers=1,
    )


_IKARUS_EFFECT_BLOCKERS = frozenset({
    "effect_lease_denied",
    "effect_lease_refused",
    "effect_lease_required",
    "effect_replay",
    "spend_envelope_denied",
    "spend_refused",
    "spend_refused_not_attempted",
})


def _ikarus_effect_blocker(results: list[dict[str, Any]]) -> str:
    """Return the first effect refusal that must never trigger a fallback."""
    for row in results:
        status = str(row.get("status") or "")
        nested = row.get("result") or {}
        nested_action = str(
            nested.get("action") if isinstance(nested, dict) else ""
        )
        provider = row.get("provider_receipt") or {}
        provider_action = str(
            provider.get("action") if isinstance(provider, dict) else ""
        )
        if status in _IKARUS_EFFECT_BLOCKERS:
            return str(
                (nested.get("note") if isinstance(nested, dict) else "")
                or row.get("reason")
                or status
            )
        if nested_action in _IKARUS_EFFECT_BLOCKERS:
            return str(
                nested.get("note") or row.get("reason") or nested_action
            )
        if provider_action in _IKARUS_EFFECT_BLOCKERS:
            return str(
                provider.get("note") or row.get("reason") or provider_action
            )
    return ""


_IKARUS_PROVIDER_RAN_STATUSES = frozenset({
    "offloaded",
    "gated_held",
    "gated_artifact_lost",
    "write_gate_failed",
    "escalated_after_verify_fail",
})


def _ikarus_provider_facts(
    results: list[dict[str, Any]] | None,
) -> tuple[list[str], list[str]]:
    """Return conservatively labelled routed and actually-run providers.

    ``lane`` on an assignment is routing evidence.  It is not, by itself,
    proof that a provider process started: an Effect-Lease or storage refusal
    carries the same assignment shape.  ``actual_providers`` therefore needs
    both a post-attempt terminal status and an explicit nested/receipt provider
    observation; the scheduler route is never used as a fallback.
    """
    assigned: list[str] = []
    actual: list[str] = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        nested = row.get("result") if isinstance(row.get("result"), dict) else {}
        receipt = (row.get("provider_receipt")
                   if isinstance(row.get("provider_receipt"), dict) else {})
        assigned_values = [row.get("provider"), row.get("lane")]
        observed_values = [
            nested.get("provider"), receipt.get("provider"),
            receipt.get("provider_id"), receipt.get("runtime_id"),
        ]
        routed = [str(value).strip() for value in assigned_values
                  if str(value or "").strip()]
        observed = [str(value).strip() for value in observed_values
                    if str(value or "").strip()]
        for provider in routed:
            if provider not in assigned:
                assigned.append(provider)
        if str(row.get("status") or "") in _IKARUS_PROVIDER_RAN_STATUSES:
            # Routing is intent, never execution evidence.  A pre-provider
            # failure can be coarsened to one of these terminal statuses, so
            # only an explicit nested/receipt provider may be called actual.
            for provider in observed:
                if provider not in actual:
                    actual.append(provider)
    return assigned, actual


def _ikarus_blocked_report(
    payload: dict[str, Any], error: str, results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    requested_lane = str(payload.get("lane") or "local_only")
    assigned_providers, actual_providers = _ikarus_provider_facts(results)
    return {
        "request": payload,
        "bridge_status": "failed",
        "lane": requested_lane,
        "requested_lane": requested_lane,
        "assigned_providers": assigned_providers,
        "actual_providers": actual_providers,
        "orchestrator": "ikarus",
        "error": error,
        "result": {
            "strategy": payload.get("strategy"),
            "assignments": list(results or []),
        },
    }


def _bridge_effect_identity(
    effect_identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate the file bridge's private, journal-backed replay identity.

    This material arrives through a keyword-only process boundary, never from
    the request JSON.  It identifies an Effect Lease; it does not grant one.
    The canonical issuer still signs, persists and verifies the resulting
    capability before ``WaveExecutor`` can dispatch anything.
    """
    if effect_identity is None:
        return {}
    if not isinstance(effect_identity, Mapping):
        raise TypeError("effect_identity must be a mapping")
    attempt_id = effect_identity.get("attempt_id")
    lease_id = effect_identity.get("lease_id")
    issued_text = effect_identity.get("issued_at")
    if not all(isinstance(value, str) and value.strip()
               for value in (attempt_id, lease_id, issued_text)):
        raise ValueError(
            "effect_identity requires non-empty attempt_id, lease_id and issued_at"
        )
    try:
        issued_at = datetime.fromisoformat(str(issued_text).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("effect_identity issued_at is not ISO-8601") from exc
    if issued_at.tzinfo is None:
        raise ValueError("effect_identity issued_at must include a timezone")
    return {
        "attempt_id": str(attempt_id),
        "lease_id": str(lease_id),
        "issued_at": issued_at,
    }


def _try_ikarus(
    payload: dict[str, Any], *,
    effect_identity: Mapping[str, Any] | None = None,
    mission_projection_dir: Path | None = None,
) -> dict[str, Any] | None:
    from .kernel.offload_lease import WaveLeaseKillSwitchEngaged

    if payload.get("strategy") == "spawn":
        return _ikarus_blocked_report(
            payload,
            "strategy='spawn' has no canonical leased multi-task adapter; "
            "refusing instead of dispatching outside WaveExecutor",
        )

    try:
        availability = _ikarus_availability(
            str(payload.get("lane") or "local_only")
        )
        from .kairos.scheduler import KairosScheduler

        ikarus = KairosScheduler(availability=availability, project=payload.get("project"))
        task_dict = {
            "objective": payload["objective"],
            "paths": list(payload.get("paths") or []),
        }
        assignments = ikarus.accept(
            [task_dict], repo_root=payload["repo_root"]
        )
        if not assignments or not assignments[0].accepted:
            return None
        assignment = assignments[0]
    except Exception:
        return None

    source_revision = _head_sha_safe(str(payload["repo_root"]))
    if not source_revision:
        return _ikarus_blocked_report(
            payload,
            "repository HEAD is unavailable; refusing to issue a lease with "
            "invented source provenance",
        )

    try:
        from .build_exec import EffectBounds, WaveExecutor
        from .ikarus_supervisor import MissionSupervisor
        from .orchestration import run_mission

        session = _one_task_session(payload, assignment)
        if mission_projection_dir is not None and not isinstance(
            mission_projection_dir, Path
        ):
            raise TypeError("mission_projection_dir must be a Path")
        supervisor = (
            None
            if mission_projection_dir is None
            else MissionSupervisor(
                repo_root=Path(str(payload["repo_root"])),
                run_dir=mission_projection_dir,
                roles={},
            )
        )
        replay_identity = _bridge_effect_identity(effect_identity)
        executor = WaveExecutor(
            availability=availability,
            effect_bounds=EffectBounds(
                mission_id=session.mission_id,
                source_revision=source_revision,
                trace_id=(str(payload.get("trace_id"))
                          if payload.get("trace_id") else None),
                **replay_identity,
            ),
        )
        _mission, mission_report = run_mission(
            session,
            source_revision=source_revision,
            executor=executor,
            repo_root=str(payload["repo_root"]),
            dry_run=False,
            parallel_advisory=False,
            resume=False,
            trace_id=(str(payload.get("trace_id"))
                      if payload.get("trace_id") else None),
            update_architecture=False,
            persist_session=False,
            supervisor=supervisor,
        )
        if len(mission_report.waves) != 1:
            raise RuntimeError(
                "one bridge request must produce exactly one mission wave"
            )
        wave = mission_report.waves[0]
        results = wave.results
    except WaveLeaseKillSwitchEngaged as exc:
        return _ikarus_blocked_report(payload, str(exc))
    except Exception as exc:
        return _ikarus_blocked_report(
            payload,
            "leased execution ended without a terminal result: "
            f"{type(exc).__name__}: {exc}",
        )
    effect_blocker = _ikarus_effect_blocker(results)
    if effect_blocker:
        return _ikarus_blocked_report(payload, effect_blocker, results)
    if not results:
        return _ikarus_blocked_report(
            payload, "WaveExecutor returned no terminal task result", results
        )
    unsuccessful = [
        r for r in results
        if r.get("status") not in ("offloaded", "gated_held")
    ]
    if unsuccessful:
        first = unsuccessful[0]
        return _ikarus_blocked_report(
            payload,
            str(
                first.get("reason")
                or first.get("error")
                or first.get("status")
                or "leased task did not complete successfully"
            ),
            results,
        )
    owners = list(dict.fromkeys(str(r.get("owner", "")) for r in results if r.get("owner")))
    requested_lane = str(payload.get("lane") or "local_only")
    assigned_providers, actual_providers = _ikarus_provider_facts(results)
    return {
        "request": payload,
        "bridge_status": "done",
        "lane": requested_lane,
        "requested_lane": requested_lane,
        "assigned_providers": assigned_providers,
        "actual_providers": actual_providers,
        "orchestrator": "ikarus",
        "agent": owners[0] if len(owners) == 1 else "multi",
        "result": {"strategy": payload.get("strategy"), "assignments": results},
    }


def _ask_claude_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed until the bridge owns canonical Claude caller authority.

    Kept as the old private seam so refusal tests and callers get a stable,
    explicit report instead of an AttributeError.  It deliberately does not
    import or invoke ``claude_bridge.ask_claude``.
    """
    requested_lane = str(payload.get("lane") or "claude")
    return {
        "request": payload,
        "bridge_status": "failed",
        "lane": requested_lane,
        "requested_lane": requested_lane,
        "assigned_providers": [],
        "actual_providers": [],
        "error": (
            "Claude dispatch is disabled on the canonical queue path: the "
            "bridge caller does not yet hold the mandatory runtime-bound "
            "Effect Lease and broker authorization"
        ),
    }


def local_only_failure_report(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request": payload,
        "bridge_status": "failed",
        "lane": "local_only",
        "requested_lane": "local_only",
        "assigned_providers": [],
        "actual_providers": [],
        "error": (
            "local_only requested, but the trusted local bench did not accept "
            "the task; external fallback is prohibited"
        ),
    }


KNOWN_LANES = ("auto", "local", "local_only", "claude", "codex")


def _codex_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Forced ``codex`` lane: dispatch to Codex as a read-only translator.

    Like the forced ``claude`` lane there is NO fallback -- a failure is
    reported, not silently re-billed to another lane. Unlike Claude, codex is
    an EXTERNAL UNTRUSTED lane, so the egress policy is enforced twice:
    here, BEFORE dispatch (a denied path never reaches the provider), and
    again inside the provider itself (defense in depth).

    This legacy bridge used to grant workspace-write directly, bypassing
    offload's before/after snapshot, verifier, rollback, and the newer
    worktree path.  Until Forge supplies one transaction boundary for every
    runtime, the forced lane is intentionally advisory-only.  Codex can still
    translate, inspect, and propose a patch; it cannot mutate the primary
    checkout through this split-brain seam."""
    from .config import resolve_project
    from .providers import get_provider
    from .router import route_task
    from .sensitivity import classify_data, load_policy

    try:
        pdata = resolve_project(payload.get("repo_root") or "", payload.get("project"))
        pol = load_policy(pdata) if (pdata and pdata.get("policy")) else None
        paths = payload.get("paths") or []
        verdict = classify_data(paths, extra_text=payload["objective"], policy=pol)
        if verdict.sensitive:
            return {
                "request": payload, "bridge_status": "failed", "lane": "codex",
                "error": ("egress policy refused codex dispatch: "
                          + "; ".join(verdict.reasons)[:300]),
            }
        provider = get_provider("codex_cli")
        if not provider.available():
            return {"request": payload, "bridge_status": "failed", "lane": "codex",
                    "error": "codex CLI is not on PATH (run `codex --version`)"}
        agent = route_task(payload["objective"], paths,
                           repo_root=payload.get("repo_root") or None)
        writable = False
        out = provider.run(
            objective=payload["objective"], repo_root=payload["repo_root"],
            # 1500s to match the provider's own default (codex real-task budget
            # is 8-20 min; an explicit 300 here silently overrode that and
            # killed D2/D3 wrappers while codex was still finishing on disk).
            paths=paths, agent=agent, timeout_s=int(payload.get("timeout_s", 1500)),
            policy=pol, writable=writable,
        )
        return {
            "request": payload, "bridge_status": "done", "lane": "codex",
            "agent": out.get("agent"), "persona": out.get("persona"),
            "mutation_blocked": (
                "forced codex is advisory-only until Forge provides a verified "
                "worktree transaction"
            ),
            "report": out["report"],
        }
    except Exception as exc:
        return {"request": payload, "bridge_status": "failed", "lane": "codex",
                "error": str(exc)}


def _configure_report(payload: dict[str, Any]) -> dict[str, Any]:
    """strategy='configure': KairosScheduler mints/edits an agent role. Deterministic,
    local, and never spends -- independent of lane."""
    from .kairos.scheduler import KairosScheduler
    try:
        result = KairosScheduler(project=payload.get("project")).configure(
            payload.get("role") or {}, payload.get("repo_root") or None,
            overwrite=bool(payload.get("overwrite")),
        )
        return {"request": payload, "bridge_status": "done", "lane": "local",
                "orchestrator": "ikarus", "agent": "ikarus", "result": result}
    except Exception as exc:
        return {"request": payload, "bridge_status": "failed", "lane": "local", "error": str(exc)}


def process_bridge_payload(
    payload: dict[str, Any], *,
    effect_identity: Mapping[str, Any] | None = None,
    mission_projection_dir: Path | None = None,
) -> dict[str, Any]:
    if payload.get("strategy") == "configure":
        return _configure_report(payload)
    # Fail-closed: a missing or unrecognized lane (typo, hand-edited/legacy
    # outbox file) is treated as local_only so the watcher can never bill an
    # unlabeled task to a paid provider unattended. External direct fallback is
    # disabled for every lane until this caller owns the mandatory authority.
    lane = payload.get("lane") or "local_only"
    if lane not in KNOWN_LANES:
        lane = "local_only"
    payload = {**payload, "lane": lane}
    if lane == "codex":
        # ``provider.codex`` is still INVENTORY_ONLY in the effect-boundary
        # catalogue: CodexCLIProvider.run has not adopted the canonical
        # runtime-bound Effect Lease / broker authorization seam.  The Hand now
        # makes project-owned lanes reachable from chat, so keeping this legacy
        # direct call here would turn a documented gap into a new effectful
        # bypass.  Retain _codex_report for old read-only callers and evidence,
        # but do not let the canonical bridge start it until that provider is
        # centrally brokered.
        return {
            "request": payload,
            "bridge_status": "failed",
            "lane": "codex",
            "requested_lane": "codex",
            "assigned_providers": [],
            "actual_providers": [],
            "error": (
                "codex dispatch is disabled: provider.codex has not adopted "
                "the canonical runtime-bound Effect Lease and broker "
                "authorization seam"
            ),
        }
    report = None
    if lane in ("auto", "local", "local_only"):
        report = _try_ikarus(
            payload,
            effect_identity=effect_identity,
            mission_projection_dir=mission_projection_dir,
        )
    if report is None and lane == "local_only":
        return local_only_failure_report(payload)
    if report is None:
        # ``auto``/``local`` may route through the leased WaveExecutor when an
        # assignment is accepted. They may not turn an ineligible assignment
        # into a legacy direct Claude call that has no caller-held broker
        # authority. The explicit ``claude`` lane reaches the same refusal.
        report = _ask_claude_report(payload)
    return report
