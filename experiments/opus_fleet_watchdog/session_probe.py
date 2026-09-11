"""Fail-closed host/session observation for the advisory fleet experiment.

The probe is deliberately read-only.  It combines an instantaneous Windows
process census with the hook activity that Daedalus already records in each
registered project and mtimes from Codex's existing daily rollout files.  It
creates no PID, heartbeat, lease, or session files and reads no rollout content.

Hook state has no SessionEnd event, so a fresh hook artifact means "activity
within the grace window", not "proved live".  That conservative distinction is
intentional: incomplete observation and recent activity both prevent dispatch.

Long-lived VS Code Claude ``stream-json`` and Codex ``app-server`` processes do
not block by presence alone: doing so would starve the fleet whenever an editor
stayed open.  Fresh registered-project hooks and Codex rollout mtimes provide
the activity signal for those services.  Direct Claude batch/worker calls,
Codex exec calls, and package CLIs outside a known IDE service still block for
their full process lifetime; an idle terminal CLI can therefore delay work.

This is a preflight observation, not a lock against humans.  A CLI can start
after the census, and a single quiet turn lasting beyond the 30-minute grace
can look idle.  A supervisor should narrow that TOCTOU window by probing
immediately before fan-out, but no read-only host observation can eliminate it.

Iron Plan: EXPERIMENT (Gate 0, bounded read-only advisory workload).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from daedalus.foundation.projects import list_projects, load_project

from .core import SessionProbeResult


RECENT_ACTIVITY_S = 30 * 60
PROCESS_TIMEOUT_S = 8
MAX_PROCESS_OUTPUT_BYTES = 1_000_000

_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STATE_FILE = re.compile(r"^state-(?P<session>[A-Za-z0-9_-]{1,64})\.json$")

POWERSHELL_ARGV_PREFIX = (
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
)


# Static by construction: there are no caller-controlled values in this
# program.  PIDs are unnecessary for the decision and therefore never leave
# CIM.  Command lines and executable paths are inspected only in memory by the
# Python classifier and are never copied into SessionProbeResult.
PROCESS_CENSUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$filter = @(
    "Name = 'claude.exe'",
    "Name = 'claude'",
    "Name = 'claude-code.exe'",
    "Name = 'claude-code'",
    "Name = 'codex.exe'",
    "Name = 'codex'",
    "Name = 'node.exe'",
    "Name = 'node'"
) -join ' OR '
$rows = @(
    Get-CimInstance -ClassName Win32_Process -Filter $filter |
        ForEach-Object {
            [PSCustomObject]@{
                name = [string] $_.Name
                executable_path = if ($null -eq $_.ExecutablePath) { $null } else { [string] $_.ExecutablePath }
                command_line = if ($null -eq $_.CommandLine) { $null } else { [string] $_.CommandLine }
            }
        }
)
[PSCustomObject]@{
    ok = $true
    rows = $rows
} | ConvertTo-Json -Compress -Depth 4
""".strip()


@dataclass(frozen=True)
class _ProcessObservation:
    count: int
    sources: tuple[str, ...]
    claude_services: int = 0
    codex_app_servers: int = 0
    error: str = ""


@dataclass(frozen=True)
class _HookObservation:
    count: int
    sources: tuple[str, ...]
    errors: tuple[str, ...] = ()
    clock_skew: bool = False


@dataclass(frozen=True)
class _CodexActivityObservation:
    count: int
    sources: tuple[str, ...]
    error: str = ""
    clock_skew: bool = False


