# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

import json
import os
import sys

import pytest
from daedalus.adapters.events import (
    AgentCapabilities, SessionStarted, TextDelta, ToolRequested, ToolCompleted,
    FileRead, CommandOutput, AgentMessage, SessionEnded, TransportRecord,
    event_to_transport_record,
)
from daedalus.adapters import (
    InMemoryTransportSink,
    RuntimeConfig,
    SubprocessAdapter,
    RUNTIME_PROFILES,
)


@pytest.mark.asyncio
async def test_subprocess_adapter_claude_profile():
    adapter = SubprocessAdapter.claude(repo_root=".")
    caps = await adapter.capabilities()
    assert caps.streaming is True
    assert caps.resume is False


@pytest.mark.asyncio
async def test_subprocess_adapter_codex_profile():
    adapter = SubprocessAdapter.codex(repo_root=".")
    caps = await adapter.capabilities()
    assert caps.streaming is True


@pytest.mark.asyncio
async def test_subprocess_adapter_from_name():
    for name in ("claude", "codex"):
        adapter = SubprocessAdapter.from_name(name, repo_root=".")
        caps = await adapter.capabilities()
        assert isinstance(caps, AgentCapabilities)
        assert caps.hidden_state_access is False


def test_runtime_profiles_match_verified_cli_contracts():
    assert set(RUNTIME_PROFILES) == {"claude", "codex"}
    assert "--print" in RUNTIME_PROFILES["claude"].default_args
    assert "exec" in RUNTIME_PROFILES["codex"].default_args
    assert "--json" in RUNTIME_PROFILES["codex"].default_args


def test_from_name_unknown_raises():
    with pytest.raises(ValueError, match="Unknown or unverified runtime"):
        SubprocessAdapter.from_name("antigravity")


@pytest.mark.asyncio
async def test_custom_adapter_honors_session_cwd_and_reports_exit(tmp_path):
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    script = (
        "import json,os,sys;"
        "print(json.dumps({'type':'message','content':os.getcwd()+'|'+sys.argv[1]}))"
    )
    sink = InMemoryTransportSink()
    adapter = SubprocessAdapter(
        RuntimeConfig(
            command=sys.executable,
            default_args=("-c", script),
            prompt_mode="argument",
        ),
        repo_root=str(tmp_path),
        sink=sink,
        runtime_name="test-runtime",
    )
    session_id = await adapter.create_session(
        {"cwd": str(worktree), "prompt": "hello"}
    )
    events = [event async for event in adapter.events(session_id)]
    await adapter.terminate(session_id)

    message = next(event for event in events if isinstance(event, AgentMessage))
    ended = next(event for event in events if isinstance(event, SessionEnded))
    cwd, prompt = message.content.rsplit("|", 1)
    assert os.path.normcase(cwd) == os.path.normcase(str(worktree.resolve()))
    assert prompt == "hello"
    assert ended.exit_code == 0
    assert [record.direction for record in sink.records] == [
        "input",
        "system",
        "output",
        "system",
    ]
    assert all(record.runtime == "test-runtime" for record in sink.records)
    assert sink.records[0].content == "hello"


def test_transport_record_round_trip_preserves_payload_and_provenance():
    event = ToolRequested(
        tool_name="read_file",
        arguments={"path": "src/core.py"},
        call_id="call-1",
    )
    record = event_to_transport_record(
        event,
        session_id="session-1",
        runtime="custom",
        direction="output",
        sequence=7,
        metadata={"cwd": "C:/repo"},
    )

    restored = TransportRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.payload["arguments"] == {"path": "src/core.py"}
    assert restored.metadata["cwd"] == "C:/repo"
    assert "read_file" in restored.embedding_text()


def test_events_dataclasses():
    started = SessionStarted(session_id="123")
    assert started.session_id == "123"

    delta = TextDelta(text="hello")
    assert delta.text == "hello"

    requested = ToolRequested(tool_name="test", arguments={"a": 1}, call_id="c1")
    assert requested.tool_name == "test"
    assert requested.arguments == {"a": 1}
    assert requested.call_id == "c1"


