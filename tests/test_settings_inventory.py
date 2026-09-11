"""The settings-surface projection must describe the tree that exists.

Every assertion here is a MEASUREMENT of the current backend, not a wish.
Three of these tests pin defects on purpose: when someone gives an env-only
widening knob a real admission path, or stops forcing an ``auto_start`` flag
to False, or teaches the kernel to read the persisted document, the pinned
set changes and the test goes red so the packet gets updated instead of the
inventory quietly drifting.
"""

from __future__ import annotations

import json

import pytest

from daedalus.interfaces.desktop.configuration import defaults, normalize_config
from daedalus.interfaces.desktop.settings_inventory import (
    GROUPS,
    SOURCE_DEFAULT,
    SOURCE_ENVIRONMENT,
    SOURCE_FORCED,
    SOURCE_PERSISTED,
    SOURCES,
    WRITE_DESKTOP_SETTINGS,
    WRITE_ENVIRONMENT_ONLY,
    WRITE_NONE,
    WRITE_PATHS,
    SettingDescriptor,
    describe_settings,
    environment_shadowed_settings,
    inert_settings,
    unconfirmed_widening_settings,
)
from daedalus.kernel.policy.ledger import DEFAULT_CEILING_USD, DEFAULT_MAX_CALLS
from daedalus.kernel.policy.limits import LIMIT_AXES, ExecutionLimitPolicy


@pytest.fixture()
def config() -> dict:
    """A normalized document exactly as ``manager.config`` holds one."""

    return defaults()


def _by_id(rows: tuple[SettingDescriptor, ...]) -> dict[str, SettingDescriptor]:
    return {row.id: row for row in rows}


# --------------------------------------------------------------------------- #
# Shape                                                                       #
# --------------------------------------------------------------------------- #


def test_every_descriptor_uses_the_declared_vocabulary(config):
    rows = describe_settings(config, {})
    assert rows, "the projection must not be empty"
    for row in rows:
        assert row.group in GROUPS, row.id
        assert row.source in SOURCES, row.id
        assert row.write_path in WRITE_PATHS, row.id
        assert isinstance(row.widens_authority, bool), row.id
        assert isinstance(row.requires_confirmation, bool), row.id
        assert isinstance(row.per_project, bool), row.id
        assert row.note.strip(), f"{row.id} must say something true about itself"


def test_setting_ids_are_unique_and_ordering_is_deterministic(config):
    first = describe_settings(config, {})
    second = describe_settings(config, {})
    ids = [row.id for row in first]
    assert len(ids) == len(set(ids))
    assert [row.id for row in second] == ids


def test_as_dict_is_json_serializable(config):
    payload = [row.as_dict() for row in describe_settings(config, {})]
    assert json.loads(json.dumps(payload)) == payload


def test_descriptors_are_frozen(config):
    row = describe_settings(config, {})[0]
    with pytest.raises(Exception):
        row.effective = "tampered"  # type: ignore[misc]


def test_non_mapping_inputs_are_refused(config):
    with pytest.raises(TypeError):
        describe_settings([], {})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        describe_settings(config, None)  # type: ignore[arg-type]


def test_projection_mutates_neither_input(config):
    before_config = json.dumps(config, sort_keys=True)
    environ = {"DAEDALUS_BUDGET_USD": "12"}
    before_environ = dict(environ)
    describe_settings(config, environ)
    assert json.dumps(config, sort_keys=True) == before_config
    assert environ == before_environ


# --------------------------------------------------------------------------- #
# The projection agrees with the code defaults it claims to describe          #
# --------------------------------------------------------------------------- #


def test_defaults_match_the_kernel_constants(config):
    rows = _by_id(describe_settings(config, {}))
    assert rows["budget.period_ceiling_usd"].default == DEFAULT_CEILING_USD
    assert rows["budget.max_calls"].default == DEFAULT_MAX_CALLS
    assert rows["caps.mode"].default == ExecutionLimitPolicy().mode
    for axis in LIMIT_AXES:
        assert rows[f"caps.configured.{axis}"].default is True


