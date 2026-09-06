"""Read-only desktop status projections over the existing manager state."""
from __future__ import annotations

import contextlib
import json
from typing import Any


def bridge_status_is_managed(manager: Any, status: dict[str, Any]) -> bool:
    """v0.1.6 never owns or adopts a bridge watcher."""

    del manager, status
    return False


def ide_status(
    manager: Any,
    project: Any = None,
    *,
    error_type: type[Exception],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project loopback reachability without spawning a discovery command."""

    del error_type
    generation = manager.config if config is None else config
    mode = generation["ide"]["mode"]
    return {
        "mode": mode,
        "endpoint": generation["ide"]["endpoint"],
        "ui_url": manager._ide_ui_url(project, config=generation),
        "installed": False,
        "available": False,
        "executable": "",
        "observed": False,
        "reachable": False,
        "last_error": "not probed by the read-only desktop projection",
        "detail": "",
        "managed": False,
        "process_running": False,
        "configured_executable": generation["ide"]["executable"],
        "image": generation["ide"]["docker_image"],
        "runtime_downloads": False,
    }


def budget_status(
    manager: Any,
    *,
    budget_kernel: Any,
    execution_limit_policy: Any,
    config: dict[str, Any] | None = None,
    policy_error: str | None = None,
) -> dict[str, Any]:
    """Project configured and ledger-backed execution-limit state."""

    generation = manager.config if config is None else config
    configured = generation["budget"]
    policy = execution_limit_policy.from_dict(generation["caps"])
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
    current_policy_error = (
        manager._budget_policy_error if policy_error is None else policy_error
    )
    if current_policy_error:
        base["last_error"] = current_policy_error
        return base
    try:
        state = budget_kernel.ledger().state_readonly()
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
        "limit_policy_fingerprint_sha256": state.limit_policy_fingerprint_sha256,
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
        "billable_call_ceiling_enabled": state.billable_call_ceiling_enabled,
        "explicit_envelope_ceiling_enforced": state.mission_spend_ceiling_enabled,
        "mission_spend_ceiling_enabled": state.mission_spend_ceiling_enabled,
        "last_error": "",
    }


def _heartbeat_projection(file_bridge: Any) -> dict[str, Any]:
    """Detach and validate heartbeat state without letting bad bytes crash GET."""

    try:
        value = file_bridge.heartbeat_status()
        if type(value) is not dict:
            raise ValueError("heartbeat projection is not an object")
        state = value.get("state")
        if state not in {"none", "alive", "busy", "wedged", "stale"}:
            raise ValueError("heartbeat state is missing or unsupported")
        return json.loads(json.dumps(value))
    except Exception as exc:
        return {
            "state": "invalid",
            "detail": (
                "heartbeat state is malformed: "
                f"{type(exc).__name__}: {str(exc)[:500]}"
            ),
        }


def snapshot(
    manager: Any,
    *,
    file_bridge: Any,
    environ: Any,
    tunnel_target_var: str,
) -> dict[str, Any]:
    """Build the established desktop JSON projection without side effects."""

    del environ, tunnel_target_var

    from ..http.effects import mutation_route_wired
    from .effects import (
        MANAGED_BRIDGE_UNAVAILABLE,
        MANAGED_IDE_UNAVAILABLE,
        MANAGED_OLLAMA_UNAVAILABLE,
        REMOTE_SSH_UNAVAILABLE,
    )

    lock = getattr(manager, "_lock", None)
    guard = lock if hasattr(lock, "__enter__") else contextlib.nullcontext()
    with guard:
        # Exactly one detached configuration generation feeds every nested
        # projector. No helper may re-read manager.config during this snapshot.
        config = json.loads(json.dumps(manager.config))
        try:
            ollama_observation = json.loads(
                json.dumps(manager._ollama_observation)
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            ollama_observation = {
                "observed": False,
                "reachable": False,
                "last_error": "stored Ollama observation is invalid",
            }
        config_error = str(getattr(manager, "_config_error", ""))
        budget_policy_error = str(
            getattr(manager, "_budget_policy_error", "")
        )
        bridge_start_error = str(
            getattr(manager, "_bridge_start_error", "")
        )

    bridge_status = _heartbeat_projection(file_bridge)
    remote = config["ollama"]["remote"]
    budget = manager._budget_status(
        config=config,
        policy_error=budget_policy_error,
    )
    caps = {
        "available": budget["available"],
        "mode": budget["mode"],
        "configured": budget["configured_caps"],
        "effective": budget["effective_caps"],
        "fingerprint_sha256": budget["limit_policy_fingerprint_sha256"],
        "last_error": budget["last_error"],
        "external_limits_remain": True,
        "ariadne_campaign_live": mutation_route_wired("/api/ariadne"),
    }
    configured_endpoint = config["ollama"]["local_host"]
    observation_matches = (
        ollama_observation.get("endpoint") == configured_endpoint
    )
    result = {
        "config": config,
        "config_path": str(manager.config_path),
        "config_error": config_error,
        "budget": budget,
        "caps": caps,
        "budget_error": budget["last_error"],
        "credential_policy": {
            "ssh_key_only": True,
            "stores_passwords": False,
            "stores_private_key_bytes": False,
            "host_key_verification": "unavailable",
        },
        "services": {
            "bridge": {
                **bridge_status,
                "managed": False,
                "last_error": bridge_start_error,
                "managed_start_available": False,
                "availability_reason": MANAGED_BRIDGE_UNAVAILABLE,
            },
            "ollama": {
                "mode": config["ollama"]["mode"],
                "endpoint": configured_endpoint,
                "physical_target": "",
                "observed": bool(
                    observation_matches and ollama_observation.get("observed")
                ),
                "observed_at": (
                    ollama_observation.get("observed_at")
                    if observation_matches
                    else None
                ),
                "reachable": bool(
                    observation_matches and ollama_observation.get("reachable")
                ),
                "last_error": str(
                    ollama_observation.get("last_error")
                    if observation_matches
                    else "not probed for the configured endpoint"
                ),
                "tunnel_running": False,
                "local_process_running": False,
                "managed_start_available": False,
                "remote_ssh_available": False,
                "availability_reason": (
                    REMOTE_SSH_UNAVAILABLE
                    if config["ollama"]["mode"] == "remote_ssh"
                    else MANAGED_OLLAMA_UNAVAILABLE
                ),
                "fingerprint_configured": bool(remote["host_key_fingerprint"]),
                "host_key_verified": False,
                "host_key_status": "not_checked",
            },
            "ide": {
                **manager._ide_status(config=config),
                "managed_start_available": False,
                "availability_reason": MANAGED_IDE_UNAVAILABLE,
            },
        },
    }
    # The public projection never returns a live manager-owned mapping.
    return json.loads(json.dumps(result))
