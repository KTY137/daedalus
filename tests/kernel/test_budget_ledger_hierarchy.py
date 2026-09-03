from __future__ import annotations

import ast
import json
from pathlib import Path
import pickle
import subprocess
import sys

import daedalus.budget as legacy
from daedalus.kernel.events import envelope
import daedalus.kernel.policy as policy
import daedalus.kernel.policy.ledger as owner
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "budget.py"
OWNER = ROOT / "daedalus" / "kernel" / "policy" / "ledger.py"
LEDGER_NAMES = {
    "BudgetRefused",
    "BudgetState",
    "BudgetUnavailable",
    "Ledger",
    "Reservation",
    "SpendEnvelope",
    "ledger",
    "open_envelope",
    "reserve",
    "reset_default_ledger",
}


def _definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_legacy_and_hierarchy_paths_resolve_to_one_ledger_authority() -> None:
    for name in LEDGER_NAMES:
        assert getattr(legacy, name) is getattr(owner, name)
        if name != "ledger":
            assert getattr(policy, name) is getattr(owner, name)
    assert legacy._BudgetLock is owner._BudgetLock
    assert policy.ledger is owner


def test_budget_facade_contains_no_second_ledger_implementation() -> None:
    assert not LEDGER_NAMES & _definitions(FACADE)
    source = FACADE.read_text(encoding="utf-8")
    assert "from .kernel.policy.ledger import" in source


def test_ledger_owner_has_no_process_provider_or_effect_authority() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    definitions = _definitions(OWNER)
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
        "classify_argv",
        "classify_url",
        "guard",
        "install_process_guard",
        "uninstall_process_guard",
    } & definitions
    assert not {
        "subprocess",
        "urllib.request",
        "daedalus.providers",
        "daedalus.gates",
        "daedalus.spine",
    } & imports
    assert not {"Popen", "urlopen", "begin_effect"} & called


def test_cold_ledger_import_does_not_load_legacy_budget_or_providers() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "import daedalus.kernel.policy.ledger;"
                "print(json.dumps(sorted(n for n in sys.modules if "
                "n == 'daedalus.budget' or n.startswith('daedalus.providers') "
                "or n.startswith('daedalus.gates') or n.startswith('daedalus.spine'))))"
            ),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_legacy_pickle_globals_resolve_to_canonical_ledger_classes() -> None:
    assert pickle.loads(b"cdaedalus.budget\nLedger\n.") is owner.Ledger
    assert pickle.loads(b"cdaedalus.budget\nReservation\n.") is owner.Reservation


def test_default_ledger_locator_is_unchanged() -> None:
    assert owner.DEFAULT_LEDGER_PATH == ROOT / "runs" / "budget" / "ledger.json"
    assert legacy.DEFAULT_LEDGER_PATH is owner.DEFAULT_LEDGER_PATH


def test_envelope_producer_ledger_names_the_canonical_writer() -> None:
    assert "daedalus/kernel/policy/ledger.py" in envelope.UNCONVERTED_PRODUCERS
    assert "daedalus/budget.py" not in envelope.UNCONVERTED_PRODUCERS


def test_structure_packet_keeps_the_effect_registry_digest() -> None:
    assert registry_sha256() == (
        "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
    )
