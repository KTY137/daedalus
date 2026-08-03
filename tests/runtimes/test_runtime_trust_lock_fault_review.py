from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.broker as broker


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(broker))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def test_terminal_fence_translates_only_sqlite_acquisition_failure() -> None:
    function = _function("_finish_completed_under_runtime_fence")
    handlers = [
        handler
        for node in ast.walk(function)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    sqlite_handlers = [
        handler
        for handler in handlers
        if isinstance(handler.type, ast.Attribute)
        and isinstance(handler.type.value, ast.Name)
        and handler.type.value.id == "sqlite3"
        and handler.type.attr == "Error"
    ]
    assert len(sqlite_handlers) == 1
    handler = sqlite_handlers[0]
    raises = [node for node in ast.walk(handler) if isinstance(node, ast.Raise)]
    assert len(raises) == 1
    raised = raises[0]
    assert isinstance(raised.exc, ast.Call)
    assert _call_name(raised.exc) == "RuntimeProviderTrustFenceError"
    assert isinstance(raised.cause, ast.Name)
    assert raised.cause.id == handler.name
    assert len(raised.exc.args) == 1
    assert isinstance(raised.exc.args[0], ast.Constant)
    assert (
        raised.exc.args[0].value
        == "runtime trust terminal fence could not be acquired"
    )


def test_terminal_fence_failure_routes_through_durable_cancellation() -> None:
    function = _function("run_runtime_provider")
    trust_handlers = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if (
                isinstance(handler.type, ast.Name)
                and handler.type.id == "RuntimeProviderTrustFenceError"
            ):
                trust_handlers.append(handler)
    assert len(trust_handlers) == 1
    handler = trust_handlers[0]
    calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_cancel_for_trust_loss"
    ]
    assert len(calls) == 1
    phases = [
        keyword.value.value
        for keyword in calls[0].keywords
        if keyword.arg == "phase" and isinstance(keyword.value, ast.Constant)
    ]
    assert phases == ["terminal-runtime-fence"]
    assert any(
        isinstance(node, ast.Raise) and node.exc is None
        for node in ast.walk(handler)
    )


def test_lock_failure_path_does_not_retain_sqlite_exception_text() -> None:
    function = _function("_finish_completed_under_runtime_fence")
    handler = next(
        handler
        for node in ast.walk(function)
        if isinstance(node, ast.Try)
        for handler in node.handlers
        if isinstance(handler.type, ast.Attribute)
        and isinstance(handler.type.value, ast.Name)
        and handler.type.value.id == "sqlite3"
        and handler.type.attr == "Error"
    )
    assert not any(isinstance(node, ast.JoinedStr) for node in ast.walk(handler))
    assert not any(
        isinstance(node, ast.Call) and _call_name(node) in {"str", "repr"}
        for node in ast.walk(handler)
    )
