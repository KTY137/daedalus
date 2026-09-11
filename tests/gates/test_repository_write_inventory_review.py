from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.gates.repository.write_inventory as inventory


SOURCE_PATH = Path(inventory.__file__).resolve()
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, name
    return matches[0]


def _call_names(node: ast.AST) -> tuple[str, ...]:
    result: list[str] = []
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Call):
            continue
        target = candidate.func
        if isinstance(target, ast.Name):
            result.append(target.id)
        elif isinstance(target, ast.Attribute):
            parts = [target.attr]
            value = target.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            result.append(".".join(reversed(parts)))
    return tuple(result)


def test_inventory_module_has_no_write_or_repository_authority() -> None:
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_imports = {
        "subprocess",
        "sqlite3",
        "shutil",
        "tempfile",
        "git",
        "docker",
        "daedalus.kairos",
        "daedalus.runtimes",
        "daedalus.kernel.owner_approval",
    }
    assert not forbidden_imports.intersection(imported)

    calls = set(_call_names(TREE))
    forbidden_calls = {
        "open",
        "Path.write_text",
        "Path.write_bytes",
        "os.remove",
        "os.unlink",
        "os.replace",
        "subprocess.run",
        "promote_candidates",
        "issue_owner_approval",
        "begin_effect",
    }
    assert not forbidden_calls.intersection(calls)


def test_all_unknown_or_mutating_surfaces_remain_blocking() -> None:
    assert inventory._ALLOWED_KINDS - inventory._BLOCKING_KINDS == {
        "sqlite_read_only"
    }
    assert {
        "filesystem_mutation",
        "path_mutation",
        "write_mode_open",
        "ambiguous_open_mode",
        "os_open_write",
        "ambiguous_os_open_flags",
        "sqlite_write_or_create",
        "ambiguous_sqlite_mode",
        "git_mutation_process",
        "process_effect_unknown",
        "ambiguous_binding",
    } <= inventory._BLOCKING_KINDS


def test_report_cannot_claim_primary_checkout_target_proof() -> None:
    payload = inventory.RepositoryWriteInventory(
        source_revision="d" * 40,
        package_root="daedalus",
        scan_input_sha256="e" * 64,
        files_scanned=1,
        callsites=(),
    ).to_dict()
    assert payload["primary_checkout_target_proven"] is False
    assert payload["scope"] == "potential_repository_write_surface"
    assert "guarded" not in inventory._ALLOWED_KINDS
    assert "central" not in inventory._ALLOWED_KINDS
    assert "trusted" not in inventory._ALLOWED_KINDS


def test_process_parser_never_marks_a_command_nonblocking() -> None:
    process = _function("_process_kind")
    rendered = ast.get_source_segment(SOURCE, process)
    assert rendered is not None
    assert "git_mutation_process" in rendered
    assert "process_effect_unknown" in rendered
    assert "sqlite_read_only" not in rendered
    assert "return None" not in rendered


def test_method_expression_fallback_precedes_call_classification() -> None:
    scanner = _function("_callsites_for_file")
    rendered = ast.get_source_segment(SOURCE, scanner)
    assert rendered is not None
    assert 'raw = f"<expression>.{node.func.attr}"' in rendered
    assert rendered.index('raw = f"<expression>.{node.func.attr}"') < rendered.index(
        "_classify_call("
    )
    assert "node.func.attr in (_PATH_METHODS | {\"open\"})" in rendered


def test_revision_and_file_bytes_are_mandatory_report_inputs() -> None:
    scanner = _function("scan_repository_write_surfaces")
    rendered = ast.get_source_segment(SOURCE, scanner)
    assert rendered is not None
    assert "_SOURCE_REVISION.fullmatch(source_revision)" in rendered
    assert "_production_files(package_root)" in rendered
    assert "scan_input_sha256=_scan_input(files, root)" in rendered
    assert rendered.index("_production_files(package_root)") < rendered.index(
        "_scan_input(files, root)"
    )

    scan_input = _function("_scan_input")
    scan_source = ast.get_source_segment(SOURCE, scan_input)
    assert scan_source is not None
    assert "path.read_bytes()" in scan_source
    assert "hashlib.sha256" in scan_source
    assert "canonical_json(entries)" in scan_source


def test_public_surface_is_read_only_and_narrow() -> None:
    public_functions = {
        node.name
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert public_functions == {"scan_repository_write_surfaces"}
    signature = inspect.signature(inventory.scan_repository_write_surfaces)
    assert tuple(signature.parameters) == ("repository_root", "source_revision")
    assert signature.parameters["source_revision"].kind is inspect.Parameter.KEYWORD_ONLY
    assert all(
        parameter.kind not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
        for parameter in signature.parameters.values()
    )
