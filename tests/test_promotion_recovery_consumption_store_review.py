from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.kernel.promotion_recovery_consumption_store as store


SOURCE_PATH = Path(store.__file__).resolve()
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1, name
    node = matches[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _method(class_name: str, method_name: str) -> ast.FunctionDef:
    classes = [
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    assert len(classes) == 1, class_name
    matches = [
        node
        for node in classes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    assert len(matches) == 1, f"{class_name}.{method_name}"
    return matches[0]


def _call_names(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Call):
            continue
        target = candidate.func
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            parts: list[str] = [target.attr]
            cursor = target.value
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)
            names.append(".".join(reversed(parts)))
    return tuple(names)


def test_module_has_no_repository_effect_or_owner_issuer_authority() -> None:
    forbidden_import_roots = {
        "subprocess",
        "git",
        "docker",
        "daedalus.kairos",
        "daedalus.providers",
        "daedalus.runtimes",
    }
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(
        name == root or name.startswith(root + ".")
        for name in imported
        for root in forbidden_import_roots
    )

    forbidden_calls = {
        "promote_candidates",
        "merge_pull_request",
        "create_worktree",
        "reap_branches",
        "issue_owner_approval",
        "issue_promotion_recovery_decision",
        "terminalize_promotion_effect",
        "cancel_effect",
    }
    all_calls = set(_call_names(TREE))
    assert not forbidden_calls.intersection(all_calls)


def test_compatibility_constructor_cannot_initialize_or_create_paths() -> None:
    constructor = _method(
        "PreprovisionedPromotionRecoveryConsumptionLedger",
        "__init__",
    )
    calls = set(_call_names(constructor))
    assert "super" not in calls
    assert "self._initialize" not in calls
    assert "mkdir" not in calls
    assert "sqlite3.connect" not in calls
    assert "inspect_promotion_recovery_consumption_store" in calls


def test_writer_open_is_existing_store_only() -> None:
    opener = _method(
        "PreprovisionedPromotionRecoveryConsumptionLedger",
        "_connect_verified",
    )
    rendered = ast.get_source_segment(SOURCE, opener)
    assert rendered is not None
    assert 'mode = "ro" if read_only else "rw"' in rendered
    assert "mode=rwc" not in rendered
    assert "mode=memory" not in rendered
    assert "mkdir" not in set(_call_names(opener))
    assert rendered.index("inspect_promotion_recovery_consumption_store") < rendered.index(
        "sqlite3.connect"
    )
    assert rendered.count("inspect_promotion_recovery_consumption_store") == 2


def test_inspection_is_read_only_and_schema_exact() -> None:
    opener = _function("_open_read_only")
    rendered = ast.get_source_segment(SOURCE, opener)
    assert rendered is not None
    assert "?mode=ro" in rendered
    assert "PRAGMA query_only=ON" in rendered

    contract = _function("_connection_contract")
    contract_source = ast.get_source_segment(SOURCE, contract)
    assert contract_source is not None
    required = (
        "PRAGMA integrity_check",
        "PRAGMA user_version",
        "SELECT type, name, sql",
        "_normalized_sql(object_sql)",
        "PRAGMA table_info",
        "columns != _COLUMNS",
        "tuple(int(row[3]) for row in table_rows)",
        "any(row[4] is not None for row in table_rows)",
        "PRAGMA index_list",
        "PRAGMA index_info",
        "str(row[3])",
        "int(row[4])",
        "projected_contract != _UNIQUE_INDEX_CONTRACT",
        "unique_constraints != _UNIQUE_CONSTRAINTS",
        "schema_version != _SCHEMA_VERSION",
    )
    for fragment in required:
        assert fragment in contract_source

    assert "decision_sha256 TEXT NOT NULL PRIMARY KEY" in store._SCHEMA_SQL
    assert store._SCHEMA_DESCRIPTOR["sql"] == store._normalized_sql(store._SCHEMA_SQL)


def test_initializer_is_the_only_publication_authority_and_does_not_clobber() -> None:
    initializer = _function("initialize_promotion_recovery_consumption_store")
    calls = set(_call_names(initializer))
    rendered = ast.get_source_segment(SOURCE, initializer)
    assert rendered is not None
    assert "tempfile.mkstemp" in calls
    assert "os.link" in calls
    assert "os.replace" not in calls
    assert "os.rename" not in calls
    assert "mkdir" not in calls
    assert rendered.index("os.path.lexists(target)") < rendered.index("tempfile.mkstemp")
    assert rendered.index("_connection_contract(connection)") < rendered.index(
        "os.link(temporary, target)"
    )
    assert rendered.index("temporary_identity = _file_identity(temporary)") < (
        rendered.index("os.link(temporary, target)")
    )
    assert rendered.index("os.link(temporary, target)") < rendered.index(
        "_file_identity(target) != published_identity"
    )
    assert rendered.index("os.link(temporary, target)") < rendered.index(
        "inspect_promotion_recovery_consumption_store(target)"
    )
    assert "_remove_own_publication(target, published_identity)" in rendered


def test_failed_publication_cleanup_is_identity_guarded() -> None:
    cleanup = _function("_remove_own_publication")
    rendered = ast.get_source_segment(SOURCE, cleanup)
    assert rendered is not None
    assert "_file_identity(target)" in rendered
    assert rendered.index("current_identity != published_identity") < rendered.index(
        "target.unlink()"
    )
    assert "target.unlink()" not in ast.get_source_segment(
        SOURCE,
        _function("initialize_promotion_recovery_consumption_store"),
    )


def test_store_adapter_is_additive_and_not_production_wiring() -> None:
    assert issubclass(
        store.PreprovisionedPromotionRecoveryConsumptionLedger,
        store.PromotionRecoveryConsumptionLedger,
    )
    assert store.PreprovisionedPromotionRecoveryConsumptionLedger is not (
        store.PromotionRecoveryConsumptionLedger
    )
    public_functions = {
        node.name
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert public_functions == {
        "initialize_promotion_recovery_consumption_store",
        "inspect_promotion_recovery_consumption_store",
    }
    assert "effect_boundary" not in SOURCE
    assert "ENTRYPOINTS" not in SOURCE
    assert "REGISTRY_BY_ID" not in SOURCE


def test_public_signatures_do_not_accept_authority_smuggling() -> None:
    initialize = inspect.signature(store.initialize_promotion_recovery_consumption_store)
    inspect_store = inspect.signature(store.inspect_promotion_recovery_consumption_store)
    constructor = inspect.signature(
        store.PreprovisionedPromotionRecoveryConsumptionLedger.__init__
    )
    assert tuple(initialize.parameters) == ("path",)
    assert tuple(inspect_store.parameters) == ("path",)
    assert tuple(constructor.parameters) == ("self", "path", "clock")
    assert all(
        parameter.kind not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
        for signature in (initialize, inspect_store, constructor)
        for parameter in signature.parameters.values()
    )
