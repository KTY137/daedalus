"""The browser gate's per-suite budget, and why it is overridable.

`tools/gui_check.py` is the documented way to run the browser acceptance
suite -- `playwright.config.ts` says "Run it through the harness, never by
hand". Its per-suite budget was a hard-coded 600s, sized for a machine
running only this.

[MEASURED 2026-09-03] the shell suite took 13.9 minutes on this box while
parallel agent sessions held ~87 python processes. The harness therefore
reported ``VERDICT: FAIL -- the cockpit does not do what it says`` for a
suite whose 45 specs were, in the same minutes, all green. A FAIL that
means "the machine was busy" is exactly the kind of number this repository
refuses to report, and the practical consequence was that the browser gate
could not be run here at all.

The override does not weaken the gate: the default is unchanged, a timeout
is still a FAIL, and a value that is not a positive number is IGNORED
rather than obeyed -- otherwise a typo would be a way to remove the bound.
"""
from __future__ import annotations

import pytest

from tools import gui_check


def test_the_default_budget_is_unchanged_when_nothing_is_set():
    assert gui_check.suite_timeout_s({}) == 600.0
    assert gui_check.SUITE_TIMEOUT_DEFAULT_S == 600


def test_an_operator_can_say_how_slow_their_box_is():
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: "1800"}) == 1800.0
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: " 900.5 "}) == 900.5


@pytest.mark.parametrize("value", ["", "   ", "off", "none", "0", "-1", "nan-ish", "1e"])
def test_a_value_that_is_not_a_positive_number_cannot_remove_the_bound(value: str):
    """A typo must not be a way to disable the timeout. Every one of these
    falls back to the default rather than becoming "no limit"."""
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: value}) == 600.0


def test_the_timeout_message_tells_the_operator_what_to_do():
    """A verdict that cannot be acted on costs the next person an hour.

    The first version of this test asserted against the module's SOURCE and
    passed for the wrong reason -- the name appears there inside an f-string
    placeholder, not in anything a human ever reads. It asserts the produced
    message now.
    """
    message = gui_check.timeout_message(600.0)
    assert "did not finish within 600s" in message
    # both causes named, so nobody has to guess which one they have
    assert "under load" in message
    assert "stuck" in message
    # and the lever is in the sentence, not only in the source
    assert gui_check.SUITE_TIMEOUT_ENV in message
    assert gui_check.timeout_message(1800.0).startswith(
        "the browser suite did not finish within 1800s"
    )
