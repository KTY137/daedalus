"""The kernel must read what the owner admitted, and only what was admitted.

G1-SETTINGS-02 closes defect D1 of G1-SETTINGS-01 in both directions:

* a value saved through ``PUT /api/desktop/settings`` reaches a process the
  desktop did not start;
* a value that reaches the kernel cannot WIDEN past what was admitted, so the
  process environment stops being an unconfirmed authority-widening path
  (master plan section 4.1).

Every test here is a MEASUREMENT of the composed resolution, and each one is
written so that removing the code it guards turns it red -- see the mutation
table in ``docs/work-packets/G1-SETTINGS-02_ADMITTED_EXECUTION_LIMITS.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.interfaces.desktop.configuration import defaults, normalize_config
from daedalus.interfaces.desktop.sidecar import bundled_root
from daedalus.kernel.policy.ledger import (
    ADMITTED_SETTINGS_REL,
    ROOT,
    AdmittedSettingsUnreadable,
    BudgetUnavailable,
    DEFAULT_CEILING_USD,
    DEFAULT_MAX_CALLS,
    Ledger,
    SOURCE_ADMITTED_DOCUMENT,
    SOURCE_COMPOSED,
    SOURCE_DEFAULT,
    SOURCE_ENVIRONMENT,
    SOURCE_ISSUED_CONTRACT,
    admitted_settings_path,
    load_admitted_settings,
)
from daedalus.kernel.policy.limits import (
    LIMIT_AXES,
    ExecutionLimitPolicy,
    LimitAxes,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
)

BUDGET_ENV = (
    "DAEDALUS_BUDGET_USD",
    "DAEDALUS_BUDGET_MAX_CALLS",
    "DAEDALUS_EXECUTION_LIMIT_POLICY",
    "DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED",
)


@pytest.fixture(autouse=True)
def _clean_budget_environment(monkeypatch):
    """Start every case from an environment that states nothing."""

    for name in BUDGET_ENV:
        monkeypatch.delenv(name, raising=False)


def _admit(root: Path, **overrides) -> dict:
    """Write a document the way the admitted path writes one, and return it."""

    document = defaults()
    budget = {k: v for k, v in overrides.items() if k in document["budget"]}
    document["budget"].update(budget)
    if "caps" in overrides:
        document["caps"] = overrides["caps"]
    document = normalize_config(document)
    target = root / ADMITTED_SETTINGS_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return document


def _policy_env(policy: ExecutionLimitPolicy) -> str:
    return policy.to_env_value()


@pytest.fixture()
def desktop(tmp_path, monkeypatch):
    """A manager whose effects are admitted, exactly as the desktop suite does.

    ``save_settings`` is an effect: it takes an ``EffectLease`` behind an armed
    kill switch.  Arming an operator permit in ``tmp_path`` is the same setup
    ``tests/test_desktop_runtime.py`` uses; without it the save refuses, which
    is the correct fail-closed behaviour and not what these cases are about.
    """

    from daedalus import budget as budget_kernel
    from daedalus.desktop_runtime import DesktopRuntimeManager
    from daedalus.spine.killswitch import ENV_SWITCH_PATH, KillSwitch

    permit = tmp_path / "operator-armed-desktop-switch"
    KillSwitch(permit).arm(note="G1-SETTINGS-02 test operator")
    monkeypatch.setenv(ENV_SWITCH_PATH, str(permit))
    monkeypatch.setenv(
        budget_kernel.ENV_LEDGER, str(tmp_path / "desktop-budget.json")
    )
    budget_kernel.reset_default_ledger()

    manager = DesktopRuntimeManager(tmp_path)
    monkeypatch.setattr(
        manager,
        "_ide_status",
        lambda project=None, **kwargs: {"reachable": False, "last_error": "offline"},
    )
    try:
        yield manager
    finally:
        manager.close()
        budget_kernel.reset_default_ledger()


UNBOUNDED = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)


# --------------------------------------------------------------------------- #
# D1, direction (a): the admitted document reaches the kernel                 #
# --------------------------------------------------------------------------- #


def test_admitted_document_reaches_a_process_the_desktop_did_not_start(tmp_path):
    """MEASURED before the fix: 5.0 and 40, whatever the owner had saved."""

    _admit(tmp_path, period_ceiling_usd=200.0, max_calls=5000)
    ledger = Ledger(runtime_root=tmp_path)

    assert ledger.ceiling_usd() == 200.0
    assert ledger.max_calls() == 5000


def test_admitted_unbounded_mode_reaches_the_kernel(tmp_path):
    _admit(tmp_path, caps=UNBOUNDED.as_dict())
    policy = Ledger(runtime_root=tmp_path).execution_limit_policy()

    assert policy.mode == MODE_UNBOUNDED_EXECUTION
    for axis in LIMIT_AXES:
        assert policy.enforces(axis) is False, axis


def test_a_missing_document_leaves_every_reader_exactly_as_it_was(tmp_path):
    """Blast radius: no ``config/connections.json`` means nothing changes."""

    ledger = Ledger(runtime_root=tmp_path)

    assert ledger.ceiling_usd() == DEFAULT_CEILING_USD
    assert ledger.max_calls() == DEFAULT_MAX_CALLS
    assert ledger.execution_limit_policy() == ExecutionLimitPolicy()
    assert load_admitted_settings(tmp_path) is None


# --------------------------------------------------------------------------- #
# D1, direction (b): an unadmitted variable cannot widen                      #
# --------------------------------------------------------------------------- #


def test_unadmitted_environment_cannot_widen_past_the_admitted_document(
    tmp_path, monkeypatch
):
    """MEASURED before the fix: 999999.0 and 1000000 reached the kernel."""

    _admit(tmp_path, period_ceiling_usd=200.0, max_calls=5000)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "1000000")
    ledger = Ledger(runtime_root=tmp_path)

    assert ledger.ceiling_usd() == 200.0
    assert ledger.max_calls() == 5000


def test_unadmitted_environment_cannot_disable_a_cap_the_document_enforces(
    tmp_path, monkeypatch
):
    _admit(tmp_path)  # bounded
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", _policy_env(UNBOUNDED))
    ledger = Ledger(runtime_root=tmp_path)

    policy = ledger.execution_limit_policy()
    for axis in LIMIT_AXES:
        assert policy.enforces(axis) is True, axis

    report = ledger.limit_provenance()["execution_limit_policy"]
    assert report["source"] == SOURCE_ADMITTED_DOCUMENT
    assert set(report["refused_environment_axes"]) == set(LIMIT_AXES)


def test_the_retired_period_boolean_cannot_disable_an_admitted_ceiling(
    tmp_path, monkeypatch
):
    """The fifth env-only widening knob, found by review of the read half."""

    _admit(tmp_path)
    monkeypatch.setenv("DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED", "0")

    assert Ledger(runtime_root=tmp_path).period_ceiling_enabled() is True
    # ... and with nothing admitted it still decides alone, which is the gap
    # the projection now names instead of reporting "bounded".
    assert Ledger(runtime_root=tmp_path / "nowhere").period_ceiling_enabled() is False


# --------------------------------------------------------------------------- #
# The cost that was named rather than discovered: narrowing still wins        #
# --------------------------------------------------------------------------- #


def test_a_deliberately_narrower_variable_still_wins(tmp_path, monkeypatch):
    """Every shell, CI job and test that LOWERS a cap keeps working."""

    _admit(tmp_path, period_ceiling_usd=200.0, max_calls=5000)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "2")
    ledger = Ledger(runtime_root=tmp_path)

    assert ledger.ceiling_usd() == 1.0
    assert ledger.max_calls() == 2
    report = ledger.limit_provenance()
    assert report["period_ceiling_usd"]["source"] == SOURCE_ENVIRONMENT
    assert report["period_ceiling_usd"]["refused_environment_value"] is None


def test_a_narrower_variable_still_narrows_an_admitted_unbounded_document(
    tmp_path, monkeypatch
):
    _admit(tmp_path, caps=UNBOUNDED.as_dict())
    monkeypatch.setenv(
        "DAEDALUS_EXECUTION_LIMIT_POLICY", _policy_env(ExecutionLimitPolicy())
    )
    policy = Ledger(runtime_root=tmp_path).execution_limit_policy()

    for axis in LIMIT_AXES:
        assert policy.enforces(axis) is True, axis


def test_mixed_narrowing_composes_axis_by_axis(tmp_path, monkeypatch):
    _admit(
        tmp_path,
        caps=ExecutionLimitPolicy(
            mode=MODE_CUSTOM,
            configured=LimitAxes(period_usd=False, tokens=True),
        ).as_dict(),
    )
    monkeypatch.setenv(
        "DAEDALUS_EXECUTION_LIMIT_POLICY",
        _policy_env(
            ExecutionLimitPolicy(
                mode=MODE_CUSTOM,
                configured=LimitAxes(period_usd=True, tokens=False),
            )
        ),
    )
    ledger = Ledger(runtime_root=tmp_path)
    policy = ledger.execution_limit_policy()

    assert policy.enforces("period_usd") is True, "the environment narrowed it"
    assert policy.enforces("tokens") is True, "the document narrowed it"
    assert ledger.limit_provenance()["execution_limit_policy"]["source"] == (
        SOURCE_COMPOSED
    )


# --------------------------------------------------------------------------- #
# Design question 2: an environment value that never went through admission   #
# --------------------------------------------------------------------------- #


def test_an_unadmitted_widening_is_honoured_but_never_silent(
    tmp_path, monkeypatch
):
    """Honoured, because refusing would break every existing shell workflow.

    Reported, because honouring it silently is what made D1 invisible.
    """

    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", _policy_env(UNBOUNDED))
    ledger = Ledger(runtime_root=tmp_path)

    assert ledger.ceiling_usd() == 999999.0
    report = ledger.limit_provenance()
    assert report["admitted_document"] is None
    assert report["unadmitted_widening"] is True
    assert report["period_ceiling_usd"]["unadmitted_widening"] is True
    assert set(report["execution_limit_policy"]["unadmitted_disabled_axes"]) == set(
        LIMIT_AXES
    )


def test_an_unadmitted_narrowing_is_not_reported_as_a_widening(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1")
    report = Ledger(runtime_root=tmp_path).limit_provenance()

    assert report["unadmitted_widening"] is False
    assert report["period_ceiling_usd"]["unadmitted_widening"] is False


# --------------------------------------------------------------------------- #
# Refusals and fault injection                                                #
# --------------------------------------------------------------------------- #


def test_a_corrupt_document_refuses_instead_of_falling_back_to_the_environment(
    tmp_path, monkeypatch
):
    """Fail-closed, or corrupting the file is an escape hatch from the bound."""

    target = tmp_path / ADMITTED_SETTINGS_REL
    target.parent.mkdir(parents=True)
    target.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    ledger = Ledger(runtime_root=tmp_path)

    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.ceiling_usd()
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.max_calls()
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.execution_limit_policy()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param('["not", "an", "object"]', id="not-an-object"),
        pytest.param('{"budget": 3}', id="budget-not-an-object"),
        pytest.param('{"budget": {"period_ceiling_usd": "free"}}', id="ceiling-text"),
        pytest.param('{"budget": {"period_ceiling_usd": 0}}', id="ceiling-zero"),
        pytest.param('{"budget": {"period_ceiling_usd": -2}}', id="ceiling-negative"),
        pytest.param('{"budget": {"max_calls": -3}}', id="calls-negative"),
        pytest.param('{"budget": {"max_calls": true}}', id="calls-boolean"),
        pytest.param('{"budget": {"max_calls": 2.5}}', id="calls-fractional"),
        pytest.param('{"caps": {"mode": "off", "configured": {}}}', id="caps-mode"),
        pytest.param('{"caps": "unbounded"}', id="caps-text"),
    ],
)
def test_an_unusable_admitted_value_refuses(tmp_path, monkeypatch, payload):
    target = tmp_path / ADMITTED_SETTINGS_REL
    target.parent.mkdir(parents=True)
    target.write_text(payload, encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")

    with pytest.raises(AdmittedSettingsUnreadable):
        load_admitted_settings(tmp_path)


def test_an_unstated_axis_imposes_no_bound(tmp_path):
    """A partial hand-written document constrains only what it states."""

    target = tmp_path / ADMITTED_SETTINGS_REL
    target.parent.mkdir(parents=True)
    target.write_text('{"budget": {"period_ceiling_usd": 2.0}}', encoding="utf-8")
    admitted = load_admitted_settings(tmp_path)

    assert admitted is not None
    assert admitted.period_ceiling_usd == 2.0
    assert admitted.max_calls is None
    assert admitted.limit_policy is None
    assert Ledger(runtime_root=tmp_path).max_calls() == DEFAULT_MAX_CALLS


def test_a_directory_where_the_document_belongs_refuses(tmp_path):
    (tmp_path / ADMITTED_SETTINGS_REL).mkdir(parents=True)

    with pytest.raises(AdmittedSettingsUnreadable):
        load_admitted_settings(tmp_path)


def test_an_unusable_environment_value_still_refuses_with_a_document(
    tmp_path, monkeypatch
):
    _admit(tmp_path, period_ceiling_usd=200.0)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "free")

    with pytest.raises(BudgetUnavailable):
        Ledger(runtime_root=tmp_path).ceiling_usd()


def test_an_unusable_environment_policy_still_refuses_with_a_document(
    tmp_path, monkeypatch
):
    _admit(tmp_path)
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", "{invalid")

    with pytest.raises(BudgetUnavailable):
        Ledger(runtime_root=tmp_path).execution_limit_policy()


# --------------------------------------------------------------------------- #
# Section 4.1: the confirmation, and the contracts a save must not rewrite    #
# --------------------------------------------------------------------------- #


def test_the_widened_document_the_kernel_honours_required_a_confirmation(
    desktop, tmp_path, monkeypatch
):
    """End to end: the only path that can produce a widened document demands
    ``caps.confirm_widening``, and the kernel then honours what that path
    wrote.  If the confirmation ever stops being required, the first half of
    this test stops raising and the case goes red."""

    with pytest.raises(ValueError) as unconfirmed:
        desktop.save_settings(
            {"section_updates": {"budget": {"period_ceiling_usd": 500.0}}}
        )
    assert "confirm_widening" in str(unconfirmed.value)
    assert "period_ceiling_usd" in str(unconfirmed.value)
    assert not (tmp_path / ADMITTED_SETTINGS_REL).exists(), (
        "a refused widening must leave no document behind"
    )

    desktop.save_settings(
        {
            "section_updates": {
                "budget": {"period_ceiling_usd": 500.0, "confirm_widening": True}
            }
        }
    )

    for name in BUDGET_ENV:
        monkeypatch.delenv(name, raising=False)
    assert (tmp_path / ADMITTED_SETTINGS_REL).exists()
    assert Ledger(runtime_root=tmp_path).ceiling_usd() == 500.0


def test_a_narrowing_needs_no_confirmation_and_reaches_the_kernel(
    desktop, tmp_path, monkeypatch
):
    desktop.save_settings(
        {"section_updates": {"budget": {"period_ceiling_usd": 1.0}}}
    )

    for name in BUDGET_ENV:
        monkeypatch.delenv(name, raising=False)
    assert Ledger(runtime_root=tmp_path).ceiling_usd() == 1.0


def test_an_issued_contract_is_not_rewritten_by_a_later_document(tmp_path):
    """Master plan section 4.1, verbatim: an already issued contract stands."""

    _admit(tmp_path, period_ceiling_usd=200.0, max_calls=5000)
    issued = Ledger(
        tmp_path / "ledger.json",
        runtime_root=tmp_path,
        ceiling_usd=42.0,
        max_calls=7,
        execution_limit_policy=ExecutionLimitPolicy(),
    )

    _admit(tmp_path, period_ceiling_usd=1.0, max_calls=1, caps=UNBOUNDED.as_dict())

    assert issued.ceiling_usd() == 42.0
    assert issued.max_calls() == 7
    assert issued.execution_limit_policy().enforces("period_usd") is True
    report = issued.limit_provenance()
    assert report["period_ceiling_usd"]["source"] == SOURCE_ISSUED_CONTRACT
    assert report["execution_limit_policy"]["source"] == SOURCE_ISSUED_CONTRACT


def test_an_open_spend_envelope_keeps_the_cap_it_was_issued(tmp_path):
    _admit(tmp_path, period_ceiling_usd=200.0)
    ledger = Ledger(tmp_path / "ledger.json", runtime_root=tmp_path)

    envelope = ledger.open_envelope(label="issued", cap_usd=3.0)
    try:
        _admit(tmp_path, period_ceiling_usd=1.0)
        assert envelope.cap_usd == 3.0
        assert envelope.state()["cap_usd"] == 3.0
    finally:
        envelope.close(reason="test")


# --------------------------------------------------------------------------- #
# The document is found in code, never through the environment                #
# --------------------------------------------------------------------------- #


def test_no_environment_variable_relocates_the_admitted_document(monkeypatch):
    """A variable that named the file would be the hole this packet closes."""

    fake = "C:/nowhere" if Path("C:/").exists() else "/nowhere"
    for name in (
        "DAEDALUS_BUDGET_LEDGER",
        "DAEDALUS_DESKTOP_ROOT",
        "DAEDALUS_ROOT",
        "DAEDALUS_RUNTIME_ROOT",
        "DAEDALUS_CONFIG",
        "DAEDALUS_SETTINGS",
        "PWD",
    ):
        monkeypatch.setenv(name, fake)

    assert admitted_settings_path() == ROOT / ADMITTED_SETTINGS_REL


def test_the_anchor_is_the_packaged_desktop_runtime_root():
    """Direction (a) only closes if both entrypoints resolve the same root.

    ``sidecar.prepare_runtime`` creates ``config/`` under ``bundled_root()``
    and the desktop writes ``config/connections.json`` there.  If either
    anchor moves without the other, a saved value stops reaching the kernel
    and this case says so.
    """

    assert admitted_settings_path() == bundled_root() / ADMITTED_SETTINGS_REL


def test_the_relative_location_matches_the_single_writer():
    """``effects.py`` publishes to ``<root>/config/connections.json``."""

    assert ADMITTED_SETTINGS_REL == Path("config") / "connections.json"


# --------------------------------------------------------------------------- #
# The projection must not drift from the reader it describes                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("document_ceiling", [None, 1.0, 5.0, 200.0])
@pytest.mark.parametrize("environment_ceiling", [None, "1", "5", "999999"])
def test_the_projection_reports_what_the_ledger_resolves(
    tmp_path, monkeypatch, document_ceiling, environment_ceiling
):
    from daedalus.interfaces.desktop.settings_inventory import describe_settings

    document = defaults()
    if document_ceiling is not None:
        document = _admit(tmp_path, period_ceiling_usd=document_ceiling)
    environ = {}
    if environment_ceiling is not None:
        monkeypatch.setenv("DAEDALUS_BUDGET_USD", environment_ceiling)
        environ["DAEDALUS_BUDGET_USD"] = environment_ceiling

    rows = {
        row.id: row
        for row in describe_settings(
            document, environ, document_present=document_ceiling is not None
        )
    }
    assert rows["budget.period_ceiling_usd"].effective == (
        Ledger(runtime_root=tmp_path).ceiling_usd()
    )


@pytest.mark.parametrize("document_mode", [None, "bounded", "unbounded_execution"])
@pytest.mark.parametrize(
    "environment_mode", [None, "bounded", "unbounded_execution", "legacy_off"]
)
def test_the_projection_reports_the_caps_the_ledger_resolves(
    tmp_path, monkeypatch, document_mode, environment_mode
):
    from daedalus.interfaces.desktop.settings_inventory import describe_settings

    document = defaults()
    if document_mode is not None:
        document = _admit(
            tmp_path, caps=ExecutionLimitPolicy(mode=document_mode).as_dict()
        )
    environ: dict[str, str] = {}
    if environment_mode == "legacy_off":
        environ["DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED"] = "0"
    elif environment_mode is not None:
        environ["DAEDALUS_EXECUTION_LIMIT_POLICY"] = _policy_env(
            ExecutionLimitPolicy(mode=environment_mode)
        )
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    rows = {
        row.id: row
        for row in describe_settings(
            document, environ, document_present=document_mode is not None
        )
    }
    resolved = Ledger(runtime_root=tmp_path).execution_limit_policy()
    assert rows["caps.mode"].effective == resolved.mode
    for axis in LIMIT_AXES:
        assert rows[f"caps.configured.{axis}"].effective == getattr(
            resolved.configured, axis
        ), axis


def test_the_projection_refuses_a_non_boolean_document_flag():
    from daedalus.interfaces.desktop.settings_inventory import describe_settings

    with pytest.raises(TypeError):
        describe_settings(defaults(), {}, document_present="yes")
