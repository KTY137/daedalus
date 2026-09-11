from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = ROOT / "daedalus" / "kernel"
OFFLOAD_SOURCE = KERNEL_ROOT / "offload_lease.py"
CHIP_CLI_SOURCE = ROOT / "daedalus" / "chip_design" / "cli.py"


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


def test_kernel_has_no_gate_import_edge() -> None:
    forbidden: list[str] = []
    for source_path in sorted(KERNEL_ROOT.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "daedalus.gates" or module.startswith(
                    "daedalus.gates."
                ):
                    forbidden.append(f"{source_path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "daedalus.gates" or alias.name.startswith(
                        "daedalus.gates."
                    ):
                        forbidden.append(
                            f"{source_path.relative_to(ROOT)}:{node.lineno}"
                        )

    assert forbidden == []


def test_chip_lease_requires_verifier_and_binds_it_before_issuer() -> None:
    tree = ast.parse(OFFLOAD_SOURCE.read_text(encoding="utf-8"))
    function = _function(tree, "acquire_chip_eda_lease")
    keyword_defaults = dict(
        zip(
            (argument.arg for argument in function.args.kwonlyargs),
            function.args.kw_defaults,
            strict=True,
        )
    )
    assert "repository_head_verifier" in keyword_defaults
    assert keyword_defaults["repository_head_verifier"] is None
    assert "execution_plan_validator" in keyword_defaults
    assert isinstance(keyword_defaults["execution_plan_validator"], ast.Constant)
    assert keyword_defaults["execution_plan_validator"].value is None

    verification_calls = _named_calls(function, "repository_head_verifier")
    plan_validation_calls = _named_calls(function, "execution_plan_validator")
    issuer_calls = _named_calls(function, "_acquire_effect_lease_impl")
    assert len(verification_calls) == 1
    assert len(plan_validation_calls) == 1
    assert len(issuer_calls) == 1
    assert plan_validation_calls[0].lineno < verification_calls[0].lineno
    assert verification_calls[0].lineno < issuer_calls[0].lineno


def test_chip_cli_composes_gate_verifier_before_eda_execution() -> None:
    tree = ast.parse(CHIP_CLI_SOURCE.read_text(encoding="utf-8"))
    gate_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "daedalus.gates.repository.head_revision"
        for alias in node.names
    ]
    assert "verify_repository_head_revision" in gate_imports

    function = _function(tree, "main")
    acquisitions = _named_calls(function, "acquire_chip_eda_lease")
    executions = _named_calls(function, "run_admitted_eda")
    assert len(acquisitions) == 1
    assert len(executions) == 1
    verifier_keywords = [
        keyword.value
        for keyword in acquisitions[0].keywords
        if keyword.arg == "repository_head_verifier"
    ]
    assert len(verifier_keywords) == 1
    assert isinstance(verifier_keywords[0], ast.Name)
    assert verifier_keywords[0].id == "verify_repository_head_revision"
    validator_keywords = [
        keyword.value
        for keyword in acquisitions[0].keywords
        if keyword.arg == "execution_plan_validator"
    ]
    assert len(validator_keywords) == 1
    assert isinstance(validator_keywords[0], ast.Name)
    assert validator_keywords[0].id == "validate_eda_execution_plan"
    assert acquisitions[0].lineno < executions[0].lineno