def fleet_session_probe(
    *,
    now: float | None = None,
    recent_s: float = RECENT_ACTIVITY_S,
    process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    platform_name: str | None = None,
    project_lister: Callable[[], Sequence[str]] | None = None,
    project_loader: Callable[[str], Mapping[str, Any]] | None = None,
    codex_home: str | os.PathLike[str] | None = None,
) -> SessionProbeResult:
    """Observe external CLI and hook activity without creating liveness state.

    ``active_sessions`` is a conservative blocker-observation count, not a
    uniqueness claim.  One Claude session can be represented by both a process
    and a hook file; callers must use only the ``> 0`` distinction.

    The injected callables are test seams.  Production defaults always inspect
    the full Daedalus project registry and the current Windows host.
    """

    observed_at = time.time() if now is None else _finite_nonnegative(now, "now")
    window = _finite_positive(recent_s, "recent_s")
    host = os.name if platform_name is None else platform_name

    errors: list[str] = []
    if host != "nt":
        processes = _ProcessObservation(0, (), error="unsupported_host")
    else:
        processes = _observe_windows_processes(process_runner)
    if processes.error:
        errors.append(processes.error)

    hooks = _observe_registered_hooks(
        now=observed_at,
        recent_s=window,
        project_lister=project_lister or list_projects,
        project_loader=project_loader or load_project,
        windows_paths=host == "nt",
    )
    errors.extend(hooks.errors)

    codex_activity = _observe_codex_activity(
        now=observed_at,
        recent_s=window,
        codex_home=codex_home,
    )
    if codex_activity.error:
        errors.append(codex_activity.error)

    sources = tuple(
        sorted(
            set(processes.sources)
            | set(hooks.sources)
            | set(codex_activity.sources)
        )
    )
    active = processes.count + hooks.count + codex_activity.count
    if errors:
        reason = "probe_incomplete:" + ",".join(sorted(set(errors)))
        return SessionProbeResult(False, active, sources, reason)
    if active:
        skew = hooks.clock_skew or codex_activity.clock_skew
        reason = "active_evidence:clock_skew" if skew else "active_evidence"
        return SessionProbeResult(True, active, sources, reason)
    return SessionProbeResult(True, 0, (), "")


