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
from types import SimpleNamespace

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
# Section 4.1 encoding: a disabled cap has no live-looking number             #
# --------------------------------------------------------------------------- #


def test_a_disabled_axis_reports_a_null_effective_value(tmp_path, monkeypatch):
    """MEASURED 2026-09-11 before the fix: ``effective: 1.0`` sat beside
    ``period_usd: false``, i.e. a live-looking ceiling on an axis with no
    ceiling at all, using the word ``effective`` with the opposite meaning
    from ``BudgetState`` in the same module."""

    _admit(tmp_path, caps=UNBOUNDED.as_dict())
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1.0")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "2")
    report = Ledger(runtime_root=tmp_path).limit_provenance()

    for key in ("period_ceiling_usd", "max_calls"):
        row = report[key]
        assert row["enforced"] is False, key
        assert row["effective"] is None, key
        assert row["configured"] is not None, "the retained fallback stays"
    assert report["period_ceiling_usd"]["configured"] == 1.0
    assert report["max_calls"]["configured"] == 2
    assert report["execution_limit_policy"]["effective_axes"]["period_usd"] is False


def test_the_report_agrees_with_budget_state_on_a_disabled_axis(tmp_path):
    """One module, one meaning for the word ``effective``."""

    _admit(tmp_path, period_ceiling_usd=3.0, caps=UNBOUNDED.as_dict())
    ledger = Ledger(tmp_path / "ledger.json", runtime_root=tmp_path)
    report = ledger.limit_provenance()["period_ceiling_usd"]
    state = ledger.state()

    assert report["effective"] == state.effective_period_ceiling_usd is None
    assert report["configured"] == state.ceiling_usd == 3.0
    assert report["enforced"] == state.period_ceiling_enabled is False


def test_an_enforced_axis_still_reports_its_number(tmp_path, monkeypatch):
    _admit(tmp_path, period_ceiling_usd=200.0)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "7")
    row = Ledger(runtime_root=tmp_path).limit_provenance()["period_ceiling_usd"]

    assert row["enforced"] is True
    assert row["effective"] == 7.0 == row["configured"]
    assert row["nullified_environment_value"] is None


def test_a_narrower_bound_nullified_by_an_admitted_disabled_axis_is_reported(
    tmp_path, monkeypatch
):
    """The direction the review found silent, and it is the one that costs.

    A WIDER variable is refused and named. A NARROWER variable made moot by an
    axis the admitted document disabled used to produce nothing at all.
    """

    _admit(tmp_path, caps=UNBOUNDED.as_dict())
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1.0")
    row = Ledger(runtime_root=tmp_path).limit_provenance()["period_ceiling_usd"]

    assert row["nullified_environment_value"] == 1.0
    assert row["refused_environment_value"] is None, "it asked for less, not more"


def test_the_rendered_line_does_not_name_a_source_for_a_disabled_axis(
    tmp_path, monkeypatch
):
    from daedalus import budget as budget_kernel
    from daedalus.interfaces.cli import token_monitor

    _admit(tmp_path, caps=UNBOUNDED.as_dict())
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1.0")
    monkeypatch.setattr(
        budget_kernel,
        "Ledger",
        lambda **kwargs: Ledger(tmp_path / "ledger.json", runtime_root=tmp_path),
    )
    rendered = token_monitor._render_budget_view(token_monitor._budget_view())

    assert "ceiling from environment" not in rendered
    assert "period USD ceiling disabled" in rendered
    assert "DAEDALUS_BUDGET_USD=1.0" in rendered
    assert "no longer bounds anything" in rendered


def test_the_nullified_clause_never_claims_an_admission_that_did_not_happen(
    tmp_path, monkeypatch
):
    """MEASURED 2026-09-11 before the guard: with ``admitted_document: None``
    the line still read "the admitted document disabled the axis", announcing
    a confirmation nobody gave and telling an operator to stop hunting the
    rogue variable."""

    from daedalus import budget as budget_kernel
    from daedalus.interfaces.cli import token_monitor

    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", _policy_env(UNBOUNDED))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1.0")
    monkeypatch.setattr(
        budget_kernel,
        "Ledger",
        lambda **kwargs: Ledger(tmp_path / "ledger.json", runtime_root=tmp_path),
    )
    view = token_monitor._budget_view()
    assert view["limit_provenance"]["admitted_document"] is None
    rendered = token_monitor._render_budget_view(view)

    assert "the admitted document disabled the axis" not in rendered
    assert "the axis is disabled" in rendered
    assert "DAEDALUS_BUDGET_USD=1.0" in rendered


