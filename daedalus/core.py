from __future__ import annotations

import json
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import metrics
from .claude_bridge import ask_claude
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
        g["_try_ikarus"] = lambda payload: None
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
    return {"selected_lane": selected, "recommended_lane": "auto", "reason": "Ollama is unavailable; auto can use trusted fallback with confirmation policy."}


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
    from .ikarus import Ikarus

    repo_root = resolve_repo_root(None, project)
    plan = Ikarus(project=project).spawn(objective, repo_root, dry_run=True)
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
    }


def _try_ikarus(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        availability = _availability_from_doctor()
        from .ikarus import Ikarus

        ikarus = Ikarus(availability=availability, project=payload.get("project"))
        if payload.get("strategy") == "spawn":
            results = ikarus.spawn(payload["objective"], payload["repo_root"], dry_run=False)
        else:
            results = ikarus.dispatch(
                payload["repo_root"],
                [{"objective": payload["objective"], "paths": payload["paths"]}],
                dry_run=False,
            )
    except Exception:
        return None
    if not results or any(r.get("status") != "offloaded" for r in results):
        return None
    owners = list(dict.fromkeys(str(r.get("owner", "")) for r in results if r.get("owner")))
    return {
        "request": payload,
        "bridge_status": "done",
        "lane": "local",
        "orchestrator": "ikarus",
        "agent": owners[0] if len(owners) == 1 else "multi",
        "result": {"strategy": payload.get("strategy"), "assignments": results},
    }


def _ask_claude_report(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = ask_claude(
            objective=payload["objective"],
            repo_root=payload["repo_root"],
            paths=payload["paths"],
            model=payload["model"],
            timeout_s=int(payload.get("timeout_s", 300)),
        )
        return {
            "request": payload,
            "bridge_status": "done",
            "lane": "claude",
            "agent": result["agent"],
            "report": result["report"],
        }
    except Exception as exc:
        return {
            "request": payload,
            "bridge_status": "failed",
            "lane": "claude",
            "error": str(exc),
        }


def local_only_failure_report(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request": payload,
        "bridge_status": "failed",
        "lane": "local",
        "error": "local_only requested, but the local bench did not return a verified offload; Claude fallback skipped.",
    }


KNOWN_LANES = ("auto", "local", "local_only", "claude")


def _configure_report(payload: dict[str, Any]) -> dict[str, Any]:
    """strategy='configure': Ikarus mints/edits an agent role. Deterministic,
    local, and never spends -- independent of lane."""
    from .ikarus import Ikarus
    try:
        result = Ikarus(project=payload.get("project")).configure(
            payload.get("role") or {}, payload.get("repo_root") or None,
            overwrite=bool(payload.get("overwrite")),
        )
        return {"request": payload, "bridge_status": "done", "lane": "local",
                "orchestrator": "ikarus", "agent": "ikarus", "result": result}
    except Exception as exc:
        return {"request": payload, "bridge_status": "failed", "lane": "local", "error": str(exc)}


def process_bridge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("strategy") == "configure":
        return _configure_report(payload)
    # Fail-closed: a missing or unrecognized lane (typo, hand-edited/legacy
    # outbox file) is treated as local_only so the watcher can never bill an
    # unlabeled task to a paid provider unattended. Only 'auto'/'local' spend.
    lane = payload.get("lane") or "local_only"
    if lane not in KNOWN_LANES:
        lane = "local_only"
    payload = {**payload, "lane": lane}
    report = None
    if lane in ("auto", "local", "local_only"):
        report = _try_ikarus(payload)
    if report is None and lane == "local_only":
        return local_only_failure_report(payload)
    if report is None:
        report = _ask_claude_report(payload)
    return report
