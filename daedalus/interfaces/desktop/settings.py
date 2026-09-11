"""Desktop settings persistence, consent, and environment projection.

The stable ``daedalus.desktop_runtime`` manager remains the only public and
effect-facing entry.  Every authority-bearing dependency and process action is
resolved through ports supplied by that facade on each call.
"""
from __future__ import annotations

from typing import Any


_SECTION_UPDATE_KEY = "section_updates"
_SECTION_UPDATE_SCOPES = (
    frozenset(("bridge", "ollama")),
    frozenset(("budget", "caps")),
)
_SECTION_UPDATE_NAMES = _SECTION_UPDATE_SCOPES[0] | _SECTION_UPDATE_SCOPES[1]


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
        #
        # THIS IS THE CODE-DEFAULT FALLBACK G1-SETTINGS-02 ARGUES AGAINST, AND
        # IT IS FINE HERE.  The argument there is that resolving a CAP by
        # falling back to the code default can widen -- a document that set
        # $1.00 would become $5.00.  Nothing is resolved here: the returned
        # values only seed the settings form so the owner can see and repair
        # something, the caller sets ``_budget_policy_error`` from the third
        # element, and that error makes every ledger read fail closed and the
        # status project ``available: false``.  No spend is admitted against
        # these numbers.  If that ever stops being true, this fallback becomes
        # the defect the packet describes.
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


def prepare_settings(
    manager: Any,
    raw: Any,
    *,
    json_module: Any,
    normalize_config: Any,
    execution_limit_policy: Any,
    limit_axes: Any,
    mode_custom: str,
) -> dict[str, Any]:
    """Purely validate a full or owner-scoped update and return a snapshot."""

    with manager._lock:
        if not isinstance(raw, dict):
            raise ValueError("settings must be a JSON object")
        # Detach the request once, before validation.  ``save_settings`` is a
        # Python API as well as an HTTP target, so a caller may still own and
        # mutate the supplied mapping from another thread.  Both the lease
        # decision and the authorised commit must consume this same immutable-
        # by-ownership snapshot; otherwise a local route could be authorised
        # and a concurrently substituted remote route persisted.
        try:
            raw = json_module.loads(json_module.dumps(raw))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ValueError("settings must be a JSON-compatible object") from exc
        if _SECTION_UPDATE_KEY in raw:
            if set(raw) != {_SECTION_UPDATE_KEY}:
                raise ValueError(
                    "section_updates cannot be combined with full settings fields"
                )
            updates = raw[_SECTION_UPDATE_KEY]
            if not isinstance(updates, dict):
                raise ValueError("section_updates must be a JSON object")
            if not updates:
                raise ValueError("section_updates must contain at least one section")
            unsupported = sorted(
                str(name) for name in updates if name not in _SECTION_UPDATE_NAMES
            )
            if unsupported:
                raise ValueError(
                    "unsupported settings section_updates: "
                    + ", ".join(unsupported)
                )
            update_names = set(updates)
            if not any(
                update_names <= scope for scope in _SECTION_UPDATE_SCOPES
            ):
                raise ValueError(
                    "section_updates must target only one settings owner"
                )
            for name, value in updates.items():
                if not isinstance(value, dict):
                    raise ValueError(
                        f"section_updates.{name} must be a JSON object"
                    )
            # Resolve the section-granular write against the newest committed
            # document while holding the same lock as validation and save.
            incoming = dict(manager.config)
            incoming.update({name: dict(value) for name, value in updates.items()})
            supplied_sections = update_names
        else:
            incoming = dict(raw)
            supplied_sections = set(incoming)
        budget_supplied = "budget" in supplied_sections
        caps_supplied = "caps" in supplied_sections
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

        # The owner receives a detached normalized value.  No writer,
        # environment mutation, service call, switch or ledger is reachable
        # from this preparation module.
        return json_module.loads(json_module.dumps(new))


def environment_projection(
    manager: Any,
    *,
    budget_kernel: Any,
    env_execution_limit_policy: str,
    execution_limit_policy: Any,
    tunnel_forward_var: str,
    tunnel_target_var: str,
    remote_ok_var: str,
    trusted_hosts_var: str,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return process-environment assignments/removals without applying them."""

    assignments: dict[str, str] = {}
    removals: list[str] = []

    if manager._budget_policy_error:
        # A deliberately invalid canonical policy makes every Ledger read fail
        # closed while the settings UI stays available for repair.
        assignments[env_execution_limit_policy] = "{invalid"
    else:
        budget = manager.config["budget"]
        policy = execution_limit_policy.from_dict(manager.config["caps"])
        assignments[env_execution_limit_policy] = policy.to_env_value()
        removals.append(budget_kernel.ENV_PERIOD_CEILING_ENABLED)
        assignments[budget_kernel.ENV_CEILING] = format(
            budget["period_ceiling_usd"], ".17g"
        )
        assignments[budget_kernel.ENV_MAX_CALLS] = str(budget["max_calls"])
    ollama = manager.config["ollama"]
    assignments["OLLAMA_MODEL"] = ollama["model"]
    trusted = [
        value.strip()
        for value in manager._base_trusted.split(",")
        if value.strip()
    ]
    # Persisted legacy remote settings remain readable and repairable, but
    # v0.1.6 never projects them into transport consent, peer trust, or a
    # tunnel endpoint before exact SSH peer/key-custody contracts exist.
    assignments["OLLAMA_HOST"] = ollama["local_host"]
    removals.extend((tunnel_forward_var, tunnel_target_var, remote_ok_var))
    if trusted:
        assignments[trusted_hosts_var] = ",".join(dict.fromkeys(trusted))
    else:
        removals.append(trusted_hosts_var)
    return assignments, tuple(dict.fromkeys(removals))


__all__ = [
    "environment_projection",
    "load",
    "prepare_settings",
    "read_budget_environment",
]
