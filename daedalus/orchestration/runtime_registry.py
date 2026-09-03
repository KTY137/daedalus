"""CLI-first, API-ready runtime registry.

Daedalus orchestration should depend on runtime capabilities, not on random
subprocess calls scattered through the app. This registry exposes a stable
status/test surface for CLIs today and API providers later.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..foundation.env import load_env
from ..providers.ollama import DEFAULT_HOST, DEFAULT_MODEL


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    label: str
    mode: str
    command: str = ""
    env_key: str = ""
    local: bool = False
    trusted_with_ip: bool = False
    can_write: bool = False
    agentic: bool = False
    notes: str = ""


_COMMAND_ENV = {
    "claude_code_cli": "DAEDALUS_CLAUDE_CLI",
    "codex_cli": "DAEDALUS_CODEX_CLI",
    "ollama_cli": "DAEDALUS_OLLAMA_CLI",
}


RUNTIMES: tuple[RuntimeSpec, ...] = (
    RuntimeSpec(
        id="claude_code_cli",
        label="Claude Code CLI",
        mode="cli",
        command="claude",
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Primary frontier runtime. Uses existing Claude Code CLI authentication.",
    ),
    RuntimeSpec(
        id="codex_cli",
        label="Codex CLI",
        mode="cli",
        command="codex",
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Codex participates through AGENTS.md and the Daedalus file bus when CLI auth is available.",
    ),
    RuntimeSpec(
        id="ollama_http",
        label="Ollama HTTP",
        mode="local_http",
        local=True,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Preferred local model interface; no API key required.",
    ),
    RuntimeSpec(
        id="ollama_cli",
        label="Ollama CLI",
        mode="cli",
        command="ollama",
        local=True,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Fallback local model interface.",
    ),
    RuntimeSpec(
        id="anthropic_api",
        label="Anthropic API",
        mode="api",
        env_key="ANTHROPIC_API_KEY",
        trusted_with_ip=True,
        can_write=False,
        agentic=False,
        notes="API-ready future slot; not required when Claude Code CLI is authenticated.",
    ),
    RuntimeSpec(
        id="openai_api",
        label="OpenAI API",
        mode="api",
        env_key="OPENAI_API_KEY",
        trusted_with_ip=False,
        can_write=False,
        agentic=False,
        notes="API-ready future slot; Codex CLI can be used first.",
    ),
)


def _home_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    for key in ("HOME", "USERPROFILE"):
        raw = str(env.get(key, "")).strip()
        if raw:
            return Path(raw)
    try:
        return Path.home()
    except (OSError, RuntimeError):
        return None


def _usable_command(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        return os.name == "nt" or os.access(path, os.X_OK)
    except OSError:
        return False


def _codex_extension_payload(
    *,
    platform_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, str] | None:
    """The one Codex extension payload compatible with this host.

    The OpenAI extension can bundle several native payloads side by side. A
    wildcard below ``bin/*`` therefore is not discovery: on Windows it can
    select the bundled Linux ELF before ``windows-*/codex.exe``. Keep this
    mapping in lockstep with the extension's own native-binary layout and
    refuse architectures it does not publish instead of guessing.
    """

    host = (sys.platform if platform_name is None else platform_name).lower()
    if host == "win32":
        os_family = "windows"
        executable = "codex.exe"
    elif host == "darwin":
        os_family = "macos"
        executable = "codex"
    elif host.startswith("linux"):
        os_family = "linux"
        executable = "codex"
    else:
        return None

    host_machine = (platform.machine() if machine is None else machine).lower()
    if host_machine in {"amd64", "x86_64"}:
        architecture = "x86_64"
    elif host_machine in {"arm64", "aarch64"}:
        architecture = "aarch64"
    else:
        return None
    return f"{os_family}-{architecture}", executable


def _extension_candidates(home: Path, runtime_id: str) -> list[Path]:
    """Bounded editor-extension discovery, never a home-directory crawl."""
    roots = (
        home / ".vscode" / "extensions",
        home / ".vscode-server" / "extensions",
        home / ".cursor" / "extensions",
        home / ".windsurf" / "extensions",
    )
    patterns: tuple[str, ...]
    if runtime_id == "claude_code_cli":
        patterns = (
            "anthropic.claude-code-*/resources/native-binary/claude",
            "anthropic.claude-code-*/resources/native-binary/claude.exe",
        )
    elif runtime_id == "codex_cli":
        payload = _codex_extension_payload()
        if payload is None:
            return []
        directory, executable = payload
        patterns = (f"openai.chatgpt-*/bin/{directory}/{executable}",)
    else:
        return []
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            found.extend(root.glob(pattern))
    # Newest installed extension first. The path is a deterministic tie-break.
    def rank(path: Path) -> tuple[float, str]:
        try:
            return path.stat().st_mtime, str(path)
        except OSError:
            return 0.0, str(path)
    return sorted(found, key=rank, reverse=True)


def resolve_runtime_command(
    runtime_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve one registered CLI without assuming the server's ``PATH``.

    Resolution is portable and narrow: an explicit Daedalus override, PATH,
    documented/common per-user install roots, then known editor-extension
    payloads. It never recursively scans a profile or guesses a network path.
    """
    env = os.environ if environ is None else environ
    spec = next((row for row in RUNTIMES if row.id == runtime_id), None)
    if spec is None or spec.mode != "cli" or not spec.command:
        return None

    candidates: list[Path] = []
    override = str(env.get(_COMMAND_ENV.get(runtime_id, ""), "")).strip()
    if override:
        candidates.append(Path(override))

    on_path = shutil.which(spec.command, path=env.get("PATH"))
    if on_path:
        candidates.append(Path(on_path))

    home = _home_dir(env)
    suffixes = (".exe", ".cmd", ".bat", "") if os.name == "nt" else ("",)
    if home is not None:
        for directory in (home / ".local" / "bin", home / "bin"):
            candidates.extend(directory / f"{spec.command}{suffix}" for suffix in suffixes)
        candidates.extend(_extension_candidates(home, runtime_id))

    if os.name == "nt":
        local = str(env.get("LOCALAPPDATA", "")).strip()
        roaming = str(env.get("APPDATA", "")).strip()
        if runtime_id == "ollama_cli" and local:
            candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
        if roaming:
            npm = Path(roaming) / "npm"
            candidates.extend(npm / f"{spec.command}{suffix}" for suffix in suffixes)
        if runtime_id == "codex_cli" and local:
            candidates.append(Path(local) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
    else:
        for directory in (Path("/usr/local/bin"), Path("/opt/homebrew/bin"), Path("/snap/bin")):
            candidates.append(directory / spec.command)
        if sys.platform == "darwin" and runtime_id == "ollama_cli":
            candidates.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)
        if _usable_command(candidate):
            return str(candidate.resolve())
    return None


