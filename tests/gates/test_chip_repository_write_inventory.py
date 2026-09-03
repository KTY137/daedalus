from __future__ import annotations

import ast
from pathlib import Path

from daedalus.gates.repository.write_inventory_v2 import (
    scan_repository_write_surfaces_v2,
)
from scripts.declare_write_surfaces import (
    NameIndex,
    _dominance,
    resolve_central_doors,
)


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
EXECUTOR_PATH = "daedalus/chip_design/executor.py"
CLI_PATH = "daedalus/chip_design/cli.py"
COMPLETION_PATH = "daedalus/chip_design/completion_publication.py"
KERNEL_PATH = "daedalus/kernel/offload_lease.py"
CHIP_ENTRYPOINT = "cli.daedalus_chip"
PRIVATE_COMPLETION_WRITERS = frozenset(
    {
        "_retain_chip_eda_terminal_artifact",
        "_record_chip_eda_publication",
    }
)
FORBIDDEN_COMPLETION_WRITE_TARGETS = frozenset(
    {
        "candidate_path",
        "candidate_root",
        "candidate",
        "output_dir",
        "project_path",
        "project_root",
        "source_path",
        "source_project",
        "source_root",
        "workspace_path",
        "workspace_root",
        "worktree_path",
        "worktree_root",
    }
)


