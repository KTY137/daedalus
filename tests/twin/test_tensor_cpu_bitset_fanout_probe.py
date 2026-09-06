from __future__ import annotations

import dataclasses
import importlib

import pytest

_PROBE = importlib.import_module("experiments.tensor_gpu.cpu_bitset_fanout_probe")
_BASELINE = importlib.import_module("experiments.tensor_gpu.cpu_bitset_baseline")
_CONTRACT = importlib.import_module("experiments.tensor_gpu.boolean_probe_contract")
_RESIDENCY = importlib.import_module("experiments.tensor_gpu.cpu_bitset_residency_probe")

ProbeCase = _PROBE.ProbeCase
build_boolean_fanout = _PROBE.build_boolean_fanout
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


def test_fanout_probe_reuses_existing_contract_and_residency_primitives() -> None:
    assert _PROBE.ProbeCase is _CONTRACT.ProbeCase
    assert _PROBE.build_boolean_chain is _RESIDENCY.build_boolean_chain
    assert _PROBE._preflight_csr_chain is _RESIDENCY._preflight_csr_chain
    assert _PROBE.pack_rows is _BASELINE.pack_rows
    assert _PROBE._block_from_masks is _BASELINE._block_from_masks
    assert _PROBE._measure_repeated is _BASELINE._measure_repeated


def test_fanout_is_revision_bound_and_typed() -> None:
    prefix, tails, metadata = build_boolean_fanout(
        _case(),
        relation_count=3,
        query_count=3,
    )

    assert len(prefix) == 2
    assert len(tails) == 3
    assert metadata["prefix_relation_count"] == 2
    assert metadata["query_count"] == 3
    assert metadata["shared_subject_digest"] == prefix[0].subject.digest
    assert len({block.subject.digest for block in (*prefix, *tails)}) == 1
    for tail in tails:
        assert prefix[-1].column_axis == tail.row_axis
        assert tail.semiring_name == "boolean"


def test_fanout_matches_recomputed_and_csr_oracles() -> None:
    report = run_probe(
        (_case(),),
        relation_count=3,
        query_count=3,
        max_resident_mib=64,
    )
    result = report["cases"][0]

    assert report["schema"] == "daedalus-tensor-cpu-bitset-fanout/1"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert result["status"] == "verified"
    assert result["resident_prefix"]["admitted"] is True
    assert result["resident_prefix"]["storage_bytes"] > 0
    assert result["resident_prefix"]["storage_bytes"] <= result["resident_prefix"]["budget_bytes"]
    assert result["correctness"] == {
        "recomputed_support_and_digest_equal": True,
        "cpu_oracle_executed_for_all_queries": True,
        "cpu_oracle_support_and_digest_equal": True,
    }
    assert (
        result["resident_query_batch"]["digests"]
        == result["recomputed_query_batch"]["digests"]
    )
    assert len(result["resident_query_batch"]["digests"]) == 3


def test_resident_query_batch_does_not_recompute_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix, tails, _ = build_boolean_fanout(
        _case(),
        relation_count=3,
        query_count=2,
    )
    prefix_packed, tails_packed, _, _ = _PROBE._pack_fanout(prefix, tails)
    prefix_rows = _RESIDENCY._compose_packed_chain_unchecked(prefix_packed)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("resident query batch recomputed the shared prefix")

    monkeypatch.setattr(_PROBE, "_compose_packed_chain_unchecked", forbidden)
    outputs = _PROBE._materialize_query_batch(prefix, tails, prefix_rows, tails_packed)

    assert len(outputs) == 2
    with pytest.raises(AssertionError, match="recomputed the shared prefix"):
        _PROBE._recompute_query_batch(prefix, tails, prefix_packed, tails_packed)


def test_fanout_invalidates_on_fourfold_subject_change() -> None:
    prefix, tails, _ = build_boolean_fanout(
        _case(),
        relation_count=3,
        query_count=2,
    )
    other_case = ProbeCase(
        size=12,
        density=0.2,
        repeats=2,
        warmup=1,
        max_device_mib=64,
        cpu_max_operations=5_000_000,
    )
    other_left, _, _ = _CONTRACT.build_boolean_case(other_case)
    invalid_tail = dataclasses.replace(tails[0], subject=other_left.subject)

    with pytest.raises(ValueError, match="different Fourfold subject"):
        _PROBE._validate_fanout(prefix, (invalid_tail, tails[1]))


def test_fanout_memory_budget_blocks_without_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PROBE, "_packed_storage_bytes", lambda rows: 2 * 1024 * 1024)
    result = _PROBE.run_case(
        _case(),
        relation_count=3,
        query_count=2,
        max_resident_mib=1,
    )

    assert result["status"] == "blocked-resident-memory-budget"
    assert result["claim"] == "none"
    assert result["resident_prefix"] == {
        "storage_bytes": 2 * 1024 * 1024,
        "budget_bytes": 1024 * 1024,
        "admitted": False,
    }
    assert "resident_query_batch" not in result


def test_fanout_keeps_reference_budget_fail_closed() -> None:
    report = run_probe(
        (_case(cpu_max_operations=0),),
        relation_count=3,
        query_count=2,
        max_resident_mib=64,
    )
    result = report["cases"][0]

    assert result["status"] == "performance-only"
    assert result["correctness"]["cpu_oracle_executed_for_all_queries"] is False
    assert result["correctness"]["cpu_oracle_support_and_digest_equal"] is None
    assert result["correctness"]["recomputed_support_and_digest_equal"] is True


def test_fanout_bounds_are_explicit() -> None:
    with pytest.raises(ValueError, match="relation_count"):
        build_boolean_fanout(_case(), relation_count=2, query_count=2)
    with pytest.raises(ValueError, match="query_count"):
        build_boolean_fanout(_case(), relation_count=3, query_count=1)
    with pytest.raises(ValueError, match="max_resident_mib"):
        run_probe(
            (_case(),),
            relation_count=3,
            query_count=2,
            max_resident_mib=0,
        )
