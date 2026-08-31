"""Desktop-owned lifecycle for the file bridge, Ollama, and local IDE."""
from __future__ import annotations

import atexit
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from . import budget as budget_kernel
from . import runtime_registry
from .limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    ExecutionLimitPolicy,
    LimitAxes,
    LimitPolicyError,
    MODE_CUSTOM,
    store_in_env as store_limit_policy_in_env,
)
from .projects import ProjectRegistryUnavailable, resolve_registered_project_root
from .spine.cancel import ManagedProcess

CONFIG_REL = Path("config/connections.json")
KNOWN_HOSTS_REL = Path("config/known_hosts")
LOG_REL = Path("runs/desktop_runtime.log")

TUNNEL_FORWARD_VAR = "DAEDALUS_OLLAMA_TUNNEL_FORWARD"
TUNNEL_TARGET_VAR = "DAEDALUS_OLLAMA_TUNNEL_TARGET"
REMOTE_OK_VAR = "DAEDALUS_OLLAMA_REMOTE_OK"
TRUSTED_HOSTS_VAR = "DAEDALUS_TRUSTED_HOSTS"

IDE_DOCKER_CONTAINER = "daedalus-openvscode"
IDE_DOCKER_WORKSPACE = "/home/workspace"
IDE_DOCKER_IMAGE = "daedalus/openvscode-server:1.109.5"
IDE_DOCKER_OWNER_LABEL = "dev.daedalus.desktop.service"
IDE_DOCKER_OWNER_VALUE = "openvscode"
IDE_DOCKER_PROJECT_LABEL = "dev.daedalus.desktop.project-sha256"

DEFAULT_CONFIG: dict[str, Any] = {
    "bridge": {"auto_start": True},
    "budget": {
        "period_ceiling_usd": budget_kernel.DEFAULT_CEILING_USD,
        "max_calls": budget_kernel.DEFAULT_MAX_CALLS,
    },
    "caps": ExecutionLimitPolicy().as_dict(),
    "ide": {
        "mode": "native",
        "auto_start": False,
        "endpoint": "http://127.0.0.1:3000",
        "executable": "",
        "docker_image": IDE_DOCKER_IMAGE,
    },
    "ollama": {
        "mode": "local",
        "auto_start": True,
        "model": "qwen2.5-coder:7b",
        "local_host": "http://127.0.0.1:11434",
        "remote": {
            "host": "",
            "user": "",
            "port": 22,
            "identity_file": "",
            "host_key_fingerprint": "",
            "local_port": 11435,
            "remote_port": 11434,
            "start_method": "systemd",
            "trust_remote_host": False,
        },
    },
}

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FP_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,}={0,2}$")
_IDE_DOCKER_IMAGE_RE = re.compile(
    r"^(?:daedalus|gitpod)/openvscode-server(?:"
    r":[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9_.-]+)?"
    r"|@sha256:[0-9a-f]{64})$"
)
_DOCKER_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_DLL_DIRECTORY_LOCK = threading.Lock()


def _frozen_windows_runtime_root() -> Path | None:
    """Return PyInstaller's DLL root only for a frozen Windows process."""

    raw = getattr(sys, "_MEIPASS", "")
    if os.name != "nt" or not isinstance(raw, (str, os.PathLike)) or not str(raw):
        return None
    return Path(raw).resolve()


def _path_is_within(path: str, root: Path) -> bool:
    """Compare PATH entries without treating a similarly named sibling as nested."""

    candidate = path.strip().strip('"')
    if not candidate:
        return False
    try:
        normalized_root = os.path.normcase(os.path.abspath(str(root)))
        normalized_candidate = os.path.normcase(os.path.abspath(candidate))
        return os.path.commonpath((normalized_root, normalized_candidate)) == normalized_root
    except (OSError, ValueError):
        return False


def _ollama_child_environment(
    environ: dict[str, str] | os._Environ[str],
    frozen_root: Path | None,
) -> dict[str, str]:
    """Copy the environment without exposing packaged DLLs to Ollama children."""

    child = dict(environ)
    if frozen_root is None:
        return child
    entries = child.get("PATH", "").split(os.pathsep)
    child["PATH"] = os.pathsep.join(
        entry for entry in entries if not _path_is_within(entry, frozen_root)
    )
    return child


def _set_windows_dll_directory(path: str | None) -> None:
    """Set the process DLL directory and fail closed when Windows refuses."""

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    setter = kernel32.SetDllDirectoryW
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_int
    if not setter(path):
        code = ctypes.get_last_error()
        raise OSError(code, f"SetDllDirectoryW({path!r}) failed")


def _spawn_ollama_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout: Any,
    stderr: Any,
    frozen_root: Path | None,
) -> ManagedProcess:
    """Spawn Ollama without leaking PyInstaller's DLL search path.

    ``SetDllDirectoryW`` changes process-global state, so the reset, spawn and
    restoration are one critical section.  The managed child is closed if the
    restoration itself fails; returning a running child after corrupting the
    parent's DLL search state would be unsafe.
    """

    def spawn() -> ManagedProcess:
        return ManagedProcess(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
        )

    if frozen_root is None:
        return spawn()

    with _DLL_DIRECTORY_LOCK:
        _set_windows_dll_directory(None)
        managed: ManagedProcess | None = None
        try:
            managed = spawn()
        finally:
            try:
                _set_windows_dll_directory(str(frozen_root))
            except BaseException:
                if managed is not None:
                    try:
                        managed.close(grace_s=0.0)
                    except BaseException:
                        pass
                raise
        return managed


class DesktopRuntimeError(RuntimeError):
    pass