def _enclosing_function_names(
    source_path: Path,
    positions: set[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    owners: dict[tuple[int, int], str] = {}
    for node in ast.walk(tree):
        position = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
        if not isinstance(node, ast.Call) or position not in positions:
            continue
        current = parents.get(id(node))
        while current is not None and not isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            current = parents.get(id(current))
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owners[position] = current.name
    return owners


def _tree(source_path: Path) -> ast.Module:
    return ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _owner(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    current = parents.get(id(node))
    while current is not None and not isinstance(
        current, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        current = parents.get(id(current))
    return (
        current.name
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef))
        else "<module>"
    )


def _callee_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _production_calls(callee: str) -> list[tuple[str, str, ast.Call]]:
    found: list[tuple[str, str, ast.Call]] = []
    for source_path in sorted((ROOT / "daedalus").rglob("*.py")):
        tree = _tree(source_path)
        parents = _parents(tree)
        relative = source_path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee_name(node) == callee:
                found.append((relative, _owner(node, parents), node))
    return sorted(found, key=lambda item: (item[0], item[2].lineno, item[2].col_offset))


def _function(source_path: Path, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(_tree(source_path))
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected one {name} definition in {source_path}"
    return matches[0]


def _calls_in(node: ast.AST, callee: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and _callee_name(child) == callee
    ]


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    assert all(keyword.arg is not None for keyword in call.keywords)
    result = {str(keyword.arg): keyword.value for keyword in call.keywords}
    assert len(result) == len(call.keywords)
    return result


def _expression(node: ast.AST) -> str:
    return ast.unparse(node)


def _literal_all(source_path: Path) -> tuple[str, ...]:
    matches = [
        node.value
        for node in _tree(source_path).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(matches) == 1
    value = ast.literal_eval(matches[0])
    assert isinstance(value, list) and all(isinstance(item, str) for item in value)
    return tuple(value)


def _argument_names(function: ast.FunctionDef) -> set[str]:
    arguments = function.args
    return {
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }


def _referenced_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
    } | {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
    }


def test_chip_capture_writes_are_directly_lease_dominated() -> None:
    inventory = scan_repository_write_surfaces_v2(
        ROOT,
        source_revision=REVISION,
    )
    surfaces = tuple(
        surface for surface in inventory.surfaces if surface.path == EXECUTOR_PATH
    )

    assert len(surfaces) == 2
    assert {surface.callee for surface in surfaces} == {"tempfile.TemporaryFile"}
    assert all(surface.blocking for surface in surfaces)

    positions = {(surface.line, surface.column) for surface in surfaces}
    owners = _enclosing_function_names(ROOT / EXECUTOR_PATH, positions)
    assert owners == {position: "run_admitted_eda" for position in positions}

    doors, skipped = resolve_central_doors(ROOT)
    chip_doors = tuple(door for door in doors if door.door_id == CHIP_ENTRYPOINT)
    assert len(chip_doors) == 1, skipped
    assert chip_doors[0].rel_path == EXECUTOR_PATH

    dominance = _dominance(ROOT, chip_doors[0], NameIndex.build(ROOT))
    assert dominance.leased_refusal == ""
    assert positions <= dominance.leased_positions


def test_chip_completion_writers_are_private_and_finalizer_only() -> None:
    imports: list[tuple[str, str, str, str | None]] = []
    for source_path in sorted((ROOT / "daedalus").rglob("*.py")):
        relative = source_path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(source_path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.name in PRIVATE_COMPLETION_WRITERS:
                    imports.append((relative, str(node.module), alias.name, alias.asname))
    assert sorted(imports) == [
        (
            CLI_PATH,
            "daedalus.kernel.offload_lease",
            "_record_chip_eda_publication",
            "_record_chip_eda_publication_facade",
        ),
        (
            CLI_PATH,
            "daedalus.kernel.offload_lease",
            "_retain_chip_eda_terminal_artifact",
            "_retain_chip_eda_terminal_artifact_facade",
        ),
    ]

    exported = set(_literal_all(ROOT / KERNEL_PATH))
    assert PRIVATE_COMPLETION_WRITERS.isdisjoint(exported)

    retain_calls = _production_calls("_retain_chip_eda_terminal_artifact")
    record_calls = _production_calls("_record_chip_eda_publication")
    assert [(path, owner) for path, owner, _call in retain_calls] == [
        (CLI_PATH, "_terminal_stored_artifact"),
        (CLI_PATH, "_finalize_phase_publication"),
        (CLI_PATH, "_finalize_phase_publication"),
    ]
    assert [(path, owner) for path, owner, _call in record_calls] == [
        (CLI_PATH, "_finalize_phase_publication")
    ]

    common_bindings = {
        "authority_root": "authority_root",
        "source_revision": "authority_source_revision",
        "authorization": "authorization",
        "execution": "execution",
        "terminal_receipt": "terminal",
        "artifact_store": "store",
    }
    for _path, _owner_name, call in retain_calls:
        keywords = _keywords(call)
        assert FORBIDDEN_COMPLETION_WRITE_TARGETS.isdisjoint(keywords)
        assert {
            key: _expression(keywords[key]) for key in common_bindings
        } == common_bindings

    record_keywords = _keywords(record_calls[0][2])
    assert FORBIDDEN_COMPLETION_WRITE_TARGETS.isdisjoint(record_keywords)
    assert {
        key: _expression(record_keywords[key])
        for key in ("authority_root", "source_revision", "artifact_store")
    } == {
        "authority_root": "authority_root",
        "source_revision": "authority_source_revision",
        "artifact_store": "store",
    }
    assert _expression(record_keywords["evidence_root"]) == (
        "write_evidence_root(authority_root, authority_source_revision)"
    )

    terminal_wrapper_calls = _production_calls("_terminal_stored_artifact")
    assert {
        (path, owner) for path, owner, _call in terminal_wrapper_calls
    } == {(CLI_PATH, "_retained_publication_artifacts")}
    assert len(terminal_wrapper_calls) == 5
    assert {
        ast.literal_eval(_keywords(call)["role"])
        for _path, _owner_name, call in terminal_wrapper_calls
    } == {
        "attempt_contract",
        "execution_plan",
        "mission_contract",
        "policy_decision",
        "runtime_manifest",
    }
    assert [
        (path, owner)
        for path, owner, _call in _production_calls("_retained_publication_artifacts")
    ] == [(CLI_PATH, "_finalize_phase_publication")]
    assert _production_calls("_retained_artifacts") == []
    assert {
        (path, owner)
        for path, owner, _call in _production_calls("_stored_artifact")
    } <= {(CLI_PATH, "_retained_artifacts")}


def test_chip_completion_writes_are_terminal_cas_authority_bookkeeping() -> None:
    kernel_path = ROOT / KERNEL_PATH
    completion_path = ROOT / COMPLETION_PATH
    verifier = _function(kernel_path, "_verify_chip_eda_terminal_bookkeeping")
    retain_facade = _function(kernel_path, "_retain_chip_eda_terminal_artifact")
    record_facade = _function(kernel_path, "_record_chip_eda_publication")
    retain = _function(completion_path, "retain_chip_eda_terminal_artifact")
    record = _function(completion_path, "record_chip_eda_publication")

    for function in (verifier, retain_facade, record_facade, retain, record):
        assert FORBIDDEN_COMPLETION_WRITE_TARGETS.isdisjoint(
            _argument_names(function)
        )
        assert FORBIDDEN_COMPLETION_WRITE_TARGETS.isdisjoint(
            _referenced_names(function)
        )

    ledger_calls = _calls_in(verifier, "lease_ledger_path")
    evidence_root_calls = _calls_in(verifier, "write_evidence_root")
    assert len(ledger_calls) == len(evidence_root_calls) == 1
    assert [_expression(arg) for arg in ledger_calls[0].args] == ["authority_root"]
    assert [_expression(arg) for arg in evidence_root_calls[0].args] == [
        "authority_root",
        "source_revision",
    ]
    returns = [node for node in ast.walk(verifier) if isinstance(node, ast.Return)]
    assert len(returns) == 1 and returns[0].value is evidence_root_calls[0]

    retain_ports = _calls_in(retain_facade, "terminal_artifact_retainer")
    record_ports = _calls_in(record_facade, "publication_recorder")
    assert len(retain_ports) == len(record_ports) == 1

    retain_verifiers = _calls_in(retain, "_verify_chip_eda_terminal_bookkeeping")
    assert len(retain_verifiers) == 1
    assert {
        key: _expression(value)
        for key, value in _keywords(retain_verifiers[0]).items()
    } == {
        "authority_root": "authority_root",
        "source_revision": "source_revision",
        "authorization": "authorization",
        "execution": "execution",
        "terminal_receipt": "terminal_receipt",
    }
    cas_writes = _calls_in(retain, "put_bytes")
    assert len(cas_writes) == 1
    assert isinstance(cas_writes[0].func, ast.Attribute)
    assert _expression(cas_writes[0].func.value) == "artifact_store"
    assert _expression(_keywords(cas_writes[0])["expected_sha256"]) == (
        "expected_sha256"
    )
    allowed_assignments = [
        node.value
        for node in ast.walk(retain)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "allowed"
            for target in node.targets
        )
    ]
    assert len(allowed_assignments) == 1
    assert ast.literal_eval(allowed_assignments[0]) == {
        "runtime_manifest": "runtime-manifest.json",
        "execution_plan": "eda-execution-plan.json",
        "mission_contract": "mission.json",
        "attempt_contract": "attempt.json",
        "policy_decision": "policy-decision.json",
        "chip_run_receipt": None,
        "chip_evidence_packet": None,
    }

    record_verifiers = _calls_in(record, "_verify_chip_eda_terminal_bookkeeping")
    assert len(record_verifiers) == 1
    assert {
        key: _expression(value)
        for key, value in _keywords(record_verifiers[0]).items()
    } == {
        "authority_root": "authority_root",
        "source_revision": "source_revision",
        "authorization": "authorization",
        "execution": "execution",
        "terminal_receipt": "terminal_receipt",
    }
    comparisons = [
        node for node in ast.walk(record) if isinstance(node, ast.Compare)
    ]
    assert any(
        {"evidence_root", "expected_evidence_root"} <= _referenced_names(node)
        for node in comparisons
    )
    assert any(
        {"artifact_store", "expected_evidence_root"} <= _referenced_names(node)
        for node in comparisons
    )

    publication_records = _calls_in(record, "_publish_evidence_record")
    publication_indexes = _calls_in(record, "_publish_exact_bytes_once")
    index_paths = _calls_in(record, "_chip_publication_index_path")
    assert len(publication_records) == len(publication_indexes) == len(index_paths) == 1
    assert [_expression(arg) for arg in publication_records[0].args[:2]] == [
        "evidence_root",
        "'chip-publication'",
    ]
    assert _expression(publication_indexes[0].args[0]) == "index_path"
    assert _expression(index_paths[0].args[0]) == "evidence_root"

    raw_write_callees = {
        "open",
        "mkdir",
        "move",
        "rename",
        "rmtree",
        "unlink",
        "write",
        "write_bytes",
        "write_text",
    }
    assert not {
        _callee_name(call)
        for function in (verifier, retain, record)
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
    }.intersection(raw_write_callees)
    replace_calls = [
        call
        for function in (verifier, retain, record)
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and _callee_name(call) == "replace"
    ]
    assert len(replace_calls) == 1
    assert isinstance(replace_calls[0].func, ast.Attribute)
    assert _expression(replace_calls[0].func.value) == "str(finished_at)"
