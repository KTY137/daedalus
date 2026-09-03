from __future__ import annotations

import ast
import json
from pathlib import Path
import pickle
import subprocess
import sys

import daedalus.budget as legacy
import daedalus.kernel.policy as policy
import daedalus.kernel.policy.pricing as pricing
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / "daedalus" / "budget.py"
OWNER = ROOT / "daedalus" / "kernel" / "policy" / "pricing.py"
PRICING_NAMES = {
    "BudgetError",
    "Estimate",
    "UnknownPrice",
    "VendorPrice",
    "price_call",
    "subscription_vendors",
}


def _definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_legacy_and_hierarchy_paths_resolve_to_one_pricing_authority() -> None:
    for name in PRICING_NAMES:
        assert getattr(legacy, name) is getattr(pricing, name)
        assert getattr(policy, name) is getattr(pricing, name)
    assert legacy._PRICES is pricing._PRICES
    assert legacy.FREE_VENDORS is pricing.FREE_VENDORS


def test_budget_facade_contains_no_second_pricing_implementation() -> None:
    assert not PRICING_NAMES & _definitions(LEGACY)
    source = LEGACY.read_text(encoding="utf-8")
    assert "from .kernel.policy.pricing import" in source


def test_pricing_owner_has_no_ledger_process_or_provider_authority() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    imports: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    assert not {
        "Ledger",
        "Reservation",
        "SpendEnvelope",
        "install_process_guard",
        "reserve",
    } & definitions
    assert not {"subprocess", "urllib.request", "sqlite3"} & imports
    assert not {"Popen", "urlopen", "begin_effect"} & called


def test_cold_pricing_import_does_not_load_legacy_budget_or_providers() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "import daedalus.kernel.policy.pricing;"
                "print(json.dumps(sorted(n for n in sys.modules if "
                "n == 'daedalus.budget' or n.startswith('daedalus.providers'))))"
            ),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_legacy_pickle_global_still_resolves_to_the_canonical_class() -> None:
    assert pickle.loads(b"cdaedalus.budget\nEstimate\n.") is pricing.Estimate


def test_structure_packet_keeps_the_effect_registry_digest() -> None:
    assert registry_sha256() == (
        "615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752"
    )
