from __future__ import annotations

import importlib

import pytest

_PROBE = importlib.import_module("experiments.tensor_gpu.cpu_bitset_residency_probe")
_BASELINE = importlib.import_module("experiments.tensor_gpu.cpu_bitset_baseline")
_CONTRACT = importlib.import_module("experiments.tensor_gpu.boolean_probe_contract")

ProbeCase = _PROBE.ProbeCase
build_boolean_chain = _PROBE.build_boolean_chain
execute_resident_chain = _PROBE.execute_resident_chain
run_probe = _PROBE.run_probe


def _case(*, cpu_max_operations: int = 5_000_000) -> object:
    return ProbeCase(
        size=12,
        density=0.25,
        repeats=2,
        warmup=1,
        max_device_mib=64,
        cpu_max_operations=cpu_max_operations,
    )


def test_residency_probe_reuses_existing_contract_and_bitset_primitives() -> None:
    assert _PROBE.ProbeCase is _CONTRACT.ProbeCase
    assert _PROBE.build_boolean_case is _CONTRACT.build_boolean_case
    assert _PROBE.pack_rows is _BASELINE.pack_rows
    assert _PROBE.compose_packed_rows is _BASELINE.compose_packed_rows
    assert _PROBE._block_from_masks is _BASELINE._block_from_masks
    assert _PROBE._measure_repeated is _BASELINE._measure_repeated


def test_chain_is_revision_bound_and_typed_at_every_boundary() -> None:
    chain, metadata = build_boolean_chain(_case(), relation_count=4)

    assert len(chain) == 4
    assert metadata["relation_count"] == 4
    assert metadata["composition_count"] == 3
    assert metadata["avoided_intermediate_materializations"] == 2
    assert len({block.subject.digest for block in chain}) == 1
    for left, right in zip(chain, chain[1:]):
        assert left.column_axis == right.row_axis
        assert left.semiring_name == right.semiring_name == "boolean"


def test_resident_chain_matches_csr_and_materialized_bitset_oracles() -> None:
    report = run_probe((_case(),), relation_count=3)
    result = report["cases"][0]

    assert report["schema"] == "daedalus-tensor-cpu-bitset-residency/1"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["relation_count"] == 3
    assert result["status"] == "verified"
    assert result["correctness"] == {
        "materialized_bitset_support_equal": True,
        "materialized_bitset_digest_equal": True,
        "cpu_oracle_executed": True,
        "cpu_oracle_support_equal": True,
        "cpu_oracle_digest_equal": True,
    }
    assert (
        result["cpu_bitset_resident_chain"]["digest"]
        == result["cpu_bitset_materialized_chain"]["digest"]
        == result["cpu_reference_chain"]["digest"]
    )
    assert result["cpu_bitset_resident_chain"]["samples"] == 2
    assert result["cpu_bitset_materialized_chain"]["samples"] == 2
    assert result["cpu_reference_chain"]["samples"] == 2


def test_resident_execution_materializes_only_one_final_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, _ = build_boolean_chain(_case(), relation_count=4)
    globals_map = execute_resident_chain.__globals__
    original = globals_map["_block_from_masks"]
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setitem(globals_map, "_block_from_masks", counted)
    execution = execute_resident_chain(chain, repeats=2, warmup=1)

    assert calls == 1
    assert execution.block.signature.relation == _PROBE.FINAL_RELATION
    assert len(execution.kernel_ms) == 2


def test_residency_probe_keeps_reference_budget_fail_closed() -> None:
    report = run_probe((_case(cpu_max_operations=0),), relation_count=3)
    result = report["cases"][0]

    assert result["status"] == "performance-only"
    assert result["cpu_reference_chain"]["status"] == "skipped-total-operation-bound"
    assert result["cpu_reference_chain"]["samples"] == 0
    assert result["correctness"]["cpu_oracle_executed"] is False
    assert result["correctness"]["cpu_oracle_support_equal"] is None
    assert result["correctness"]["materialized_bitset_support_equal"] is True


def test_residency_probe_refuses_invalid_chain_bounds_and_adjacency() -> None:
    for relation_count in (1, _PROBE.MAX_CHAIN_RELATIONS + 1):
        with pytest.raises(ValueError, match="relation_count"):
            build_boolean_chain(_case(), relation_count=relation_count)

    left, _, _ = _CONTRACT.build_boolean_case(_case())
    with pytest.raises(ValueError, match="shared typed middle axis"):
        _PROBE._validate_chain((left, left))


def test_residency_report_exposes_materialization_crossover_without_claim() -> None:
    report = run_probe((_case(),), relation_count=3)
    result = report["cases"][0]

    assert "materializes only the final" in report["measurement_contract"]
    assert result["case"]["avoided_intermediate_materializations"] == 1
    assert result["cpu_bitset_resident_chain"]["pack_all_inputs_ms"] >= 0.0
    assert result["cpu_bitset_resident_chain"]["validate_all_inputs_ms"] >= 0.0
    assert result["cpu_bitset_resident_chain"]["final_canonicalize_ms"] >= 0.0
    assert set(result["diagnostic_ratios"]) == {
        "materialized_bitset_chain_over_resident_kernel",
        "materialized_bitset_chain_over_resident_one_shot",
        "csr_chain_over_resident_one_shot",
        "csr_chain_over_materialized_bitset_chain",
    }
    assert result["claim"] == "none"
