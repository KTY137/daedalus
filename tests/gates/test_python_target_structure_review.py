from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/python_target_structure.py"
)
CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "daedalus/runtimes/contracts/python_targets.py"
)


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_module_is_structural_and_never_executes_target_code() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "importlib",
        "runpy",
        "subprocess",
        "inspect",
        "pkgutil",
        "sqlite3",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(forbidden_imports)
    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "ast.parse" in calls
    for forbidden in (
        "exec",
        "eval",
        "compile",
        "__import__",
        "importlib.import_module",
        "runpy.run_module",
        "subprocess.run",
        "subprocess.Popen",
    ):
        assert forbidden not in calls
    assert "Callable" not in source
    assert "Protocol" not in source
    assert "**kwargs" not in source


def test_exact_source_digest_precedes_ast_and_definition_projection() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "resolve_python_target_structure"
    )
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    read_lines = [
        line for name, line in calls if name == "read_repository_source"
    ]
    parse_lines = [line for name, line in calls if name == "_parse_source"]
    resolve_lines = [
        line for name, line in calls if name == "_resolve_definition_chain"
    ]
    assert len(read_lines) == len(parse_lines) == len(resolve_lines) == 1
    source = ast.get_source_segment(
        TARGET.read_text(encoding="utf-8"),
        function,
    )
    assert source is not None
    digest_index = source.index(
        "snapshot.source_sha256 != expected_source_sha256"
    )
    parse_index = source.index("tree = _parse_source(snapshot)")
    resolve_index = source.index(
        "chain = _resolve_definition_chain(tree, object_path)"
    )
    assert digest_index < parse_index < resolve_index


def test_definition_chain_is_unique_and_conservative() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for fragment in (
        "if not matches:",
        "if len(matches) != 1:",
        "if not isinstance(selected, ast.ClassDef):",
        "only classes may contain a qualified target child",
        "ast.FunctionDef",
        "ast.AsyncFunctionDef",
        "ast.ClassDef",
    ):
        assert fragment in source
    assert "ast.Assign" not in source
    assert "ast.Lambda" not in source


def test_result_cannot_launder_structure_into_behavior() -> None:
    source = "\n".join(
        (
            TARGET.read_text(encoding="utf-8"),
            CONTRACT.read_text(encoding="utf-8"),
        )
    )
    assert source.count('"structural_target_verified": True') == 1
    assert source.count('"behavior_verified": False') == 1
    assert source.count('"executed": False') == 1
    for forbidden in (
        "guard_contract_semantics_verified",
        "evidence_authenticated",
        "gate_report_bound",
        '"closed"',
        "OwnerApproval",
        "PromotionReceipt",
        "EffectLease",
    ):
        assert forbidden not in source


def test_module_uses_shared_repository_tree_boundary() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert "from daedalus.gates.repository_tree import" in source
    assert "read_repository_source" in source
    for forbidden in (
        "os.open",
        "Path.read_text",
        "Path.read_bytes",
        "open(",
    ):
        assert forbidden not in source
