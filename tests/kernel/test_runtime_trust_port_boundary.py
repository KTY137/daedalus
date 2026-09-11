from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = ROOT / "daedalus" / "kernel"
CONTRACTS_SOURCE = KERNEL_ROOT / "contracts" / "security.py"
FACADE_SOURCE = KERNEL_ROOT / "runtime_authorization_issuer.py"
ADMISSION_SOURCE = (
    ROOT / "daedalus" / "runtimes" / "admission" / "authorization.py"
)
REGISTRY_SOURCE = ROOT / "daedalus" / "spine" / "effect_boundary.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(functions) == 1
    return functions[0]


def _named_calls(function: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def test_kernel_has_no_direct_runtime_import_edge() -> None:
    forbidden: list[str] = []
    for source_path in sorted(KERNEL_ROOT.rglob("*.py")):
        for node in ast.walk(_tree(source_path)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "daedalus.runtimes" or module.startswith(
                    "daedalus.runtimes."
                ):
                    forbidden.append(f"{source_path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "daedalus.runtimes" or alias.name.startswith(
                        "daedalus.runtimes."
                    ):
                        forbidden.append(
                            f"{source_path.relative_to(ROOT)}:{node.lineno}"
                        )

    assert forbidden == []


def test_kernel_contracts_own_only_neutral_runtime_trust_protocols() -> None:
    tree = _tree(CONTRACTS_SOURCE)
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    assert {
        "RuntimeTrustLedgerPort",
        "RuntimeTrustPortError",
        "RuntimeTrustRecordPort",
    } <= set(classes)
    assert any(
        isinstance(decorator, ast.Name) and decorator.id == "runtime_checkable"
        for decorator in classes["RuntimeTrustLedgerPort"].decorator_list
    )
    assert any(
        isinstance(decorator, ast.Name) and decorator.id == "runtime_checkable"
        for decorator in classes["RuntimeTrustRecordPort"].decorator_list
    )


def test_contract_package_exports_the_exact_security_port_objects() -> None:
    from daedalus.kernel import contracts
    from daedalus.kernel.contracts import security

    for name in (
        "RuntimeTrustLedgerPort",
        "RuntimeTrustPortError",
        "RuntimeTrustRecordPort",
    ):
        assert getattr(contracts, name) is getattr(security, name)


def test_legacy_facade_is_lazy_and_defines_no_parallel_authority() -> None:
    tree = _tree(FACADE_SOURCE)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert functions == {"__dir__", "__getattr__"}
    resolver = _function(tree, "__getattr__")
    imports = _named_calls(resolver, "import_module")
    assert len(imports) == 1
    assert not _named_calls(_function(tree, "__dir__"), "import_module")

    owner_module = "daedalus.runtimes.admission"
    owner_before = sys.modules.get(owner_module)
    facade_globals = {
        "__name__": "_g1_runtime_02_legacy_facade_probe",
        "__package__": "daedalus.kernel",
    }
    exec(compile(tree, str(FACADE_SOURCE), "exec"), facade_globals)
    assert sys.modules.get(owner_module) is owner_before


def test_runtime_admission_owns_the_concrete_composition() -> None:
    tree = _tree(ADMISSION_SOURCE)
    imports = {
        (node.module or "", alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert (
        "daedalus.runtimes.trust_store",
        "RuntimeTrustLedger",
    ) in imports
    assert (
        "daedalus.kernel.runtime_effects",
        "issue_runtime_bound_effect_lease",
    ) in imports

    composer = _function(tree, "acquire_runtime_bound_authorization")
    trust_calls = _named_calls(composer, "runtime_trust_ledger")
    issue_calls = _named_calls(composer, "issue_runtime_bound_effect_lease")
    authorization_calls = _named_calls(composer, "RuntimeBoundEffectAuthorization")
    assert len(trust_calls) == len(issue_calls) == len(authorization_calls) == 1
    assert (
        trust_calls[0].lineno
        < issue_calls[0].lineno
        < authorization_calls[0].lineno
    )


def test_runtime_provider_registry_admission_state_is_unchanged() -> None:
    tree = _tree(REGISTRY_SOURCE)
    wiring: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "EntrypointSpec"
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        identifier = keywords.get("id")
        value = keywords.get("wiring")
        if not isinstance(identifier, ast.Constant) or not isinstance(
            identifier.value, str
        ):
            continue
        if isinstance(value, ast.Attribute):
            wiring[identifier.value] = value.attr

    assert wiring["provider.claude"] == "INVENTORY_ONLY"
    assert wiring["provider.codex"] == "INVENTORY_ONLY"
    assert wiring["provider.ollama"] == "LOCAL_GUARDS"