def runtime_subprocess_env(
    runtime_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Child environment bound to the runtime's existing local state root."""
    env = dict(os.environ if environ is None else environ)
    if runtime_id == "codex_cli" and not str(env.get("CODEX_HOME", "")).strip():
        home = _home_dir(env)
        codex_home = home / ".codex" if home is not None else None
        # OpenAI's public contract requires CODEX_HOME to exist. Never create or
        # copy it here; merely make the already-present state visible to a child
        # launched from a service whose home-directory lookup may be absent.
        if codex_home is not None and codex_home.is_dir():
            env["CODEX_HOME"] = str(codex_home)
    return env


def _run_version(spec: RuntimeSpec) -> tuple[bool, str, str]:
    path = resolve_runtime_command(spec.id)
    if not path:
        override = _COMMAND_ENV.get(spec.id, "")
        hint = f" or set {override}" if override else ""
        return False, "", f"{spec.command} not found on PATH or supported install locations{hint}"
    try:
        completed = subprocess.run(
            # Spawn the RESOLVED path, not the bare name: npm ships `codex` as a
            # .CMD shim on Windows and CreateProcess cannot launch it by name
            # (WinError 2), so this probe reported codex as unavailable even
            # with the CLI installed and logged in. `claude`/`ollama` are real
            # .EXEs, which is why only codex was affected. Same lesson is
            # already encoded in providers/codex_cli.py and doctor.py.
            [path, "--version"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            env=runtime_subprocess_env(spec.id),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, path, str(exc)
    output = (completed.stdout or completed.stderr or "").strip()
    ok = completed.returncode == 0
    return ok, path, output or f"exit {completed.returncode}"


def _ollama_http_status() -> dict[str, Any]:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    want = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    from ..providers.ollama import ollama_endpoint_admission, ollama_http_base_url

    allowed, lane, reason = ollama_endpoint_admission(host)
    if not allowed:
        return {
            "available": False,
            "auth_status": "egress_refused",
            "command_path": "",
            "version": "",
            "endpoint": host,
            "lane": lane,
            "models": [],
            "selected_model": want,
            "model_present": False,
            "last_error": reason,
        }
    try:
        with urllib.request.urlopen(ollama_http_base_url(host) + "/api/tags", timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = [m.get("model") or m.get("name") for m in payload.get("models", [])]
        stem = want.split(":")[0]
        return {
            "available": True,
            "auth_status": "local",
            "command_path": "",
            "version": "",
            "endpoint": host,
            "lane": lane,
            "models": models,
            "selected_model": want,
            "model_present": any(stem in (m or "") for m in models),
            "last_error": "",
        }
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "available": False,
            "auth_status": "local_unreachable",
            "command_path": "",
            "version": "",
            "endpoint": host,
            "lane": lane,
            "models": [],
            "selected_model": want,
            "model_present": False,
            "last_error": str(exc),
        }


def runtime_status(runtime_id: str) -> dict[str, Any]:
    load_env()
    spec = next((r for r in RUNTIMES if r.id == runtime_id), None)
    if spec is None:
        raise KeyError(f"unknown runtime '{runtime_id}'")
    base = asdict(spec)
    if spec.id == "ollama_http":
        return {**base, **_ollama_http_status()}
    if spec.mode == "cli":
        ok, path, detail = _run_version(spec)
        if spec.id == "ollama_cli" and ok:
            server = _ollama_http_status()
            return {
                **base,
                **server,
                "available": bool(server.get("available")),
                "auth_status": (
                    "cli_detected_server_reachable"
                    if server.get("available") else server.get("auth_status")
                ),
                "command_path": path,
                "version": detail,
            }
        return {
            **base,
            "available": ok,
            "auth_status": "cli_detected" if ok else "unavailable",
            "command_path": path,
            "version": detail if ok else "",
            "models": [],
            "selected_model": "",
            "model_present": False,
            "last_error": "" if ok else detail,
        }
    configured = bool(os.environ.get(spec.env_key)) if spec.env_key else False
    return {
        **base,
        "available": configured,
        "auth_status": "configured" if configured else "not_configured",
        "command_path": "",
        "version": "",
        "models": [],
        "selected_model": "",
        "model_present": False,
        "last_error": "" if configured else f"{spec.env_key} is not set",
    }


# --------------------------------------------------------------------------- #
# THE CACHE, AND WHY IT MUST CARRY WHEN IT MEASURED (owner decision 2026-08-27) #
# --------------------------------------------------------------------------- #
# runtime_status launches each CLI to read its --version, so /api/runtimes/status
# is slow BY CONSTRUCTION and grows with use: MEASURED 16.6s under load, 28.0s on
# a quiet box, 36.1s after the Playwright suite (docs/design/handoffs-2026-08-26).
# The owner's ruling is to cache the probe rather than relaunch every CLI on every
# poll -- but a cached reading that reports "erreichbar" for a CLI that broke a
# minute ago is the exact lie this codebase forbids. So the contract is: every
# CACHED row carries `measured_at` (when the probe actually ran) and
# `measured_age_s`, and the surface shows it. The uncached path -- the direct
# callers in tests and elsewhere -- is byte-identical to before; the field
# appears only when a caller opts into the cache.
_STATUS_CACHE_TTL_S = float(os.environ.get("DAEDALUS_RUNTIME_STATUS_TTL_S", "30"))
_status_cache_lock = threading.Lock()
#: runtime_id -> (monotonic_at, measured_at_iso, row) for the last probe.
_status_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reset_status_cache() -> None:
    """Drop every cached probe. For tests and for a deliberate refresh."""
    with _status_cache_lock:
        _status_cache.clear()


def cached_runtime_status(
    runtime_id: str, *, ttl_s: float | None = None
) -> dict[str, Any]:
    """`runtime_status` behind a per-runtime TTL cache, stamped with when the
    probe ran. On a hit within the TTL the stored row is returned verbatim with
    a fresh `measured_age_s`; on a miss or expiry the probe runs and the row is
    stamped `measured_at` now. Each runtime is cached independently, so one slow
    CLI never forces the others to be re-probed."""
    ttl = _STATUS_CACHE_TTL_S if ttl_s is None else float(ttl_s)
    now_mono = time.monotonic()
    with _status_cache_lock:
        entry = _status_cache.get(runtime_id)
        # Strict: a reading is fresh only while it is YOUNGER than the TTL, so a
        # zero TTL is always expired (an explicit "do not cache") rather than a
        # one-shot cache that a same-tick second call would still hit.
        if entry is not None and (now_mono - entry[0]) < ttl:
            mono_at, iso_at, row = entry
            return {
                **row,
                "measured_at": iso_at,
                "measured_age_s": round(now_mono - mono_at, 3),
            }
    # Probe OUTSIDE the lock -- it can take seconds, and holding the lock would
    # serialise every concurrent poll behind one slow CLI, which is the cost
    # this cache exists to remove.
    try:
        row = runtime_status(runtime_id)
    except Exception as exc:  # noqa: BLE001 - a probe failure is a row, not a raise
        spec = next((r for r in RUNTIMES if r.id == runtime_id), None)
        base = asdict(spec) if spec is not None else {"id": runtime_id}
        row = {**base, "available": False, "auth_status": "error", "last_error": str(exc)}
    iso_at = _now_iso()
    with _status_cache_lock:
        _status_cache[runtime_id] = (time.monotonic(), iso_at, row)
    return {**row, "measured_at": iso_at, "measured_age_s": 0.0}


def all_status(*, use_cache: bool = False, ttl_s: float | None = None) -> dict[str, Any]:
    rows = []
    for spec in RUNTIMES:
        if use_cache:
            rows.append(cached_runtime_status(spec.id, ttl_s=ttl_s))
            continue
        try:
            rows.append(runtime_status(spec.id))
        except Exception as exc:
            rows.append({**asdict(spec), "available": False, "auth_status": "error", "last_error": str(exc)})
    return {"runtimes": rows}


def test_runtime(runtime_id: str) -> dict[str, Any]:
    """Safe readiness test; no paid LLM prompt is sent."""
    row = runtime_status(runtime_id)
    return {
        "runtime": runtime_id,
        "ok": bool(row.get("available")),
        "mode": row.get("mode"),
        "detail": row.get("version") or row.get("last_error") or row.get("endpoint") or row.get("auth_status"),
    }
