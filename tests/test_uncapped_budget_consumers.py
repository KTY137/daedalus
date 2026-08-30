from __future__ import annotations

from types import SimpleNamespace

from daedalus.token_monitor import _render_budget_view
from tools import funnel


def _uncapped_state(**patch):
    values = {
        "period_ceiling_enabled": False,
        "remaining_usd": None,
        "ceiling_usd": 5.0,
        "spent_usd": 12.5,
        "calls": 2,
        "max_calls": 40,
        "billable_call_ceiling_enabled": True,
    }
    values.update(patch)
    return SimpleNamespace(**values)


def test_funnel_renders_uncapped_without_comparing_or_formatting_none():
    state = _uncapped_state()

    assert "period USD ceiling uncapped" in funnel.budget_verdict(state, 1)
    assert funnel.budget_summary(state) == "$12.50 of uncapped, 2 of 40 calls"


def test_funnel_uncapped_mode_still_refuses_at_the_call_axis():
    verdict = funnel.budget_verdict(
        _uncapped_state(calls=40, max_calls=40), 1
    )

    assert verdict.startswith("NO --")
    assert "call axis" in verdict


def test_funnel_reports_disabled_call_axis_without_a_numeric_sentinel():
    state = _uncapped_state(
        calls=400,
        max_calls=1,
        billable_call_ceiling_enabled=False,
    )

    assert funnel.budget_verdict(state, 100).startswith("YES")
    summary = funnel.budget_summary(state)
    assert "400 calls recorded, call ceiling disabled" in summary
    assert "of 1 calls" not in summary


def test_token_monitor_renders_uncapped_without_a_fake_numeric_ceiling():
    rendered = _render_budget_view(
        {
            "available": True,
            "period_ceiling_enabled": False,
            "ceiling_usd": 5.0,
            "spent_usd": 12.5,
            "reserved_usd": 1.25,
            "calls": 3,
            "max_calls": 40,
            "billable_call_ceiling_enabled": True,
            "period_key": "2026-08-30",
        }
    )

    assert "uncapped period USD ceiling" in rendered
    assert "$5.00 ceiling" not in rendered


def test_token_monitor_renders_disabled_call_axis_without_fake_headroom():
    rendered = _render_budget_view(
        {
            "available": True,
            "period_ceiling_enabled": True,
            "ceiling_usd": 5.0,
            "spent_usd": 1.0,
            "reserved_usd": 0.0,
            "calls": 99,
            "max_calls": 1,
            "billable_call_ceiling_enabled": False,
            "period_key": "2026-08-30",
        }
    )

    assert "99 calls recorded; call ceiling disabled" in rendered
    assert "99 of 1 calls" not in rendered