def test_one_number_never_carries_two_contradictory_explanations(
    tmp_path, monkeypatch
):
    """MEASURED 2026-09-11 before the ``refused is None`` clause: a $5 document
    with every axis disabled and DAEDALUS_BUDGET_USD=5000.0 reported 5000.0
    under BOTH refused_environment_value and nullified_environment_value."""

    _admit(tmp_path, period_ceiling_usd=5.0, caps=UNBOUNDED.as_dict())
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "5000.0")
    row = Ledger(runtime_root=tmp_path).limit_provenance()["period_ceiling_usd"]

    assert row["refused_environment_value"] == 5000.0, "it asked for more"
    assert row["nullified_environment_value"] is None
    assert not (
        row["refused_environment_value"] is not None
        and row["nullified_environment_value"] is not None
    ), "the two keys are mutually exclusive"


def test_the_reporting_surface_is_guarded_at_its_call_site(tmp_path, monkeypatch):
    """The 'never raises' contract is structural here, not documentary.

    ``limit_provenance`` catches ``BudgetUnavailable``. A future branch that
    raised something else would break the promise silently, and a monitor is
    the worst place to find that out.
    """

    from daedalus import budget as budget_kernel
    from daedalus.interfaces.cli import token_monitor

    class _Exploding(Ledger):
        def limit_provenance(self):
            raise OSError("a stat this surface never expected")

    monkeypatch.setattr(
        budget_kernel,
        "Ledger",
        lambda **kwargs: _Exploding(tmp_path / "ledger.json", runtime_root=tmp_path),
    )
    view = token_monitor._budget_view()

    assert view["limit_provenance"]["resolved"] is False
    assert "OSError" in view["limit_provenance"]["unresolved_reason"]
    assert "defect in the reporting surface" in (
        view["limit_provenance"]["unresolved_reason"]
    )


# --------------------------------------------------------------------------- #
# Refusals and fault injection                                                #
# --------------------------------------------------------------------------- #


def _corrupt(root: Path) -> Path:
    target = root / ADMITTED_SETTINGS_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ not json", encoding="utf-8")
    return target


def test_a_corrupt_document_refuses_instead_of_falling_back_to_the_environment(
    tmp_path, monkeypatch
):
    """Fail-closed, or corrupting the file is an escape hatch from the bound."""

    _corrupt(tmp_path)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    ledger = Ledger(runtime_root=tmp_path)

    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.ceiling_usd()
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.max_calls()
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.execution_limit_policy()


# --------------------------------------------------------------------------- #
# The refusal is narrowed: it stops a SPEND, not a READ                       #
# --------------------------------------------------------------------------- #


def test_a_corrupt_document_stops_every_spend_and_work_admission(tmp_path):
    """One bad file must fail closed where money moves."""

    from daedalus.kernel.policy.pricing import Estimate

    _corrupt(tmp_path)
    ledger = Ledger(tmp_path / "ledger.json", runtime_root=tmp_path)

    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.state()
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.reserve(
            Estimate("deepseek", "m", 0.01, 1, "priced"), label="blocked"
        )
    with pytest.raises(AdmittedSettingsUnreadable):
        ledger.open_envelope(label="blocked", cap_usd=1.0)


def test_a_corrupt_document_does_not_break_read_only_reporting(tmp_path):
    """One bad file must NOT become total unavailability.

    Before this packet a corrupt desktop document broke only the desktop.
    Making the kernel read it must not convert that into every CLI on the
    machine refusing, so the reporting surface still answers -- and answers
    with the file to repair.
    """

    target = _corrupt(tmp_path)
    report = Ledger(runtime_root=tmp_path).limit_provenance()

    assert report["resolved"] is False
    assert report["admitted_document"] == str(target)
    assert str(target) in report["admitted_document_unreadable"]
    assert "corrupt" in report["admitted_document_unreadable"]
    assert (
        "no new spend or work admission will be accepted"
        in report["admitted_document_unreadable"]
    )


