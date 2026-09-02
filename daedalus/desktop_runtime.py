"""Desktop-owned lifecycle for the file bridge, Ollama, and local IDE."""
from __future__ import annotations

import atexit
import hashlib
import hmac
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
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from . import budget as budget_kernel
from .orchestration import runtime_registry
from .interfaces.desktop import configuration as desktop_configuration
from .interfaces.desktop import http as desktop_http
from .interfaces.desktop import lifecycle as desktop_lifecycle
from .interfaces.desktop import projection as desktop_projection
from .interfaces.desktop import settings as desktop_settings
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
IDE_DOCKER_IMAGE = desktop_configuration.DEFAULT_IDE_DOCKER_IMAGE
IDE_DOCKER_OWNER_LABEL = "dev.daedalus.desktop.service"
IDE_DOCKER_OWNER_VALUE = "openvscode"
IDE_DOCKER_PROJECT_LABEL = "dev.daedalus.desktop.project-sha256"

DEFAULT_CONFIG: dict[str, Any] = desktop_configuration.DEFAULT_CONFIG

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
    return desktop_configuration.defaults(
        budget_defaults=budget_defaults,
        caps_defaults=caps_defaults,
    )


def _port(value: Any, name: str, low: int = 1) -> int:
    return desktop_configuration.port(value, name, low)


def _loopback_endpoint(value: Any) -> str:
    return desktop_configuration.loopback_endpoint(value)


def _ide_endpoint(value: Any) -> str:
    return desktop_configuration.ide_endpoint(value)


def _numeric_host(value: str) -> str | None:
    return desktop_configuration.numeric_host(value)


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
    return desktop_configuration.normalize_config(
        raw,
        budget_defaults=budget_defaults,
        caps_defaults=caps_defaults,
    )


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
        return desktop_settings.read_budget_environment(
            budget_kernel=budget_kernel,
            default_config=DEFAULT_CONFIG,
            json_module=json,
        )

    def _load(self) -> dict[str, Any]:
        return desktop_settings.load(
            self,
            json_module=json,
            defaults=_defaults,
            normalize_config=normalize_config,
        )

    def _save(self) -> None:
        desktop_settings.save(
            self,
            json_module=json,
            os_module=os,
            error_type=DesktopRuntimeError,
        )

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
        return desktop_settings.save_settings(
            self,
            raw,
            json_module=json,
            normalize_config=normalize_config,
            execution_limit_policy=ExecutionLimitPolicy,
            limit_axes=LimitAxes,
            mode_custom=MODE_CUSTOM,
            error_type=DesktopRuntimeError,
        )

    def apply_environment(self) -> None:
        desktop_settings.apply_environment(
            self,
            environ=os.environ,
            budget_kernel=budget_kernel,
            env_execution_limit_policy=ENV_EXECUTION_LIMIT_POLICY,
            execution_limit_policy=ExecutionLimitPolicy,
            store_limit_policy_in_env=store_limit_policy_in_env,
            numeric_host=_numeric_host,
            tunnel_forward_var=TUNNEL_FORWARD_VAR,
            tunnel_target_var=TUNNEL_TARGET_VAR,
            remote_ok_var=REMOTE_OK_VAR,
            trusted_hosts_var=TRUSTED_HOSTS_VAR,
        )

    def bootstrap(self) -> dict[str, Any]:
        return desktop_lifecycle.bootstrap(self, error_type=DesktopRuntimeError)

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
        return desktop_projection.bridge_status_is_managed(self, status)

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
        return desktop_projection.ide_status(
            self,
            project,
            error_type=DesktopRuntimeError,
        )

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
        desktop_lifecycle.close(
            self,
            strict=strict,
            timeout=timeout,
            error_type=DesktopRuntimeError,
        )

    def _budget_status(self) -> dict[str, Any]:
        return desktop_projection.budget_status(
            self,
            budget_kernel=budget_kernel,
            execution_limit_policy=ExecutionLimitPolicy,
        )

    def snapshot(self) -> dict[str, Any]:
        from . import file_bridge

        return desktop_projection.snapshot(
            self,
            file_bridge=file_bridge,
            environ=os.environ,
            tunnel_target_var=TUNNEL_TARGET_VAR,
        )


def install_web_integration(web_api: Any, manager: DesktopRuntimeManager) -> None:
    """Add desktop routes without creating a second HTTP/control server."""
    desktop_http.install_web_integration(
        web_api,
        manager,
        desktop_error=DesktopRuntimeError,
        project_registry_unavailable=ProjectRegistryUnavailable,
        resolve_project_root=resolve_registered_project_root,
        compare_digest=hmac.compare_digest,
        split_url=urlsplit,
    )
