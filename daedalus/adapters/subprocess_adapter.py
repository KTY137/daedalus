"""Subprocess transport for explicitly configured, non-interactive agent CLIs.

This is a process/event normalization layer, not a universal agent protocol:
each CLI still needs a verified command profile and provider-specific event
parser.  Built-in profiles are limited to CLIs whose local ``--help`` contract
is exercised by tests and whose execution is one-shot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Literal

from .base import AgentAdapter
from .events import (
    AgentCapabilities,
    AgentEvent,
    AgentMessage,
    CommandOutput,
    SessionEnded,
    SessionStarted,
    TextDelta,
    ToolCompleted,
    ToolRequested,
    event_to_transport_record,
)
from .transport import TransportSink

logger = logging.getLogger(__name__)

PromptMode = Literal["argument", "stdin", "none"]


@dataclass(frozen=True)
class RuntimeConfig:
    """Verified process-launch contract for one CLI runtime."""

    command: str
    default_args: tuple[str, ...] = ()
    streaming: bool = True
    resume: bool = False
    hidden_state_access: bool = False
    output_format: str = "jsonl"  # jsonl | text
    prompt_mode: PromptMode = "argument"
    stdin_prompt_marker: str | None = None
    cwd_arg: str | None = None
    model_arg: str | None = None
    close_stdin_after_prompt: bool = True
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 600


# These profiles describe one-shot, non-interactive invocations.  Antigravity
# isn't listed: no ``agy`` executable or stable JSON protocol exists on this
# machine, and a desktop/IDE session does not imply a callable CLI contract.
RUNTIME_PROFILES: dict[str, RuntimeConfig] = {
    "claude": RuntimeConfig(
        command="claude",
        default_args=(
            "--print",
            "--verbose",
            "--input-format",
            "text",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "dontAsk",
        ),
        output_format="jsonl",
        prompt_mode="stdin",
        model_arg="--model",
    ),
    "codex": RuntimeConfig(
        command="codex",
        default_args=(
            "exec",
            "--json",
            "--ask-for-approval",
            "never",
            "--sandbox",
            "workspace-write",
        ),
        output_format="jsonl",
        prompt_mode="stdin",
        stdin_prompt_marker="-",
        cwd_arg="-C",
        model_arg="--model",
    ),
}


@dataclass
class _Session:
    process: asyncio.subprocess.Process
    cwd: Path
    stderr_task: asyncio.Task[bytes]
    started_at: float
    timeout_s: int


class SubprocessAdapter(AgentAdapter):
    """Run a configured CLI in a bounded working directory and normalize output."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        repo_root: str | None = None,
        timeout_s: int = 600,
        sink: TransportSink | None = None,
        runtime_name: str | None = None,
    ):
        if config is not None:
            self._config = config
        elif command:
            self._config = RuntimeConfig(
                command=command,
                default_args=tuple(args or ()),
                timeout_s=timeout_s,
            )
        else:
            raise ValueError("Either config or command must be provided")

        root = Path(repo_root or os.getcwd()).resolve()
        if not root.is_dir():
            raise ValueError(f"repo_root is not a directory: {root}")
        self._repo_root = root
        self._sessions: dict[str, _Session] = {}
        self._sink = sink
        self._runtime_name = runtime_name or Path(self._config.command).stem
        self._sequences: dict[str, int] = {}

    @classmethod
    def claude(cls, repo_root: str | None = None, **kw: Any) -> "SubprocessAdapter":
        return cls(config=RUNTIME_PROFILES["claude"], repo_root=repo_root, **kw)

    @classmethod
    def codex(cls, repo_root: str | None = None, **kw: Any) -> "SubprocessAdapter":
        return cls(config=RUNTIME_PROFILES["codex"], repo_root=repo_root, **kw)

    @classmethod
    def from_name(
        cls,
        name: str,
        repo_root: str | None = None,
        **kw: Any,
    ) -> "SubprocessAdapter":
        profile = RUNTIME_PROFILES.get(name)
        if profile is None:
            raise ValueError(
                f"Unknown or unverified runtime {name!r}. "
                f"Verified profiles: {sorted(RUNTIME_PROFILES)}. "
                "Pass an explicit RuntimeConfig for a custom CLI."
            )
        return cls(config=profile, repo_root=repo_root, **kw)

    async def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            streaming=self._config.streaming,
            resume=self._config.resume,
            hidden_state_access=False,
        )

    async def create_session(self, config: Dict[str, Any]) -> str:
        cwd = Path(config.get("cwd") or self._repo_root).resolve()
        if not cwd.is_dir():
            raise ValueError(f"session cwd is not a directory: {cwd}")

        prompt = str(config.get("prompt") or "")
        model = config.get("model")
        extra_args = [str(value) for value in config.get("args", ())]
        timeout_s = int(config.get("timeout_s") or self._config.timeout_s)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

        cmd = [self._config.command, *self._config.default_args]
        if model:
            if not self._config.model_arg:
                raise ValueError(f"{self._config.command} profile has no model option")
            cmd.extend([self._config.model_arg, str(model)])
        if self._config.cwd_arg:
            cmd.extend([self._config.cwd_arg, str(cwd)])
        cmd.extend(extra_args)

        if prompt and self._config.prompt_mode == "argument":
            cmd.append(prompt)
        elif self._config.prompt_mode == "stdin" and self._config.stdin_prompt_marker:
            cmd.append(self._config.stdin_prompt_marker)
        elif prompt and self._config.prompt_mode == "none":
            raise ValueError(f"{self._config.command} profile does not accept a prompt")

        session_id = f"{Path(self._config.command).stem}_{uuid.uuid4().hex[:8]}"
        env = {**os.environ, **self._config.env}
        logger.info("[%s] spawning %s in %s", session_id, cmd[0], cwd)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
        assert process.stderr is not None
        session = _Session(
            process=process,
            cwd=cwd,
            stderr_task=asyncio.create_task(process.stderr.read()),
            started_at=time.monotonic(),
            timeout_s=timeout_s,
        )
        self._sessions[session_id] = session
        self._sequences[session_id] = 0

        if prompt and self._config.prompt_mode == "stdin":
            await self._publish(
                session_id,
                AgentMessage(content=prompt, role="user"),
                direction="input",
            )
            await self._write_stdin(session_id, prompt)
            if self._config.close_stdin_after_prompt and process.stdin:
                process.stdin.close()
        elif prompt:
            await self._publish(
                session_id,
                AgentMessage(content=prompt, role="user"),
                direction="input",
            )
        return session_id

    async def _write_stdin(self, session_id: str, text: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.process.stdin is None:
            raise RuntimeError(f"session {session_id} not found or stdin unavailable")
        if session.process.stdin.is_closing():
            raise RuntimeError(f"session {session_id} stdin is closed")
        session.process.stdin.write((text + "\n").encode("utf-8"))
        await session.process.stdin.drain()

    async def send(self, session_id: str, message: Any) -> None:
        text = message if isinstance(message, str) else json.dumps(message)
        await self._publish(
            session_id,
            AgentMessage(content=text, role="user"),
            direction="input",
        )
        await self._write_stdin(session_id, text)

    async def _publish(
        self,
        session_id: str,
        event: AgentEvent,
        *,
        direction: str,
    ) -> None:
        if self._sink is None:
            return
        sequence = self._sequences.get(session_id, 0)
        self._sequences[session_id] = sequence + 1
        record = event_to_transport_record(
            event,
            session_id=session_id,
            runtime=self._runtime_name,
            direction=direction,
            sequence=sequence,
            metadata={"cwd": str(self._sessions[session_id].cwd)},
        )
        await self._sink.publish(record)

    async def events(self, session_id: str) -> AsyncIterator[AgentEvent]:
        session = self._sessions.get(session_id)
        if session is None or session.process.stdout is None:
            raise RuntimeError(f"session {session_id} not found")

        process = session.process
        started = SessionStarted(session_id=session_id)
        await self._publish(session_id, started, direction="system")
        yield started

        while True:
            remaining = session.timeout_s - (time.monotonic() - session.started_at)
            if remaining <= 0:
                await self._stop_process(process)
                raise TimeoutError(
                    f"session {session_id} exceeded {session.timeout_s} seconds"
                )
            try:
                raw_line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=remaining,
                )
            except asyncio.TimeoutError as exc:
                await self._stop_process(process)
                raise TimeoutError(
                    f"session {session_id} exceeded {session.timeout_s} seconds"
                ) from exc
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            event = self._parse_line(line)
            if event is not None:
                await self._publish(session_id, event, direction="output")
                yield event

        exit_code = await process.wait()
        stderr = (await session.stderr_task).decode("utf-8", errors="replace").strip()
        ended = SessionEnded(
            session_id=session_id,
            exit_code=exit_code,
            stderr=stderr[-4000:],
        )
        await self._publish(session_id, ended, direction="system")
        yield ended

    def _parse_line(self, line: str) -> AgentEvent | None:
        if self._config.output_format == "text":
            return TextDelta(text=line)
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return TextDelta(text=line)
        if not isinstance(data, dict):
            return TextDelta(text=str(data))

        event_type = str(data.get("type") or data.get("event") or "")
        if event_type:
            return self._parse_typed_event(data, event_type)
        if "result" in data:
            return AgentMessage(content=str(data["result"]))
        if "content" in data:
            return TextDelta(text=str(data["content"]))
        return TextDelta(text=json.dumps(data))

    def _parse_typed_event(self, data: dict[str, Any], event_type: str) -> AgentEvent | None:
        if event_type in ("text", "content_block_delta", "assistant_text"):
            text = data.get("text") or (data.get("delta") or {}).get("text", "")
            return TextDelta(text=str(text)) if text else None

        if event_type == "assistant":
            message = data.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                text = "".join(
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                return AgentMessage(content=text) if text else TextDelta(text=json.dumps(data))

        if event_type in ("result", "turn.completed"):
            content = data.get("result") or data.get("message") or data.get("usage") or data
            return AgentMessage(content=content if isinstance(content, str) else json.dumps(content))

        if event_type in ("tool_use", "tool_call", "tool_requested"):
            return ToolRequested(
                tool_name=str(data.get("name") or data.get("tool_name") or "unknown"),
                arguments=data.get("input") or data.get("arguments") or {},
                call_id=str(data.get("id") or data.get("call_id") or ""),
            )

        if event_type in ("tool_result", "tool_completed"):
            return ToolCompleted(
                call_id=str(data.get("id") or data.get("call_id") or ""),
                result=data.get("content") or data.get("result"),
                is_error=bool(data.get("is_error", False)),
            )

        if event_type in ("bash", "command", "shell", "command_execution"):
            return CommandOutput(
                command=str(data.get("command") or data.get("input") or ""),
                output=str(data.get("output") or data.get("stdout") or ""),
                exit_code=int(data.get("exit_code") or 0),
            )

        if event_type in ("message", "assistant_message", "response"):
            content = data.get("content") or data.get("text") or ""
            return AgentMessage(content=str(content))

        # Lifecycle events are still observable, but aren't misrepresented as
        # text generated by the model.
        return AgentMessage(content=json.dumps(data), role="system")

    async def approve(self, session_id: str, call_id: str, result: Any = None) -> None:
        raise NotImplementedError(
            "one-shot CLI profiles do not expose a portable approval protocol"
        )

    async def reject(self, session_id: str, call_id: str, reason: str) -> None:
        raise NotImplementedError(
            "one-shot CLI profiles do not expose a portable approval protocol"
        )

    async def interrupt(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session and session.process.returncode is None:
            try:
                session.process.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                return

    @staticmethod
    async def _stop_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except (ProcessLookupError, OSError):
            return

    async def terminate(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        self._sequences.pop(session_id, None)
        if session is None:
            return
        await self._stop_process(session.process)
        if not session.stderr_task.done():
            try:
                await asyncio.wait_for(session.stderr_task, timeout=1)
            except asyncio.TimeoutError:
                session.stderr_task.cancel()
