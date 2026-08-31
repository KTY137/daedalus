from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import daedalus.budget as facade
from daedalus.runtimes.execution import budget_process as owner
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "budget.py"
OWNER = ROOT / "daedalus" / "runtimes" / "execution" / "budget_process.py"
MOVED_NAMES = {
    "classify_argv",
    "classify_url",
    "guard",
    "uninstall_process_guard",
}


def _definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_facade_reexports_one_process_adapter_authority() -> None:
    for name in MOVED_NAMES:
        assert getattr(facade, name) is getattr(owner, name)
    assert facade.BILLABLE_SITES is owner.BILLABLE_SITES
    assert facade._INSTALLED is owner._INSTALLED


def test_effect_facade_keeps_only_composition_and_registered_decision() -> None:
    definitions = _definitions(FACADE)
    assert definitions & {
        "classify_argv",
        "classify_url",
        "guard",
        "uninstall_process_guard",
    } == set()
    assert definitions & {
        "install_process_guard",
        "process_guard_boundary_decision",
    } == {
        "install_process_guard",
        "process_guard_boundary_decision",
    }


def test_facade_installer_composes_current_legacy_ports() -> None:
    tree = ast.parse(
        inspect.getsource(facade.install_process_guard),
        filename=str(FACADE),
    )
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_install_runtime_process_guard"
    )
    bindings = {
        keyword.arg: keyword.value.id
        for keyword in call.keywords
        if keyword.arg is not None and isinstance(keyword.value, ast.Name)
    }
    assert bindings == {
        "argv_classifier": "classify_argv",
        "url_classifier": "classify_url",
        "reserve_call": "reserve",
    }


def test_owner_installer_uses_injected_classifier_and_reservation_ports() -> None:
    seen: list[tuple[str, str]] = []

    class Settled:
        def settle(self) -> None:
            seen.append(("settle", "ok"))

    def classify(argv: Any) -> str | None:
        return "test_vendor" if argv == ["synthetic-vendor"] else None

    def reserve_call(vendor: str, *, label: str) -> Settled:
        seen.append((vendor, label))
        return Settled()

    original = lambda argv: "spawned"  # noqa: E731
    wrapped = owner._guarded_spawn(
        original,
        "test.spawn",
        argv_classifier=classify,
        reserve_call=reserve_call,
    )
    assert wrapped(["synthetic-vendor"]) == "spawned"
    assert seen == [
        ("test_vendor", "test.spawn: synthetic-vendor"),
        ("settle", "ok"),
    ]


def test_process_owner_does_not_import_facade_provider_gate_or_spine() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    assert "daedalus.budget" not in imports
    assert not any(
        name.startswith(prefix)
        for name in imports
        for prefix in (
            "daedalus.providers",
            "daedalus.gates",
            "daedalus.spine",
        )
    )


def test_cold_owner_import_does_not_load_facade_providers_or_gates() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "import daedalus.runtimes.execution.budget_process;"
                "print(json.dumps(sorted(n for n in sys.modules if "
                "n == 'daedalus.budget' or n.startswith('daedalus.providers') "
                "or n.startswith('daedalus.gates'))))"
            ),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_structure_packet_keeps_the_effect_registry_digest() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