def _observe_windows_processes(
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> _ProcessObservation:
    try:
        completed = runner(
            [*POWERSHELL_ARGV_PREFIX, PROCESS_CENSUS_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=PROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return _ProcessObservation(0, (), error="process_census_timeout")
    except Exception:  # noqa: BLE001 - runner/host failures all fail closed
        return _ProcessObservation(0, (), error="process_census_failed")

    if getattr(completed, "returncode", 1) != 0:
        return _ProcessObservation(0, (), error="process_census_failed")
    output = getattr(completed, "stdout", "")
    if not isinstance(output, str) or not output.strip():
        return _ProcessObservation(0, (), error="process_census_invalid")
    if len(output.encode("utf-8", errors="replace")) > MAX_PROCESS_OUTPUT_BYTES:
        return _ProcessObservation(0, (), error="process_census_invalid")
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return _ProcessObservation(0, (), error="process_census_invalid")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return _ProcessObservation(0, (), error="process_census_invalid")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return _ProcessObservation(0, (), error="process_census_invalid")

    count = 0
    claude_services = 0
    codex_app_servers = 0
    sources: set[str] = set()
    for raw in rows:
        parsed = _parse_process_row(raw)
        if parsed is None:
            return _ProcessObservation(0, (), error="process_census_invalid")
        classification = _classify_process(*parsed)
        if classification == "claude-vscode-service":
            claude_services += 1
            continue
        if classification == "codex-app-server":
            codex_app_servers += 1
            continue
        if classification:
            count += 1
            sources.add(classification)
    return _ProcessObservation(
        count,
        tuple(sorted(sources)),
        claude_services=claude_services,
        codex_app_servers=codex_app_servers,
    )


def _parse_process_row(raw: object) -> tuple[str, str | None, str | None] | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    path = raw.get("executable_path")
    command_line = raw.get("command_line")
    if not isinstance(name, str) or not name.strip():
        return None
    if path is not None and not isinstance(path, str):
        return None
    if command_line is not None and not isinstance(command_line, str):
        return None
    return name.strip(), path, command_line


def _classify_process(
    name: str, executable_path: str | None, command_line: str | None
) -> str | None:
    image = Path(name).name.casefold()
    if image in {"claude", "claude.exe", "claude-code", "claude-code.exe"}:
        if _known_electron_desktop("claude", executable_path, command_line):
            return None
        tokens = _command_tokens(command_line)
        if any(token in {"-p", "--print", "--bg"} for token in tokens):
            return "windows:claude-cli"
        if _known_claude_vscode_service(executable_path, tokens):
            return "claude-vscode-service"
        return "windows:claude-cli"
    if image in {"codex", "codex.exe"}:
        if _known_electron_desktop("codex", executable_path, command_line):
            return None
        if "app-server" in _command_tokens(command_line):
            return "codex-app-server"
        return "windows:codex-cli"
    if image in {"node", "node.exe"}:
        vendor = _node_cli_vendor(command_line)
        if vendor == "claude":
            return "windows:claude-cli"
        if vendor == "codex":
            return "windows:codex-cli"
    return None


def _known_claude_vscode_service(
    executable_path: str | None, tokens: tuple[str, ...]
) -> bool:
    path = _slash(executable_path)
    if "/.vscode/extensions/anthropic.claude-code-" not in path:
        return False
    for index, token in enumerate(tokens[:-1]):
        if token.casefold() == "--input-format" and tokens[index + 1].casefold() == "stream-json":
            return True
        if token.casefold() == "--input-format=stream-json":
            return True
    return any(token.casefold() == "--input-format=stream-json" for token in tokens)


def _known_electron_desktop(
    vendor: str, executable_path: str | None, command_line: str | None
) -> bool:
    path = _slash(executable_path)
    command = _slash(command_line)
    executable = f"/app/{vendor}.exe"
    if f"/windowsapps/{vendor}_" in path and executable in path:
        return True
    # A non-MSIX Electron installation still exposes app.asar.  Require the
    # app marker as well as the vendor image; a CLI prompt merely mentioning
    # app.asar must not change classification.
    return "/resources/app.asar" in command and (
        f"/{vendor}/" in command or f"/{vendor}.exe" in command
    )


def _node_cli_vendor(command_line: str | None) -> str | None:
    tokens = _command_tokens(command_line)
    # The executable is token zero.  Bound inspection to the launcher/package
    # prefix so arbitrary prompt prose later in argv cannot create a match.
    for token in tokens[1:8]:
        normalized = _slash(token.strip('"\''))
        for vendor, package in (
            ("claude", "@anthropic-ai/claude-code"),
            ("codex", "@openai/codex"),
        ):
            if normalized == package or normalized.startswith(package + "@"):
                return vendor
            if f"/node_modules/{package}/" in normalized:
                return vendor
            if normalized.endswith(f"/node_modules/{package}"):
                return vendor
    return None


def _command_tokens(command_line: str | None) -> tuple[str, ...]:
    if not command_line:
        return ()
    try:
        return tuple(token.strip('"') for token in shlex.split(command_line, posix=False))
    except (TypeError, ValueError):
        return ()


def _slash(value: str | None) -> str:
    return (value or "").replace("\\", "/").casefold()


def _observe_codex_activity(
    *,
    now: float,
    recent_s: float,
    codex_home: str | os.PathLike[str] | None,
) -> _CodexActivityObservation:
    """Stat only today's/yesterday's Codex rollout files.

    Codex ``app-server`` is a long-lived IDE service and therefore not activity
    by itself.  Rollout mtimes are an existing vendor fact that changes during
    a turn.  Content and concrete paths never leave this function.
    """

    try:
        configured = codex_home
        if configured is None:
            configured = os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
        root = Path(configured).expanduser()
        if not root.is_absolute():
            return _CodexActivityObservation(0, (), "codex_activity_invalid")
        sessions = root / "sessions"
        sessions_stat = sessions.stat()
    except FileNotFoundError:
        return _CodexActivityObservation(0, ())
    except (OSError, TypeError, ValueError):
        return _CodexActivityObservation(0, (), "codex_activity_failed")
    if not stat.S_ISDIR(sessions_stat.st_mode):
        return _CodexActivityObservation(0, (), "codex_activity_failed")

    try:
        today = datetime.fromtimestamp(now).date()
    except (OverflowError, OSError, ValueError):
        return _CodexActivityObservation(0, (), "codex_activity_invalid")

    fresh = False
    clock_skew = False
    for day in (today, today - timedelta(days=1)):
        day_dir = sessions / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        try:
            day_stat = day_dir.stat()
        except FileNotFoundError:
            continue
        except OSError:
            return _CodexActivityObservation(0, (), "codex_activity_failed")
        if not stat.S_ISDIR(day_stat.st_mode):
            return _CodexActivityObservation(0, (), "codex_activity_failed")
        try:
            entries = list(day_dir.iterdir())
        except OSError:
            return _CodexActivityObservation(0, (), "codex_activity_failed")
        for entry in entries:
            if not (entry.name.startswith("rollout-") and entry.name.endswith(".jsonl")):
                continue
            try:
                item_stat = entry.stat()
            except OSError:
                return _CodexActivityObservation(0, (), "codex_activity_failed")
            if not stat.S_ISREG(item_stat.st_mode):
                return _CodexActivityObservation(0, (), "codex_activity_failed")
            age = now - item_stat.st_mtime
            if age <= recent_s:
                fresh = True
                clock_skew = clock_skew or age < 0

    if fresh:
        return _CodexActivityObservation(
            1, ("codex:recent-activity",), clock_skew=clock_skew
        )
    return _CodexActivityObservation(0, ())


def _observe_registered_hooks(
    *,
    now: float,
    recent_s: float,
    project_lister: Callable[[], Sequence[str]],
    project_loader: Callable[[str], Mapping[str, Any]],
    windows_paths: bool,
) -> _HookObservation:
    try:
        raw_names = project_lister()
    except Exception:  # noqa: BLE001 - registry observation is fail-closed
        return _HookObservation(0, (), ("project_registry_failed",))
    if not isinstance(raw_names, (list, tuple)) or not raw_names:
        return _HookObservation(0, (), ("project_registry_empty",))
    if any(not isinstance(name, str) or not _PROJECT_NAME.fullmatch(name) for name in raw_names):
        return _HookObservation(0, (), ("project_registry_invalid",))
    if len(set(raw_names)) != len(raw_names):
        return _HookObservation(0, (), ("project_registry_invalid",))

    roots: list[tuple[str, Path]] = []
    seen_roots: set[str] = set()
    for name in raw_names:
        try:
            data = project_loader(name)
            root_value = data.get("repo_root") if isinstance(data, Mapping) else None
            if not isinstance(root_value, (str, os.PathLike)):
                raise ValueError("missing root")
            unresolved = Path(root_value).expanduser()
            if not unresolved.is_absolute():
                raise ValueError("relative root")
            root = unresolved.resolve(strict=True)
            if not root.is_dir():
                raise ValueError("root is not a directory")
        except FileNotFoundError:
            return _HookObservation(0, (), ("project_root_missing",))
        except Exception:  # noqa: BLE001 - invalid/unreadable config is unknown
            return _HookObservation(0, (), ("project_registry_invalid",))
        key = _root_key(root, windows_paths=windows_paths)
        if key not in seen_roots:
            roots.append((name, root))
            seen_roots.add(key)

    total = 0
    sources: set[str] = set()
    errors: list[str] = []
    clock_skew = False
    for project, root in roots:
        count, recent, skew, error = _scan_hook_root(root, now=now, recent_s=recent_s)
        if error:
            errors.append(error)
            continue
        total += count
        clock_skew = clock_skew or skew
        if recent:
            sources.add(f"hooks:{project}")
    return _HookObservation(
        total,
        tuple(sorted(sources)),
        tuple(sorted(set(errors))),
        clock_skew,
    )


def _scan_hook_root(
    root: Path, *, now: float, recent_s: float
) -> tuple[int, bool, bool, str]:
    hooks = root / "runs" / "hooks"
    try:
        hooks_stat = hooks.stat()
    except FileNotFoundError:
        return 0, False, False, ""
    except OSError:
        return 0, False, False, "hook_scan_failed"
    if not stat.S_ISDIR(hooks_stat.st_mode):
        return 0, False, False, "hook_scan_failed"

    try:
        entries = list(hooks.iterdir())
    except OSError:
        return 0, False, False, "hook_scan_failed"

    sessions: set[str] = set()
    anonymous = 0
    ledger_recent = False
    clock_skew = False
    for entry in entries:
        name = entry.name
        match = _STATE_FILE.fullmatch(name)
        is_ledger = name in {"ledger.jsonl", "ledger.jsonl.1"}
        if match is None and not is_ledger:
            continue
        try:
            item_stat = entry.stat()
        except OSError:
            return 0, False, False, "hook_scan_failed"
        if not stat.S_ISREG(item_stat.st_mode):
            return 0, False, False, "hook_scan_failed"
        age = now - item_stat.st_mtime
        if age > recent_s:
            continue
        if age < 0:
            clock_skew = True
        if is_ledger:
            ledger_recent = True
            continue
        session_id = match.group("session")
        if _SESSION_ID.fullmatch(session_id) and session_id != "unknown":
            sessions.add(session_id)
        else:
            anonymous += 1

    count = len(sessions) + anonymous
    if ledger_recent and count == 0:
        # The ledger covers events that do not update state and state writes
        # that were lost after a hook lock timeout.  It proves activity, but
        # not a distinct session identity, so add at most one observation.
        count = 1
    return count, count > 0, clock_skew, ""


def _root_key(root: Path, *, windows_paths: bool) -> str:
    value = str(root).replace("\\", "/")
    return value.casefold() if windows_paths else value


def _finite_nonnegative(value: float, label: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if converted < 0 or converted in {float("inf"), float("-inf")} or converted != converted:
        raise ValueError(f"{label} must be a finite non-negative number")
    return converted


def _finite_positive(value: float, label: str) -> float:
    converted = _finite_nonnegative(value, label)
    if converted <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return converted


__all__: Sequence[str] = (
    "MAX_PROCESS_OUTPUT_BYTES",
    "POWERSHELL_ARGV_PREFIX",
    "PROCESS_CENSUS_SCRIPT",
    "PROCESS_TIMEOUT_S",
    "RECENT_ACTIVITY_S",
    "fleet_session_probe",
)