# ---------------------------------------------------------------------------
# Gate-0 central effect boundary: the adapter family is centrally wired.
# These tests are the family's fail-closed and mutation probes: deleting the
# begin_effect call in any of the four entrypoints turns them red.
# ---------------------------------------------------------------------------

def _spawnless_adapter(tmp_path, **kw):
    return SubprocessAdapter(
        RuntimeConfig(
            command=sys.executable,
            default_args=("-c", "print('unused')"),
            prompt_mode="argument",
        ),
        repo_root=str(tmp_path),
        **kw,
    )


@pytest.mark.asyncio
async def test_create_session_is_refused_fail_closed_without_the_guard_contract(
    tmp_path, monkeypatch
):
    from daedalus.spine import effect_boundary
    from daedalus.spine.effect_boundary import EffectStartRefused

    adapter = _spawnless_adapter(tmp_path)
    monkeypatch.setattr(
        effect_boundary,
        "GUARD_CONTRACT_IMPLEMENTED",
        {name: False for name in effect_boundary.GUARD_CONTRACT_IMPLEMENTED},
    )
    with pytest.raises(EffectStartRefused):
        await adapter.create_session({"prompt": "hello"})
    assert adapter._sessions == {}, "a refused start must not track a session"


@pytest.mark.asyncio
async def test_create_session_is_refused_when_the_profile_decision_denies(
    tmp_path, monkeypatch
):
    from daedalus.spine.effect_boundary import EffectStartRefused, GuardDecision

    adapter = _spawnless_adapter(tmp_path)
    monkeypatch.setattr(
        adapter,
        "_adapter_profile_decision",
        lambda **_kw: GuardDecision(
            "runtime.adapter_profile", False, "launch contract failed"
        ),
    )
    with pytest.raises(EffectStartRefused, match="denied by runtime.adapter_profile"):
        await adapter.create_session({"prompt": "hello"})
    assert adapter._sessions == {}


@pytest.mark.asyncio
async def test_create_session_retains_a_boundary_receipt_on_the_valid_chain(tmp_path):
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    adapter = SubprocessAdapter(
        RuntimeConfig(
            command=sys.executable,
            default_args=("-c", "print('{}')"),
            prompt_mode="argument",
        ),
        repo_root=str(tmp_path),
    )
    session_id = await adapter.create_session({"cwd": str(worktree)})
    try:
        receipt = adapter._effect_receipts[session_id]
        assert receipt.entrypoint_id == "adapter.subprocess"
        assert receipt.guard_decisions[0].contract == "runtime.adapter_profile"
        assert "explicit-config" in receipt.guard_decisions[0].evidence
    finally:
        await adapter.terminate(session_id)
    assert session_id not in adapter._effect_receipts


@pytest.mark.asyncio
async def test_control_methods_refuse_fail_closed_and_leave_the_session_tracked(
    tmp_path, monkeypatch
):
    from daedalus.spine import effect_boundary
    from daedalus.spine.effect_boundary import EffectStartRefused

    worktree = tmp_path / "candidate"
    worktree.mkdir()
    script = "import time; time.sleep(30)"
    adapter = SubprocessAdapter(
        RuntimeConfig(
            command=sys.executable,
            default_args=("-c", script),
            prompt_mode="none",
            close_stdin_after_prompt=False,
        ),
        repo_root=str(tmp_path),
    )
    session_id = await adapter.create_session({"cwd": str(worktree)})
    try:
        monkeypatch.setattr(
            effect_boundary,
            "GUARD_CONTRACT_IMPLEMENTED",
            {name: False for name in effect_boundary.GUARD_CONTRACT_IMPLEMENTED},
        )
        with pytest.raises(EffectStartRefused):
            await adapter.send(session_id, "ping")
        with pytest.raises(EffectStartRefused):
            await adapter.interrupt(session_id)
        with pytest.raises(EffectStartRefused):
            await adapter.terminate(session_id)
        assert session_id in adapter._sessions, (
            "a refused terminate must not silently drop the tracked session"
        )
    finally:
        monkeypatch.undo()
        await adapter.terminate(session_id)
