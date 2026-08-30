"""Daedalus-owned tool catalogue and bounded invocation projection for Hermes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Iterable, Mapping, Protocol

from .protocol import canonical_sha256


class HermesToolError(ValueError):
    pass


class ToolInvoker(Protocol):
    def __call__(self, name: str, arguments: Mapping[str, object]) -> object: ...


_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def _validate_schema(schema: object, *, path: str = "$") -> None:
    if not isinstance(schema, Mapping):
        raise HermesToolError(f"{path}: tool schema must be an object")
    allowed = {
        "type",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
    unknown = set(schema) - allowed
    if unknown:
        raise HermesToolError(f"{path}: unsupported schema keywords: {sorted(unknown)}")
    kind = schema.get("type")
    if kind not in _JSON_TYPES:
        raise HermesToolError(f"{path}: schema type must be one accepted JSON type")
    if "description" in schema and not isinstance(schema["description"], str):
        raise HermesToolError(f"{path}: description must be text")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise HermesToolError(f"{path}: enum must be a nonempty list")
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", False)
        if not isinstance(properties, Mapping) or any(not isinstance(key, str) for key in properties):
            raise HermesToolError(f"{path}: object properties must be a string-keyed object")
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise HermesToolError(f"{path}: required must be a string list")
        if len(required) != len(set(required)) or not set(required) <= set(properties):
            raise HermesToolError(f"{path}: required fields must uniquely reference properties")
        if additional is not False:
            raise HermesToolError(f"{path}: additionalProperties must be false")
        for key, nested in properties.items():
            _validate_schema(nested, path=f"{path}.{key}")
    elif kind == "array":
        if "items" not in schema:
            raise HermesToolError(f"{path}: array schema requires items")
        _validate_schema(schema["items"], path=f"{path}[]")


def _validate_value(value: object, schema: Mapping[str, object], *, path: str = "$") -> None:
    kind = schema["type"]
    valid = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[str(kind)]
    if not valid:
        raise HermesToolError(f"{path}: value does not satisfy type {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise HermesToolError(f"{path}: value is not in the allowed enum")
    if kind == "object":
        assert isinstance(value, Mapping)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = set(required) - set(value)
        unknown = set(value) - set(properties)
        if missing:
            raise HermesToolError(f"{path}: missing required fields: {sorted(missing)}")
        if unknown:
            raise HermesToolError(f"{path}: unknown fields: {sorted(unknown)}")
        assert isinstance(properties, Mapping)
        for key, nested in properties.items():
            if key in value:
                assert isinstance(nested, Mapping)
                _validate_value(value[key], nested, path=f"{path}.{key}")
    elif kind == "array":
        assert isinstance(value, list)
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise HermesToolError(f"{path}: array is too short")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise HermesToolError(f"{path}: array is too long")
        nested = schema["items"]
        assert isinstance(nested, Mapping)
        for index, item in enumerate(value):
            _validate_value(item, nested, path=f"{path}[{index}]")
    elif kind == "string":
        assert isinstance(value, str)
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise HermesToolError(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise HermesToolError(f"{path}: string is too long")
    elif kind in {"integer", "number"}:
        numeric = float(value)  # type: ignore[arg-type]
        if "minimum" in schema and numeric < float(schema["minimum"]):
            raise HermesToolError(f"{path}: number is below minimum")
        if "maximum" in schema and numeric > float(schema["maximum"]):
            raise HermesToolError(f"{path}: number is above maximum")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "a").replace("-", "a").isalnum():
            raise HermesToolError("tool name must be a nonempty conservative identifier")
        if not isinstance(self.description, str) or not self.description:
            raise HermesToolError("tool description is required")
        _validate_schema(self.parameters)

    def to_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description, "parameters": dict(self.parameters)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ToolSpec":
        if set(value) != {"name", "description", "parameters"} or not isinstance(value["parameters"], Mapping):
            raise HermesToolError("tool specification fields are not exact")
        return cls(name=str(value["name"]), description=str(value["description"]), parameters=dict(value["parameters"]))


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    observation: str
    observation_digest: str
    receipt_digest: str
    invocation_digest: str
    refusal: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize_result(value: object) -> tuple[str, str]:
    if isinstance(value, Mapping):
        observation = value.get("observation", value.get("result", value))
        receipt = value.get("receipt_digest", "")
        if isinstance(observation, str):
            text = observation
        else:
            text = json.dumps(observation, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        receipt_text = str(receipt) if receipt else canonical_sha256(value)
        if len(receipt_text) != 64:
            receipt_text = canonical_sha256({"receipt": receipt_text})
        return text, receipt_text
    if isinstance(value, str):
        return value, canonical_sha256({"result": value})
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return text, canonical_sha256({"result": value})


class DaedalusToolProvider:
    """Immutable allowlist; effects occur only through the injected kernel invoker."""

    def __init__(
        self,
        tools: Iterable[ToolSpec],
        *,
        invoker: ToolInvoker,
        request_id: str,
        task_id: str,
        max_observation_characters: int = 200_000,
    ) -> None:
        materialized = tuple(tools)
        names = [tool.name for tool in materialized]
        if len(names) != len(set(names)):
            raise HermesToolError("tool names must be unique")
        if not request_id or not task_id:
            raise HermesToolError("request_id and task_id are required")
        if not 1 <= max_observation_characters <= 2_000_000:
            raise HermesToolError("observation character bound is invalid")
        self._tools = {tool.name: tool for tool in materialized}
        self._invoker = invoker
        self._request_id = request_id
        self._task_id = task_id
        self._max_observation_characters = max_observation_characters

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def definitions(self) -> tuple[dict[str, object], ...]:
        return tuple(self._tools[name].to_definition() for name in sorted(self._tools))

    @property
    def specifications(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))

    @property
    def scope_digest(self) -> str:
        return canonical_sha256([tool.to_dict() for tool in self.specifications])

    def invoke(self, name: str, arguments: Mapping[str, object]) -> ToolOutcome:
        invocation = {
            "schema": "daedalus-hermes-tool-invocation/1",
            "request_id": self._request_id,
            "task_id": self._task_id,
            "tool_scope_digest": self.scope_digest,
            "name": name,
            "arguments": dict(arguments),
        }
        invocation_digest = canonical_sha256(invocation)
        tool = self._tools.get(name)
        if tool is None:
            observation = "tool refused: not present in the authenticated Daedalus tool scope"
            return ToolOutcome(
                ok=False,
                observation=observation,
                observation_digest=canonical_sha256({"observation": observation}),
                receipt_digest=canonical_sha256({"refusal": "unknown_tool", "invocation": invocation_digest}),
                invocation_digest=invocation_digest,
                refusal="unknown_tool",
            )
        try:
            _validate_value(dict(arguments), tool.parameters)
        except HermesToolError:
            observation = "tool refused: arguments do not satisfy the authenticated schema"
            return ToolOutcome(
                ok=False,
                observation=observation,
                observation_digest=canonical_sha256({"observation": observation}),
                receipt_digest=canonical_sha256({"refusal": "invalid_arguments", "invocation": invocation_digest}),
                invocation_digest=invocation_digest,
                refusal="invalid_arguments",
            )
        try:
            raw = self._invoker(name, dict(arguments))
            observation, receipt_digest = _normalize_result(raw)
            if len(observation) > self._max_observation_characters:
                observation = observation[: self._max_observation_characters]
                ok = False
                refusal = "observation_truncated"
            else:
                ok = True
                refusal = ""
            return ToolOutcome(
                ok=ok,
                observation=observation,
                observation_digest=canonical_sha256({"observation": observation}),
                receipt_digest=receipt_digest,
                invocation_digest=invocation_digest,
                refusal=refusal,
            )
        except BaseException as exc:
            error_type = type(exc).__name__
            observation = f"tool failed inside the Daedalus kernel boundary: {error_type}"
            return ToolOutcome(
                ok=False,
                observation=observation,
                observation_digest=canonical_sha256({"observation": observation}),
                receipt_digest=canonical_sha256({"failure_type": error_type, "invocation": invocation_digest}),
                invocation_digest=invocation_digest,
                refusal="kernel_tool_failure",
            )
