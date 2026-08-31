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
    "bridge": {"auto_start": True},
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
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a TCP port")
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a TCP port") from None
    if not low <= resolved <= 65535:
        raise ValueError(f"{name} must be between {low} and 65535")
    return resolved


def loopback_endpoint(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
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
    raw = str(value or "").strip().rstrip("/")
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

    cfg = defaults(
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
    cfg["ide"]["endpoint"] = ide_endpoint(
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
    cfg["ollama"]["local_host"] = loopback_endpoint(
        o.get("local_host", cfg["ollama"]["local_host"])
    )

    dst = cfg["ollama"]["remote"]
    host, user = str(r.get("host", "")).strip(), str(r.get("user", "")).strip()
    if host and (host.startswith("-") or not _HOST_RE.fullmatch(host)):
        raise ValueError("remote.host must be a DNS name or IPv4 address")
    if user and not _USER_RE.fullmatch(user):
        raise ValueError("remote.user contains unsupported characters")
    dst["host"], dst["user"] = host, user
    dst["port"] = port(r.get("port", 22), "remote.port")
    dst["local_port"] = port(r.get("local_port", 11435), "remote.local_port", 1024)
    dst["remote_port"] = port(r.get("remote_port", 11434), "remote.remote_port")

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
        if dst["trust_remote_host"] and numeric_host(host) is None:
            raise ValueError("trusted remote hosts must be numeric IP addresses")
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