def test_every_limit_axis_is_described(config):
    ids = {row.id for row in describe_settings(config, {})}
    for axis in LIMIT_AXES:
        assert f"caps.configured.{axis}" in ids


def test_untouched_document_reports_default_not_persisted(config):
    for row in describe_settings(config, {}):
        assert row.source != SOURCE_PERSISTED, row.id


def test_a_changed_document_reports_persisted(config):
    changed = normalize_config(
        {"budget": {"period_ceiling_usd": 1.0, "max_calls": 7}},
        budget_defaults=config["budget"],
        caps_defaults=config["caps"],
    )
    rows = _by_id(describe_settings(changed, {}))
    assert rows["budget.period_ceiling_usd"].source == SOURCE_PERSISTED
    assert rows["budget.period_ceiling_usd"].effective == 1.0
    assert rows["budget.max_calls"].source == SOURCE_PERSISTED
    assert rows["budget.max_calls"].effective == 7


# --------------------------------------------------------------------------- #
# DEFECT 1: the kernel reads the environment, not the persisted document      #
# --------------------------------------------------------------------------- #


def _saved(config, **budget):
    return normalize_config(
        {"budget": budget},
        budget_defaults=config["budget"],
        caps_defaults=config["caps"],
    )


def test_a_narrower_variable_still_decides(config):
    """Ledger precedence, reproduced: the STRICTEST of the two decides."""

    saved = _saved(config, period_ceiling_usd=200.0, max_calls=5000)
    rows = _by_id(describe_settings(saved, {"DAEDALUS_BUDGET_USD": "3.5"}))
    row = rows["budget.period_ceiling_usd"]
    assert row.source == SOURCE_ENVIRONMENT
    assert row.effective == 3.5, "the owner saved 200.0 and 3.5 is narrower"
    assert row.environment_variable == "DAEDALUS_BUDGET_USD"
    assert row.refused_environment_value is None, "a narrowing is never refused"


def test_a_wider_variable_is_refused_and_named(config):
    """G1-SETTINGS-02: an unadmitted variable cannot widen past the document."""

    saved = _saved(config, period_ceiling_usd=200.0, max_calls=5000)
    rows = _by_id(describe_settings(saved, {"DAEDALUS_BUDGET_USD": "999999"}))
    row = rows["budget.period_ceiling_usd"]
    assert row.source == SOURCE_PERSISTED
    assert row.effective == 200.0
    assert row.refused_environment_value == 999999.0


def test_without_a_document_on_disk_the_variable_decides_alone(config):
    """``manager.config`` is a full mapping even when nothing was ever saved."""

    rows = _by_id(
        describe_settings(
            config, {"DAEDALUS_BUDGET_USD": "999999"}, document_present=False
        )
    )
    row = rows["budget.period_ceiling_usd"]
    assert row.source == SOURCE_ENVIRONMENT
    assert row.effective == 999999.0


def test_blank_environment_value_is_absent_like_the_readers_treat_it(config):
    rows = _by_id(describe_settings(config, {"DAEDALUS_BUDGET_USD": "   "}))
    assert rows["budget.period_ceiling_usd"].source == SOURCE_DEFAULT


def test_environment_shadowed_view_lists_exactly_the_shadowed_rows(config):
    """MEASURED 2026-09-11. ``9`` no longer shadows the default ``5.0``: the
    ledger takes the strictest, so only a NARROWER variable shadows now."""

    environ = {"DAEDALUS_BUDGET_USD": "1", "OLLAMA_MODEL": "llama3:8b"}
    shadowed = {row.id for row in environment_shadowed_settings(config, environ)}
    assert shadowed == {"budget.period_ceiling_usd", "ollama.model"}

    wider = {"DAEDALUS_BUDGET_USD": "9", "OLLAMA_MODEL": "llama3:8b"}
    shadowed = {row.id for row in environment_shadowed_settings(config, wider)}
    assert shadowed == {"ollama.model"}, "a wider variable shadows nothing"


