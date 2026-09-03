"""Focused contract tests for the legacy benchmark authority consolidation."""
from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from daedalus.orchestration import benchmark


ROOT = Path(__file__).resolve().parents[1]


def _decision(**overrides):
    values = {
        "provider": "ollama",
        "persona": "local",
        "mode": "advisory",
        "sensitive": False,
        "risk": "low",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_cost_run_is_explicitly_ineligible_for_comparative_evidence() -> None:
    with mock.patch.object(
        benchmark,
        "route_task",
        return_value={"name": "docs-dev", "model_tier": "sonnet"},
    ), mock.patch.object(
        benchmark,
        "select_provider",
        return_value=_decision(),
    ):
        result = benchmark.run(json_out=True)

    assert result["schema"] == "daedalus.benchmark.cost-estimate/2"
    assert result["classification"] == "planning_estimate"
    assert result["comparative_evidence_eligible"] is False
    assert result["rows"]
    assert all("estimated_routed_usd" in row for row in result["rows"])
    assert "measured_savings_vs_opus_pct" not in result["summary"]

    assumptions = result["assumptions"]
    assert assumptions["task_set_revision_frozen"] is False
    assert assumptions["token_counts_measured"] is False
    assert assumptions["prices_verified_at_runtime"] is False
    assert assumptions["posture_observed_at_runtime"] is False


def test_legacy_live_path_refuses_instead_of_running_an_evaluator() -> None:
    with pytest.raises(benchmark.LiveBenchmarkRetired, match="canonical daedalus.eval"):
        benchmark.run_live(".")


def test_benchmark_module_contains_no_parallel_live_execution_engine() -> None:
    source = inspect.getsource(benchmark)
    forbidden = (
        "from .offload import offload",
        "offload(task.objective",
        "metrics.summary()",
        "MEASURED saves",
        "time.time()",
    )
    for token in forbidden:
        assert token not in source
    assert "parser.error(LIVE_BENCHMARK_RETIREMENT)" in source


def test_representative_workload_is_immutable_and_declared_legacy() -> None:
    assert isinstance(benchmark.TASKS, tuple)
    assert benchmark._assumptions()["task_set"] == "legacy_representative_tct_slice"
    task = benchmark.TASKS[0]
    assert isinstance(task.paths, tuple)
    with pytest.raises(FrozenInstanceError):
        task.ctx_tokens = 1


def test_estimator_retains_advisory_apply_overhead() -> None:
    with mock.patch.object(
        benchmark,
        "route_task",
        return_value={"name": "docs-dev", "model_tier": "sonnet"},
    ), mock.patch.object(
        benchmark,
        "select_provider",
        return_value=_decision(provider="ollama", mode="advisory"),
    ):
        result = benchmark.run(json_out=True)

    first = result["rows"][0]
    expected = benchmark._cost("claude_sonnet", benchmark.APPLY_IN, benchmark.APPLY_OUT)
    assert first["estimated_routed_usd"] == round(expected, 6)
