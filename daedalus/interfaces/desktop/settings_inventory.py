"""One read-only description of the settings surface that already exists.

This module is a PROJECTION and nothing else.  It owns no state, opens no
file, mutates no environment, and reaches no effect entrypoint.  Every value
it reports is derived from three inputs the caller already holds:

* :data:`daedalus.interfaces.desktop.configuration.DEFAULT_CONFIG` -- the code
  defaults;
* a normalized desktop settings document (``manager.config``) -- what the
  owner persisted through ``PUT /api/desktop/settings``;
* a process environment mapping -- what actually decides the value at read
  time for the axes whose canonical reader is
  :class:`daedalus.kernel.policy.ledger.Ledger` or
  :func:`daedalus.kernel.policy.limits.load_from_env`.

The point of the projection is the third column.  Measured 2026-09-10: the
desktop persists ``budget``/``caps``/``ollama`` into
``config/connections.json`` and then *projects them into its own process
environment*; the kernel reads the environment, never the document.  A
process that is not the desktop therefore reads the code default, and an
ambient variable inherited from a parent wins over what the owner saved.
:func:`describe_settings` says so per setting instead of leaving a UI to
imply that the stored document is the effective value.

Nothing here is a boundary.  The kill switch, egress admission, bounded write
roots, secret and tool policy, and the confirmation requirement for
authority-widening writes are enforced by their owners; this module only
reports which settings carry them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any, Final

from ...kernel.policy.limits import (
    LIMIT_AXES,
    LIMIT_MODES,
    ExecutionLimitPolicy,
    LimitPolicyError,
)
from .configuration import DEFAULT_CONFIG, defaults


# --------------------------------------------------------------------------- #
# Where an effective value came from.                                         #
# --------------------------------------------------------------------------- #
#: Nothing configured it; the reported value is the code default.
SOURCE_DEFAULT: Final = "default"
#: The persisted desktop document decides, and nothing shadows it.
SOURCE_PERSISTED: Final = "persisted"
#: A process environment variable decides at read time, whatever the document
#: holds.  This is a statement about the canonical READER, not about who wrote
#: the variable: the desktop writes most of these into its own environment.
SOURCE_ENVIRONMENT: Final = "environment"
#: Normalization overrides whatever the caller asked for.  The request is
#: accepted, reported as saved, and discarded.
SOURCE_FORCED: Final = "forced"

SOURCES: Final[tuple[str, ...]] = (
    SOURCE_DEFAULT,
    SOURCE_PERSISTED,
    SOURCE_ENVIRONMENT,
    SOURCE_FORCED,
)


# --------------------------------------------------------------------------- #
# The admission path a write travels, if any.                                 #
# --------------------------------------------------------------------------- #
#: ``PUT /api/desktop/settings`` -> ``prepare_settings`` -> ``EffectLease`` ->
#: atomic publish.  The only admission path that validates, demands
#: ``caps.confirm_widening`` for a widening, and leaves a receipt.
WRITE_DESKTOP_SETTINGS: Final = "desktop_settings"
#: Settable only by exporting an environment variable before the process
#: starts.  No validation parity with the desktop path, no confirmation, no
#: receipt.  A setting that both widens authority and carries this write path
#: is a defect, not a design; see :func:`unconfirmed_widening_settings`.
WRITE_ENVIRONMENT_ONLY: Final = "environment_only"
#: Hand-edited JSON in ``<repo>/.agentenv/agentenv.json`` or
#: ``projects/<name>.json``.  ``register_project`` writes identity only and
#: ``rewrite_project_team`` writes ``team`` only; every other key in those
#: files has no programmatic writer at all.
WRITE_PROJECT_FILE: Final = "project_file"
#: Accepted by the API, validated, and then overwritten by normalization.
#: No caller can make the stored value differ from the forced one.
WRITE_NONE: Final = "none"

WRITE_PATHS: Final[tuple[str, ...]] = (
    WRITE_DESKTOP_SETTINGS,
    WRITE_ENVIRONMENT_ONLY,
    WRITE_PROJECT_FILE,
    WRITE_NONE,
)


GROUP_EXECUTION_LIMITS: Final = "execution_limits"
GROUP_LOCAL_RUNTIME: Final = "local_runtime"
GROUP_EDITOR: Final = "editor"
GROUP_TRUST: Final = "trust"
GROUP_PROJECT_POLICY: Final = "project_policy"

GROUPS: Final[tuple[str, ...]] = (
    GROUP_EXECUTION_LIMITS,
    GROUP_LOCAL_RUNTIME,
    GROUP_EDITOR,
    GROUP_TRUST,
    GROUP_PROJECT_POLICY,
)


@dataclass(frozen=True, slots=True)
class SettingDescriptor:
    """One setting, described once, for every reader that needs the shape.

    ``effective`` is the value that would actually be used right now given the
    supplied document and environment.  ``source`` names which of the three
    inputs decided it.  ``widens_authority`` and ``requires_confirmation`` are
    properties of the SETTING, not of the path a particular caller used, which
    is exactly what makes the ``requires_confirmation`` /
    ``write_path == WRITE_ENVIRONMENT_ONLY`` combination detectable.
    """

    id: str
    group: str
    value_type: str
    default: Any
    effective: Any
    source: str
    widens_authority: bool
    requires_confirmation: bool
    per_project: bool
    write_path: str
    environment_variable: str | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        """Return a plain JSON-compatible mapping in a stable key order."""

        return {
            "id": self.id,
            "group": self.group,
            "value_type": self.value_type,
            "default": self.default,
            "effective": self.effective,
            "source": self.source,
            "widens_authority": self.widens_authority,
            "requires_confirmation": self.requires_confirmation,
            "per_project": self.per_project,
            "write_path": self.write_path,
            "environment_variable": self.environment_variable,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# Environment variables whose reader is the kernel, not the document.         #
# --------------------------------------------------------------------------- #
ENV_BUDGET_USD: Final = "DAEDALUS_BUDGET_USD"
ENV_BUDGET_MAX_CALLS: Final = "DAEDALUS_BUDGET_MAX_CALLS"
ENV_BUDGET_PERIOD: Final = "DAEDALUS_BUDGET_PERIOD"
ENV_BUDGET_LEDGER: Final = "DAEDALUS_BUDGET_LEDGER"
ENV_BUDGET_ON_UNKNOWN: Final = "DAEDALUS_BUDGET_ON_UNKNOWN"
ENV_SUBSCRIPTION_VENDORS: Final = "DAEDALUS_SUBSCRIPTION_VENDORS"
ENV_LIMIT_POLICY: Final = "DAEDALUS_EXECUTION_LIMIT_POLICY"
ENV_OLLAMA_HOST: Final = "OLLAMA_HOST"
ENV_OLLAMA_MODEL: Final = "OLLAMA_MODEL"
ENV_OLLAMA_EMBED_MODEL: Final = "OLLAMA_EMBED_MODEL"
ENV_TRUSTED_HOSTS: Final = "DAEDALUS_TRUSTED_HOSTS"
ENV_OLLAMA_REMOTE_OK: Final = "DAEDALUS_OLLAMA_REMOTE_OK"


def _present(environ: Mapping[str, str], name: str) -> bool:
    """A variable counts as set only when it carries a non-blank value.

    This matches ``ledger._env_float`` / ``_env_int`` / ``limits.load_from_env``,
    all of which treat an empty or whitespace value as absent.
    """

    raw = environ.get(name)
    return raw is not None and bool(raw.strip())


def _coerce_positive_float(raw: str) -> Any:
    """``ledger._env_float`` semantics: unusable means fail-closed, not a guess."""

    try:
        value = float(raw)
    except ValueError:
        return None
    return value if isfinite(value) and value > 0 else None


def _coerce_positive_int(raw: str) -> Any:
    """``ledger._env_int`` semantics."""

    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _shadowed(
    *,
    setting_id: str,
    group: str,
    value_type: str,
    default: Any,
    stored: Any,
    environ: Mapping[str, str],
    variable: str,
    widens_authority: bool,
    requires_confirmation: bool,
    note: str,
    coerce: Callable[[str], Any] | None = None,
) -> SettingDescriptor:
    """Describe a setting the desktop persists but the kernel reads from env.

    Precedence mirrors the canonical readers exactly: a non-blank variable
    wins, otherwise the value the desktop document holds is what this process
    would project, otherwise the code default.  ``coerce`` reproduces the
    reader's own parse so the reported effective value has the reader's type;
    a value the reader would refuse is reported as ``None``, because that is
    what fail-closed looks like, not as the raw text.
    """

    if _present(environ, variable):
        raw = environ[variable].strip()
        return SettingDescriptor(
            id=setting_id,
            group=group,
            value_type=value_type,
            default=default,
            effective=coerce(raw) if coerce is not None else raw,
            source=SOURCE_ENVIRONMENT,
            widens_authority=widens_authority,
            requires_confirmation=requires_confirmation,
            per_project=False,
            write_path=WRITE_DESKTOP_SETTINGS,
            environment_variable=variable,
            note=note,
        )
    source = SOURCE_PERSISTED if stored != default else SOURCE_DEFAULT
    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type=value_type,
        default=default,
        effective=stored,
        source=source,
        widens_authority=widens_authority,
        requires_confirmation=requires_confirmation,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=variable,
        note=note,
    )


def _env_only(
    *,
    setting_id: str,
    group: str,
    value_type: str,
    default: Any,
    environ: Mapping[str, str],
    variable: str,
    widens_authority: bool,
    requires_confirmation: bool,
    note: str,
) -> SettingDescriptor:
    """Describe a setting with no admission path at all."""

    set_here = _present(environ, variable)
    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type=value_type,
        default=default,
        effective=environ[variable].strip() if set_here else default,
        source=SOURCE_ENVIRONMENT if set_here else SOURCE_DEFAULT,
        widens_authority=widens_authority,
        requires_confirmation=requires_confirmation,
        per_project=False,
        write_path=WRITE_ENVIRONMENT_ONLY,
        environment_variable=variable,
        note=note,
    )


def _forced(
    *,
    setting_id: str,
    group: str,
    forced_value: Any,
    note: str,
) -> SettingDescriptor:
    """Describe a setting the API accepts and normalization then discards."""

    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type="boolean",
        default=forced_value,
        effective=forced_value,
        source=SOURCE_FORCED,
        widens_authority=False,
        requires_confirmation=False,
        per_project=False,
        write_path=WRITE_NONE,
        environment_variable=None,
        note=note,
    )


def _stored(
    config: Mapping[str, Any],
    base: Mapping[str, Any],
    section: str,
    key: str,
) -> Any:
    """Read one leaf from a normalized document, falling back to the default."""

    block = config.get(section)
    if isinstance(block, Mapping) and key in block:
        return block[key]
    return base[section][key]


def describe_settings(
    config: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[SettingDescriptor, ...]:
    """Project one typed description of the whole settings surface.

    ``config`` is a normalized desktop settings document -- exactly the shape
    :func:`daedalus.interfaces.desktop.configuration.normalize_config`
    returns and ``manager.config`` holds.  ``environ`` is the process
    environment the kernel would read.  Neither is mutated and neither is
    resolved from a global: a caller inspecting a saved document against a
    hypothetical environment gets an honest answer for that pair.

    Ordering is deterministic and grouped, so two processes describing the
    same pair produce the same tuple.
    """

    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    if not isinstance(environ, Mapping):
        raise TypeError("environ must be a mapping")

    # THE default is what ``defaults()`` produces on THIS host, not the raw
    # ``DEFAULT_CONFIG`` literal.  Measured 2026-09-10: ``defaults()``
    # rewrites ``ide.mode`` to "docker" on Windows, so a projection that
    # compared against the literal would report a fresh Windows install as
    # having "persisted" an editor choice the owner never made.
    base = defaults()

    out: list[SettingDescriptor] = []

    # -- execution limits ------------------------------------------------- #
    out.append(_shadowed(
        setting_id="budget.period_ceiling_usd",
        group=GROUP_EXECUTION_LIMITS,
        value_type="number",
        default=base["budget"]["period_ceiling_usd"],
        stored=_stored(config, base, "budget", "period_ceiling_usd"),
        environ=environ,
        variable=ENV_BUDGET_USD,
        coerce=_coerce_positive_float,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Raising it is a widening and the desktop path demands "
            "caps.confirm_widening. Ledger.ceiling_usd() reads the "
            "environment variable, so a process the desktop did not start "
            "sees the code default instead of this value."
        ),
    ))
    out.append(_shadowed(
        setting_id="budget.max_calls",
        group=GROUP_EXECUTION_LIMITS,
        value_type="integer",
        default=base["budget"]["max_calls"],
        stored=_stored(config, base, "budget", "max_calls"),
        environ=environ,
        variable=ENV_BUDGET_MAX_CALLS,
        coerce=_coerce_positive_int,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Raising it is a widening and the desktop path demands "
            "caps.confirm_widening. Ledger.max_calls() reads the environment "
            "variable."
        ),
    ))

    caps = config.get("caps")
    caps = caps if isinstance(caps, Mapping) else base["caps"]
    env_policy_set = _present(environ, ENV_LIMIT_POLICY)
    # Decode the environment policy exactly the way the Ledger does.  An
    # undecodable value is not "some string": it makes every Ledger read fail
    # closed, so the honest effective value is None with the reason attached,
    # never raw bytes dressed up as a mode or a boolean.
    env_policy: ExecutionLimitPolicy | None = None
    env_policy_note = ""
    if env_policy_set:
        try:
            env_policy = ExecutionLimitPolicy.from_env_value(
                environ[ENV_LIMIT_POLICY]
            )
        except LimitPolicyError as exc:
            env_policy_note = (
                f" The current environment value is invalid ({exc}), so every "
                "Ledger read fails closed rather than picking a mode."
            )
    stored_mode = caps.get("mode", base["caps"]["mode"])
    out.append(SettingDescriptor(
        id="caps.mode",
        group=GROUP_EXECUTION_LIMITS,
        value_type=f"enum[{'|'.join(LIMIT_MODES)}]",
        default=base["caps"]["mode"],
        effective=(
            (env_policy.mode if env_policy is not None else None)
            if env_policy_set
            else stored_mode
        ),
        source=(
            SOURCE_ENVIRONMENT if env_policy_set
            else SOURCE_PERSISTED if stored_mode != base["caps"]["mode"]
            else SOURCE_DEFAULT
        ),
        widens_authority=True,
        requires_confirmation=True,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=ENV_LIMIT_POLICY,
        note=(
            "unbounded_execution disables all eight resource axes. The "
            "desktop path refuses that without caps.confirm_widening; "
            "Ledger.execution_limit_policy() prefers the environment "
            "variable, which has no confirmation." + env_policy_note
        ),
    ))
    configured = caps.get("configured")
    configured = (
        configured if isinstance(configured, Mapping)
        else base["caps"]["configured"]
    )
    for axis in LIMIT_AXES:
        stored_axis = configured.get(axis, True)
        out.append(SettingDescriptor(
            id=f"caps.configured.{axis}",
            group=GROUP_EXECUTION_LIMITS,
            value_type="boolean",
            default=True,
            effective=(
                (
                    getattr(env_policy.configured, axis)
                    if env_policy is not None
                    else None
                )
                if env_policy_set
                else stored_axis
            ),
            source=(
                SOURCE_ENVIRONMENT if env_policy_set
                else SOURCE_PERSISTED if stored_axis is not True
                else SOURCE_DEFAULT
            ),
            widens_authority=True,
            requires_confirmation=True,
            per_project=False,
            write_path=WRITE_DESKTOP_SETTINGS,
            environment_variable=ENV_LIMIT_POLICY,
            note=(
                "Retained per-axis choice. It only takes effect in custom "
                "mode; bounded and unbounded_execution derive their effective "
                "flags without rewriting it."
            ),
        ))

    out.append(_env_only(
        setting_id="budget.period",
        group=GROUP_EXECUTION_LIMITS,
        value_type="enum[day|total]",
        default="day",
        environ=environ,
        variable=ENV_BUDGET_PERIOD,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "How long the USD ceiling lasts. No desktop field exists, so the "
            "UI shows a ceiling without saying over what period it applies."
        ),
    ))
    out.append(_env_only(
        setting_id="budget.ledger_path",
        group=GROUP_EXECUTION_LIMITS,
        value_type="path",
        default="runs/budget/ledger.json",
        environ=environ,
        variable=ENV_BUDGET_LEDGER,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Repointing the ledger at a fresh path presents zero recorded "
            "spend to the same ceiling. No admission path and no "
            "confirmation exist for it."
        ),
    ))
    out.append(_env_only(
        setting_id="budget.on_unknown_price",
        group=GROUP_EXECUTION_LIMITS,
        value_type="enum[worst_case|refuse]",
        default="worst_case",
        environ=environ,
        variable=ENV_BUDGET_ON_UNKNOWN,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "Only narrows: an unrecognized value falls back to worst_case, "
            "so this knob cannot make an unknown call cheaper."
        ),
    ))
    out.append(_env_only(
        setting_id="budget.subscription_vendors",
        group=GROUP_EXECUTION_LIMITS,
        value_type="csv[vendor]",
        default="",
        environ=environ,
        variable=ENV_SUBSCRIPTION_VENDORS,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "A vendor named here bills $0 against the USD ceiling while its "
            "calls still count. That is a monetary widening with no "
            "admission path and no confirmation."
        ),
    ))

    # -- local runtime ---------------------------------------------------- #
    out.append(_shadowed(
        setting_id="ollama.model",
        group=GROUP_LOCAL_RUNTIME,
        value_type="string",
        default=base["ollama"]["model"],
        stored=_stored(config, base, "ollama", "model"),
        environ=environ,
        variable=ENV_OLLAMA_MODEL,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "Thirteen call sites read the environment variable directly; the "
            "persisted value reaches them only through the desktop's own "
            "process environment."
        ),
    ))
    out.append(_shadowed(
        setting_id="ollama.local_host",
        group=GROUP_LOCAL_RUNTIME,
        value_type="url",
        default=base["ollama"]["local_host"],
        stored=_stored(config, base, "ollama", "local_host"),
        environ=environ,
        variable=ENV_OLLAMA_HOST,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "The desktop path accepts loopback only. The environment "
            "variable accepts any host; the egress fence "
            "(sensitivity.lane_for_host) is what refuses repository content "
            "to a non-loopback endpoint, not this setting."
        ),
    ))
    out.append(SettingDescriptor(
        id="ollama.mode",
        group=GROUP_LOCAL_RUNTIME,
        value_type="enum[local|remote_ssh]",
        default=base["ollama"]["mode"],
        effective=_stored(config, base, "ollama", "mode"),
        source=(
            SOURCE_PERSISTED
            if _stored(config, base, "ollama", "mode") != base["ollama"]["mode"]
            else SOURCE_DEFAULT
        ),
        widens_authority=True,
        requires_confirmation=False,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=None,
        note=(
            "remote_ssh is refused unconditionally by the effect owner "
            "(REMOTE_SSH_UNAVAILABLE), so the whole ollama.remote block is "
            "validated and stored but never acted on."
        ),
    ))
    out.append(_env_only(
        setting_id="ollama.embed_model",
        group=GROUP_LOCAL_RUNTIME,
        value_type="string",
        default="nomic-embed-text",
        environ=environ,
        variable=ENV_OLLAMA_EMBED_MODEL,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "Read at import time by health and memory embeddings. No desktop "
            "field exists even though ollama.model has one."
        ),
    ))
    out.append(_forced(
        setting_id="ollama.auto_start",
        group=GROUP_LOCAL_RUNTIME,
        forced_value=False,
        note=(
            "normalize_config validates the boolean and then stores False. "
            "lifecycle.bootstrap still branches on it, so that branch is "
            "unreachable."
        ),
    ))
    out.append(_forced(
        setting_id="bridge.auto_start",
        group=GROUP_LOCAL_RUNTIME,
        forced_value=False,
        note=(
            "Same forced-False shape as ollama.auto_start, and the managed "
            "bridge itself raises MANAGED_BRIDGE_UNAVAILABLE."
        ),
    ))

    # -- editor ----------------------------------------------------------- #
    for key, value_type in (
        ("mode", "enum[native|docker]"),
        ("endpoint", "url"),
        ("executable", "path"),
        ("docker_image", "string"),
    ):
        stored_value = _stored(config, base, "ide", key)
        out.append(SettingDescriptor(
            id=f"ide.{key}",
            group=GROUP_EDITOR,
            value_type=value_type,
            default=base["ide"][key],
            effective=stored_value,
            source=(
                SOURCE_PERSISTED
                if stored_value != base["ide"][key]
                else SOURCE_DEFAULT
            ),
            widens_authority=key == "executable",
            requires_confirmation=False,
            per_project=False,
            write_path=WRITE_DESKTOP_SETTINGS,
            environment_variable=None,
            note=(
                "Validated and persisted, but start_ide/stop_ide raise "
                "MANAGED_IDE_UNAVAILABLE, so the only reader is the "
                "read-only status projection."
            ),
        ))
    out.append(_forced(
        setting_id="ide.auto_start",
        group=GROUP_EDITOR,
        forced_value=False,
        note=(
            "Forced False, and lifecycle.bootstrap's ide branch is therefore "
            "unreachable."
        ),
    ))

    # -- trust ------------------------------------------------------------ #
    out.append(_env_only(
        setting_id="trust.declared_hosts",
        group=GROUP_TRUST,
        value_type="csv[host]",
        default="",
        environ=environ,
        variable=ENV_TRUSTED_HOSTS,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "sensitivity.declared_trusted_hosts() moves a named address "
            "inside the egress trust boundary, so repository content may "
            "leave this machine for it. Read once at desktop start into "
            "_base_trusted and re-projected verbatim; there is no field, no "
            "validation and no confirmation."
        ),
    ))
    out.append(_env_only(
        setting_id="trust.ollama_remote_consent",
        group=GROUP_TRUST,
        value_type="host",
        default="",
        environ=environ,
        variable=ENV_OLLAMA_REMOTE_OK,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Exact-host egress consent for the Ollama lane "
            "(providers.ollama.remote_endpoint_consented). The desktop "
            "settings save REMOVES this variable from the process "
            "environment as a side effect, which revokes consent without "
            "saying so."
        ),
    ))

    # -- project policy --------------------------------------------------- #
    out.append(SettingDescriptor(
        id="project.write_wave_policy",
        group=GROUP_PROJECT_POLICY,
        value_type="enum[never]",
        default="never",
        effective="never",
        source=SOURCE_DEFAULT,
        widens_authority=False,
        requires_confirmation=False,
        per_project=True,
        write_path=WRITE_PROJECT_FILE,
        environment_variable=None,
        note=(
            "config.resolve_write_wave_policy collapses every value, "
            "including the legacy low_risk/always spellings, to never. It is "
            "a sealed-promotion floor, not an adjustable setting."
        ),
    ))
    out.append(SettingDescriptor(
        id="project.policy.external_write_lanes",
        group=GROUP_PROJECT_POLICY,
        value_type="list[lane]",
        default=[],
        effective=None,
        source=SOURCE_DEFAULT,
        widens_authority=True,
        requires_confirmation=True,
        per_project=True,
        write_path=WRITE_PROJECT_FILE,
        environment_variable=None,
        note=(
            "Lets a named untrusted external lane APPLY a change instead of "
            "advising, and it costs real money. Effective value is per "
            "repository, so this row reports None rather than pretend one "
            "global answer exists. Only a hand edit can set it."
        ),
    ))

    return tuple(out)


def unconfirmed_widening_settings(
    config: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[SettingDescriptor, ...]:
    """Settings that widen authority but have no confirming admission path.

    Section 4.1 of the master plan requires an explicit transient confirmation
    for every transition that widens authority, verified by the effectful
    backend before any settings, environment, ledger or work-admission effect.
    A row returned here declares ``requires_confirmation`` and is nonetheless
    settable by exporting a variable, where no backend verifies anything.

    This is a MEASUREMENT, not a guard: it reports the gap so a test can pin
    the known set and go red when a new one is added.  Closing the gap means
    giving these settings an admission path, which is write-side work and is
    deliberately not done here.
    """

    return tuple(
        row
        for row in describe_settings(config, environ)
        if row.requires_confirmation and row.write_path == WRITE_ENVIRONMENT_ONLY
    )


def environment_shadowed_settings(
    config: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[SettingDescriptor, ...]:
    """Settings whose effective value comes from the environment right now.

    Every row here is one where the desktop UI would display the persisted
    document while the kernel reads something else.
    """

    return tuple(
        row
        for row in describe_settings(config, environ)
        if row.source == SOURCE_ENVIRONMENT
    )


def inert_settings(
    config: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[SettingDescriptor, ...]:
    """Settings accepted by the API that no live path consumes.

    Either normalization forces the stored value (``WRITE_NONE``) or the only
    consumer is a feature that refuses unconditionally.  Reported so a UI can
    stop offering a control that cannot change anything.
    """

    return tuple(
        row
        for row in describe_settings(config, environ)
        if row.write_path == WRITE_NONE
        or row.group == GROUP_EDITOR
        or row.id == "ollama.mode"
    )


__all__ = [
    "GROUPS",
    "GROUP_EDITOR",
    "GROUP_EXECUTION_LIMITS",
    "GROUP_LOCAL_RUNTIME",
    "GROUP_PROJECT_POLICY",
    "GROUP_TRUST",
    "SOURCES",
    "SOURCE_DEFAULT",
    "SOURCE_ENVIRONMENT",
    "SOURCE_FORCED",
    "SOURCE_PERSISTED",
    "SettingDescriptor",
    "WRITE_DESKTOP_SETTINGS",
    "WRITE_ENVIRONMENT_ONLY",
    "WRITE_NONE",
    "WRITE_PATHS",
    "WRITE_PROJECT_FILE",
    "describe_settings",
    "environment_shadowed_settings",
    "inert_settings",
    "unconfirmed_widening_settings",
]
