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

# The composition rule is the LEDGER'S, and it is imported rather than
# reproduced.  A projection that re-derived "strictest wins" would be a second
# answer to the same question, and the one that drifts is always the copy.
from ...kernel.policy.ledger import (
    SOURCE_ADMITTED_DOCUMENT as LEDGER_SOURCE_ADMITTED_DOCUMENT,
    SOURCE_COMPOSED as LEDGER_SOURCE_COMPOSED,
    SOURCE_DEFAULT as LEDGER_SOURCE_DEFAULT,
    SOURCE_ENVIRONMENT as LEDGER_SOURCE_ENVIRONMENT,
    environment_limit_policy,
    strictest_number,
    strictest_policy,
)
from ...kernel.policy.pricing import BudgetError, _PRICES
from ...sensitivity import parse_declared_trusted_hosts
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
#: The persisted desktop document decides.  For the execution-limit axes this
#: is the kernel's ``SOURCE_ADMITTED_DOCUMENT``: since 2026-09-11
#: :class:`daedalus.kernel.policy.ledger.Ledger` composes the admitted document
#: with the environment, strictest-wins, so the document decides whenever it is
#: the narrower of the two.
SOURCE_PERSISTED: Final = "persisted"
#: A process environment variable decides at read time, being the narrower of
#: the two inputs (or the only one).  This is a statement about the canonical
#: READER, not about who wrote the variable: the desktop writes most of these
#: into its own environment.
SOURCE_ENVIRONMENT: Final = "environment"
#: Neither input alone: the strictest per-axis flag was taken from both.  Only
#: reachable for the execution-limit policy, where enforcement composes axis by
#: axis instead of collapsing to one number.
SOURCE_COMPOSED: Final = "composed"
#: Normalization overrides whatever the caller asked for.  The request is
#: accepted, reported as saved, and discarded.
SOURCE_FORCED: Final = "forced"

SOURCES: Final[tuple[str, ...]] = (
    SOURCE_DEFAULT,
    SOURCE_PERSISTED,
    SOURCE_ENVIRONMENT,
    SOURCE_COMPOSED,
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
    #: What the environment asked for and did not get, because the admitted
    #: document was narrower.  ``None`` whenever nothing was refused -- a
    #: narrowing is never refused, because the desktop admission path accepts a
    #: narrowing without a confirmation either.  For the limit policy this is a
    #: tuple of the axes the environment tried to disable.
    refused_environment_value: Any = None

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
            "refused_environment_value": (
                list(self.refused_environment_value)
                if isinstance(self.refused_environment_value, tuple)
                else self.refused_environment_value
            ),
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
ENV_PERIOD_CEILING_ENABLED: Final = "DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED"
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
) -> SettingDescriptor:
    """Describe a setting the desktop persists but the kernel reads from env.

    This is still the pre-G1-SETTINGS-02 precedence, and it is still exact for
    the rows that use it: ``OLLAMA_MODEL`` and ``OLLAMA_HOST`` are read
    verbatim by their consumers, so there is no "narrower" of two strings to
    take and a non-blank variable simply wins.  The composed precedence lives
    in :func:`_composed_number` and applies only to the numeric caps whose
    reader is :class:`daedalus.kernel.policy.ledger.Ledger`.
    """

    if _present(environ, variable):
        return SettingDescriptor(
            id=setting_id,
            group=group,
            value_type=value_type,
            default=default,
            effective=environ[variable].strip(),
            source=SOURCE_ENVIRONMENT,
            widens_authority=widens_authority,
            requires_confirmation=requires_confirmation,
            per_project=False,
            write_path=WRITE_DESKTOP_SETTINGS,
            environment_variable=variable,
            note=note,
        )
    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type=value_type,
        default=default,
        effective=stored,
        source=SOURCE_PERSISTED if stored != default else SOURCE_DEFAULT,
        widens_authority=widens_authority,
        requires_confirmation=requires_confirmation,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=variable,
        note=note,
    )


