"""Neutral read/evaluate ports consumed by measurement-driven orchestration.

The kernel names the capability but does not import an evaluator
implementation.  Concrete Gate-1 composition lives above the kernel and is
injected at the registered compatibility door.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class EvaluationBaselinePort(Protocol):
    """Load the retained evaluator baseline without mutating it."""

    def __call__(self) -> Mapping[str, Any]: ...


@runtime_checkable
class EvaluationGatePort(Protocol):
    """Run the advisory evaluator and return its structured verdict."""

    def __call__(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class EvaluationPorts:
    """Explicit evaluator capabilities available to a picker invocation."""

    load_baseline: EvaluationBaselinePort
    run_gate: EvaluationGatePort


__all__ = [
    "EvaluationBaselinePort",
    "EvaluationGatePort",
    "EvaluationPorts",
]