def test_an_unreadable_document_is_never_reported_as_an_absent_one(
    tmp_path, monkeypatch
):
    """The actual bug behind the question: unreadable is not absent.

    Admission refuses and reporting says ``None``.  Neither may fall through to
    the branch where the environment decides alone, because that fallthrough is
    how corrupting a file would buy back an unadmitted widening.
    """

    _corrupt(tmp_path)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "1000000")
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", _policy_env(UNBOUNDED))
    report = Ledger(runtime_root=tmp_path).limit_provenance()

    assert report["period_ceiling_usd"]["effective"] is None
    assert report["max_calls"]["effective"] is None
    assert report["execution_limit_policy"]["mode"] is None
    assert report["execution_limit_policy"]["effective_axes"] is None
    assert report["unadmitted_widening"] is False
    for axis in ("period_ceiling_usd", "max_calls"):
        assert report[axis]["source"] is None, axis


def test_the_report_shape_is_the_same_whether_or_not_it_resolved(tmp_path):
    """A caller must not have to branch on two different report shapes."""

    resolved = Ledger(runtime_root=tmp_path).limit_provenance()
    _corrupt(tmp_path)
    unresolved = Ledger(runtime_root=tmp_path).limit_provenance()

    assert set(resolved) == set(unresolved)
    for axis in ("period_ceiling_usd", "max_calls", "execution_limit_policy"):
        assert set(resolved[axis]) == set(unresolved[axis]), axis
    assert resolved["resolved"] is True
    assert json.dumps(unresolved)  # JSON-serializable, like the resolved shape


def test_an_unusable_variable_is_reported_without_blaming_the_document(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "free")
    report = Ledger(runtime_root=tmp_path).limit_provenance()

    assert report["resolved"] is False
    assert report["admitted_document_unreadable"] == ""
    assert "DAEDALUS_BUDGET_USD" in report["unresolved_reason"]
    assert report["period_ceiling_usd"]["effective"] is None


def test_the_read_only_surfaces_still_run_with_a_corrupt_document(
    tmp_path, monkeypatch
):
    """The three read paths the tree actually has, exercised end to end."""

    from daedalus import budget as budget_kernel
    from daedalus.interfaces.cli import token_monitor
    from daedalus.orchestration import loop as loop_module

    _corrupt(tmp_path)
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "999999")
    monkeypatch.setattr(
        token_monitor,
        "REPO_ROOT",
        token_monitor.REPO_ROOT,
    )

    # 1. token-monitor: runs, reports unavailable, and names the file.
    def _ledger(**kwargs):
        return Ledger(tmp_path / "ledger.json", runtime_root=tmp_path)

    monkeypatch.setattr(budget_kernel, "Ledger", _ledger)
    view = token_monitor._budget_view()
    assert view["available"] is False
    rendered = token_monitor._render_budget_view(view)
    assert "budget: unavailable" in rendered
    assert str(tmp_path / ADMITTED_SETTINGS_REL) in rendered
    assert "no new spend or work admission will be accepted" in rendered

    # 2. the loop's spend probe: never raises, reports unreadable, which the
    #    caller treats as a reason to STOP rather than to continue.
    monkeypatch.setattr(budget_kernel, "ledger", _ledger)
    spend = loop_module.read_spend()
    assert spend.readable is False
    assert spend.spent_usd == 0.0
    assert "AdmittedSettingsUnreadable" in spend.error


def test_the_desktop_status_projection_reports_instead_of_raising(tmp_path):
    """The third read path: the desktop's own status panel."""

    from daedalus.interfaces.desktop import projection

    _corrupt(tmp_path)
    document = defaults()
    manager = SimpleNamespace(config=document, _budget_policy_error="")
    fake_kernel = SimpleNamespace(
        BudgetError=BudgetUnavailable.__mro__[1],
        ledger=lambda: Ledger(tmp_path / "ledger.json", runtime_root=tmp_path),
    )
    status = projection.budget_status(
        manager,
        budget_kernel=fake_kernel,
        execution_limit_policy=ExecutionLimitPolicy,
    )

    assert status["available"] is False
    assert str(tmp_path / ADMITTED_SETTINGS_REL) in status["last_error"]
    assert (
        "no new spend or work admission will be accepted" in status["last_error"]
    )


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
