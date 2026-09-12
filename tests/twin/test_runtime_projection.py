"""Executable tensor integration, not a learned-retrieval benchmark."""
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.twin.reference_compiler import compile_reference_project
from daedalus.twin import runtime_projection as runtime

FIXTURE = Path(__file__).resolve().parents[2] / "examples/fourfold_wiki_app"
CANDIDATE = "b" * 64


@pytest.fixture
def compiled():
    return compile_reference_project(FIXTURE, source_revision="a" * 40,
                                     created_at="2026-09-11T20:00:00Z", source_tree_sha256=CANDIDATE)


def test_real_reference_compilation_executes_typed_tensor_kernel(compiled):
    first = runtime.compile_runtime_projection(compiled, candidate_tree_sha256=CANDIDATE)
    assert first == runtime.compile_runtime_projection(compiled, candidate_tree_sha256=CANDIDATE)
    assert first["relation_blocks"] == 11 and first["semantic_facts"] == 67
    assert first["verified_bindings"] == 31
    assert first["candidate_tree_sha256"] == CANDIDATE
    assert first["source_fourfold_sha256"] == compiled.snapshot.digest
    assert first["kernel_owned"] is True and first["authoritative"] is False
    assert first["semiring"] == "boolean" and len(first["projection_sha256"]) == 64


@pytest.mark.parametrize("digest", ["c" * 64, "bad", "", None, True])
def test_wrong_or_missing_candidate_binding_refuses(compiled, digest):
    with pytest.raises((ValueError, TypeError)):
        runtime.compile_runtime_projection(compiled, candidate_tree_sha256=digest)


def test_unbound_source_compilation_cannot_claim_a_candidate(compiled):
    with pytest.raises(ValueError, match="exact compiled candidate"):
        runtime.compile_runtime_projection(replace(compiled, source_tree_sha256=None), candidate_tree_sha256=CANDIDATE)


def test_stale_forest_revision_refuses(compiled):
    forest = replace(compiled.forest, provenance={**compiled.forest.provenance, "source_revision": "c" * 40})
    with pytest.raises(ValueError):
        runtime.compile_runtime_projection(replace(compiled, forest=forest), candidate_tree_sha256=CANDIDATE)


def test_partial_plane_is_not_silently_relabelled_complete(compiled):
    planes = tuple(replace(p, status="partial", reason="incomplete extraction") if p.plane == "code" else p
                   for p in compiled.snapshot.planes)
    snapshot = replace(compiled.snapshot, planes=planes,
                       provenance=replace(compiled.snapshot.provenance, input_digests=tuple({
                           *compiled.snapshot.provenance.input_digests, *(p.digest for p in planes)})))
    with pytest.raises(ValueError, match="complete endpoint"):
        runtime.compile_runtime_projection(replace(compiled, snapshot=snapshot), candidate_tree_sha256=CANDIDATE)


def test_compiler_failure_has_no_fake_empty_projection(compiled, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("unsupported retained relation")
    monkeypatch.setattr(runtime, "compile_relation_blocks", fail)
    with pytest.raises(ValueError, match="unsupported retained"):
        runtime.compile_runtime_projection(compiled, candidate_tree_sha256=CANDIDATE)