def _defaults(
    *,
    budget_defaults: dict[str, Any] | None = None,
    caps_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = json.loads(json.dumps(DEFAULT_CONFIG))
    if budget_defaults:
        defaults["budget"].update(budget_defaults)
    if caps_defaults:
        defaults["caps"] = json.loads(json.dumps(caps_defaults))
    if os.name == "nt":
        defaults["ide"]["mode"] = "docker"
    return defaults


def _port(value: Any, name: str, low: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a TCP port")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a TCP port") from None
    if not low <= port <= 65535:
        raise ValueError(f"{name} must be between {low} and 65535")
    return port


def _loopback_endpoint(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        host, port = parsed.hostname or "", parsed.port
        local = bool(ipaddress.ip_address(host).is_loopback)
    except (ValueError, UnicodeError):
        raise ValueError("local_host must look like http://127.0.0.1:11434") from None
    if (
        not local
        or parsed.scheme != "http"
        or port is None
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("local_host must look like http://127.0.0.1:11434")
    # Preserve brackets around IPv6 loopback. Reconstructing from
    # parsed.hostname would turn http://[::1]:11434 into an invalid URL.
    return raw


def _ide_endpoint(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        host, port = parsed.hostname or "", parsed.port
        local = bool(ipaddress.ip_address(host).is_loopback)
    except (ValueError, UnicodeError):
        raise ValueError("ide.endpoint must look like http://127.0.0.1:3000") from None
    if (
        not local
        or parsed.scheme != "http"
        or port is None
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("ide.endpoint must look like http://127.0.0.1:3000")
    return raw


def _numeric_host(value: str) -> str | None:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if addr.is_unspecified or addr.is_multicast or addr.is_reserved or addr.is_link_local:
        return None
    return str(addr)


def _pid_is_alive(value: Any) -> bool:
    """Return whether a heartbeat PID still names a live process.

    A bridge heartbeat is persistent runtime state, not an ownership lease.  In
    particular it commonly survives the packaged backend that wrote it.  The
    desktop may use it to avoid starting a second live watcher, but only after
    checking the process named by the heartbeat.  ``os.kill(pid, 0)`` is not
    used on Windows: Python maps non-console signals there to
    ``TerminateProcess``, so a liveness read must go through a query handle.
    """

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return False
    try:
        pid = int(value)
    except (TypeError, ValueError, OverflowError):
        return False
    if pid <= 0 or pid > 0xFFFF_FFFF:
        return False
    # POSIX ``pid_t`` is a signed C integer on every supported target.  Python
    # raises OverflowError before issuing kill(2) for the upper DWORD half.
    if os.name != "nt" and pid > 0x7FFF_FFFF:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            synchronize = 0x0010_0000
            wait_object_0 = 0
            wait_timeout = 258
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(
                synchronize,
                False,
                pid,
            )
            if not handle:
                # Access denied proves that a process owns the PID even though
                # this user cannot inspect it.  ERROR_INVALID_PARAMETER is what
                # OpenProcess reports for an exited/nonexistent PID; every
                # other failure remains conservatively live so a query failure
                # cannot create a second watcher.
                return ctypes.get_last_error() != 87
            try:
                waited = kernel32.WaitForSingleObject(handle, 0)
                if waited == wait_object_0:
                    return False
                if waited == wait_timeout:
                    return True
                # WAIT_FAILED or an unknown result is a query failure, not
                # evidence that it is safe to create a second watcher.
                return True
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
    except OSError:
        return True
    return True


def normalize_config(
    raw: Any,
    *,
    budget_defaults: dict[str, Any] | None = None,
    caps_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Whitelist settings. Passwords, tokens, key bytes and commands are invalid."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("settings must be a JSON object")
    if "budget" in raw and not isinstance(raw["budget"], dict):
        raise ValueError("budget settings must be a JSON object")
    if "caps" in raw and not isinstance(raw["caps"], dict):
        raise ValueError("caps settings must be a JSON object")
    if "ide" in raw and not isinstance(raw["ide"], dict):
        raise ValueError("ide settings must be a JSON object")
    b = raw.get("bridge") if isinstance(raw.get("bridge"), dict) else {}
    budget = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
    caps = raw.get("caps") if isinstance(raw.get("caps"), dict) else None
    i = raw.get("ide") if isinstance(raw.get("ide"), dict) else {}
    o = raw.get("ollama") if isinstance(raw.get("ollama"), dict) else {}
    r = o.get("remote") if isinstance(o.get("remote"), dict) else {}

    cfg = _defaults(
        budget_defaults=budget_defaults,
        caps_defaults=caps_defaults,
    )
    cfg["bridge"]["auto_start"] = bool(b.get("auto_start", True))
    unsupported_budget = sorted(
        set(budget)
        - {"period_ceiling_enabled", "period_ceiling_usd", "max_calls"}
    )
    if unsupported_budget:
        raise ValueError(
            f"unsupported budget settings: {', '.join(unsupported_budget)}"
        )
    legacy_enabled = budget.get("period_ceiling_enabled")
    if "period_ceiling_enabled" in budget and not isinstance(
        legacy_enabled, bool
    ):
        raise ValueError("budget.period_ceiling_enabled must be a boolean")
    ceiling = budget.get("period_ceiling_usd", cfg["budget"]["period_ceiling_usd"])
    if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)):
        raise ValueError("budget.period_ceiling_usd must be a number")
    ceiling = float(ceiling)
    if not isfinite(ceiling) or ceiling <= 0:
        raise ValueError(
            "budget.period_ceiling_usd must be finite and greater than zero"
        )
    max_calls = budget.get("max_calls", cfg["budget"]["max_calls"])
    if type(max_calls) is not int or max_calls <= 0:
        raise ValueError("budget.max_calls must be a positive integer")
    cfg["budget"] = {
        "period_ceiling_usd": ceiling,
        "max_calls": max_calls,
    }
    try:
        if caps is not None:
            policy = ExecutionLimitPolicy.from_dict(caps)
        elif "period_ceiling_enabled" in budget:
            # Revision 9 migration is deliberately narrow: its single
            # uncapped USD choice becomes custom with only period_usd off.
            policy = (
                ExecutionLimitPolicy()
                if legacy_enabled
                else ExecutionLimitPolicy(
                    mode=MODE_CUSTOM,
                    configured=LimitAxes(period_usd=False),
                )
            )
        else:
            policy = ExecutionLimitPolicy.from_dict(cfg["caps"])
    except LimitPolicyError as exc:
        raise ValueError(f"invalid caps settings: {exc}") from exc
    cfg["caps"] = policy.as_dict()
    unsupported_ide = sorted(
        set(i) - {"mode", "auto_start", "endpoint", "executable", "docker_image"}
    )
    if unsupported_ide:
        raise ValueError(f"unsupported ide settings: {', '.join(unsupported_ide)}")
    ide_mode = str(i.get("mode", cfg["ide"]["mode"])).strip()
    if ide_mode not in {"native", "docker"}:
        raise ValueError("ide.mode must be native or docker")
    cfg["ide"]["mode"] = ide_mode
    cfg["ide"]["auto_start"] = bool(i.get("auto_start", False))
    cfg["ide"]["endpoint"] = _ide_endpoint(
        i.get("endpoint", cfg["ide"]["endpoint"])
    )
    executable = str(i.get("executable", "")).strip()
    if len(executable) > 4096 or any(ord(ch) < 32 for ch in executable):
        raise ValueError("ide.executable must be a valid local path")
    if ide_mode == "docker" and executable:
        raise ValueError("ide.executable is only valid when ide.mode is native")
    cfg["ide"]["executable"] = executable
    docker_image = str(i.get("docker_image", cfg["ide"]["docker_image"])).strip()
    if not _IDE_DOCKER_IMAGE_RE.fullmatch(docker_image):
        raise ValueError(
            "ide.docker_image must be a pinned daedalus/openvscode-server or "
            "gitpod/openvscode-server version/digest"
        )
    cfg["ide"]["docker_image"] = docker_image
    if ide_mode == "docker" and cfg["ide"]["endpoint"] != "http://127.0.0.1:3000":
        raise ValueError("docker IDE endpoint must be exactly http://127.0.0.1:3000")
    mode = str(o.get("mode", "local")).strip()
    if mode not in {"local", "remote_ssh"}:
        raise ValueError("ollama.mode must be local or remote_ssh")
    cfg["ollama"]["mode"] = mode
    cfg["ollama"]["auto_start"] = bool(o.get("auto_start", True))

    model = str(o.get("model", cfg["ollama"]["model"])).strip()
    if not model or len(model) > 200 or any(ord(ch) < 32 for ch in model):
        raise ValueError("ollama.model must be 1..200 printable characters")
    cfg["ollama"]["model"] = model
    cfg["ollama"]["local_host"] = _loopback_endpoint(
        o.get("local_host", cfg["ollama"]["local_host"])
    )

    dst = cfg["ollama"]["remote"]
    host, user = str(r.get("host", "")).strip(), str(r.get("user", "")).strip()
    if host and (host.startswith("-") or not _HOST_RE.fullmatch(host)):
        raise ValueError("remote.host must be a DNS name or IPv4 address")
    if user and not _USER_RE.fullmatch(user):
        raise ValueError("remote.user contains unsupported characters")
    dst["host"], dst["user"] = host, user
    dst["port"] = _port(r.get("port", 22), "remote.port")
    dst["local_port"] = _port(r.get("local_port", 11435), "remote.local_port", 1024)
    dst["remote_port"] = _port(r.get("remote_port", 11434), "remote.remote_port")

    identity = str(r.get("identity_file", "")).strip()
    if any(ch in identity for ch in ("\x00", "\n", "\r")):
        raise ValueError("remote.identity_file is invalid")
    dst["identity_file"] = identity

    fingerprint = str(r.get("host_key_fingerprint", "")).strip()
    if fingerprint and not _FP_RE.fullmatch(fingerprint):
        raise ValueError("host key fingerprint must use OpenSSH SHA256:... format")
    dst["host_key_fingerprint"] = fingerprint

    method = str(r.get("start_method", "systemd")).strip()
    if method not in {"systemd", "windows", "none"}:
        raise ValueError("remote.start_method must be systemd, windows, or none")
    dst["start_method"] = method
    dst["trust_remote_host"] = bool(r.get("trust_remote_host", False))

    if mode == "remote_ssh":
        if not host or not user:
            raise ValueError("remote SSH mode requires remote.host and remote.user")
        if dst["trust_remote_host"] and _numeric_host(host) is None:
            raise ValueError("trusted remote hosts must be numeric IP addresses")
    return cfg


def install_tunnel_egress_policy() -> None:
    """Classify a local SSH forward by its physical peer, not 127.0.0.1."""
    from . import sensitivity

    current = sensitivity.lane_for_host
    if getattr(current, "_daedalus_tunnel_aware", False):
        return
    original = current

    def tunnel_aware(host: str | None) -> str:
        forward = os.environ.get(TUNNEL_FORWARD_VAR, "").strip().rstrip("/")
        target = os.environ.get(TUNNEL_TARGET_VAR, "").strip().rstrip("/")
        asked = (host or "").strip().rstrip("/")
        return original(target) if forward and target and asked == forward else original(host)

    tunnel_aware._daedalus_tunnel_aware = True  # type: ignore[attr-defined]
    sensitivity.lane_for_host = tunnel_aware


class DesktopRuntimeManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / CONFIG_REL
        self.known_hosts_path = self.root / KNOWN_HOSTS_REL
        self.log_path = self.root / LOG_REL
        self._lock = threading.RLock()
        self._bridge: threading.Thread | None = None
        self._bridge_owner_token: str | None = None
        self._bridge_process_identity: str | None = None
        self._bridge_start_error = ""
        self._bridge_stop = threading.Event()
        self._tunnel: subprocess.Popen[bytes] | None = None
        self._ollama: ManagedProcess | None = None
        self._ide: subprocess.Popen[bytes] | None = None
        self._ide_docker_managed_id: str | None = None
        self._tunnel_log = None
        self._ollama_log = None
        self._ide_log = None
        self._closed = False
        self._base_trusted = os.environ.get(TRUSTED_HOSTS_VAR, "")
        self._config_error = ""
        self._budget_policy_error = ""
        (
            self._budget_environment_defaults,
            self._caps_environment_defaults,
            self._budget_environment_error,
        ) = self._read_budget_environment()
        self.config = self._load()
        self.apply_environment()
        atexit.register(self.close)

    @staticmethod
    def _read_budget_environment(
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Read cap fallbacks/policy without touching the usage ledger."""

        probe = budget_kernel.Ledger()
        try:
            return {
                "period_ceiling_usd": probe.ceiling_usd(),
                "max_calls": probe.max_calls(),
            }, probe.execution_limit_policy().as_dict(), ""
        except budget_kernel.BudgetError as exc:
            # Keep the desktop repairable, but do not silently replace an
            # invalid monetary policy with a spend-authorising default.
            return (
                dict(DEFAULT_CONFIG["budget"]),
                json.loads(json.dumps(DEFAULT_CONFIG["caps"])),
                str(exc),
            )

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._budget_policy_error = self._budget_environment_error
            return _defaults(
                budget_defaults=self._budget_environment_defaults,
                caps_defaults=self._caps_environment_defaults,
            )
        except (OSError, json.JSONDecodeError) as exc:
            self._config_error = f"cannot read {self.config_path}: {exc}"
            self._budget_policy_error = (
                "desktop settings are unreadable; spend remains refused until "
                "valid budget settings are saved"
            )
            return _defaults(
                budget_defaults=self._budget_environment_defaults,
                caps_defaults=self._caps_environment_defaults,
            )
        try:
            config = normalize_config(
                raw,
                budget_defaults=self._budget_environment_defaults,
                caps_defaults=self._caps_environment_defaults,
            )
        except ValueError as exc:
            self._config_error = f"invalid desktop settings: {exc}"
            self._budget_policy_error = (
                "desktop settings are invalid; spend remains refused until "
                "valid budget settings are saved"
            )
            return _defaults(
                budget_defaults=self._budget_environment_defaults,
                caps_defaults=self._caps_environment_defaults,
            )
        persisted_policy = (
            isinstance(raw, dict)
            and (
                "caps" in raw
                or (
                    isinstance(raw.get("budget"), dict)
                    and "period_ceiling_enabled" in raw["budget"]
                )
            )
        )
        if persisted_policy:
            # A valid persisted desktop policy is authoritative for this
            # process and repairs a stale/invalid deployment environment.
            self._budget_policy_error = ""
        else:
            self._budget_policy_error = self._budget_environment_error
        return config

    def _save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.config_path.with_name(f".{self.config_path.name}.{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps(self.config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            os.replace(tmp, self.config_path)
        except OSError as exc:
            raise DesktopRuntimeError(f"cannot write {self.config_path}: {exc}") from exc

    def _log(self, message: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as out:
                out.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
        except OSError:
            pass

    @staticmethod
    def _creationflags() -> int:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0

    def _child_log(self, label: str):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        out = self.log_path.open("ab", buffering=0)
        out.write(f"\n--- {label} {time.strftime('%Y-%m-%dT%H:%M:%S')} ---\n".encode())
        return out

    def save_settings(self, raw: Any) -> dict[str, Any]:
        with self._lock:
            if not isinstance(raw, dict):
                raise ValueError("settings must be a JSON object")
            incoming = dict(raw)
            budget_supplied = "budget" in incoming
            caps_supplied = "caps" in incoming
            if self._budget_policy_error and not (
                budget_supplied and caps_supplied
            ):
                raise ValueError(
                    "valid explicit budget and caps settings are required to "
                    "repair the unavailable execution-limit policy"
                )
            confirmations: list[tuple[str, bool]] = []
            if not budget_supplied:
                # Older clients know nothing about this section. Their PUT must
                # not silently reset configured positive fallbacks.
                incoming["budget"] = dict(self.config["budget"])
            elif isinstance(incoming["budget"], dict):
                budget_raw = dict(incoming["budget"])
                if "confirm_widening" in budget_raw:
                    legacy_confirmation = budget_raw.pop("confirm_widening")
                    if not isinstance(legacy_confirmation, bool):
                        raise ValueError(
                            "budget.confirm_widening must be a boolean"
                        )
                    confirmations.append(("budget", legacy_confirmation))
                incoming["budget"] = budget_raw

            if caps_supplied and isinstance(incoming["caps"], dict):
                caps_raw = dict(incoming["caps"])
                if "confirm_widening" in caps_raw:
                    caps_confirmation = caps_raw.pop("confirm_widening")
                    if not isinstance(caps_confirmation, bool):
                        raise ValueError(
                            "caps.confirm_widening must be a boolean"
                        )
                    confirmations.append(("caps", caps_confirmation))
                incoming["caps"] = caps_raw
            elif not caps_supplied:
                # A Revision-9 client may still send its one boolean. Project
                # that single choice into the current configured axes without
                # changing any other owner selection.
                current_policy = ExecutionLimitPolicy.from_dict(
                    self.config["caps"]
                )
                legacy_period = (
                    incoming["budget"].get("period_ceiling_enabled")
                    if isinstance(incoming.get("budget"), dict)
                    else None
                )
                if isinstance(legacy_period, bool):
                    configured = current_policy.configured.as_dict()
                    configured["period_usd"] = legacy_period
                    mode = current_policy.mode
                    if mode == "bounded" and not legacy_period:
                        mode = MODE_CUSTOM
                    incoming["caps"] = ExecutionLimitPolicy(
                        mode=mode,
                        configured=LimitAxes.from_dict(configured),
                    ).as_dict()
                else:
                    incoming["caps"] = current_policy.as_dict()

            if len({value for _, value in confirmations}) > 1:
                raise ValueError(
                    "caps.confirm_widening conflicts with legacy "
                    "budget.confirm_widening"
                )
            confirm_widening = confirmations[0][1] if confirmations else False
            new = normalize_config(
                incoming,
                budget_defaults=self.config["budget"],
                caps_defaults=self.config["caps"],
            )
            old_budget = self.config["budget"]
            new_budget = new["budget"]
            old_policy = ExecutionLimitPolicy.from_dict(self.config["caps"])
            new_policy = ExecutionLimitPolicy.from_dict(new["caps"])
            disabled_axes = [
                axis
                for axis, was_enforced in old_policy.effective.as_dict().items()
                if was_enforced and not new_policy.enforces(axis)
            ]
            raised_fallbacks = [
                field
                for field in ("period_ceiling_usd", "max_calls")
                if new_budget[field] > old_budget[field]
            ]
            widening = disabled_axes or raised_fallbacks
            if widening and confirm_widening is not True:
                affected = ", ".join([*disabled_axes, *raised_fallbacks])
                raise ValueError(
                    "caps.confirm_widening=true is required for execution-limit "
                    f"widening affecting: {affected}"
                )

            # All validation and widening consent checks happen before any
            # service stop, file write, environment mutation, or ledger read.
            old_route = (
                self.config["ollama"]["mode"],
                self.config["ollama"]["local_host"],
                json.dumps(self.config["ollama"]["remote"], sort_keys=True),
            )
            new_route = (
                new["ollama"]["mode"],
                new["ollama"]["local_host"],
                json.dumps(new["ollama"]["remote"], sort_keys=True),
            )
            old_ide_route = (
                self.config["ide"]["mode"],
                self.config["ide"]["endpoint"],
                self.config["ide"]["executable"],
                self.config["ide"]["docker_image"],
            )
            new_ide_route = (
                new["ide"]["mode"],
                new["ide"]["endpoint"],
                new["ide"]["executable"],
                new["ide"]["docker_image"],
            )
            if old_route != new_route:
                self.stop_ollama()
            if old_ide_route != new_ide_route:
                self.stop_ide()
            previous = self.config
            self.config = new
            try:
                self._save()
            except DesktopRuntimeError:
                self.config = previous
                raise
            self._config_error = ""
            self._budget_policy_error = ""
            self.apply_environment()
        startup_error = ""
        if new["bridge"]["auto_start"]:
            self.ensure_bridge()
        if new["ollama"]["auto_start"]:
            try:
                self.ensure_ollama()
            except DesktopRuntimeError as exc:
                startup_error = str(exc)
                self._log(f"ollama settings autostart failed: {exc}")
        if new["ide"]["auto_start"]:
            try:
                self.ensure_ide()
            except DesktopRuntimeError as exc:
                startup_error = "; ".join(x for x in (startup_error, str(exc)) if x)
                self._log(f"IDE settings autostart failed: {exc}")
        snap = self.snapshot()
        if startup_error:
            snap["startup_error"] = startup_error
        return snap

    def apply_environment(self) -> None:
        if self._budget_policy_error:
            # A deliberately invalid canonical policy makes every Ledger read
            # fail closed while the settings UI stays available for repair.
            os.environ[ENV_EXECUTION_LIMIT_POLICY] = "{invalid"
        else:
            budget = self.config["budget"]
            policy = ExecutionLimitPolicy.from_dict(self.config["caps"])
            store_limit_policy_in_env(policy)
            os.environ.pop(budget_kernel.ENV_PERIOD_CEILING_ENABLED, None)
            os.environ[budget_kernel.ENV_CEILING] = format(
                budget["period_ceiling_usd"], ".17g"
            )
            os.environ[budget_kernel.ENV_MAX_CALLS] = str(budget["max_calls"])
        o = self.config["ollama"]
        os.environ["OLLAMA_MODEL"] = o["model"]
        trusted = [x.strip() for x in self._base_trusted.split(",") if x.strip()]
        if o["mode"] == "remote_ssh":
            r = o["remote"]
            forward = f"http://127.0.0.1:{r['local_port']}"
            target = f"http://{r['host']}:{r['remote_port']}"
            os.environ["OLLAMA_HOST"] = forward
            os.environ[TUNNEL_FORWARD_VAR] = forward
            os.environ[TUNNEL_TARGET_VAR] = target
            # Consent opens this exact transport; the egress wrapper still
            # classifies it by the physical peer unless that peer is trusted.
            os.environ[REMOTE_OK_VAR] = forward
            if r["trust_remote_host"]:
                numeric = _numeric_host(r["host"])
                if numeric:
                    trusted.append(numeric)
        else:
            os.environ["OLLAMA_HOST"] = o["local_host"]
            for key in (TUNNEL_FORWARD_VAR, TUNNEL_TARGET_VAR, REMOTE_OK_VAR):
                os.environ.pop(key, None)
        if trusted:
            os.environ[TRUSTED_HOSTS_VAR] = ",".join(dict.fromkeys(trusted))
        else:
            os.environ.pop(TRUSTED_HOSTS_VAR, None)

    def bootstrap(self) -> dict[str, Any]:
        if self.config["bridge"]["auto_start"]:
            self.ensure_bridge()
        if self.config["ollama"]["auto_start"]:
            try:
                self.ensure_ollama()
            except DesktopRuntimeError as exc:
                self._log(f"ollama autostart failed: {exc}")
        if self.config["ide"]["auto_start"]:
            try:
                self.ensure_ide()
            except DesktopRuntimeError as exc:
                self._log(f"IDE autostart failed: {exc}")
        return self.snapshot()

    # Bridge ---------------------------------------------------------------

    def _watch_bridge(
        self,
        owner_token: str,
        process_identity: str,
        stop_event: threading.Event,
    ) -> None:
        from . import file_bridge

        try:
            file_bridge.watch(
                str(self.root),
                2.0,
                project="daedalus",
                owner_token=owner_token,
                process_identity=process_identity,
                stop_event=stop_event,
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            with self._lock:
                if self._bridge_owner_token == owner_token:
                    self._bridge_start_error = detail
            self._log(f"bridge failed: {detail}")

    def _bridge_status_is_managed(self, status: dict[str, Any]) -> bool:
        return bool(
            self._bridge
            and self._bridge.is_alive()
            and self._bridge_owner_token
            and self._bridge_process_identity
            and status.get("state") in {"alive", "busy", "wedged"}
            and status.get("pid") == os.getpid()
            and status.get("owner_token") == self._bridge_owner_token
            and status.get("process_identity") == self._bridge_process_identity
        )

    def ensure_bridge(self) -> dict[str, Any]:
        from . import file_bridge

        with self._lock:
            if self._bridge and self._bridge.is_alive():
                thread = self._bridge
            else:
                self._bridge_owner_token = uuid.uuid4().hex
                self._bridge_process_identity = file_bridge.current_process_identity()
                self._bridge_start_error = ""
                self._bridge_stop = threading.Event()
                thread = threading.Thread(
                    target=self._watch_bridge,
                    args=(
                        self._bridge_owner_token,
                        self._bridge_process_identity,
                        self._bridge_stop,
                    ),
                    name="daedalus-file-bridge",
                    daemon=True,
                )
                self._bridge = thread
                thread.start()

        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            status = file_bridge.heartbeat_status()
            with self._lock:
                if self._bridge_status_is_managed(status):
                    return {**status, "managed": True, "last_error": ""}
                start_error = self._bridge_start_error
            if not thread.is_alive():
                break
            time.sleep(0.05)
        status = file_bridge.heartbeat_status()
        with self._lock:
            managed = self._bridge_status_is_managed(status)
            start_error = self._bridge_start_error
        result = {**status, "managed": managed}
        if start_error:
            result["last_error"] = start_error
        elif not managed:
            result.setdefault("last_error", "bridge ownership/readiness not established")
        return result

    # OpenVSCode Server ---------------------------------------------------

    def _probe_ide(self, timeout: float = 1.5) -> tuple[bool, str]:
        endpoint = self.config["ide"]["endpoint"].rstrip("/")
        try:
            with urllib.request.urlopen(endpoint + "/", timeout=timeout) as response:
                response.read(1)
                return 200 <= response.status < 400, ""
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return False, str(exc)

    def _discover_ide_executable(self) -> str:
        configured = self.config["ide"]["executable"]
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = self.root / path
            try:
                path = path.resolve()
            except OSError as exc:
                raise DesktopRuntimeError(
                    f"configured OpenVSCode Server executable is invalid: {exc}"
                ) from exc
            if not path.is_file():
                raise DesktopRuntimeError(
                    f"configured OpenVSCode Server executable does not exist: {path}"
                )
            return str(path)
        for command in ("openvscode-server", "openvscode-server.cmd"):
            found = shutil.which(command)
            if found:
                return found
        raise DesktopRuntimeError(
            "OpenVSCode Server is offline and 'openvscode-server' is not on PATH; "
            "configure ide.executable to an existing installation (runtime downloads are disabled)"
        )

    def _discover_docker_executable(self) -> str:
        executable = shutil.which("docker")
        if not executable:
            raise DesktopRuntimeError(
                "Docker is not installed or is not on PATH; runtime downloads are disabled"
            )
        return executable

    def _docker_exec(self, args: list[str], *, timeout: float = 20.0):
        executable = self._discover_docker_executable()
        try:
            return subprocess.run(
                [executable, *args],
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=self._creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesktopRuntimeError(f"Docker command failed: {exc}") from exc

    @staticmethod
    def _docker_error(result: Any) -> str:
        return str(result.stderr or result.stdout or f"exit {result.returncode}").strip()[:500]

    def _docker_image_error(self) -> str:
        image = self.config["ide"]["docker_image"]
        result = self._docker_exec(["image", "inspect", image])
        if result.returncode == 0:
            return ""
        return (
            f"Docker image {image!r} is not available locally: "
            f"{self._docker_error(result)} (runtime pull/build is disabled)"
        )

    def _docker_inspect_container(
        self,
        reference: str = IDE_DOCKER_CONTAINER,
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any] | None:
        result = self._docker_exec(["container", "inspect", reference], timeout=timeout)
        if result.returncode != 0:
            detail = self._docker_error(result)
            if "no such container" in detail.lower() or "no such object" in detail.lower():
                return None
            raise DesktopRuntimeError(f"cannot inspect Docker IDE container: {detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DesktopRuntimeError("Docker returned invalid container metadata") from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise DesktopRuntimeError("Docker returned unexpected container metadata")
        return payload[0]

    @staticmethod
    def _docker_container_id(container: dict[str, Any]) -> str:
        container_id = str(container.get("Id") or "")
        if not _DOCKER_CONTAINER_ID_RE.fullmatch(container_id):
            raise DesktopRuntimeError("Docker returned an invalid container ID")
        return container_id

    @staticmethod
    def _docker_container_owned(container: dict[str, Any]) -> bool:
        labels = container.get("Config", {}).get("Labels") or {}
        return labels.get(IDE_DOCKER_OWNER_LABEL) == IDE_DOCKER_OWNER_VALUE

    @staticmethod
    def _docker_project_hash(folder: Path) -> str:
        canonical = os.path.normcase(str(folder)).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _docker_mount_source_matches(source: Any, folder: Path) -> bool:
        if not isinstance(source, str) or not source:
            return False
        try:
            mounted = Path(source).resolve()
        except OSError:
            return False
        return os.path.normcase(str(mounted)) == os.path.normcase(str(folder))

    def _docker_container_matches(self, container: dict[str, Any], folder: Path) -> bool:
        config = container.get("Config", {})
        labels = config.get("Labels") or {}
        mounts = container.get("Mounts") or []
        bindings = container.get("HostConfig", {}).get("PortBindings") or {}
        published = bindings.get("3000/tcp") or []
        loopback_publish = (
            len(published) == 1
            and published[0].get("HostIp") == "127.0.0.1"
            and published[0].get("HostPort") == "3000"
        )
        return (
            self._docker_container_owned(container)
            and config.get("Image") == self.config["ide"]["docker_image"]
            and labels.get(IDE_DOCKER_PROJECT_LABEL) == self._docker_project_hash(folder)
            and any(
                mount.get("Type") == "bind"
                and self._docker_mount_source_matches(mount.get("Source"), folder)
                and mount.get("Destination") == IDE_DOCKER_WORKSPACE
                and mount.get("RW") is True
                for mount in mounts
            )
            and loopback_publish
        )

    def _canonical_ide_project(self, project: Any, *, required: bool = False) -> Path | None:
        if project is None or project == "":
            if required:
                raise DesktopRuntimeError("Docker IDE requires a selected project folder")
            return None
        if not isinstance(project, (str, os.PathLike)):
            raise DesktopRuntimeError("IDE project must be a local folder path")
        raw = os.fspath(project)
        if not isinstance(raw, str):
            raise DesktopRuntimeError("IDE project must be a local folder path")
        if not raw or len(raw) > 4096 or any(ord(ch) < 32 for ch in raw):
            raise DesktopRuntimeError("IDE project must be a valid local folder path")
        folder = Path(raw).expanduser()
        if not folder.is_absolute():
            folder = self.root / folder
        try:
            folder = folder.resolve()
        except OSError as exc:
            raise DesktopRuntimeError(f"IDE project path is invalid: {exc}") from exc
        if not folder.is_dir():
            raise DesktopRuntimeError(f"IDE project folder does not exist: {folder}")
        return folder

    def _ide_ui_url(self, project: Any = None) -> str:
        endpoint = self.config["ide"]["endpoint"].rstrip("/")
        folder = self._canonical_ide_project(
            project, required=self.config["ide"]["mode"] == "docker" and project not in (None, "")
        )
        if self.config["ide"]["mode"] == "docker":
            return endpoint + "/?" + urlencode(
                {"folder": IDE_DOCKER_WORKSPACE}, safe="/"
            )
        if folder is None:
            return endpoint + "/"
        # The folder only selects the browser workspace. It is deliberately not
        # passed to Popen, so project input cannot add or alter CLI arguments.
        return endpoint + "/?" + urlencode({"folder": str(folder)})

    def _ide_status(self, project: Any = None) -> dict[str, Any]:
        if self.config["ide"]["mode"] == "docker":
            return self._docker_ide_status(project)
        ok, detail = self._probe_ide()
        running = bool(self._ide and self._ide.poll() is None)
        executable = ""
        discovery_error = ""
        try:
            executable = self._discover_ide_executable()
        except DesktopRuntimeError as exc:
            # A status read must remain observational. Missing installations
            # are reported to the UI and never trigger a download or start.
            discovery_error = str(exc)
        installed = bool(executable)
        return {
            "endpoint": self.config["ide"]["endpoint"],
            "ui_url": self._ide_ui_url(project),
            "installed": installed,
            "available": installed,
            "executable": executable,
            "reachable": ok,
            "last_error": "" if ok else (discovery_error or detail),
            "detail": discovery_error,
            "managed": running,
            "process_running": running,
            "configured_executable": self.config["ide"]["executable"],
            "runtime_downloads": False,
        }

    def ensure_ide(self, project: Any = None) -> dict[str, Any]:
        if self.config["ide"]["mode"] == "docker":
            return self._ensure_docker_ide(project)
        ui_url = self._ide_ui_url(project)
        ok, _ = self._probe_ide()
        if ok:
            status = self._ide_status(project)
            status["ui_url"] = ui_url
            return status
        with self._lock:
            if not (self._ide and self._ide.poll() is None):
                executable = self._discover_ide_executable()
                parsed = urlsplit(self.config["ide"]["endpoint"])
                assert parsed.hostname is not None and parsed.port is not None
                if self._ide_log:
                    try:
                        self._ide_log.close()
                    except OSError:
                        pass
                try:
                    self._ide_log = self._child_log("OpenVSCode Server")
                    self._ide = subprocess.Popen(
                        [
                            executable,
                            "--host",
                            parsed.hostname,
                            "--port",
                            str(parsed.port),
                            "--without-connection-token",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=self._ide_log,
                        stderr=self._ide_log,
                        creationflags=self._creationflags(),
                    )
                except OSError as exc:
                    if self._ide_log:
                        try:
                            self._ide_log.close()
                        except OSError:
                            pass
                        self._ide_log = None
                    raise DesktopRuntimeError(
                        f"cannot start OpenVSCode Server: {exc}"
                    ) from exc
            proc = self._ide
        detail = ""
        end = time.monotonic() + 8
        while proc and proc.poll() is None and time.monotonic() < end:
            ok, detail = self._probe_ide(0.5)
            if ok:
                break
            time.sleep(0.2)
        if not proc or proc.poll() is not None:
            raise DesktopRuntimeError(f"OpenVSCode Server exited; see {self.log_path}")
        status = self._ide_status(project)
        status["ui_url"] = ui_url
        if not status["reachable"] and detail:
            status["last_error"] = detail
        return status

    def _docker_ide_status(self, project: Any = None) -> dict[str, Any]:
        ok, probe_detail = self._probe_ide()
        executable = ""
        detail = ""
        image_available = False
        container: dict[str, Any] | None = None
        try:
            executable = self._discover_docker_executable()
            detail = self._docker_image_error()
            image_available = not detail
            container = self._docker_inspect_container()
        except DesktopRuntimeError as exc:
            detail = str(exc)
        owned = bool(container and self._docker_container_owned(container))
        running = bool(owned and container and container.get("State", {}).get("Running") is True)
        if container is not None:
            if not owned:
                detail = (
                    f"Docker container {IDE_DOCKER_CONTAINER!r} is not owned by Daedalus"
                )
        elif ok and not detail:
            detail = "IDE endpoint is occupied by an unmanaged service"
        reachable = bool(ok and running)
        return {
            "mode": "docker",
            "endpoint": self.config["ide"]["endpoint"],
            "ui_url": self._ide_ui_url(project),
            "installed": image_available,
            "available": image_available,
            "executable": executable,
            "reachable": reachable,
            "last_error": "" if reachable else (detail or probe_detail),
            "detail": detail,
            "managed": running,
            "process_running": running,
            "configured_executable": "",
            "image": self.config["ide"]["docker_image"],
            "container_name": IDE_DOCKER_CONTAINER,
            "runtime_downloads": False,
        }

    def _remove_owned_docker_ide(
        self, container: dict[str, Any], *, timeout: float = 20.0
    ) -> None:
        if not self._docker_container_owned(container):
            raise DesktopRuntimeError(
                f"refusing to remove unowned Docker container {IDE_DOCKER_CONTAINER!r}"
            )
        container_id = self._docker_container_id(container)
        result = self._docker_exec(
            ["container", "rm", "--force", container_id], timeout=timeout
        )
        if result.returncode != 0:
            raise DesktopRuntimeError(
                f"cannot remove Docker IDE container: {self._docker_error(result)}"
            )
        if self._ide_docker_managed_id == container_id:
            self._ide_docker_managed_id = None

    def _ensure_docker_ide(self, project: Any) -> dict[str, Any]:
        folder = self._canonical_ide_project(project, required=True)
        assert folder is not None
        with self._lock:
            image_error = self._docker_image_error()
            if image_error:
                raise DesktopRuntimeError(image_error)
            container = self._docker_inspect_container()
            if container is not None and not self._docker_container_owned(container):
                raise DesktopRuntimeError(
                    f"fixed Docker container name {IDE_DOCKER_CONTAINER!r} is already in use"
                )
            if container is not None and not self._docker_container_matches(container, folder):
                self._remove_owned_docker_ide(container)
                container = None

            if container is None:
                ok, _ = self._probe_ide()
                if ok:
                    raise DesktopRuntimeError("IDE endpoint is occupied by an unmanaged service")
                mount = f"type=bind,source={folder},target={IDE_DOCKER_WORKSPACE}"
                result = self._docker_exec(
                    [
                        "run",
                        "--detach",
                        "--name",
                        IDE_DOCKER_CONTAINER,
                        "--label",
                        f"{IDE_DOCKER_OWNER_LABEL}={IDE_DOCKER_OWNER_VALUE}",
                        "--label",
                        f"{IDE_DOCKER_PROJECT_LABEL}={self._docker_project_hash(folder)}",
                        "--init",
                        "--publish",
                        "127.0.0.1:3000:3000",
                        "--mount",
                        mount,
                        "--pull",
                        "never",
                        self.config["ide"]["docker_image"],
                        "--port",
                        "3000",
                        "--default-folder",
                        IDE_DOCKER_WORKSPACE,
                    ]
                )
            elif container.get("State", {}).get("Running") is not True:
                result = self._docker_exec(
                    ["container", "start", self._docker_container_id(container)]
                )
            else:
                result = None

            if result is not None and result.returncode != 0:
                raise DesktopRuntimeError(
                    f"cannot start Docker IDE container: {self._docker_error(result)}"
                )
            managed = self._docker_inspect_container()
            if managed is None or not self._docker_container_matches(managed, folder):
                raise DesktopRuntimeError(
                    "Docker IDE container metadata does not match the selected project"
                )
            self._ide_docker_managed_id = self._docker_container_id(managed)
        detail = ""
        end = time.monotonic() + 8
        while time.monotonic() < end:
            ok, detail = self._probe_ide(0.5)
            if ok:
                break
            time.sleep(0.2)
        status = self._docker_ide_status(project)
        if not status["reachable"]:
            status["last_error"] = detail or status["last_error"]
        return status

    def stop_ide(
        self,
        *,
        owned_only: bool = False,
        strict: bool = False,
        timeout: float = 8.0,
    ) -> None:
        if self.config["ide"]["mode"] == "docker":
            managed_id = self._ide_docker_managed_id
            if not managed_id:
                return
            deadline = time.monotonic() + max(0.1, timeout)

            def remaining() -> float:
                value = deadline - time.monotonic()
                if value <= 0:
                    raise DesktopRuntimeError("Docker IDE cleanup timed out")
                return value

            with self._lock:
                try:
                    container = self._docker_inspect_container(
                        managed_id, timeout=remaining()
                    )
                    if container is None:
                        self._ide_docker_managed_id = None
                        return
                    inspected_id = self._docker_container_id(container)
                    if inspected_id != managed_id:
                        raise DesktopRuntimeError(
                            "Docker IDE container identity changed during cleanup"
                        )
                    if container is not None and self._docker_container_owned(container):
                        self._remove_owned_docker_ide(
                            container, timeout=remaining()
                        )
                    else:
                        raise DesktopRuntimeError(
                            f"refusing to stop unowned Docker container {managed_id!r}"
                        )
                except DesktopRuntimeError as exc:
                    self._log(f"Docker IDE stop failed: {exc}")
                    if strict:
                        raise
            return
        with self._lock:
            proc, self._ide = self._ide, None
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            if self._ide_log:
                try:
                    self._ide_log.close()
                except OSError:
                    pass
                self._ide_log = None

    # Ollama ---------------------------------------------------------------

    def _probe(self, timeout: float = 1.5) -> tuple[bool, str]:
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        try:
            with urllib.request.urlopen(host + "/api/tags", timeout=timeout) as response:
                json.loads(response.read().decode("utf-8"))
                return 200 <= response.status < 300, ""
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
            return False, str(exc)

    def ensure_ollama(self) -> dict[str, Any]:
        return (
            self.ensure_remote_ollama()
            if self.config["ollama"]["mode"] == "remote_ssh"
            else self.ensure_local_ollama()
        )

    def ensure_local_ollama(self) -> dict[str, Any]:
        ok, detail = self._probe()
        if ok:
            return {"mode": "local", "running": True, "reachable": True, "detail": ""}
        with self._lock:
            if not (self._ollama and self._ollama.poll() is None):
                resolved = runtime_registry.resolve_runtime_command("ollama_cli")
                exe = str(Path(resolved).resolve()) if resolved else ""
                if not exe:
                    raise DesktopRuntimeError(
                        "Ollama is offline and its executable was not found on PATH "
                        "or a supported install location"
                    )
                service_cwd = self.root / "runs" / "services" / "ollama"
                try:
                    service_cwd.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise DesktopRuntimeError(
                        f"cannot prepare the local Ollama service directory: {exc}"
                    ) from exc
                frozen_root = _frozen_windows_runtime_root()
                child_env = _ollama_child_environment(os.environ, frozen_root)
                self._ollama_log = self._child_log("local ollama")
                try:
                    self._ollama = _spawn_ollama_process(
                        [exe, "serve"],
                        cwd=service_cwd,
                        env=child_env,
                        stdout=self._ollama_log,
                        stderr=self._ollama_log,
                        frozen_root=frozen_root,
                    )
                except Exception as exc:
                    try:
                        self._ollama_log.close()
                    except OSError:
                        pass
                    self._ollama_log = None
                    raise DesktopRuntimeError(f"cannot start local Ollama: {exc}") from exc
            proc = self._ollama
        end = time.monotonic() + 6
        while proc and proc.poll() is None and time.monotonic() < end:
            ok, detail = self._probe(0.5)
            if ok:
                break
            time.sleep(0.2)
        return {
            "mode": "local",
            "running": bool(proc and proc.poll() is None),
            "reachable": ok,
            "detail": detail,
        }

    # SSH ------------------------------------------------------------------

    def _remote(self) -> dict[str, Any]:
        return self.config["ollama"]["remote"]

    def _pin_host_key(self) -> None:
        r = self._remote()
        fp = r["host_key_fingerprint"]
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        if not fp:
            if self.known_hosts_path.exists() and self.known_hosts_path.stat().st_size:
                return
            raise DesktopRuntimeError(
                "First SSH connection requires the server's SHA256 host-key fingerprint"
            )
        keyscan, keygen = shutil.which("ssh-keyscan"), shutil.which("ssh-keygen")
        if not keyscan or not keygen:
            raise DesktopRuntimeError("ssh-keyscan and ssh-keygen are required")
        try:
            scan = subprocess.run(
                [keyscan, "-T", "5", "-p", str(r["port"]), r["host"]],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
                creationflags=self._creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesktopRuntimeError(f"SSH host-key scan failed: {exc}") from exc
        keys = [
            line.strip()
            for line in scan.stdout.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        matched: list[str] = []
        for key in keys:
            name = ""
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.known_hosts_path.parent, delete=False
                ) as tmp:
                    tmp.write(key + "\n")
                    name = tmp.name
                checked = subprocess.run(
                    [keygen, "-lf", name, "-E", "sha256"],
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                    creationflags=self._creationflags(),
                )
                if checked.returncode == 0 and fp in checked.stdout.split():
                    matched.append(key)
            finally:
                if name:
                    try:
                        Path(name).unlink()
                    except OSError:
                        pass
        if not matched:
            raise DesktopRuntimeError("SSH host-key fingerprint mismatch; connection refused")
        tmp = self.known_hosts_path.with_name(f".{self.known_hosts_path.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(matched) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.known_hosts_path)

    def _ssh(self) -> list[str]:
        r = self._remote()
        exe = shutil.which("ssh")
        if not exe:
            raise DesktopRuntimeError("OpenSSH client 'ssh' is not on PATH")
        args = [
            exe, "-T", "-p", str(r["port"]),
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
        ]
        if r["identity_file"]:
            key = Path(r["identity_file"]).expanduser()
            if not key.is_file():
                raise DesktopRuntimeError(f"SSH identity file does not exist: {key}")
            args += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
        return args

    def _target(self) -> str:
        r = self._remote()
        return f"{r['user']}@{r['host']}"

    def _start_remote_service(self) -> None:
        method = self._remote()["start_method"]
        if method == "none":
            return
        command = (
            "sudo -n systemctl start ollama && systemctl is-active --quiet ollama"
            if method == "systemd"
            else (
                'powershell.exe -NoProfile -NonInteractive -Command '
                '"$p=Get-Process ollama -ErrorAction SilentlyContinue; '
                "if (-not $p) { Start-Process -WindowStyle Hidden "
                "-FilePath 'ollama' -ArgumentList 'serve' }\""
            )
        )
        try:
            run = subprocess.run(
                self._ssh() + [self._target(), command],
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=self._creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesktopRuntimeError(f"remote Ollama start failed: {exc}") from exc
        if run.returncode:
            detail = (run.stderr or run.stdout or f"exit {run.returncode}").strip()
            if method == "systemd":
                detail += " (use passwordless permission for 'systemctl start ollama', or 'already running')"
            raise DesktopRuntimeError(f"remote Ollama start failed: {detail[:500]}")

    def ensure_remote_ollama(self) -> dict[str, Any]:
        if self.config["ollama"]["mode"] != "remote_ssh":
            raise DesktopRuntimeError("remote Ollama is not selected")
        self._pin_host_key()
        with self._lock:
            if not (self._tunnel and self._tunnel.poll() is None):
                self._start_remote_service()
                r = self._remote()
                self._tunnel_log = self._child_log("ollama ssh tunnel")
                args = self._ssh() + [
                    "-o", "ExitOnForwardFailure=yes",
                    "-L", f"127.0.0.1:{r['local_port']}:127.0.0.1:{r['remote_port']}",
                    self._target(),
                    "cat",
                ]
                self._tunnel = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=self._tunnel_log,
                    stderr=self._tunnel_log,
                    creationflags=self._creationflags(),
                )
            proc = self._tunnel
        ok, detail = False, ""
        end = time.monotonic() + 8
        while proc and proc.poll() is None and time.monotonic() < end:
            ok, detail = self._probe(0.5)
            if ok:
                break
            time.sleep(0.25)
        if not proc or proc.poll() is not None:
            raise DesktopRuntimeError(f"SSH tunnel exited; see {self.log_path}")
        return {
            "mode": "remote_ssh",
            "running": True,
            "reachable": ok,
            "detail": detail,
            "target": os.environ.get(TUNNEL_TARGET_VAR, ""),
        }

    def stop_ollama_transport(self) -> None:
        with self._lock:
            proc, self._tunnel = self._tunnel, None
            if proc and proc.poll() is None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                    proc.terminate()
                    proc.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            if self._tunnel_log:
                try:
                    self._tunnel_log.close()
                except OSError:
                    pass
                self._tunnel_log = None

    def stop_ollama(self) -> None:
        """Stop only Ollama processes whose lifecycle this desktop owns."""

        self.stop_ollama_transport()
        with self._lock:
            proc, self._ollama = self._ollama, None
            try:
                # Always close the ManagedProcess.  On Windows releasing its
                # Job Object kills descendants even when the direct parent has
                # already exited, which is the exact orphan-server failure mode.
                if proc is not None:
                    proc.close(grace_s=2.0)
            except Exception as exc:
                self._log(f"local Ollama stop failed: {exc}")
            finally:
                if self._ollama_log:
                    try:
                        self._ollama_log.close()
                    except OSError:
                        pass
                    self._ollama_log = None

    def close(self, *, strict: bool = False, timeout: float = 8.0) -> None:
        self._closed = True
        self._bridge_stop.set()
        cleanup_error: DesktopRuntimeError | None = None
        try:
            self.stop_ide(owned_only=True, strict=strict, timeout=timeout)
        except DesktopRuntimeError as exc:
            cleanup_error = exc
        self.stop_ollama()
        if strict and cleanup_error is not None:
            raise cleanup_error

    def _budget_status(self) -> dict[str, Any]:
        configured = self.config["budget"]
        policy = ExecutionLimitPolicy.from_dict(self.config["caps"])
        effective = policy.effective
        base: dict[str, Any] = {
            "available": False,
            "mode": policy.mode,
            "caps": policy.as_dict(),
            "configured_caps": policy.configured.as_dict(),
            "effective_caps": effective.as_dict(),
            "limit_policy_fingerprint_sha256": policy.fingerprint_sha256,
            "period_ceiling_enabled": effective.period_usd,
            "period_ceiling_usd": configured["period_ceiling_usd"],
            "effective_period_ceiling_usd": (
                configured["period_ceiling_usd"] if effective.period_usd else None
            ),
            "remaining_period_usd": None,
            "spent_usd": None,
            "reserved_usd": None,
            "committed_usd": None,
            "envelope_hold_usd": None,
            "max_calls": configured["max_calls"],
            "effective_max_calls": (
                configured["max_calls"] if effective.billable_calls else None
            ),
            "remaining_calls": None,
            "remaining_billable_calls": None,
            "calls": None,
            "open_calls": None,
            "period": None,
            "period_key": None,
            "call_ceiling_enforced": effective.billable_calls,
            "billable_call_ceiling_enabled": effective.billable_calls,
            "explicit_envelope_ceiling_enforced": effective.mission_spend,
            "mission_spend_ceiling_enabled": effective.mission_spend,
            "last_error": "",
        }
        if self._budget_policy_error:
            base["last_error"] = self._budget_policy_error
            return base
        try:
            state = budget_kernel.ledger().state()
        except (budget_kernel.BudgetError, OSError) as exc:
            base["last_error"] = str(exc)
            return base
        return {
            **base,
            "available": True,
            "mode": state.limit_policy_mode,
            "caps": {
                "mode": state.limit_policy_mode,
                "configured": dict(state.configured_limit_axes or {}),
            },
            "configured_caps": dict(state.configured_limit_axes or {}),
            "effective_caps": dict(state.effective_limit_axes or {}),
            "limit_policy_fingerprint_sha256": (
                state.limit_policy_fingerprint_sha256
            ),
            "period_ceiling_enabled": state.period_ceiling_enabled,
            "period_ceiling_usd": state.ceiling_usd,
            "effective_period_ceiling_usd": state.effective_period_ceiling_usd,
            "remaining_period_usd": state.remaining_usd,
            "spent_usd": state.spent_usd,
            "reserved_usd": state.reserved_usd,
            "committed_usd": state.committed_usd,
            "envelope_hold_usd": state.envelope_hold_usd,
            "max_calls": state.max_calls,
            "effective_max_calls": state.effective_max_calls,
            "remaining_calls": state.remaining_calls,
            "remaining_billable_calls": state.remaining_calls,
            "calls": state.calls,
            "open_calls": state.open_calls,
            "period": state.period,
            "period_key": state.period_key,
            "call_ceiling_enforced": state.billable_call_ceiling_enabled,
            "billable_call_ceiling_enabled": (
                state.billable_call_ceiling_enabled
            ),
            "explicit_envelope_ceiling_enforced": (
                state.mission_spend_ceiling_enabled
            ),
            "mission_spend_ceiling_enabled": (
                state.mission_spend_ceiling_enabled
            ),
            "last_error": "",
        }

    def snapshot(self) -> dict[str, Any]:
        from . import file_bridge

        ok, err = self._probe()
        bridge_status = file_bridge.heartbeat_status()
        r = self.config["ollama"]["remote"]
        budget_status = self._budget_status()
        caps_status = {
            "available": budget_status["available"],
            "mode": budget_status["mode"],
            "configured": budget_status["configured_caps"],
            "effective": budget_status["effective_caps"],
            "fingerprint_sha256": budget_status[
                "limit_policy_fingerprint_sha256"
            ],
            "last_error": budget_status["last_error"],
            "external_limits_remain": True,
            "ariadne_campaign_live": False,
        }
        return {
            "config": self.config,
            "config_path": str(self.config_path),
            "config_error": self._config_error,
            "budget": budget_status,
            "caps": caps_status,
            "budget_error": budget_status["last_error"],
            "credential_policy": {
                "ssh_key_only": True,
                "stores_passwords": False,
                "stores_private_key_bytes": False,
                "host_key_verification": "strict",
            },
            "services": {
                "bridge": {
                    **bridge_status,
                    "managed": self._bridge_status_is_managed(bridge_status),
                    "last_error": self._bridge_start_error,
                },
                "ollama": {
                    "mode": self.config["ollama"]["mode"],
                    "endpoint": os.environ.get("OLLAMA_HOST", ""),
                    "physical_target": os.environ.get(TUNNEL_TARGET_VAR, ""),
                    "reachable": ok,
                    "last_error": "" if ok else err,
                    "tunnel_running": bool(self._tunnel and self._tunnel.poll() is None),
                    "local_process_running": bool(self._ollama and self._ollama.poll() is None),
                    "host_key_pinned": bool(
                        r["host_key_fingerprint"]
                        or (self.known_hosts_path.exists() and self.known_hosts_path.stat().st_size)
                    ),
                },
                "ide": self._ide_status(),
            },
        }


def install_web_integration(web_api: Any, manager: DesktopRuntimeManager) -> None:
    """Add desktop routes without creating a second HTTP/control server."""
    base = web_api.DaedalusHandler

    class ManagedHandler(base):
        def _handle_get(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/host/capabilities":
                snapshot = manager.snapshot()
                projector = getattr(web_api, "_host_capabilities", None)
                capabilities = (
                    projector("desktop", snapshot)
                    if callable(projector)
                    else {
                        "host_mode": "desktop",
                        "can_manage_openvscode": bool(
                            snapshot.get("services", {}).get("ide", {}).get("available") is True),
                        "can_open_external_editor": bool(
                            snapshot.get("services", {}).get("ide", {}).get("reachable") is True),
                        "can_send_editor_commands": False,
                        "editor_commands_require_session": True,
                    }
                )
                self._send_json(web_api.core.envelope(
                    None, host_capabilities=capabilities))
                return
            if path == "/api/desktop/settings":
                self._send_json(web_api.core.envelope(None, desktop=manager.snapshot()))
                return
            super()._handle_get()

        def _handle_put(self) -> None:
            if urlsplit(self.path).path == "/api/desktop/settings":
                try:
                    snap = manager.save_settings(web_api._read_body(self))
                    web_api.runtime_registry.reset_status_cache()
                    self._send_json(web_api.core.envelope(None, desktop=snap))
                except (ValueError, DesktopRuntimeError) as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            super()._handle_put()

        def _handle_post(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path == "/api/desktop/shutdown":
                    expected = (
                        getattr(self.server, "daedalus_desktop_startup_nonce", "")
                        or ""
                    )
                    supplied = self.headers.get("X-Daedalus-Desktop-Nonce", "")
                    if not expected or not hmac.compare_digest(supplied, expected):
                        self._send_json(
                            {"ok": False, "error": "desktop parent nonce required"},
                            status=403,
                        )
                        return
                    manager.close(strict=True, timeout=6.0)
                    result = {"closed": True}
                elif path == "/api/desktop/services/bridge/start":
                    result = manager.ensure_bridge()
                elif path == "/api/desktop/services/ollama/start":
                    result = manager.ensure_ollama()
                    web_api.runtime_registry.reset_status_cache()
                elif path == "/api/desktop/services/ollama/stop":
                    manager.stop_ollama()
                    web_api.runtime_registry.reset_status_cache()
                    result = manager.snapshot()["services"]["ollama"]
                elif path == "/api/desktop/services/ide/start":
                    body = web_api._read_body(self)
                    if not isinstance(body, dict):
                        raise DesktopRuntimeError("request body must be a JSON object")
                    project_root = resolve_registered_project_root(body.get("project"))
                    result = manager.ensure_ide(project_root)
                elif path == "/api/desktop/services/ide/stop":
                    manager.stop_ide(strict=True)
                    result = manager.snapshot()["services"]["ide"]
                else:
                    super()._handle_post()
                    return
                self._send_json(web_api.core.envelope(None, service=result))
            except ProjectRegistryUnavailable as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=503)
            except (ValueError, DesktopRuntimeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    web_api.DaedalusHandler = ManagedHandler
