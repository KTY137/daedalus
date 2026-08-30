# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""A gold set for the funnel's precision metric, hand-verified 2026-07-30.

Every case below was checked against the real repository by hand that evening,
against the output of a four-tier advisory funnel over this codebase. They are
kept because a metric nobody has measured is just another claim, and this one
exists to decide whether OTHER claims are false -- so it has to be the most
carefully checked thing in the pipeline.

The set deliberately contains more NEGATIVES than positives. The failure that
matters here is calling an honest finding a lie: the metric's first version did
that 461 times in one run, and a checker that cries wolf is one its reader
learns to skip.
"""
from __future__ import annotations

import pytest

from daedalus.lanes.grounding import claim_text, judge

# What each module defines / imports, matching the real files these cases came
# from (daedalus/eval/correctness.py, daedalus/council/bus.py, and friends).
DEFINED = {
    "daedalus/eval/correctness.py": {"_refuse_primary_checkout",
                                     "derive_task_from_commit", "f2p", "p2p"},
    "daedalus/council/bus.py": {"_body_sha", "_entry_sha", "_resolve_store",
                                "append_roster"},
    "daedalus/sensitivity.py": {"lane_for_host"},
    "daedalus/tools/vet.py": {"scan_mcp"},
    "daedalus/adapters/base.py": set(),
    "daedalus/adapters/subprocess_adapter.py": {"SubprocessAdapter"},
}
IMPORTED = {
    "daedalus/adapters/base.py": {"AgentCapabilities", "AgentEvent"},
    "daedalus/eval/correctness.py": set(),
    "daedalus/council/bus.py": set(),
    "daedalus/sensitivity.py": set(),
    "daedalus/tools/vet.py": {"lane_for_host"},
    "daedalus/adapters/subprocess_adapter.py": set(),
}


def verdict(text, module):
    return judge(text, module, DEFINED, IMPORTED)[0]


# --------------------------------------------------------------------------
# positives: findings that are provably wrong about the program
# --------------------------------------------------------------------------

def test_symbol_claimed_absent_is_defined_in_that_very_file():
    # VERIFIED: _refuse_primary_checkout is at correctness.py:192. The scanner
    # saw a 120-line window that used it and concluded there was no definition.
    assert verdict(
        "_refuse_primary_checkout is referenced but never defined",
        "daedalus/eval/correctness.py") == "false"


def test_two_symbols_claimed_missing_both_exist():
    # VERIFIED: _body_sha at bus.py:182, _entry_sha at 186.
    assert verdict(
        "verify_chain calls _body_sha and _entry_sha, which do not exist",
        "daedalus/council/bus.py") == "false"


def test_symbol_absent_here_but_real_elsewhere_is_its_own_verdict():
    # VERIFIED: lane_for_host is defined in sensitivity.py, and a finding
    # placing it in vet.py is wrong about WHERE, not about WHETHER. Different
    # error, different repair, so a different verdict.
    assert verdict(
        "the egress check is broken because lane_for_host does not exist",
        "daedalus/eval/correctness.py") == "false-elsewhere"


# --------------------------------------------------------------------------
# negatives: honest findings that must never be scored as lies
# --------------------------------------------------------------------------

def test_a_claim_that_names_its_own_window_is_not_a_claim_about_the_program():
    # VERIFIED HONEST: the reader was given one chunk and said so. The names
    # are imported by the file, and the finding is true of what it was shown.
    assert verdict(
        "Imports from .events: AgentCapabilities and AgentEvent are not "
        "defined in this chunk.",
        "daedalus/adapters/base.py") == "scoped"


def test_expected_elsewhere_is_honest_not_false():
    # VERIFIED HONEST: it says outright that it expects them elsewhere.
    assert verdict(
        "_publish and _write_stdin are called but not defined in this chunk; "
        "they are expected to be defined elsewhere",
        "daedalus/adapters/subprocess_adapter.py") == "scoped"


def test_location_prefix_is_not_the_subject_of_the_claim():
    # VERIFIED HONEST: this is about a CHECK inside _resolve_store, not about
    # _resolve_store existing. The metric's first version manufactured a lie
    # out of it by reading the location column as the subject.
    raw = ("_resolve_store | medium | Mentions refusing paths under "
           "'<repo>/memory/' but code is truncated; the check may be missing "
           "| open the full function and look for the refusal")
    assert claim_text(raw).startswith("Mentions refusing paths")
    assert verdict(raw, "daedalus/council/bus.py") != "false"


def test_a_name_the_file_imports_is_undecided_not_false():
    # "not defined here" about an IMPORTED name is loose, not false. Precision
    # is what this metric spends; it does not spend it on that distinction.
    assert verdict(
        "AgentEvent is not defined anywhere",
        "daedalus/adapters/base.py") == "undecided"


def test_a_behavioural_claim_is_out_of_scope():
    # VERIFIED FALSE BY HAND, and the metric still must not claim it: the
    # funnel's top-ranked item said derive_task_from_commit never populates
    # f2p/p2p (it does, at correctness.py:1444). That is a claim about
    # BEHAVIOUR, and this metric only decides EXISTENCE. Saying "undecided"
    # here is the honest answer -- the limit is the point.
    assert verdict(
        "derive_task_from_commit never populates f2p and p2p and returns None",
        "daedalus/eval/correctness.py") == "undecided"


def test_unknown_module_is_undecided():
    assert verdict("thing is not defined", "daedalus/not/indexed.py") == "undecided"


@pytest.mark.parametrize("raw,expected", [
    ("a | high | b | c", "b"),
    ("no pipes here", "no pipes here"),
    ("x | not-a-severity | y", "x | not-a-severity | y"),
])
def test_claim_text_only_strips_a_real_finding_prefix(raw, expected):
    assert claim_text(raw) == expected