def _composed_number(
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
    document_present: bool,
    coerce: Callable[[str], Any],
) -> SettingDescriptor:
    """Describe a numeric limit the desktop persists and the kernel composes.

    Precedence mirrors the canonical reader exactly.  Until 2026-09-11 a
    non-blank variable simply won; since G1-SETTINGS-02 the ledger takes the
    STRICTEST of the admitted document and a non-blank variable, so:

    * no document on disk -- the variable decides, or the code default does;
    * a document and no variable -- the document decides;
    * both -- the smaller number decides, and when the variable was the larger
      one it is reported in ``refused_environment_value`` rather than dropped
      silently.

    ``coerce`` reproduces the reader's own parse so the reported effective
    value has the reader's type; a value the reader would refuse is reported as
    ``None``, because that is what fail-closed looks like, not as the raw text.
    """

    present = _present(environ, variable)
    environment: Any = None
    if present:
        raw = environ[variable].strip()
        environment = coerce(raw) if coerce is not None else raw

    document: Any = stored if document_present else None

    effective: Any
    refused: Any = None
    if present and environment is None:
        # The reader refuses an unusable variable outright and never falls back
        # to the document, so the honest report is fail-closed for BOTH inputs.
        effective, source = None, SOURCE_ENVIRONMENT
    else:
        effective, ledger_source, refused = strictest_number(
            document=document,
            environment=environment,
            default=default,
        )
        source = (
            SOURCE_ENVIRONMENT
            if ledger_source == LEDGER_SOURCE_ENVIRONMENT
            else SOURCE_DEFAULT
            if ledger_source == LEDGER_SOURCE_DEFAULT or effective == default
            else SOURCE_PERSISTED
        )

    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type=value_type,
        default=default,
        effective=effective,
        source=source,
        widens_authority=widens_authority,
        requires_confirmation=requires_confirmation,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=variable,
        note=note,
        refused_environment_value=refused,
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
    coerce: Callable[[str], Any] | None = None,
) -> SettingDescriptor:
    """Describe a setting with no admission path at all.

    ``coerce`` receives the RAW value, blanks included, and returns what the
    canonical reader would make of it -- or ``None`` where that reader refuses.
    Without one the row reports the stripped text, which is only honest for a
    variable its reader also uses verbatim.  A row that reports raw text where
    its reader normalises, drops or refuses is worse than no row: it states a
    fact about this machine that is not true.
    """

    raw = environ.get(variable)
    if raw is None:
        effective, source = default, SOURCE_DEFAULT
    elif coerce is not None:
        effective, source = coerce(raw), SOURCE_ENVIRONMENT
    elif raw.strip():
        effective, source = raw.strip(), SOURCE_ENVIRONMENT
    else:
        effective, source = default, SOURCE_DEFAULT
    return SettingDescriptor(
        id=setting_id,
        group=group,
        value_type=value_type,
        default=default,
        effective=effective,
        source=source,
        widens_authority=widens_authority,
        requires_confirmation=requires_confirmation,
        per_project=False,
        write_path=WRITE_ENVIRONMENT_ONLY,
        environment_variable=variable,
        note=note,
    )


# --------------------------------------------------------------------------- #
# What each canonical reader makes of a raw value.                            #
# --------------------------------------------------------------------------- #
def _coerce_period(raw: str) -> Any:
    """``Ledger.period()``: an empty value is the default, a wrong one refuses."""

    if not raw:
        return "day"
    value = raw.strip().lower()
    return value if value in ("day", "total") else None


def _coerce_legacy_period_ceiling(raw: str) -> Any:
    """``ledger.environment_limit_policy``: blank absent, garbage refuses."""

    value = raw.strip().lower()
    if not value:
        return True
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _coerce_on_unknown(raw: str) -> Any:
    """``pricing._on_unknown()``: anything unrecognised NORMALISES to worst_case."""

    value = (raw or "worst_case").strip().lower()
    return value if value in ("worst_case", "refuse") else "worst_case"


def _coerce_subscription_vendors(raw: str) -> Any:
    """``pricing.subscription_vendors()``: unknown vendor names are dropped."""

    named = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return sorted(name for name in named if name in _PRICES)


def _coerce_trusted_hosts(raw: str) -> Any:
    """``sensitivity.declared_trusted_hosts()``: names and wildcards dropped.

    Calls the one implementation rather than reproducing it. Reporting the raw
    text here would tell an owner that ``localhost`` is inside their egress
    trust boundary when the rule deliberately drops every non-numeric entry.
    """

    return sorted(parse_declared_trusted_hosts(raw))


