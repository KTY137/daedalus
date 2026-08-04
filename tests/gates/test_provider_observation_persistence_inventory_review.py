from __future__ import annotations

import ast
import inspect

import daedalus.gates.provider_observation_persistence_inventory as inventory


def test_inventory_module_has_read_only_discovery_authority() -> None:
    source = inspect.getsource(inventory)
    tree = ast.parse(source)
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert imported.isdisjoint(
        {"sqlite3", "subprocess", "socket", "requests", "httpx", "urllib"}
    )
    assert {"write_text", "write_bytes", "mkdir", "unlink", "replace"}.isdisjoint(called)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "begin_effect" not in source


def test_report_cannot_claim_closure_guarding_or_checkout_exclusion() -> None:
    source = inspect.getsource(inventory.ProviderObservationPersistenceInventory._payload)
    assert '"closed": False' in source
    assert '"inventory_only": True' in source
    assert '"canonical_inventory_integrated": False' in source
    assert '"guard_contracts_complete": False' in source
    assert '"primary_checkout_mutation_excluded": False' in source
    assert "not self.blockers" not in source


def test_scanner_fails_closed_on_every_expected_anchor() -> None:
    source = inspect.getsource(inventory._discover_surfaces)
    required = {
        "self._initialize",
        "sqlite3.connect",
        "self.path.parent.mkdir",
        "CREATE TABLE IF NOT EXISTS provider_observation_bindings",
        "self._connect",
        "BEGIN IMMEDIATE",
        "ROLLBACK",
        "INSERT INTO provider_observation_bindings",
        "connection.commit",
        "self.load",
    }
    for fragment in required:
        assert fragment in source
    assert source.count("_exact_call(") >= 8


def test_public_report_surfaces_are_always_blocking_inventory_only_rows() -> None:
    surface_source = inspect.getsource(
        inventory.ProviderObservationPersistenceSurface.to_dict
    )
    assert '"wiring": "inventory_only"' in surface_source
    assert '"guard_contract_bound": False' in surface_source
    assert '"primary_checkout_target_proven": False' in surface_source
    assert '"blocking": True' in surface_source


def test_fixed_source_path_cannot_be_redirected_by_caller() -> None:
    signature = inspect.signature(inventory.scan_provider_observation_persistence)
    assert tuple(signature.parameters) == ("repository_root", "source_revision")
    assert signature.parameters["source_revision"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inventory._SOURCE_PATH == "daedalus/runtimes/provider_observation.py"
