from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.broker as broker
import daedalus.runtimes.provider_observation as provider_observation
import daedalus.runtimes.recovery as recovery


def _function(module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(inspect.getsource(module))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_broker_requires_exact_runtime_and_observation_authority_before_effect() -> None:
    source = inspect.getsource(broker)
    run = _function(broker, "run_runtime_provider")
    keyword_names = [arg.arg for arg in run.args.kwonlyargs]
    assert "observation_authority" in keyword_names
    assert "observation_binding_ledger" in keyword_names
    assert "observation_keyring" not in keyword_names
    assert "expected_provider_id" not in keyword_names

    boundary = inspect.getsource(broker._production_observation_binding)
    assert "type(authorization) is not RuntimeBoundEffectAuthorization" in boundary
    assert "type(authority) is not ProviderObservationAuthority" in boundary
    assert "type(ledger) is not ProviderObservationBindingLedger" in boundary
    assert "isinstance(authorization, RuntimeBoundEffectAuthorization)" not in boundary
    assert "compatibility" not in boundary.lower()

    exact_position = source.index("observation_binding = _production_observation_binding(")
    validate_position = source.index("spec = _validate_binding(", exact_position)
    grant_position = source.index("    authorization.grant()", validate_position)
    begin_position = source.index("    start = authorization.begin_effect", grant_position)
    prepare_position = source.index(
        "_prepare_observation_authority_after_start(",
        begin_position,
    )
    invoke_position = source.index("        value = invoke()", prepare_position)
    assert exact_position < validate_position < grant_position < begin_position
    assert begin_position < prepare_position < invoke_position

    helper = inspect.getsource(broker._prepare_observation_authority_after_start)
    assert "ledger.verify_authority(" in helper
    assert "ledger.bind_start(" in helper
    assert "ledger.require_bound(" in helper
    assert "if replay:" in helper


def test_recovery_derives_provider_and_keyring_without_caller_substitution() -> None:
    function = _function(recovery, "reconcile_runtime_provider_unknown")
    keyword_names = [arg.arg for arg in function.args.kwonlyargs]
    assert keyword_names == [
        "authorization",
        "execution",
        "start_receipt",
        "observation",
        "observation_binding_ledger",
        "reconciled_at",
    ]
    source = inspect.getsource(recovery)
    assert "expected_provider_id:" not in source
    assert "observation_keyring:" not in source
    assert "expected_source_revision:" not in source
    assert "invoke" not in inspect.getsource(recovery.reconcile_runtime_provider_unknown)
    assert "ledger.load(execution.execution_id)" in source
    assert "ledger.require_bound(" in source
    assert "keyring=observation_binding_ledger.observation_keyring" in source
    assert "expected_provider_id=record.authority.provider_id" in source
    assert "expected_source_revision=record.authority.source_revision" in source


def test_provider_observation_module_has_no_provider_or_process_execution_authority() -> None:
    tree = ast.parse(inspect.getsource(provider_observation))
    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "asyncio.subprocess",
    }
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert imported.isdisjoint(forbidden_imports)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "ProviderObservationBindingLedger" in provider_observation.__all__
    assert "issue_provider_observation_authority" in provider_observation.__all__


def test_persisted_binding_authenticates_exact_canonical_record() -> None:
    source = inspect.getsource(provider_observation.ProviderObservationBindingLedger)
    required = [
        "record_json TEXT NOT NULL",
        "record_sha256 TEXT NOT NULL",
        "record_hmac_sha256 TEXT NOT NULL",
        "BEGIN IMMEDIATE",
        "_parse_record_json",
        "record.digest != stored_digest",
        "hmac.compare_digest",
        "record.authority != authority",
        "record.start_receipt != start_receipt",
    ]
    for fragment in required:
        assert fragment in source


def test_malformed_registry_rows_are_normalized_into_boundary_errors() -> None:
    broker_source = inspect.getsource(broker._registry_map)
    recovery_source = inspect.getsource(recovery._registry_map)
    for source in (broker_source, recovery_source):
        assert "type(row) is not EntrypointSpec" in source or (
            "type(value) is not EntrypointSpec" in source
        )
        assert "except (AttributeError, TypeError, ValueError)" in source
