"""Focused regression tests for the loop's finite safety-bound contract.

Issue #249 demonstrated that IEEE-754 NaN/+Infinity can satisfy the historical
``float(value) <= 0`` admission test and therefore disable a stop condition.
These tests keep the repair at the canonical ``LoopBounds`` boundary so custom
or injected executors cannot rely on a second safety layer to rescue an invalid
run configuration.
"""
from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from daedalus import loop as loopmod
from daedalus.loop import LoopBounds, LoopMisconfigured


class TestLoopBoundSafety(unittest.TestCase):
    def test_non_finite_wall_and_spend_bounds_are_refused(self) -> None:
        for field in ("max_wall_clock_s", "max_spend_usd"):
            for bad in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, bad=repr(bad)):
                    with self.assertRaises(LoopMisconfigured):
                        LoopBounds(**{field: bad})

    def test_count_bounds_keep_integer_semantics(self) -> None:
        for field in ("max_iterations", "max_attempts_per_candidate"):
            for bad in (True, 1.0, 1.5, "2"):
                with self.subTest(field=field, bad=repr(bad)):
                    with self.assertRaises(LoopMisconfigured):
                        LoopBounds(**{field: bad})

    def test_valid_bounds_remain_strict_json(self) -> None:
        bounds = LoopBounds(
            max_iterations=3,
            max_wall_clock_s=0.25,
            max_spend_usd=1,
            max_attempts_per_candidate=2,
        )
        encoded = json.dumps(bounds.to_dict(), allow_nan=False, sort_keys=True)
        self.assertIn('"max_wall_clock_s": 0.25', encoded)
        self.assertIn('"max_spend_usd": 1.0', encoded)

    def test_cli_nan_and_infinity_refuse_before_driver_construction(self) -> None:
        # main() deliberately crosses the canonical effect boundary before it
        # parses arguments. Stub those already-tested effects so this case can
        # assert the narrower property: parsed non-finite floats never reach a
        # LoopDriver, hence never obtain a live loop/executor.
        for flag, value in (
            ("--max-spend-usd", "nan"),
            ("--max-spend-usd", "inf"),
            ("--max-wall-clock-s", "nan"),
            ("--max-wall-clock-s", "inf"),
        ):
            with self.subTest(flag=flag, value=value), \
                 mock.patch("daedalus.dotenv.load"), \
                 mock.patch("daedalus.budget.install_process_guard"), \
                 mock.patch(
                     "daedalus.budget.process_guard_boundary_decision",
                     return_value=object(),
                 ), \
                 mock.patch("daedalus.spine.effect_boundary.begin_effect"), \
                 mock.patch.object(loopmod, "LoopDriver") as driver, \
                 mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                rc = loopmod.main([flag, value])
                self.assertEqual(rc, 2)
                driver.assert_not_called()
                self.assertIn("refusing to start", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