def test_unusable_environment_value_reports_none_not_raw_text(config):
    """``_env_float`` refuses to guess; the projection must not guess either."""

    rows = _by_id(describe_settings(config, {"DAEDALUS_BUDGET_USD": "free"}))
    assert rows["budget.period_ceiling_usd"].effective is None
    rows = _by_id(describe_settings(config, {"DAEDALUS_BUDGET_MAX_CALLS": "-3"}))
    assert rows["budget.max_calls"].effective is None


def test_environment_limit_policy_is_decoded_per_axis(config):
    """With no document on disk the variable decides, axis by axis."""

    policy = ExecutionLimitPolicy(mode="unbounded_execution")
    rows = _by_id(describe_settings(
        config,
        {"DAEDALUS_EXECUTION_LIMIT_POLICY": policy.to_env_value()},
        document_present=False,
    ))
    assert rows["caps.mode"].effective == "unbounded_execution"
    for axis in LIMIT_AXES:
        row = rows[f"caps.configured.{axis}"]
        assert row.source == SOURCE_ENVIRONMENT
        assert row.effective is True, "configured choices are retained verbatim"


def test_an_admitted_bounded_document_refuses_an_unbounded_variable(config):
    """G1-SETTINGS-02: an axis is enforced when EITHER input enforces it."""

    policy = ExecutionLimitPolicy(mode="unbounded_execution")
    rows = _by_id(describe_settings(
        config, {"DAEDALUS_EXECUTION_LIMIT_POLICY": policy.to_env_value()}
    ))
    assert rows["caps.mode"].effective == "bounded"
    assert set(rows["caps.mode"].refused_environment_value) == set(LIMIT_AXES)


def test_the_retired_period_boolean_is_modelled(config):
    """MEASURED 2026-09-11 before this row existed: the projection said
    ``bounded``/``default`` while ``Ledger.execution_limit_policy()`` returned
    ``custom`` with the period USD ceiling unenforced, and no descriptor named
    the variable at all."""

    rows = _by_id(describe_settings(
        config,
        {"DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED": "0"},
        document_present=False,
    ))
    assert rows["budget.period_ceiling_enabled"].effective is False
    assert rows["budget.period_ceiling_enabled"].source == SOURCE_ENVIRONMENT
    assert rows["caps.mode"].effective == "custom"
    assert rows["caps.configured.period_usd"].effective is False


def test_an_unusable_retired_period_boolean_reports_fail_closed(config):
    rows = _by_id(describe_settings(
        config,
        {"DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED": "maybe"},
        document_present=False,
    ))
    assert rows["budget.period_ceiling_enabled"].effective is None
    assert rows["caps.mode"].effective is None
    for axis in LIMIT_AXES:
        assert rows[f"caps.configured.{axis}"].effective is None


@pytest.mark.parametrize(
    "variable, raw, expected",
    [
        ("DAEDALUS_BUDGET_PERIOD", "week", None),
        ("DAEDALUS_BUDGET_PERIOD", "DAY", "day"),
        ("DAEDALUS_BUDGET_PERIOD", "   ", None),
        ("DAEDALUS_BUDGET_ON_UNKNOWN", "refus", "worst_case"),
        ("DAEDALUS_BUDGET_ON_UNKNOWN", "refuse", "refuse"),
        ("DAEDALUS_SUBSCRIPTION_VENDORS", "notavendor,anthropic", []),
        ("DAEDALUS_SUBSCRIPTION_VENDORS", "DeepSeek , notavendor", ["deepseek"]),
        ("DAEDALUS_TRUSTED_HOSTS", "localhost", []),
        ("DAEDALUS_TRUSTED_HOSTS", "0.0.0.0", []),
        ("DAEDALUS_TRUSTED_HOSTS", "100.119.126.9", ["100.119.126.9"]),
    ],
)
def test_env_only_rows_report_what_their_reader_makes_of_the_value(
    config, variable, raw, expected
):
    """MEASURED 2026-09-11 before the coercions: every row above reported the
    raw text, including ``localhost`` as a declared egress-trust host, which
    ``declared_trusted_hosts`` deliberately drops."""

    rows = _by_id(describe_settings(config, {variable: raw}))
    row = next(r for r in rows.values() if r.environment_variable == variable)
    assert row.effective == expected


