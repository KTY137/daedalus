"""Desktop settings persistence, consent, and environment projection.

The stable ``daedalus.desktop_runtime`` manager remains the only public and
effect-facing entry.  Every authority-bearing dependency and process action is
resolved through ports supplied by that facade on each call.
"""
from __future__ import annotations

from typing import Any


def read_budget_environment(
    *,
    budget_kernel: Any,
    default_config: dict[str, Any],
    json_module: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Read cap fallbacks and policy without touching the usage ledger."""

    probe = budget_kernel.Ledger()
    try:
        return {
            "period_ceiling_usd": probe.ceiling_usd(),
            "max_calls": probe.max_calls(),
        }, probe.execution_limit_policy().as_dict(), ""
    except budget_kernel.BudgetError as exc:
        # Keep the desktop repairable, but do not silently replace an invalid
        # monetary policy with a spend-authorising default.
        return (
            dict(default_config["budget"]),
            json_module.loads(json_module.dumps(default_config["caps"])),
            str(exc),
        )


def load(
    manager: Any,
    *,
    json_module: Any,
    defaults: Any,
    normalize_config: Any,
) -> dict[str, Any]:
    """Load and normalize settings while retaining fail-closed repair state."""

    try:
        raw = json_module.loads(manager.config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        manager._budget_policy_error = manager._budget_environment_error
        return defaults(
            budget_defaults=manager._budget_environment_defaults,
            caps_defaults=manager._caps_environment_defaults,
        )
    except (OSError, json_module.JSONDecodeError) as exc:
        manager._config_error = f"cannot read {manager.config_path}: {exc}"
        manager._budget_policy_error = (
            "desktop settings are unreadable; spend remains refused until "
            "valid budget settings are saved"
        )
        return defaults(
            budget_defaults=manager._budget_environment_defaults,
            caps_defaults=manager._caps_environment_defaults,
        )
    try:
        config = normalize_config(
            raw,
            budget_defaults=manager._budget_environment_defaults,
            caps_defaults=manager._caps_environment_defaults,
        )
    except ValueError as exc:
        manager._config_error = f"invalid desktop settings: {exc}"
        manager._budget_policy_error = (
            "desktop settings are invalid; spend remains refused until "
            "valid budget settings are saved"
        )
        return defaults(
            budget_defaults=manager._budget_environment_defaults,
            caps_defaults=manager._caps_environment_defaults,
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
        # A valid persisted desktop policy is authoritative for this process
        # and repairs a stale or invalid deployment environment.
        manager._budget_policy_error = ""
    else:
        manager._budget_policy_error = manager._budget_environment_error
    return config


def save(
    manager: Any,
    *,
    json_module: Any,
    os_module: Any,
    error_type: type[Exception],
) -> None:
    """Atomically persist the manager's already validated configuration."""

    try:
        manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = manager.config_path.with_name(
            f".{manager.config_path.name}.{os_module.getpid()}.tmp"
        )
        tmp.write_text(
            json_module.dumps(manager.config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os_module.replace(tmp, manager.config_path)
    except OSError as exc:
        raise error_type(f"cannot write {manager.config_path}: {exc}") from exc


def save_settings(
    manager: Any,
    raw: Any,
    *,
    json_module: Any,
    normalize_config: Any,
    execution_limit_policy: Any,
    limit_axes: Any,
    mode_custom: str,
    error_type: type[Exception],
) -> dict[str, Any]:
    """Validate consent, persist, project the environment, then autostart."""

    with manager._lock:
        if not isinstance(raw, dict):
            raise ValueError("settings must be a JSON object")
        incoming = dict(raw)
        budget_supplied = "budget" in incoming
        caps_supplied = "caps" in incoming
        if manager._budget_policy_error and not (
            budget_supplied and caps_supplied
        ):
            raise ValueError(
                "valid explicit budget and caps settings are required to "
                "repair the unavailable execution-limit policy"
            )
        confirmations: list[tuple[str, bool]] = []
        if not budget_supplied:
            # Older clients know nothing about this section. Their PUT must not
            # silently reset configured positive fallbacks.
            incoming["budget"] = dict(manager.config["budget"])
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
                    raise ValueError("caps.confirm_widening must be a boolean")
                confirmations.append(("caps", caps_confirmation))
            incoming["caps"] = caps_raw
        elif not caps_supplied:
            # A Revision-9 client may still send its one boolean. Project that
            # choice into the current axes without changing another owner.
            current_policy = execution_limit_policy.from_dict(
                manager.config["caps"]
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
                    mode = mode_custom
                incoming["caps"] = execution_limit_policy(
                    mode=mode,
                    configured=limit_axes.from_dict(configured),
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
            budget_defaults=manager.config["budget"],
            caps_defaults=manager.config["caps"],
        )
        old_budget = manager.config["budget"]
        new_budget = new["budget"]
        old_policy = execution_limit_policy.from_dict(manager.config["caps"])
        new_policy = execution_limit_policy.from_dict(new["caps"])
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

        # All validation and widening consent checks happen before any service
        # stop, file write, environment mutation, or ledger read.
        old_route = (
            manager.config["ollama"]["mode"],
            manager.config["ollama"]["local_host"],
            json_module.dumps(manager.config["ollama"]["remote"], sort_keys=True),
        )
        new_route = (
            new["ollama"]["mode"],
            new["ollama"]["local_host"],
            json_module.dumps(new["ollama"]["remote"], sort_keys=True),
        )
        old_ide_route = (
            manager.config["ide"]["mode"],
            manager.config["ide"]["endpoint"],
            manager.config["ide"]["executable"],
            manager.config["ide"]["docker_image"],
        )
        new_ide_route = (
            new["ide"]["mode"],
            new["ide"]["endpoint"],
            new["ide"]["executable"],
            new["ide"]["docker_image"],
        )
        if old_route != new_route:
            manager.stop_ollama()
        if old_ide_route != new_ide_route:
            manager.stop_ide()
        previous = manager.config
        manager.config = new
        try:
            manager._save()
        except error_type:
            manager.config = previous
            raise
        manager._config_error = ""
        manager._budget_policy_error = ""
        manager.apply_environment()
    startup_error = ""
    if new["bridge"]["auto_start"]:
        manager.ensure_bridge()
    if new["ollama"]["auto_start"]:
        try:
            manager.ensure_ollama()
        except error_type as exc:
            startup_error = str(exc)
            manager._log(f"ollama settings autostart failed: {exc}")
    if new["ide"]["auto_start"]:
        try:
            manager.ensure_ide()
        except error_type as exc:
            startup_error = "; ".join(
                value for value in (startup_error, str(exc)) if value
            )
            manager._log(f"IDE settings autostart failed: {exc}")
    snap = manager.snapshot()
    if startup_error:
        snap["startup_error"] = startup_error
    return snap


def apply_environment(
    manager: Any,
    *,
    environ: Any,
    budget_kernel: Any,
    env_execution_limit_policy: str,
    execution_limit_policy: Any,
    store_limit_policy_in_env: Any,
    numeric_host: Any,
    tunnel_forward_var: str,
    tunnel_target_var: str,
    remote_ok_var: str,
    trusted_hosts_var: str,
) -> None:
    """Project admitted settings into the existing process environment."""

    if manager._budget_policy_error:
        # A deliberately invalid canonical policy makes every Ledger read fail
        # closed while the settings UI stays available for repair.
        environ[env_execution_limit_policy] = "{invalid"
    else:
        budget = manager.config["budget"]
        policy = execution_limit_policy.from_dict(manager.config["caps"])
        store_limit_policy_in_env(policy)
        environ.pop(budget_kernel.ENV_PERIOD_CEILING_ENABLED, None)
        environ[budget_kernel.ENV_CEILING] = format(
            budget["period_ceiling_usd"], ".17g"
        )
        environ[budget_kernel.ENV_MAX_CALLS] = str(budget["max_calls"])
    ollama = manager.config["ollama"]
    environ["OLLAMA_MODEL"] = ollama["model"]
    trusted = [
        value.strip()
        for value in manager._base_trusted.split(",")
        if value.strip()
    ]
    if ollama["mode"] == "remote_ssh":
        remote = ollama["remote"]
        forward = f"http://127.0.0.1:{remote['local_port']}"
        target = f"http://{remote['host']}:{remote['remote_port']}"
        environ["OLLAMA_HOST"] = forward
        environ[tunnel_forward_var] = forward
        environ[tunnel_target_var] = target
        # Consent opens this exact transport; the egress wrapper still
        # classifies it by the physical peer unless that peer is trusted.
        environ[remote_ok_var] = forward
        if remote["trust_remote_host"]:
            resolved_host = numeric_host(remote["host"])
            if resolved_host:
                trusted.append(resolved_host)
    else:
        environ["OLLAMA_HOST"] = ollama["local_host"]
        for key in (tunnel_forward_var, tunnel_target_var, remote_ok_var):
            environ.pop(key, None)
    if trusted:
        environ[trusted_hosts_var] = ",".join(dict.fromkeys(trusted))
    else:
        environ.pop(trusted_hosts_var, None)


__all__ = [
    "apply_environment",
    "load",
    "read_budget_environment",
    "save",
    "save_settings",
]
