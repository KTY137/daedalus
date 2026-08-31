"""Strict JSONL protocol between the Daedalus adapter and the Hermes worker."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from typing import BinaryIO, Mapping

from .configuration import HERMES_PROTOCOL_SCHEMA

MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 80_000


class HermesProtocolError(ValueError):
    pass


_FIELDS: dict[str, frozenset[str]] = {
    "run_request": frozenset(
        {
            "schema",
            "type",
            "request_id",
            "task_id",
            "sequence",
            "system_prompt",
            "user_prompt",
            "model",
            "provider",
            "base_url",
            "api_key_env",
            "max_iterations",
            "max_wall_seconds",
            "max_tool_calls",
            "tool_definitions",
            "context_digest",
            "memory_digest",
            "workspace",
            "checkout_digest",
            "run_agent_sha256",
            "source_commit",
        }
    ),
    "worker_started": frozenset(
        {"schema", "type", "request_id", "task_id", "sequence", "checkout_digest"}
    ),
    "tool_call": frozenset(
        {"schema", "type", "request_id", "task_id", "sequence", "call_id", "name", "arguments"}
    ),
    "tool_result": frozenset(
        {
            "schema",
            "type",
            "request_id",
            "task_id",
            "sequence",
            "call_id",
            "name",
            "ok",
            "observation",
            "observation_digest",
            "receipt_digest",
            "invocation_digest",
            "refusal",
        }
    ),
    "final": frozenset(
        {
            "schema",
            "type",
            "request_id",
            "task_id",
            "sequence",
            "response",
            "messages_digest",
            "message_count",
            "tool_call_count",
        }
    ),
    "failure": frozenset(
        {
            "schema",
            "type",
            "request_id",
            "task_id",
            "sequence",
            "phase",
            "error_type",
            "error_digest",
        }
    ),
}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _bounded(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise HermesProtocolError("protocol value exceeds the node limit")
        if depth > MAX_DEPTH:
            raise HermesProtocolError("protocol value exceeds the nesting limit")
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise HermesProtocolError("protocol object keys must be strings")
                stack.append((nested, depth + 1))
        elif isinstance(item, (list, tuple)):
            stack.extend((nested, depth + 1) for nested in item)
        elif not isinstance(item, (str, int, float, bool, type(None))):
            raise HermesProtocolError("protocol value contains an unsupported type")


def validate_message(value: object, *, expected_type: str | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HermesProtocolError("protocol message must be an object")
    _bounded(value)
    message_type = value.get("type")
    if not isinstance(message_type, str) or message_type not in _FIELDS:
        raise HermesProtocolError("unknown protocol message type")
    if expected_type is not None and message_type != expected_type:
        raise HermesProtocolError(f"expected {expected_type}, received {message_type}")
    if set(value) != set(_FIELDS[message_type]):
        raise HermesProtocolError(f"{message_type} fields are not exact")
    if value["schema"] != HERMES_PROTOCOL_SCHEMA:
        raise HermesProtocolError("protocol schema mismatch")
    for name in ("request_id", "task_id"):
        if not isinstance(value[name], str) or not value[name]:
            raise HermesProtocolError(f"{name} must be a nonempty string")
    if not isinstance(value["sequence"], int) or value["sequence"] < 0:
        raise HermesProtocolError("sequence must be a nonnegative integer")
    if message_type in {"tool_call", "tool_result"}:
        for name in ("call_id", "name"):
            if not isinstance(value[name], str) or not value[name]:
                raise HermesProtocolError(f"{name} must be a nonempty string")
    if message_type == "tool_call" and not isinstance(value["arguments"], dict):
        raise HermesProtocolError("tool_call arguments must be an object")
    if message_type == "tool_result":
        if not isinstance(value["ok"], bool) or not isinstance(value["observation"], str):
            raise HermesProtocolError("tool_result ok/observation fields are invalid")
        for name in ("observation_digest", "receipt_digest", "invocation_digest"):
            if not isinstance(value[name], str) or len(value[name]) != 64:
                raise HermesProtocolError(f"{name} must be SHA-256")
        if not isinstance(value["refusal"], str):
            raise HermesProtocolError("tool_result refusal must be text")
    if message_type == "final":
        if not isinstance(value["response"], str):
            raise HermesProtocolError("final response must be text")
        if not isinstance(value["message_count"], int) or value["message_count"] < 0:
            raise HermesProtocolError("final message_count is invalid")
        if not isinstance(value["tool_call_count"], int) or value["tool_call_count"] < 0:
            raise HermesProtocolError("final tool_call_count is invalid")
    if message_type == "failure":
        for name in ("phase", "error_type", "error_digest"):
            if not isinstance(value[name], str) or not value[name]:
                raise HermesProtocolError(f"failure {name} is invalid")
    return value


def encode_message(value: Mapping[str, object]) -> bytes:
    checked = validate_message(dict(value))
    encoded = canonical_json(checked) + b"\n"
    if len(encoded) > MAX_LINE_BYTES:
        raise HermesProtocolError("protocol line exceeds the byte limit")
    return encoded


def write_message(stream: BinaryIO, value: Mapping[str, object]) -> None:
    stream.write(encode_message(value))
    stream.flush()


def read_message(stream: BinaryIO, *, expected_type: str | None = None) -> dict[str, object]:
    line = stream.readline(MAX_LINE_BYTES + 1)
    if not line:
        raise EOFError("protocol stream closed")
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise HermesProtocolError("protocol line is oversized or unterminated")
    try:
        decoded = line.decode("utf-8", errors="strict")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HermesProtocolError("protocol line is not canonical UTF-8 JSON") from exc
    return validate_message(value, expected_type=expected_type)


def message_stream(data: bytes) -> BinaryIO:
    return io.BytesIO(data)
