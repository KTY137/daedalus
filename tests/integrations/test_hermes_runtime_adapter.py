from __future__ import annotations

from hashlib import sha256
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.integrations.hermes.configuration import (
    HermesConfigurationError,
    HermesPinnedSource,
    HermesRuntimeConfig,
    HermesSandboxProfile,
    file_sha256,
)
from daedalus.integrations.hermes.runtime_adapter import (
    HermesRuntimeAdapter,
    HermesRuntimeRequest,
    HermesRuntimeResult,
)
from daedalus.integrations.hermes.session import hermes_runtime_session
from daedalus.integrations.hermes.tool_provider import DaedalusToolProvider, ToolSpec


_FAKE_RUN_AGENT = '''
import os
import time

class AIAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []

    def run_conversation(self, user_input="", prompt="", message="", query="", **kwargs):
        text = user_input or prompt or message or query
        if text == "sleep":
            time.sleep(5.0)
            return {"response": "late", "messages": []}
        if text == "env":
            return {
                "response": os.environ.get("HERMES_TEST_ALLOWED", "") + "|" + os.environ.get("HERMES_TEST_BLOCKED", ""),
                "messages": [],
            }
        if text == "unknown":
            observation = handle_function_call("missing", {})
        else:
            observation = handle_function_call("echo", {"text": text})
        self.messages = [{"role": "assistant", "content": observation}]
        return {"response": "final:" + observation, "messages": self.messages}
'''


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _fake_checkout(tmp_path: Path, *, run_agent: str = _FAKE_RUN_AGENT) -> tuple[Path, HermesPinnedSource]:
    root = tmp_path / "hermes-checkout"
    root.mkdir()
    (root / "run_agent.py").write_text(run_agent, encoding="utf-8")
    (root / "LICENSE").write_text("MIT test fixture\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Daedalus Tests")
    _git(root, "add", "run_agent.py", "LICENSE")
    _git(root, "commit", "-q", "-m", "fixture")
    source = HermesPinnedSource(
        repository="NousResearch/hermes-agent",
        release="fixture-v1",
        tag="fixture-v1",
        commit=_git(root, "rev-parse", "HEAD"),
        tree=_git(root, "rev-parse", "HEAD^{tree}"),
        run_agent_sha256=file_sha256(root / "run_agent.py"),
        license_sha256=file_sha256(root / "LICENSE"),
        archive_sha256="0" * 64,
    )
    return root, source


def _config(
    checkout: Path,
    source: HermesPinnedSource,
    *,
    max_wall_seconds: float = 10.0,
    ordinary_env_allowlist: tuple[str, ...] | None = None,
) -> HermesRuntimeConfig:
    options: dict[str, object] = {}
    if ordinary_env_allowlist is not None:
        options["ordinary_env_allowlist"] = ordinary_env_allowlist
    return HermesRuntimeConfig(
        checkout_root=str(checkout),
        python_executable=sys.executable,
        source=source,
        sandbox=HermesSandboxProfile(
            command_prefix=(),
            max_iterations=4,
            max_wall_seconds=max_wall_seconds,
            max_tool_calls=4,
            max_output_bytes=1024 * 1024,
            test_only_uncontained=True,
        ),
        **options,
    )


