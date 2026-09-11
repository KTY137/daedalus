"""Pure desktop configuration defaults and whitelist normalization.

This module owns no persistence, environment mutation, process management, or
effect entrypoint.  ``daedalus.desktop_runtime`` remains the compatibility
facade and resolves these functions per call while the strangler is active.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from ...kernel.policy.ledger import DEFAULT_CEILING_USD, DEFAULT_MAX_CALLS
from ...kernel.policy.limits import (
    ExecutionLimitPolicy,
    LimitAxes,
    LimitPolicyError,
    MODE_CUSTOM,
)


DEFAULT_IDE_DOCKER_IMAGE = "daedalus/openvscode-server:1.109.5"

DEFAULT_CONFIG: dict[str, Any] = {
    "bridge": {"auto_start": False},
    "budget": {
        "period_ceiling_usd": DEFAULT_CEILING_USD,
        "max_calls": DEFAULT_MAX_CALLS,
    },
    "caps": ExecutionLimitPolicy().as_dict(),
    "ide": {
        "mode": "native",
        "auto_start": False,
        "endpoint": "http://127.0.0.1:3000",
        "executable": "",
        "docker_image": DEFAULT_IDE_DOCKER_IMAGE,
    },
    "ollama": {
        "mode": "local",
        "auto_start": False,
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
_FP_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_IDE_DOCKER_IMAGE_RE = re.compile(
    r"^(?:daedalus|gitpod)/openvscode-server(?:"
    r":[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9_.-]+)?"
    r"|@sha256:[0-9a-f]{64})$"
)

_TOP_LEVEL_KEYS = frozenset(("bridge", "budget", "caps", "ide", "ollama"))
_BRIDGE_KEYS = frozenset(("auto_start",))
_BUDGET_KEYS = frozenset(
    ("period_ceiling_enabled", "period_ceiling_usd", "max_calls")
)
_IDE_KEYS = frozenset(
    ("mode", "auto_start", "endpoint", "executable", "docker_image")
)
_OLLAMA_KEYS = frozenset(("mode", "auto_start", "model", "local_host", "remote"))
_REMOTE_KEYS = frozenset(
    (
        "host",
        "user",
        "port",
        "identity_file",
        "host_key_fingerprint",
        "local_port",
        "remote_port",
        "start_method",
        "trust_remote_host",
    )
)


def _object(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{name} settings must be a JSON object")
    return value


def _keys(value: dict[str, Any], allowed: frozenset[str], name: str) -> None:
    unsupported = sorted(str(key) for key in value if key not in allowed)
    if unsupported:
        raise ValueError(f"unsupported {name} settings: {', '.join(unsupported)}")


def _string(value: Any, name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be a string")
    return value.strip()


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def defaults(
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


def port(value: Any, name: str, low: int = 1) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be a TCP port")
    if not low <= value <= 65535:
        raise ValueError(f"{name} must be between {low} and 65535")
    return value


def loopback_endpoint(value: Any) -> str:
    raw = _string(value, "ollama.local_host").rstrip("/")
    try:
        parsed = urlsplit(raw)
        host, resolved_port = parsed.hostname or "", parsed.port
        local = bool(ipaddress.ip_address(host).is_loopback)
    except (ValueError, UnicodeError):
        raise ValueError("local_host must look like http://127.0.0.1:11434") from None
    if (
        not local
        or parsed.scheme != "http"
        or resolved_port is None
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


def ide_endpoint(value: Any) -> str:
    raw = _string(value, "ide.endpoint").rstrip("/")
    try:
        parsed = urlsplit(raw)
        host, resolved_port = parsed.hostname or "", parsed.port
        local = bool(ipaddress.ip_address(host).is_loopback)
    except (ValueError, UnicodeError):
        raise ValueError("ide.endpoint must look like http://127.0.0.1:3000") from None
    if (
        not local
        or parsed.scheme != "http"
        or resolved_port is None
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("ide.endpoint must look like http://127.0.0.1:3000")
    return raw


def numeric_host(value: str) -> str | None:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if (
        addr.is_unspecified
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_link_local
    ):
        return None
    return str(addr)


def normalize_config(
    raw: Any,
    *,
    budget_defaults: dict[str, Any] | None = None,
    caps_defaults: dict[str, Any] | None = None,
    allow_legacy_remote: bool = False,
    current_remote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Whitelist settings. Passwords, tokens, key bytes and commands are invalid."""
    if type(raw) is not dict:
        raise ValueError("settings must be a JSON object")
    _keys(raw, _TOP_LEVEL_KEYS, "top-level")
    bridge = _object(raw["bridge"], "bridge") if "bridge" in raw else {}
    budget = _object(raw["budget"], "budget") if "budget" in raw else {}
    caps = _object(raw["caps"], "caps") if "caps" in raw else None
    ide = _object(raw["ide"], "ide") if "ide" in raw else {}
    ollama = _object(raw["ollama"], "ollama") if "ollama" in raw else {}
    remote = (
        _object(ollama["remote"], "ollama.remote")
        if "remote" in ollama
        else {}
    )
    _keys(bridge, _BRIDGE_KEYS, "bridge")
    _keys(budget, _BUDGET_KEYS, "budget")
    _keys(ide, _IDE_KEYS, "ide")
    _keys(ollama, _OLLAMA_KEYS, "ollama")
    _keys(remote, _REMOTE_KEYS, "ollama.remote")

    cfg = defaults(
        budget_defaults=budget_defaults,
        caps_defaults=caps_defaults,
    )
    # v0.1.6 has no desktop-owned bridge process.  Legacy ``true`` values are
    # migrated to the truthful disabled state; the registered CLI watcher is
    # still available as an explicit operator action.
    if "auto_start" in bridge:
        _boolean(bridge["auto_start"], "bridge.auto_start")
    cfg["bridge"]["auto_start"] = False
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
    ide_mode = _string(ide.get("mode", cfg["ide"]["mode"]), "ide.mode")
    if ide_mode not in {"native", "docker"}:
        raise ValueError("ide.mode must be native or docker")
    cfg["ide"]["mode"] = ide_mode
    if "auto_start" in ide:
        _boolean(ide["auto_start"], "ide.auto_start")
    cfg["ide"]["auto_start"] = False
    cfg["ide"]["endpoint"] = ide_endpoint(
        ide.get("endpoint", cfg["ide"]["endpoint"])
    )
    executable = _string(ide.get("executable", ""), "ide.executable")
    if len(executable) > 4096 or any(not ch.isprintable() for ch in executable):
        raise ValueError("ide.executable must be a valid local path")
    if ide_mode == "docker" and executable:
        raise ValueError("ide.executable is only valid when ide.mode is native")
    cfg["ide"]["executable"] = executable
    docker_image = _string(
        ide.get("docker_image", cfg["ide"]["docker_image"]),
        "ide.docker_image",
    )
    if not _IDE_DOCKER_IMAGE_RE.fullmatch(docker_image):
        raise ValueError(
            "ide.docker_image must be a pinned daedalus/openvscode-server or "
            "gitpod/openvscode-server version/digest"
        )
    cfg["ide"]["docker_image"] = docker_image
    if ide_mode == "docker" and cfg["ide"]["endpoint"] != "http://127.0.0.1:3000":
        raise ValueError("docker IDE endpoint must be exactly http://127.0.0.1:3000")
    mode = _string(ollama.get("mode", "local"), "ollama.mode")
    if mode not in {"local", "remote_ssh"}:
        raise ValueError("ollama.mode must be local or remote_ssh")
    cfg["ollama"]["mode"] = mode
    # Local Ollama may be explicitly probed/adopted, but the desktop never
    # starts or auto-probes it.  Persisted legacy ``true`` values are inert.
    if "auto_start" in ollama:
        _boolean(ollama["auto_start"], "ollama.auto_start")
    cfg["ollama"]["auto_start"] = False

    model = _string(ollama.get("model", cfg["ollama"]["model"]), "ollama.model")
    if not model or len(model) > 200 or any(not ch.isprintable() for ch in model):
        raise ValueError("ollama.model must be 1..200 printable characters")
    cfg["ollama"]["model"] = model
    cfg["ollama"]["local_host"] = loopback_endpoint(
        ollama.get("local_host", cfg["ollama"]["local_host"])
    )

    dst = cfg["ollama"]["remote"]
    host = _string(remote.get("host", ""), "remote.host")
    user = _string(remote.get("user", ""), "remote.user")
    if host and (host.startswith("-") or not _HOST_RE.fullmatch(host)):
        raise ValueError("remote.host must be a DNS name or IPv4 address")
    if user and not _USER_RE.fullmatch(user):
        raise ValueError("remote.user contains unsupported characters")
    dst["host"], dst["user"] = host, user
    dst["port"] = port(remote.get("port", 22), "remote.port")
    dst["local_port"] = port(
        remote.get("local_port", 11435), "remote.local_port", 1024
    )
    dst["remote_port"] = port(
        remote.get("remote_port", 11434), "remote.remote_port"
    )

    identity = _string(remote.get("identity_file", ""), "remote.identity_file")
    if len(identity) > 4096 or any(not ch.isprintable() for ch in identity):
        raise ValueError("remote.identity_file must be at most 4096 printable characters")
    dst["identity_file"] = identity

    fingerprint = _string(
        remote.get("host_key_fingerprint", ""),
        "remote.host_key_fingerprint",
    )
    if len(fingerprint) > 80:
        raise ValueError("host key fingerprint is too long")
    if fingerprint and not _FP_RE.fullmatch(fingerprint):
        raise ValueError("host key fingerprint must use OpenSSH SHA256:... format")
    dst["host_key_fingerprint"] = fingerprint

    method = _string(remote.get("start_method", "systemd"), "remote.start_method")
    if method not in {"systemd", "windows", "none"}:
        raise ValueError("remote.start_method must be systemd, windows, or none")
    dst["start_method"] = method
    dst["trust_remote_host"] = _boolean(
        remote.get("trust_remote_host", False), "remote.trust_remote_host"
    )

    if mode == "remote_ssh":
        if not host or not user:
            raise ValueError("remote SSH mode requires remote.host and remote.user")
        if dst["trust_remote_host"] and numeric_host(host) is None:
            raise ValueError("trusted remote hosts must be numeric IP addresses")
    elif not allow_legacy_remote:
        default_remote = defaults()["ollama"]["remote"]
        unchanged_legacy = (
            type(current_remote) is dict and dst == current_remote
        )
        if dst != default_remote and not unchanged_legacy:
            raise ValueError(
                "ollama.remote cannot be modified while ollama.mode is local; "
                "clear the remote block or select remote_ssh"
            )
    return cfg


__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_IDE_DOCKER_IMAGE",
    "defaults",
    "ide_endpoint",
    "loopback_endpoint",
    "normalize_config",
    "numeric_host",
    "port",
]
