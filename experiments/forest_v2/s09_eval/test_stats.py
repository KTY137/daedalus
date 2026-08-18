"""Tests for the uncertainty machinery.

A bootstrap that silently reports a too-narrow interval is worse than no
interval at all, so these check the properties the tables lean on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import stats  # noqa: E402


def test_interval_brackets_the_point_estimate():
    values = [0.0, 0.2, 0.5, 1.0, 0.3, 0.1, 0.9, 0.4]
    interval = stats.bootstrap_mean(values, resamples=500)
    assert abs(interval.point - sum(values) / len(values)) < 1e-12
    assert interval.low <= interval.point <= interval.high


def test_bootstrap_is_reproducible_across_runs():
    values = [0.1, 0.7, 0.2, 0.9]
    a = stats.bootstrap_mean(values, resamples=300, seed=7)
    b = stats.bootstrap_mean(values, resamples=300, seed=7)
    assert (a.low, a.high) == (b.low, b.high)


def test_a_constant_sample_has_a_degenerate_interval():
    interval = stats.bootstrap_mean([0.5] * 10, resamples=200)
    assert interval.low == interval.high == 0.5


def test_a_small_noisy_sample_produces_a_wide_interval():
    """The honest behaviour on n=20-ish data: wide, not confident."""
    interval = stats.bootstrap_mean([0.0] * 10 + [1.0] * 10, resamples=1000)
    assert interval.high - interval.low > 0.3


def test_empty_input_does_not_crash():
    interval = stats.bootstrap_mean([], resamples=100)
    assert interval.point == 0.0 and interval.resamples == 0


def test_paired_delta_detects_a_consistent_win():
    subject = [0.5] * 12
    reference = [0.2] * 12
    delta = stats.paired_delta("s", "r", subject, reference, resamples=500)
    assert abs(delta.delta.point - 0.3) < 1e-12
    assert delta.separated
    assert delta.share_favouring_subject == 1.0
    assert (delta.cases_better, delta.cases_worse, delta.cases_tied) == (12, 0, 0)


def test_paired_delta_reports_no_separation_when_arms_trade_wins():
    subject = [1.0, 0.0] * 6
    reference = [0.0, 1.0] * 6
    delta = stats.paired_delta("s", "r", subject, reference, resamples=1000)
    assert abs(delta.delta.point) < 1e-12
    assert not delta.separated, "trading wins evenly must not look like a win"
    assert delta.cases_better == delta.cases_worse == 6


def test_pairing_uses_the_same_resample_for_both_arms():
    """Unpaired resampling would widen this interval and hide the effect."""
    subject = [0.0, 0.1, 0.9, 1.0] * 4
    reference = [v - 0.05 for v in subject]  # tiny, perfectly consistent edge
    delta = stats.paired_delta("s", "r", subject, reference, resamples=1000)
    assert delta.separated
    assert delta.delta.high - delta.delta.low < 1e-9


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="one score per case"):
        stats.paired_delta("s", "r", [0.1, 0.2], [0.1], resamples=10)


def test_comparison_table_marks_separation():
    delta = stats.paired_delta("s", "r", [0.9] * 8, [0.1] * 8, resamples=200)
    table = stats.comparison_table([delta])
    assert "excludes 0" in table and "| yes |" in table


def test_tables_stay_printable_on_a_cp1252_console():
    """A Greek delta in the header crashed a real Windows run; keep it ASCII."""
    delta = stats.paired_delta("s", "r", [0.9] * 4, [0.1] * 4, resamples=50)
    for table in (stats.comparison_table([delta]), str(delta.delta)):
        table.encode("cp1252")  # raises UnicodeEncodeError on regression


def test_paired_delta_carries_its_query_variant():
    """Without this field the published array has colliding keys (F5).

    ``Aggregate.as_dict`` always emitted ``variant``; ``PairedDelta`` did not,
    while the harness concatenated both variants into one flat list.  A
    consumer keying on ``(subject, reference)`` therefore read the scrubbed
    number believing it was the raw one.
    """
    delta = stats.paired_delta(
        "s", "r", [0.5, 0.4], [0.1, 0.2], resamples=50, variant="scrubbed"
    )
    assert delta.variant == "scrubbed"
    assert delta.as_dict()["variant"] == "scrubbed"


def test_paired_deltas_of_two_variants_do_not_share_a_key():
    raw = stats.paired_delta("s", "r", [0.5], [0.1], resamples=20, variant="raw")
    scrubbed = stats.paired_delta(
        "s", "r", [0.2], [0.1], resamples=20, variant="scrubbed"
    )
    key = lambda d: (d.subject, d.reference, d.variant)  # noqa: E731
    assert key(raw) != key(scrubbed)
    assert (raw.subject, raw.reference) == (scrubbed.subject, scrubbed.reference), (
        "this test is only meaningful while the pair alone would collide"
    )


def test_comparison_table_shows_which_variant_each_row_is():
    rendered = stats.comparison_table(
        [stats.paired_delta("s", "r", [0.5], [0.1], resamples=20, variant="raw")]
    )
    assert "variant" in rendered.splitlines()[0]
    assert "| raw |" in rendered
