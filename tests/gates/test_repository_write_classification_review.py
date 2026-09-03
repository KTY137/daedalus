from __future__ import annotations

import ast
import inspect
import textwrap

import daedalus.gates.repository.write_classification as contract


def _tree() -> ast.Module:
    return ast.parse(textwrap.dedent(inspect.getsource(contract)))


def test_contract_has_no_effect_or_registry_authority() -> None:
    tree = _tree()
    imported: set[str] = set()
    called: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)

    forbidden_imports = {
        "os",
        "pathlib",
        "shutil",
        "sqlite3",
        "subprocess",
        "daedalus.spine.effect_boundary",
        "daedalus.kernel.effect_lease",
        "daedalus.kairos.gated_writes",
    }
    assert not (imported & forbidden_imports)
    assert not ({"open", "write_text", "write_bytes", "unlink", "replace"} & called)
    assert not (
        {"begin_effect", "grant", "begin", "finish", "promote_candidates"}
        & called
    )
    assert "ENTRYPOINTS" not in attributes
    assert "REGISTRY_BY_ID" not in attributes


def test_report_hard_codes_non_authoritative_claims_false() -> None:
    source = inspect.getsource(contract.RepositoryWriteClassificationReport._payload)
    tree = ast.parse(textwrap.dedent(source))
    dict_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    material: dict[str, object] = {}
    for node in dict_nodes:
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if isinstance(value, ast.Constant):
                    material[key.value] = value.value
    assert "evidence_authenticated" not in material
    assert material["primary_checkout_target_proven"] is False
    assert material["gate_report_bound"] is False
    assert material["closed"] is False


def test_central_candidate_requires_all_four_mechanical_evidence_families() -> None:
    source = inspect.getsource(contract.SurfaceClassification.__post_init__)
    required = {
        "GUARD_CONTRACT",
        "EFFECT_LEASE_RECEIPT",
        "RUNTIME_CONFORMANCE_RECEIPT",
        "PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT",
    }
    for name in required:
        assert name in source
    assert "issubset" in source
    assert "central classification requires a disjoint target" in source


def test_stale_inventory_and_surface_substitution_checks_are_explicit() -> None:
    input_source = inspect.getsource(contract.project_classification_input)
    projection_source = inspect.getsource(
        contract.project_repository_write_classifications
    )
    assert "source revision is stale" in input_source
    assert "inventory digest is stale" in input_source
    assert "surface is absent from the bound inventory" in projection_source
    assert "surface is duplicated" in projection_source


def test_input_verifier_keeps_an_independent_v1_literal_pin() -> None:
    source = inspect.getsource(contract.project_classification_input)
    assert (
        'value["schema"] != '
        '"daedalus-gate0-repository-write-classification-input/1"'
    ) in source
    assert 'value["schema"] != CLASSIFICATION_INPUT_SCHEMA' not in source


def test_evidence_is_bound_to_exact_surface_and_guard_contract_set() -> None:
    source = inspect.getsource(contract.SurfaceClassification.__post_init__)
    assert "surface_binding_sha256" in source
    assert "evidence surface binding differs from classification" in source
    assert "evidenced_contracts != set(self.guard_contracts)" in source
    helper = inspect.getsource(contract.surface_binding_sha256)
    assert '"source_revision"' in helper
    assert '"surface"' in helper
    assert "canonical_json" in helper
