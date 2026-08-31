"""Hermes child process for the Daedalus JSONL one-shot runtime."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import threading
import time
from types import ModuleType
from typing import Callable, Mapping

try:
    from .protocol import canonical_sha256, read_message, write_message
except ImportError:
    from daedalus.integrations.hermes.protocol import canonical_sha256, read_message, write_message


class HermesWorkerError(RuntimeError):
    pass


class _ProtocolBridge:
    def __init__(self, request: Mapping[str, object]) -> None:
        self.request_id = str(request["request_id"])
        self.task_id = str(request["task_id"])
        self.max_tool_calls = int(request["max_tool_calls"])
        self._sequence = 0
        self._calls = 0
        self._lock = threading.RLock()
        self._input = sys.stdin.buffer
        self._output = sys.__stdout__.buffer

    def emit(self, message_type: str, **fields: object) -> dict[str, object]:
        with self._lock:
            message = {
                "schema": "daedalus-hermes-worker-jsonl/1",
                "type": message_type,
                "request_id": self.request_id,
                "task_id": self.task_id,
                "sequence": self._sequence,
                **fields,
            }
            write_message(self._output, message)
            self._sequence += 1
            return message

    def call_tool(self, name: str, arguments: Mapping[str, object]) -> str:
        with self._lock:
            if self._calls >= self.max_tool_calls:
                return "tool refused: authenticated Hermes tool-call budget exhausted"
            self._calls += 1
            call_id = canonical_sha256(
                {
                    "request_id": self.request_id,
                    "task_id": self.task_id,
                    "ordinal": self._calls,
                    "name": name,
                    "arguments": dict(arguments),
                }
            )[:32]
            self.emit("tool_call", call_id=call_id, name=name, arguments=dict(arguments))
            result = read_message(self._input, expected_type="tool_result")
            if result["request_id"] != self.request_id or result["task_id"] != self.task_id:
                raise HermesWorkerError("tool result task identity mismatch")
            if result["call_id"] != call_id or result["name"] != name:
                raise HermesWorkerError("tool result correlation mismatch")
            if int(result["sequence"]) != self._sequence:
                raise HermesWorkerError("tool result sequence mismatch")
            self._sequence += 1
            return str(result["observation"])

    @property
    def tool_call_count(self) -> int:
        return self._calls


def _load_upstream(checkout_root: Path) -> ModuleType:
    path = checkout_root / "run_agent.py"
    spec = importlib.util.spec_from_file_location("daedalus_pinned_hermes_run_agent", path)
    if spec is None or spec.loader is None:
        raise HermesWorkerError("unable to construct exact Hermes module loader")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(checkout_root))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(checkout_root))
        except ValueError:
            pass
    return module


def _patch_tools(module: ModuleType, definitions: list[dict[str, object]], bridge: _ProtocolBridge) -> None:
    def get_tool_definitions(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return list(definitions)

    def handle_function_call(*args: object, **kwargs: object) -> str:
        name = kwargs.get("function_name") or kwargs.get("name") or kwargs.get("tool_name")
        arguments = kwargs.get("function_args") or kwargs.get("arguments") or kwargs.get("args")
        if name is None and args:
            name = args[0]
        if arguments is None and len(args) > 1:
            arguments = args[1]
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(name, str) or not name:
            raise HermesWorkerError("Hermes requested a tool without a name")
        if not isinstance(arguments, Mapping):
            raise HermesWorkerError("Hermes requested a tool with non-object arguments")
        return bridge.call_tool(name, arguments)

    setattr(module, "get_tool_definitions", get_tool_definitions)
    setattr(module, "handle_function_call", handle_function_call)
    model_tools = sys.modules.get("model_tools")
    if model_tools is not None:
        setattr(model_tools, "get_tool_definitions", get_tool_definitions)
        setattr(model_tools, "handle_function_call", handle_function_call)
    for candidate_name in ("toolset", "tools", "agent.tools", "agent.toolset"):
        candidate = sys.modules.get(candidate_name)
        if candidate is not None:
            if hasattr(candidate, "get_tool_definitions"):
                setattr(candidate, "get_tool_definitions", get_tool_definitions)
            if hasattr(candidate, "handle_function_call"):
                setattr(candidate, "handle_function_call", handle_function_call)


def _filtered_kwargs(callable_object: Callable[..., object], candidates: Mapping[str, object]) -> dict[str, object]:
    try:
        signature = inspect.signature(callable_object)
    except (TypeError, ValueError):
        return dict(candidates)
    accepts_varkw = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
    if accepts_varkw:
        return dict(candidates)
    return {name: value for name, value in candidates.items() if name in signature.parameters}


def _construct_agent(module: ModuleType, request: Mapping[str, object]) -> object:
    agent_type = getattr(module, "AIAgent", None)
    if agent_type is None or not callable(agent_type):
        raise HermesWorkerError("pinned Hermes run_agent.py does not expose AIAgent")
    candidates: dict[str, object] = {
        "model": str(request["model"]),
        "model_name": str(request["model"]),
        "provider": str(request["provider"]),
        "base_url": str(request["base_url"]),
        "api_key": None,
        "max_iterations": int(request["max_iterations"]),
        "max_turns": int(request["max_iterations"]),
        "run_budget_seconds": float(request["max_wall_seconds"]),
        "timeout": float(request["max_wall_seconds"]),
        "system_prompt": str(request["system_prompt"]),
        "enabled_toolsets": [],
        "disabled_toolsets": [],
        "skip_context_files": True,
        "load_soul_identity": False,
        "skip_memory": True,
        "skip_background_review": True,
        "session_db": None,
        "checkpoints_enabled": False,
        "ephemeral_system_prompt": True,
        "quiet_mode": True,
        "quiet": True,
    }
    return agent_type(**_filtered_kwargs(agent_type, candidates))


def _invoke_agent(agent: object, request: Mapping[str, object]) -> object:
    user_prompt = str(request["user_prompt"])
    system_prompt = str(request["system_prompt"])
    for name in ("run_conversation", "run", "chat", "invoke"):
        method = getattr(agent, name, None)
        if not callable(method):
            continue
        candidates = {
            "user_input": user_prompt,
            "prompt": user_prompt,
            "message": user_prompt,
            "query": user_prompt,
            "system_prompt": system_prompt,
            "max_iterations": int(request["max_iterations"]),
        }
        kwargs = _filtered_kwargs(method, candidates)
        try:
            signature = inspect.signature(method)
            required_positionals = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                and parameter.default is inspect.Parameter.empty
            ]
        except (TypeError, ValueError):
            required_positionals = []
        if required_positionals and not kwargs:
            result = method(user_prompt)
        else:
            result = method(**kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
    raise HermesWorkerError("pinned Hermes AIAgent exposes no supported one-shot method")


def _normalise_result(value: object, agent: object) -> tuple[str, object, int]:
    response: object = value
    messages: object = []
    if isinstance(value, tuple):
        if value:
            response = value[0]
        if len(value) > 1:
            messages = value[1]
    elif isinstance(value, Mapping):
        response = value.get("response", value.get("content", value.get("result", value)))
        messages = value.get("messages", [])
    for name in ("messages", "conversation", "history"):
        candidate = getattr(agent, name, None)
        if candidate and not messages:
            messages = candidate
            break
    if not isinstance(response, str):
        response = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    if not isinstance(messages, (list, tuple)):
        messages = [messages]
    return response, messages, len(messages)


def _verify_worker_source(checkout_root: Path, request: Mapping[str, object]) -> None:
    run_agent = checkout_root / "run_agent.py"
    if not run_agent.is_file():
        raise HermesWorkerError("run_agent.py is absent inside the worker sandbox")
    digest = sha256(run_agent.read_bytes()).hexdigest()
    if digest != request["run_agent_sha256"]:
        raise HermesWorkerError("run_agent.py changed between parent verification and worker import")


def main() -> int:
    bridge: _ProtocolBridge | None = None
    phase = "request"
    try:
        request = read_message(sys.stdin.buffer, expected_type="run_request")
        bridge = _ProtocolBridge(request)
        checkout_env = __import__("os").environ.get("DAEDALUS_HERMES_CHECKOUT", "")
        if not checkout_env:
            raise HermesWorkerError("worker checkout path is absent")
        checkout_root = Path(checkout_env).expanduser().resolve(strict=True)
        phase = "source_verification"
        _verify_worker_source(checkout_root, request)
        bridge.emit("worker_started", checkout_digest=str(request["checkout_digest"]))
        phase = "upstream_import"
        with redirect_stdout(sys.stderr):
            module = _load_upstream(checkout_root)
            definitions = request["tool_definitions"]
            if not isinstance(definitions, list):
                raise HermesWorkerError("tool definitions are not a list")
            _patch_tools(module, definitions, bridge)
            phase = "agent_construction"
            agent = _construct_agent(module, request)
            phase = "agent_run"
            started = time.monotonic()
            raw_result = _invoke_agent(agent, request)
            if time.monotonic() - started > float(request["max_wall_seconds"]):
                raise TimeoutError("Hermes one-shot exceeded its wall-time contract")
        response, messages, message_count = _normalise_result(raw_result, agent)
        if len(response.encode("utf-8")) > 4 * 1024 * 1024:
            raise HermesWorkerError("Hermes response exceeds the worker bound")
        bridge.emit(
            "final",
            response=response,
            messages_digest=canonical_sha256(messages),
            message_count=message_count,
            tool_call_count=bridge.tool_call_count,
        )
        return 0
    except BaseException as exc:
        if bridge is not None:
            error_type = type(exc).__name__
            try:
                bridge.emit(
                    "failure",
                    phase=phase,
                    error_type=error_type,
                    error_digest=canonical_sha256({"phase": phase, "error_type": error_type}),
                )
            except BaseException:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
