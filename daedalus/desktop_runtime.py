"""Desktop projection plus the single pinned owner for admitted effects.

v0.1.6 starts no managed bridge, Ollama, IDE, Docker, or SSH child.  The
desktop may observe an explicitly requested loopback Ollama endpoint. It owns
no external/adopted service handle and exposes no termination authority.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import budget as budget_kernel
from .interfaces.desktop import configuration as desktop_configuration
from .interfaces.desktop import effects as desktop_effects
from .interfaces.desktop import http as desktop_http
from .interfaces.desktop import projection as desktop_projection
from .interfaces.desktop import settings as desktop_settings
from .limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    ExecutionLimitPolicy,
    LimitAxes,
    LimitPolicyError,
    MODE_CUSTOM,
)
from .foundation.projects import (
    ProjectRegistryUnavailable,
    resolve_registered_project_root,
)

CONFIG_REL = Path("config/connections.json")

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


class DesktopRuntimeError(RuntimeError):
    pass


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Keep an admitted loopback probe on its exact endpoint."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


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


def _normalize_loaded_config(
    raw: Any,
    *,
    budget_defaults: dict[str, Any] | None = None,
    caps_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return desktop_configuration.normalize_config(
        raw,
        budget_defaults=budget_defaults,
        caps_defaults=caps_defaults,
        allow_legacy_remote=True,
    )


def install_tunnel_egress_policy() -> None:
    """Compatibility no-op: v0.1.6 has no SSH tunnel transport."""


class DesktopRuntimeManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / CONFIG_REL
        self._lock = threading.RLock()
        self._bridge_start_error = ""
        self._ollama_observation: dict[str, Any] = {
            "observed": False,
            "endpoint": DEFAULT_CONFIG["ollama"]["local_host"],
            "observed_at": None,
            "reachable": False,
            "last_error": "not probed by the read-only desktop projection",
        }
        self._closed = False
        # Install the narrower effect owner with the manager itself. Settings
        # persistence and exact Ollama observation are Python entrypoints too;
        # neither depends on whether the HTTP facade was installed first.
        self._effect_owner = desktop_effects.DesktopEffectOwner(
            self, error_type=DesktopRuntimeError
        )
        self._base_trusted = os.environ.get(TRUSTED_HOSTS_VAR, "")
        self._config_error = ""
        self._budget_policy_error = ""
        (
            self._budget_environment_defaults,
            self._caps_environment_defaults,
            self._budget_environment_error,
        ) = self._read_budget_environment()
        self.config = self._load()
        self._effect_owner._apply_environment_from(
            self.config,
            budget_policy_error=self._budget_policy_error,
        )

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
            normalize_config=_normalize_loaded_config,
        )

    def _require_effect_owner(self) -> desktop_effects.DesktopEffectOwner:
        owner = getattr(self, "_effect_owner", None)
        if (
            not isinstance(owner, desktop_effects.DesktopEffectOwner)
            or owner.manager is not self
        ):
            raise desktop_effects.DesktopEffectUnavailable(
                "desktop operation requires this manager's installed effect owner"
            )
        return owner

    def save_settings(self, raw: Any) -> dict[str, Any]:
        return self._require_effect_owner().save_settings(raw)

    def bootstrap(self) -> dict[str, Any]:
        return self._require_effect_owner().bootstrap()

    # Bridge ---------------------------------------------------------------

    def _bridge_status_is_managed(self, status: dict[str, Any]) -> bool:
        return desktop_projection.bridge_status_is_managed(self, status)

    def ensure_bridge(self) -> dict[str, Any]:
        return self._require_effect_owner().start_bridge()

    # OpenVSCode Server ---------------------------------------------------

    def _ide_ui_url(
        self,
        project: Any = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> str:
        # v0.1.6 does not resolve, inspect, or expose a project path because no
        # IDE capability is available. Keep only the configured loopback URL.
        del project
        generation = self.config if config is None else config
        return generation["ide"]["endpoint"].rstrip("/") + "/"

    def _ide_status(
        self,
        project: Any = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return desktop_projection.ide_status(
            self,
            project,
            error_type=DesktopRuntimeError,
            config=config,
        )

    def ensure_ide(self, project: Any = None) -> dict[str, Any]:
        return self._require_effect_owner().start_ide(project)

    def stop_ide(
        self,
        *,
        owned_only: bool = False,
        strict: bool = False,
        timeout: float = 8.0,
    ) -> None:
        del owned_only
        self._require_effect_owner().stop_ide(
            strict=strict,
            timeout=timeout,
        )

    # Ollama ---------------------------------------------------------------

    def _probe(
        self,
        timeout: float = 1.5,
        *,
        endpoint: str | None = None,
        switch: Any | None = None,
    ) -> tuple[bool, str]:
        """Read at most 1 MiB from one admitted endpoint by a total deadline."""

        if switch is None or not callable(getattr(switch, "checkpoint", None)):
            raise desktop_effects.DesktopEffectUnavailable(
                "Ollama network probe requires an authorized kill-switch checkpoint"
            )
        host = (
            endpoint
            if endpoint is not None
            else os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        ).rstrip("/")
        deadline = time.monotonic() + max(0.001, float(timeout))
        body_limit = 1024 * 1024
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                _RefuseRedirects(),
            )
            switch.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Ollama probe exceeded its deadline before open")
            with opener.open(
                host + "/api/tags",
                timeout=remaining,
            ) as response:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Ollama probe exceeded its deadline")
                status = getattr(response, "status", None)
                if type(status) is not int or not 200 <= status < 300:
                    raise ValueError("Ollama probe returned a non-success HTTP status")
                body = bytearray()
                read_once = getattr(response, "read1", None)
                if not callable(read_once):
                    read_once = response.read
                while len(body) <= body_limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Ollama probe exceeded its deadline")
                    raw = getattr(getattr(response, "fp", None), "raw", None)
                    sock = getattr(raw, "_sock", None)
                    if sock is not None and hasattr(sock, "settimeout"):
                        sock.settimeout(remaining)
                    switch.checkpoint()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "Ollama probe exceeded its deadline before read"
                        )
                    if sock is not None and hasattr(sock, "settimeout"):
                        sock.settimeout(remaining)
                    chunk = read_once(
                        min(64 * 1024, body_limit + 1 - len(body))
                    )
                    if not chunk:
                        break
                    body.extend(chunk)
                    if time.monotonic() > deadline:
                        raise TimeoutError("Ollama probe exceeded its deadline")
                if len(body) > body_limit:
                    raise ValueError("Ollama probe response exceeds 1 MiB")

                def unique_object(
                    pairs: list[tuple[str, Any]],
                ) -> dict[str, Any]:
                    value: dict[str, Any] = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError(
                                f"Ollama /api/tags contains duplicate key {key!r}"
                            )
                        value[key] = item
                    return value

                def reject_nonfinite(value: str) -> None:
                    raise ValueError(
                        f"Ollama /api/tags contains non-finite number {value}"
                    )

                payload = json.loads(
                    bytes(body).decode("utf-8"),
                    object_pairs_hook=unique_object,
                    parse_constant=reject_nonfinite,
                )
                if time.monotonic() > deadline:
                    raise TimeoutError("Ollama probe exceeded its deadline")
                if type(payload) is not dict or set(payload) != {"models"}:
                    raise ValueError(
                        "Ollama /api/tags must return exactly a models object"
                    )
                models = payload["models"]
                if type(models) is not list or any(
                    type(model) is not dict
                    or type(model.get("name")) is not str
                    or not model["name"].strip()
                    for model in models
                ):
                    raise ValueError(
                        "Ollama /api/tags models must be a list of named objects"
                    )
                if time.monotonic() > deadline:
                    raise TimeoutError("Ollama probe exceeded its deadline")
                return True, ""
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
            return False, str(exc)

    def ensure_ollama(self) -> dict[str, Any]:
        return self._require_effect_owner().start_ollama()

    def ensure_local_ollama(self) -> dict[str, Any]:
        return self.ensure_ollama()

    def _adopt_local_ollama_owned(
        self,
        endpoint: str,
        *,
        switch: Any,
    ) -> dict[str, Any]:
        ok, detail = self._probe(endpoint=endpoint, switch=switch)
        if ok:
            result = {
                "mode": "local",
                "running": True,
                "reachable": True,
                "detail": "",
            }
            self._ollama_observation = {
                "observed": True,
                "endpoint": endpoint,
                "observed_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "reachable": True,
                "last_error": "",
            }
            return result
        self._ollama_observation = {
            "observed": True,
            "endpoint": endpoint,
            "observed_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
            "reachable": False,
            "last_error": detail,
        }
        raise desktop_effects.DesktopOllamaUnreachable(
            f"{desktop_effects.MANAGED_OLLAMA_UNAVAILABLE}; loopback probe failed: {detail}"
        )

    # SSH ------------------------------------------------------------------

    def ensure_remote_ollama(self) -> dict[str, Any]:
        return self._require_effect_owner().start_ollama()

    def stop_ollama(self) -> None:
        self._require_effect_owner().stop_ollama()

    def close(self, *, strict: bool = False, timeout: float = 8.0) -> None:
        if self._closed:
            return

        self._require_effect_owner().close(strict=strict, timeout=timeout)

    def _budget_status(
        self,
        *,
        config: dict[str, Any] | None = None,
        policy_error: str | None = None,
    ) -> dict[str, Any]:
        return desktop_projection.budget_status(
            self,
            budget_kernel=budget_kernel,
            execution_limit_policy=ExecutionLimitPolicy,
            config=config,
            policy_error=policy_error,
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
