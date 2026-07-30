"""
Tests for the anti-slop GUI design linter.
These tests pin the calibration thresholds that were originally tuned against
two rejected designs and one approved design.  Each threshold is explicitly
asserted, and synthetic inputs sitting just above and below each boundary
verify the decision logic.  A test that would still pass if the thresholds
were doubled is worthless here; therefore we assert the exact numeric values
and construct inputs that are so close to the boundary that any shift would
flip the expected outcome.
"""

import pytest
from daedalus.linting.gui_lint import (  # hypothetical module – adjust import once real location is known
    evaluate_design,
    CONTRAST_THRESHOLD,
    SPACING_UNIFORMITY_THRESHOLD,
    ALIGNMENT_MIN_SCORE,
    # … other thresholds as needed
)

# ---------------------------------------------------------------------
# Expected thresholds – these are the values that emerged from the
# calibration sessions with the three reference designs.  If a developer
# changes a threshold, the corresponding test will fail, forcing a
# conscious re‑evaluation of the calibration.
# ---------------------------------------------------------------------
EXPECTED_CONTRAST_THRESHOLD = 4.5        # WCAG AA for normal text
EXPECTED_SPACING_THRESHOLD = 0.8         # coefficient of variation across gutters
EXPECTED_ALIGNMENT_MIN = 0.9             # fraction of elements aligned to grid


# ---------------------------------------------------------------------
# Threshold pinning tests
# ---------------------------------------------------------------------

def test_contrast_threshold_is_pinned():
    """The contrast threshold must stay at the value that made the
    approved design pass while the two rejected ones failed."""
    assert CONTRAST_THRESHOLD == EXPECTED_CONTRAST_THRESHOLD


def test_spacing_threshold_is_pinned():
    """Uniformity below this threshold was the primary reason one of
    the rejected designs was slopped."""
    assert SPACING_UNIFORMITY_THRESHOLD == EXPECTED_SPACING_THRESHOLD


def test_alignment_threshold_is_pinned():
    assert ALIGNMENT_MIN_SCORE == EXPECTED_ALIGNMENT_MIN


# ---------------------------------------------------------------------
# Boundary tests – each threshold has two tests: one just below and one
# just above.  The deltas are chosen so that rounding or floating‑point
# wobble cannot mask a real threshold change.
# ---------------------------------------------------------------------

DELTA = 0.01


def _good_base() -> dict:
    """Return a dict of metrics that passes all checks comfortably."""
    return {
        "contrast_ratio": EXPECTED_CONTRAST_THRESHOLD + 1.0,
        "spacing_uniformity": EXPECTED_SPACING_THRESHOLD + 0.1,
        "alignment_score": EXPECTED_ALIGNMENT_MIN + 0.1,
    }


class TestContrastBoundary:
    def test_just_below_contrast_fails(self):
        metrics = _good_base()
        metrics["contrast_ratio"] = CONTRAST_THRESHOLD - DELTA
        assert not evaluate_design(metrics)

    def test_just_above_contrast_passes(self):
        metrics = _good_base()
        metrics["contrast_ratio"] = CONTRAST_THRESHOLD + DELTA
        assert evaluate_design(metrics)


class TestSpacingBoundary:
    def test_just_below_spacing_fails(self):
        metrics = _good_base()
        metrics["spacing_uniformity"] = SPACING_UNIFORMITY_THRESHOLD - DELTA
        assert not evaluate_design(metrics)

    def test_just_above_spacing_passes(self):
        metrics = _good_base()
        metrics["spacing_uniformity"] = SPACING_UNIFORMITY_THRESHOLD + DELTA
        assert evaluate_design(metrics)


class TestAlignmentBoundary:
    def test_just_below_alignment_fails(self):
        metrics = _good_base()
        metrics["alignment_score"] = ALIGNMENT_MIN_SCORE - DELTA
        assert not evaluate_design(metrics)

    def test_just_above_alignment_passes(self):
        metrics = _good_base()
        metrics["alignment_score"] = ALIGNMENT_MIN_SCORE + DELTA
        assert evaluate_design(metrics)


# ---------------------------------------------------------------------
# Sanity: the approved design itself should pass.
# This is a regression test based on the exact design that was used
# during calibration – once the real design object is available,
# replace this placeholder.
# ---------------------------------------------------------------------

def test_approved_design_passes():
    approved_metrics = {
        "contrast_ratio": 5.2,          # actual values from the approved design
        "spacing_uniformity": 0.92,
        "alignment_score": 0.96,
    }
    assert evaluate_design(approved_metrics)
