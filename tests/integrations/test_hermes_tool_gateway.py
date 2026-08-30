from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from daedalus.integrations.hermes.tool_gateway import (
    HermesGatewayDescriptor,
    HermesToolGatewayClient,
    HermesToolGatewayError,
    HermesToolGatewayServer,
)
from daedalus.integrations.hermes.tool_provider import DaedalusToolProvider, ToolSpec


def _provider() -> DaedalusToolProvider:
    tool = ToolSpec(
        name="echo",
        description="Echo text through the caller-owned boundary.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    def invoke(name: str, arguments: object) -> object:
        assert name == "echo"
        assert isinstance(arguments, dict)
        observation = str(arguments["text"])
        return {
            "observation": observation,
            "receipt_digest": sha256(observation.encode("utf-8")).hexdigest(),
        }

    return DaedalusToolProvider(
        (tool,),
        invoker=invoke,
        request_id="request-gateway",
        task_id="task-gateway",
    )


def test_gateway_roundtrip_and_token_cleanup(tmp_path: Path) -> None:
    server = HermesToolGatewayServer(_provider(), control_root=tmp_path / "control")
    descriptor = server.start(max_calls=2)
    token_file = Path(descriptor.token_file)
    assert token_file.is_file()
    try:
        with HermesToolGatewayClient(descriptor) as client:
            outcome = client.invoke(call_id="call-1", name="echo", arguments={"text": "hello"})
        assert outcome.ok is True
        assert outcome.observation == "hello"
        assert outcome.refusal == ""
    finally:
        server.close()
    assert not token_file.exists()
    assert server.failure_type == ""


def test_gateway_enforces_authenticated_call_budget(tmp_path: Path) -> None:
    server = HermesToolGatewayServer(_provider(), control_root=tmp_path / "control")
    descriptor = server.start(max_calls=1)
    try:
        with HermesToolGatewayClient(descriptor) as client:
            first = client.invoke(call_id="call-1", name="echo", arguments={"text": "one"})
            second = client.invoke(call_id="call-2", name="echo", arguments={"text": "two"})
        assert first.ok is True
        assert second.ok is False
        assert second.refusal == "tool_call_budget_exhausted"
    finally:
        server.close()


def test_gateway_descriptor_rejects_digest_tampering(tmp_path: Path) -> None:
    descriptor = HermesGatewayDescriptor.create(
        host="127.0.0.1",
        port=31337,
        token_file=str(tmp_path / "token"),
        request_id="request",
        task_id="task",
        tool_scope_digest="1" * 64,
        max_calls=1,
        expires_at_ns=2**63 - 1,
    )
    tampered = descriptor.to_dict()
    tampered["port"] = 31338
    with pytest.raises(HermesToolGatewayError):
        HermesGatewayDescriptor.from_dict(tampered)