def _echo_tool() -> ToolSpec:
    return ToolSpec(
        name="echo",
        description="Return authenticated test text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 2000}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )


def _provider() -> DaedalusToolProvider:
    def invoke(name: str, arguments: object) -> object:
        assert name == "echo"
        assert isinstance(arguments, dict)
        observation = "echo:" + str(arguments["text"])
        return {
            "observation": observation,
            "receipt_digest": sha256(("receipt:" + observation).encode("utf-8")).hexdigest(),
        }

    return DaedalusToolProvider(
        (_echo_tool(),),
        invoker=invoke,
        request_id="request-1",
        task_id="task-1",
    )


def _execute(tmp_path: Path, prompt: str, *, max_wall_seconds: float = 10.0) -> HermesRuntimeResult:
    checkout, source = _fake_checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with hermes_runtime_session(
        tool_provider=_provider(),
        control_root=tmp_path / "control",
        workspace=workspace,
        system_prompt="Daedalus owns policy and effects.",
        user_prompt=prompt,
        config=_config(checkout, source, max_wall_seconds=max_wall_seconds),
    ) as request:
        return HermesRuntimeAdapter().execute(request)


def test_runtime_round_trip_through_caller_owned_gateway(tmp_path: Path) -> None:
    result = _execute(tmp_path, "hello")
    assert result.status == "completed"
    assert result.response == "final:echo:hello"
    assert result.tool_call_count == 1
    assert len(result.observation_digests) == 1
    assert len(result.receipt_digests) == 1
    assert len(result.invocation_digests) == 1
    assert result.terminal_error_type == ""


def test_unknown_tool_is_refused_without_bypassing_kernel(tmp_path: Path) -> None:
    result = _execute(tmp_path, "unknown")
    assert result.status == "completed"
    assert "tool refused" in result.response
    assert result.tool_call_count == 1
    assert len(result.receipt_digests) == 1


def test_runtime_timeout_kills_worker(tmp_path: Path) -> None:
    result = _execute(tmp_path, "sleep", max_wall_seconds=0.2)
    assert result.status == "timed_out"
    assert result.response == ""
    assert result.terminal_error_type == "TimeoutExpired"


def test_existing_cancellation_marker_kills_worker(tmp_path: Path) -> None:
    checkout, source = _fake_checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = tmp_path / "cancel"
    marker.write_text("stop", encoding="utf-8")
    with hermes_runtime_session(
        tool_provider=_provider(),
        control_root=tmp_path / "control",
        workspace=workspace,
        system_prompt="system",
        user_prompt="sleep",
        config=_config(checkout, source),
        cancellation_marker=marker,
    ) as request:
        result = HermesRuntimeAdapter().execute(request)
    assert result.status == "cancelled"
    assert result.terminal_error_type == "CancellationRequested"


def test_checkout_drift_is_refused_before_process_start(tmp_path: Path) -> None:
    checkout, source = _fake_checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with hermes_runtime_session(
        tool_provider=_provider(),
        control_root=tmp_path / "control",
        workspace=workspace,
        system_prompt="system",
        user_prompt="hello",
        config=_config(checkout, source),
    ) as request:
        (checkout / "run_agent.py").write_text(_FAKE_RUN_AGENT + "\n# drift\n", encoding="utf-8")
        with pytest.raises(HermesConfigurationError):
            HermesRuntimeAdapter().execute(request)


def test_environment_is_explicitly_allowlisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout, source = _fake_checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("HERMES_TEST_ALLOWED", "visible")
    monkeypatch.setenv("HERMES_TEST_BLOCKED", "secret")
    base_names = HermesRuntimeConfig(
        checkout_root=str(checkout),
        python_executable=sys.executable,
        source=source,
    ).ordinary_env_allowlist
    config = _config(
        checkout,
        source,
        ordinary_env_allowlist=tuple(dict.fromkeys((*base_names, "HERMES_TEST_ALLOWED"))),
    )
    with hermes_runtime_session(
        tool_provider=_provider(),
        control_root=tmp_path / "control",
        workspace=workspace,
        system_prompt="system",
        user_prompt="env",
        config=config,
    ) as request:
        result = HermesRuntimeAdapter().execute(request)
    assert result.status == "completed"
    assert result.response == "visible|"


def test_runtime_request_metadata_is_digest_bound(tmp_path: Path) -> None:
    checkout, source = _fake_checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with hermes_runtime_session(
        tool_provider=_provider(),
        control_root=tmp_path / "control",
        workspace=workspace,
        system_prompt="system",
        user_prompt="hello",
        config=_config(checkout, source),
    ) as request:
        restored = HermesRuntimeRequest.from_metadata(request.to_metadata())
    assert restored.digest == request.digest
    assert restored.gateway.digest == request.gateway.digest


def test_runtime_result_projection_is_self_verifying(tmp_path: Path) -> None:
    result = _execute(tmp_path, "hello")
    restored = HermesRuntimeResult.from_dict(result.to_dict())
    assert restored == result
    assert restored.result_digest in restored.output_digests