def _coerce_remote_consent(raw: str) -> Any:
    """``providers.ollama.remote_endpoint_consented()``: exact-host consent."""

    return raw.strip()


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
    *,
    document_present: bool = True,
) -> tuple[SettingDescriptor, ...]:
    """Project one typed description of the whole settings surface.

    ``config`` is a normalized desktop settings document -- exactly the shape
    :func:`daedalus.interfaces.desktop.configuration.normalize_config`
    returns and ``manager.config`` holds.  ``environ`` is the process
    environment the kernel would read.  Neither is mutated and neither is
    resolved from a global: a caller inspecting a saved document against a
    hypothetical environment gets an honest answer for that pair.

    ``document_present`` is the third fact the answer depends on since
    G1-SETTINGS-02: the ledger composes an admitted document with the
    environment only when ``config/connections.json`` EXISTS, and
    ``manager.config`` is a full normalized mapping either way.  A caller that
    holds a manager passes ``manager.config_path.exists()``.  The default is
    ``True`` because that is the narrower reading -- an existing document
    constrains the environment, an absent one does not.

    Ordering is deterministic and grouped, so two processes describing the
    same pair produce the same tuple.
    """

    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    if not isinstance(environ, Mapping):
        raise TypeError("environ must be a mapping")
    if type(document_present) is not bool:
        raise TypeError("document_present must be a boolean")

    # THE default is what ``defaults()`` produces on THIS host, not the raw
    # ``DEFAULT_CONFIG`` literal.  Measured 2026-09-10: ``defaults()``
    # rewrites ``ide.mode`` to "docker" on Windows, so a projection that
    # compared against the literal would report a fresh Windows install as
    # having "persisted" an editor choice the owner never made.
    base = defaults()

    out: list[SettingDescriptor] = []

    # -- execution limits ------------------------------------------------- #
    out.append(_composed_number(
        setting_id="budget.period_ceiling_usd",
        group=GROUP_EXECUTION_LIMITS,
        value_type="number",
        default=base["budget"]["period_ceiling_usd"],
        stored=_stored(config, base, "budget", "period_ceiling_usd"),
        environ=environ,
        variable=ENV_BUDGET_USD,
        coerce=_coerce_positive_float,
        document_present=document_present,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Raising it is a widening and the desktop path demands "
            "caps.confirm_widening. Ledger.ceiling_usd() takes the STRICTEST "
            "of this document and DAEDALUS_BUDGET_USD, so a saved value "
            "reaches every process and an ambient variable cannot raise it."
        ),
    ))
    out.append(_composed_number(
        setting_id="budget.max_calls",
        group=GROUP_EXECUTION_LIMITS,
        value_type="integer",
        default=base["budget"]["max_calls"],
        stored=_stored(config, base, "budget", "max_calls"),
        environ=environ,
        variable=ENV_BUDGET_MAX_CALLS,
        coerce=_coerce_positive_int,
        document_present=document_present,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "Raising it is a widening and the desktop path demands "
            "caps.confirm_widening. Ledger.max_calls() takes the STRICTEST of "
            "this document and DAEDALUS_BUDGET_MAX_CALLS."
        ),
    ))

    caps = config.get("caps")
    caps = caps if isinstance(caps, Mapping) else base["caps"]
    # Ask the LEDGER what this environment states, rather than decoding one
    # variable here.  Two variables can state it -- the canonical JSON one and
    # the retired Revision-9 boolean -- and a projection that modelled only the
    # first said "bounded" while the kernel ran with no period ceiling.
    # MEASURED 2026-09-11 before this call replaced the single-variable decode.
    env_policy: ExecutionLimitPolicy | None = None
    env_policy_note = ""
    env_policy_failed = False
    try:
        env_policy = environment_limit_policy(environ)
    except (BudgetError, LimitPolicyError) as exc:
        env_policy_failed = True
        env_policy_note = (
            f" The current environment value is invalid ({exc}), so every "
            "Ledger read fails closed rather than picking a mode."
        )
    env_policy_set = env_policy is not None or env_policy_failed
    stored_mode = caps.get("mode", base["caps"]["mode"])
    configured = caps.get("configured")
    configured = (
        configured if isinstance(configured, Mapping)
        else base["caps"]["configured"]
    )
    # Reproduce ``Ledger._resolve_policy`` exactly: the document participates
    # only when it exists, the variable only when it is set, and an axis is
    # enforced when EITHER of the participating inputs enforces it.
    document_policy: ExecutionLimitPolicy | None = None
    if document_present:
        try:
            document_policy = ExecutionLimitPolicy.from_dict(
                {"mode": stored_mode, "configured": dict(configured)}
            )
        except LimitPolicyError:
            document_policy = None
    composed_mode: Any
    composed_axes: Mapping[str, Any]
    refused_axes: tuple[str, ...] = ()
    if env_policy_failed:
        # An undecodable variable makes every Ledger read fail closed. Nothing
        # is composed and nothing is effective.
        composed_mode = None
        composed_axes = {axis: None for axis in LIMIT_AXES}
        caps_source = SOURCE_ENVIRONMENT
    else:
        effective_policy, caps_source, refused_axes = strictest_policy(
            document=document_policy,
            environment=env_policy,
        )
        composed_mode = effective_policy.mode
        composed_axes = effective_policy.configured.as_dict()
        caps_source = {
            LEDGER_SOURCE_ADMITTED_DOCUMENT: SOURCE_PERSISTED,
            LEDGER_SOURCE_ENVIRONMENT: SOURCE_ENVIRONMENT,
            LEDGER_SOURCE_COMPOSED: SOURCE_COMPOSED,
            LEDGER_SOURCE_DEFAULT: SOURCE_DEFAULT,
        }[caps_source]
        if (
            caps_source == SOURCE_PERSISTED
            and stored_mode == base["caps"]["mode"]
            and dict(configured) == dict(base["caps"]["configured"])
        ):
            caps_source = SOURCE_DEFAULT
    out.append(SettingDescriptor(
        id="caps.mode",
        group=GROUP_EXECUTION_LIMITS,
        value_type=f"enum[{'|'.join(LIMIT_MODES)}]",
        default=base["caps"]["mode"],
        effective=composed_mode,
        source=caps_source,
        widens_authority=True,
        requires_confirmation=True,
        per_project=False,
        write_path=WRITE_DESKTOP_SETTINGS,
        environment_variable=ENV_LIMIT_POLICY,
        note=(
            "unbounded_execution disables all eight resource axes. The "
            "desktop path refuses that without caps.confirm_widening; "
            "Ledger.execution_limit_policy() enforces an axis when EITHER "
            "this document or the environment variable enforces it, so the "
            "variable can narrow but never widen." + env_policy_note
        ),
        refused_environment_value=refused_axes or None,
    ))
    for axis in LIMIT_AXES:
        out.append(SettingDescriptor(
            id=f"caps.configured.{axis}",
            group=GROUP_EXECUTION_LIMITS,
            value_type="boolean",
            default=True,
            effective=composed_axes.get(axis),
            source=caps_source,
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
        coerce=_coerce_period,
        widens_authority=False,
        requires_confirmation=False,
        note=(
            "How long the USD ceiling lasts. No desktop field exists, so the "
            "UI shows a ceiling without saying over what period it applies. "
            "Ledger.period() lowercases the value and REFUSES anything "
            "outside day|total, whitespace included."
        ),
    ))
    out.append(_env_only(
        setting_id="budget.period_ceiling_enabled",
        group=GROUP_EXECUTION_LIMITS,
        value_type="boolean",
        default=True,
        environ=environ,
        variable=ENV_PERIOD_CEILING_ENABLED,
        coerce=_coerce_legacy_period_ceiling,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "The retired Revision-9 boolean. Ledger.execution_limit_policy() "
            "still consults it whenever DAEDALUS_EXECUTION_LIMIT_POLICY is "
            "blank or absent, so an inherited 0 disables the period USD "
            "ceiling with no field, no admission path and no confirmation. "
            "Since G1-SETTINGS-02 an admitted document overrides it, because "
            "an axis is enforced when EITHER input enforces it; with no "
            "document on disk it still decides alone. A value that is "
            "neither truthy nor falsy makes every ledger read refuse."
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
        coerce=_coerce_on_unknown,
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
        coerce=_coerce_subscription_vendors,
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
        coerce=_coerce_trusted_hosts,
        widens_authority=True,
        requires_confirmation=True,
        note=(
            "sensitivity.declared_trusted_hosts() moves a numeric address "
            "inside the egress trust boundary, so repository content may "
            "leave this machine for it. NAMES ARE DROPPED, never resolved, "
            "and so are wildcards and typos: the effective value here is "
            "what that rule kept, not what was typed. Read once at desktop "
            "start into _base_trusted and re-projected verbatim; there is "
            "no field, no validation and no confirmation."
        ),
    ))
    out.append(_env_only(
        setting_id="trust.ollama_remote_consent",
        group=GROUP_TRUST,
        value_type="host",
        default="",
        environ=environ,
        variable=ENV_OLLAMA_REMOTE_OK,
        coerce=_coerce_remote_consent,
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