def test_invalid_environment_limit_policy_reports_fail_closed(config):
    rows = _by_id(describe_settings(
        config, {"DAEDALUS_EXECUTION_LIMIT_POLICY": "{invalid"}
    ))
    assert rows["caps.mode"].effective is None
    assert "fails closed" in rows["caps.mode"].note
    for axis in LIMIT_AXES:
        assert rows[f"caps.configured.{axis}"].effective is None


# --------------------------------------------------------------------------- #
# DEFECT 2: widening knobs with no admission path (master plan section 4.1)   #
# --------------------------------------------------------------------------- #


def test_pinned_set_of_widening_settings_without_a_confirming_path(config):
    """MEASURED 2026-09-11, five rows. The fifth -- the retired Revision-9
    boolean -- was found by independent review of the read half: the
    projection modelled no row for it while the kernel still consulted it.
    Adding a sixth must be a deliberate decision."""

    found = {row.id for row in unconfirmed_widening_settings(config, {})}
    assert found == {
        "budget.ledger_path",
        "budget.period_ceiling_enabled",
        "budget.subscription_vendors",
        "trust.declared_hosts",
        "trust.ollama_remote_consent",
    }


def test_those_settings_really_have_no_admission_path(config):
    for row in unconfirmed_widening_settings(config, {}):
        assert row.write_path == WRITE_ENVIRONMENT_ONLY, row.id
        assert row.environment_variable, row.id
        assert row.widens_authority is True, row.id


def test_execution_limit_widening_does_have_a_confirming_path(config):
    """The desktop door is not the gap; contrast it with the env-only rows."""

    rows = _by_id(describe_settings(config, {}))
    for setting_id in ("budget.period_ceiling_usd", "budget.max_calls", "caps.mode"):
        row = rows[setting_id]
        assert row.requires_confirmation is True
        assert row.write_path == WRITE_DESKTOP_SETTINGS


# --------------------------------------------------------------------------- #
# DEFECT 3: settings accepted, reported as saved, and discarded               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "setting_id", ["bridge.auto_start", "ollama.auto_start", "ide.auto_start"]
)
def test_forced_flags_are_reported_as_forced(config, setting_id):
    row = _by_id(describe_settings(config, {}))[setting_id]
    assert row.source == SOURCE_FORCED
    assert row.write_path == WRITE_NONE
    assert row.effective is False


@pytest.mark.parametrize(
    "section", ["bridge", "ollama", "ide"]
)
def test_the_forced_claim_matches_normalize_config(config, section):
    """The projection's claim is checked against the normalizer, not asserted."""

    request = json.loads(json.dumps(config))
    request[section]["auto_start"] = True
    stored = normalize_config(
        request, budget_defaults=config["budget"], caps_defaults=config["caps"]
    )
    assert stored[section]["auto_start"] is False, (
        "normalize_config no longer forces this flag; the projection's "
        "SOURCE_FORCED claim is now false and must be updated"
    )


def test_inert_settings_cover_the_dead_editor_and_remote_surface(config):
    found = {row.id for row in inert_settings(config, {})}
    assert found == {
        "bridge.auto_start",
        "ollama.auto_start",
        "ollama.mode",
        "ide.auto_start",
        "ide.mode",
        "ide.endpoint",
        "ide.executable",
        "ide.docker_image",
    }


# --------------------------------------------------------------------------- #
# Boundaries are described, never adjusted                                    #
# --------------------------------------------------------------------------- #


def test_sealed_promotion_is_reported_as_a_floor_not_a_choice(config):
    row = _by_id(describe_settings(config, {}))["project.write_wave_policy"]
    assert row.effective == "never"
    assert row.value_type == "enum[never]"


def test_per_project_rows_do_not_claim_one_global_effective_value(config):
    rows = [row for row in describe_settings(config, {}) if row.per_project]
    assert rows, "the project-scoped surface must be represented"
    for row in rows:
        assert row.write_path == "project_file", row.id
    external = _by_id(describe_settings(config, {}))[
        "project.policy.external_write_lanes"
    ]
    assert external.effective is None
    assert external.widens_authority is True
