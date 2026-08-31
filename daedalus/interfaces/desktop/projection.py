"""Read-only desktop status projections over the existing manager state."""
from __future__ import annotations

import os
from typing import Any


def bridge_status_is_managed(manager: Any, status: dict[str, Any]) -> bool:
    """Bind a bridge heartbeat to the exact manager-owned watcher identity."""

    return bool(
        manager._bridge
        and manager._bridge.is_alive()
        and manager._bridge_owner_token
        and manager._bridge_process_identity
        and status.get("state") in {"alive", "busy", "wedged"}
        and status.get("pid") == os.getpid()
        and status.get("owner_token") == manager._bridge_owner_token
        and status.get("process_identity") == manager._bridge_process_identity
    )


def ide_status(
    manager: Any,
    project: Any = None,
    *,
    error_type: type[Exception],
) -> dict[str, Any]:
    """Project native or Docker IDE state without starting or downloading it."""

    if manager.config["ide"]["mode"] == "docker":
        return manager._docker_ide_status(project)
    ok, detail = manager._probe_ide()
    running = bool(manager._ide and manager._ide.poll() is None)
    executable = ""
    discovery_error = ""
    try:
        executable = manager._discover_ide_executable()
    except error_type as exc:
        # A status read must remain observational. Missing installations are
        # reported to the UI and never trigger a download or start.
        discovery_error = str(exc)
    installed = bool(executable)
    return {
        "endpoint": manager.config["ide"]["endpoint"],
        "ui_url": manager._ide_ui_url(project),
        "installed": installed,
        "available": installed,
        "executable": executable,
        "reachable": ok,
        "last_error": "" if ok else (discovery_error or detail),
        "detail": discovery_error,
        "managed": running,
        "process_running": running,
        "configured_executable": manager.config["ide"]["executable"],
        "runtime_downloads": False,
    }


def budget_status(
    manager: Any,
    *,
    budget_kernel: Any,
    execution_limit_policy: Any,
) -> dict[str, Any]:
    """Project configured and ledger-backed execution-limit state."""

    configured = manager.config["budget"]
    policy = execution_limit_policy.from_dict(manager.config["caps"])
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
    if manager._budget_policy_error:
        base["last_error"] = manager._budget_policy_error
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


def snapshot(
    manager: Any,
    *,
    file_bridge: Any,
    environ: Any,
    tunnel_target_var: str,
) -> dict[str, Any]:
    """Build the established desktop JSON projection without side effects."""

    ok, err = manager._probe()
    bridge_status = file_bridge.heartbeat_status()
    remote = manager.config["ollama"]["remote"]
    budget = manager._budget_status()
    caps = {
        "available": budget["available"],
        "mode": budget["mode"],
        "configured": budget["configured_caps"],
        "effective": budget["effective_caps"],
        "fingerprint_sha256": budget["limit_policy_fingerprint_sha256"],
        "last_error": budget["last_error"],
        "external_limits_remain": True,
        "ariadne_campaign_live": False,
    }
    return {
        "config": manager.config,
        "config_path": str(manager.config_path),
        "config_error": manager._config_error,
        "budget": budget,
        "caps": caps,
        "budget_error": budget["last_error"],
        "credential_policy": {
            "ssh_key_only": True,
            "stores_passwords": False,
            "stores_private_key_bytes": False,
            "host_key_verification": "strict",
        },
        "services": {
            "bridge": {
                **bridge_status,
                "managed": manager._bridge_status_is_managed(bridge_status),
                "last_error": manager._bridge_start_error,
            },
            "ollama": {
                "mode": manager.config["ollama"]["mode"],
                "endpoint": environ.get("OLLAMA_HOST", ""),
                "physical_target": environ.get(tunnel_target_var, ""),
                "reachable": ok,
                "last_error": "" if ok else err,
                "tunnel_running": bool(
                    manager._tunnel and manager._tunnel.poll() is None
                ),
                "local_process_running": bool(
                    manager._ollama and manager._ollama.poll() is None
                ),
                "host_key_pinned": bool(
                    remote["host_key_fingerprint"]
                    or (
                        manager.known_hosts_path.exists()
                        and manager.known_hosts_path.stat().st_size
                    )
                ),
            },
            "ide": manager._ide_status(),
        },
    }
