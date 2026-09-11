"""Evaluator adapter for the measurement-driven picker.

This is composition, not evaluator authority: ``daedalus.eval.harness`` keeps
owning the baseline and advisory gate.  The adapter only binds those existing
functions to the neutral ports consumed below the orchestration layer.
"""
from __future__ import annotations

from ...kernel.contracts.evaluation import EvaluationPorts


def _load_baseline():
    from ...eval.harness import load_baseline

    return load_baseline()


def _run_gate():
    from ...eval.harness import run_gate

    return run_gate()


def picker_evaluation_ports() -> EvaluationPorts:
    """Bind the existing evaluator implementation for one CLI invocation."""

    return EvaluationPorts(load_baseline=_load_baseline, run_gate=_run_gate)


__all__ = ["picker_evaluation_ports"]
