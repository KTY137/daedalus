"""Pinned one-shot Hermes process behind Daedalus-authenticated metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Mapping

from .configuration import (
    HERMES_PROTOCOL_SCHEMA,
    HermesConfigurationError,
    HermesRuntimeConfig,
    build_sanitized_environment,
    ensure_disjoint_roots,
    verify_hermes_checkout,
)
from .context_provider import ExplicitContextProvider
from .event_adapter import HermesEventError, HermesEventLedger
from .memory_provider import ReadOnlyMemoryProvider
from .protocol import HermesProtocolError, canonical_sha256, read_message, write_message
from .tool_gateway import HermesGatewayDescriptor, HermesToolGatewayClient, HermesToolGatewayError
from .tool_provider import ToolSpec

RUNTIME_REQUEST_SCHEMA = "daedalus-hermes-runtime-request/1"
RUNTIME_RESULT_SCHEMA = "daedalus-hermes-runtime-result/1"


class HermesRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesRuntimeRequest:
    request_id: str
    task_id: str
    workspace: str
    system_prompt: str
    user_prompt: str
    config: HermesRuntimeConfig
    context: ExplicitContextProvider
    memory: ReadOnlyMemoryProvider
    tools: tuple[ToolSpec, ...]
    gateway: HermesGatewayDescriptor
    cancellation_marker: str = ""

    def __post_init__(self) -> None:
        if not self.request_id or not self.task_id:
            raise HermesRuntimeError("Hermes request identity is required")
        if not self.workspace or not isinstance(self.system_prompt, str) or not isinstance(self.user_prompt, str):
            raise HermesRuntimeError("Hermes workspace and prompts are required")
        if self.gateway.request_id != self.request_id or self.gateway.task_id != self.task_id:
            raise HermesRuntimeError("Hermes gateway and runtime request identities differ")
        expected_scope = canonical_sha256([tool.to_dict() for tool in sorted(self.tools, key=lambda item: item.name)])
        if self.gateway.tool_scope_digest != expected_scope:
            raise HermesRuntimeError("Hermes gateway tool scope does not match the runtime request")

    @property
    def digest(self) -> str:
        return canonical_sha256(self._unsigned_metadata())

    def _unsigned_metadata(self) -> dict[str, object]:
        return {
            "schema": RUNTIME_REQUEST_SCHEMA,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "workspace": self.workspace,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "config": self.config.to_metadata(),
            "context": self.context.to_metadata(),
            "memory": self.memory.to_metadata(),
            "tools": [tool.to_dict() for tool in self.tools],
            "gateway": self.gateway.to_dict(),
            "cancellation_marker": self.cancellation_marker,
        }

    def to_metadata(self) -> dict[str, object]:
        value = self._unsigned_metadata()
        value["digest"] = self.digest
        return value

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> "HermesRuntimeRequest":
        exact = {
            "schema",
            "request_id",
            "task_id",
            "workspace",
            "system_prompt",
            "user_prompt",
            "config",
            "context",
            "memory",
            "tools",
            "gateway",
            "cancellation_marker",
            "digest",
        }
        if set(value) != exact or value["schema"] != RUNTIME_REQUEST_SCHEMA:
            raise HermesRuntimeError("Hermes runtime request metadata is not exact")
        config = value["config"]
        context = value["context"]
        memory = value["memory"]
        tools = value["tools"]
        gateway = value["gateway"]
        if not all(isinstance(item, Mapping) for item in (config, context, memory, gateway)):
            raise HermesRuntimeError("Hermes runtime request contains non-object records")
        if not isinstance(tools, list) or any(not isinstance(item, Mapping) for item in tools):
            raise HermesRuntimeError("Hermes runtime request tools must be object records")
        request = cls(
            request_id=str(value["request_id"]),
            task_id=str(value["task_id"]),
            workspace=str(value["workspace"]),
            system_prompt=str(value["system_prompt"]),
            user_prompt=str(value["user_prompt"]),
            config=HermesRuntimeConfig.from_metadata(config),
            context=ExplicitContextProvider.from_metadata(context),
            memory=ReadOnlyMemoryProvider.from_metadata(memory),
            tools=tuple(ToolSpec.from_dict(item) for item in tools),
            gateway=HermesGatewayDescriptor.from_dict(gateway),
            cancellation_marker=str(value["cancellation_marker"]),
        )
        if value["digest"] != request.digest:
            raise HermesRuntimeError("Hermes runtime request digest mismatch")
        return request


@dataclass(frozen=True)
class HermesRuntimeResult:
    request_id: str
    task_id: str
    status: str
    response: str
    messages_digest: str
    event_digest: str
    checkout_digest: str
    stderr_digest: str
    tool_call_count: int
    observation_digests: tuple[str, ...]
    receipt_digests: tuple[str, ...]
    invocation_digests: tuple[str, ...]
    terminal_error_type: str = ""
    schema: str = RUNTIME_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RUNTIME_RESULT_SCHEMA:
            raise HermesRuntimeError("Hermes runtime result schema mismatch")
        if self.status not in {
            "completed",
            "failed",
            "cancelled",
            "timed_out",
            "protocol_error",
            "process_error",
        }:
            raise HermesRuntimeError("unknown Hermes runtime status")
        for digest in (
            self.messages_digest,
            self.event_digest,
            self.checkout_digest,
            self.stderr_digest,
            *self.observation_digests,
            *self.receipt_digests,
            *self.invocation_digests,
        ):
            if not isinstance(digest, str) or len(digest) != 64:
                raise HermesRuntimeError("Hermes runtime result contains a non-SHA256 digest")

    @property
    def result_digest(self) -> str:
        return canonical_sha256(self._unsigned())

    @property
    def output_digests(self) -> tuple[str, ...]:
        values = {
            self.result_digest,
            canonical_sha256({"response": self.response}),
            self.messages_digest,
            self.event_digest,
            self.checkout_digest,
            self.stderr_digest,
            *self.observation_digests,
            *self.receipt_digests,
            *self.invocation_digests,
        }
        return tuple(sorted(values))

    def _unsigned(self) -> dict[str, object]:
        value = asdict(self)
        value["observation_digests"] = list(self.observation_digests)
        value["receipt_digests"] = list(self.receipt_digests)
        value["invocation_digests"] = list(self.invocation_digests)
        return value

    def to_dict(self) -> dict[str, object]:
        value = self._unsigned()
        value["result_digest"] = self.result_digest
        value["output_digests"] = list(self.output_digests)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HermesRuntimeResult":
        exact = {
            "schema",
            "request_id",
            "task_id",
            "status",
            "response",
            "messages_digest",
            "event_digest",
            "checkout_digest",
            "stderr_digest",
            "tool_call_count",
            "observation_digests",
            "receipt_digests",
            "invocation_digests",
            "terminal_error_type",
            "result_digest",
            "output_digests",
        }
        if set(value) != exact:
            raise HermesRuntimeError("Hermes runtime result fields are not exact")
        for name in ("observation_digests", "receipt_digests", "invocation_digests", "output_digests"):
            if not isinstance(value[name], list) or any(not isinstance(item, str) for item in value[name]):
                raise HermesRuntimeError(f"{name} must be a digest list")
        result = cls(
            schema=str(value["schema"]),
            request_id=str(value["request_id"]),
            task_id=str(value["task_id"]),
            status=str(value["status"]),
            response=str(value["response"]),
            messages_digest=str(value["messages_digest"]),
            event_digest=str(value["event_digest"]),
            checkout_digest=str(value["checkout_digest"]),
            stderr_digest=str(value["stderr_digest"]),
            tool_call_count=int(value["tool_call_count"]),
            observation_digests=tuple(value["observation_digests"]),
            receipt_digests=tuple(value["receipt_digests"]),
            invocation_digests=tuple(value["invocation_digests"]),
            terminal_error_type=str(value["terminal_error_type"]),
        )
        if value["result_digest"] != result.result_digest or tuple(value["output_digests"]) != result.output_digests:
            raise HermesRuntimeError("Hermes runtime result digest projection mismatch")
        return result


class _BoundedStderr:
    def __init__(self, stream: object, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._digest = sha256()
        self._count = 0
        self._thread = threading.Thread(target=self._consume, name="daedalus-hermes-stderr", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _consume(self) -> None:
        stream = self._stream
        while True:
            chunk = stream.read(64 * 1024)  # type: ignore[attr-defined]
            if not chunk:
                return
            self._count += len(chunk)
            if self._count <= self._limit:
                self._digest.update(chunk)
            elif self._count - len(chunk) < self._limit:
                self._digest.update(chunk[: self._limit - (self._count - len(chunk))])

    def finish(self) -> str:
        self._thread.join(timeout=2.0)
        self._digest.update(f"\nbytes={self._count}".encode("ascii"))
        return self._digest.hexdigest()


class HermesRuntimeAdapter:
    def __init__(self, *, git_executable: str = "git") -> None:
        self._git_executable = git_executable

    @staticmethod
    def _worker_command(config: HermesRuntimeConfig) -> list[str]:
        package_root = Path(__file__).resolve().parents[3]
        bootstrap = (
            "import runpy,sys;"
            f"sys.path.insert(0,{str(package_root)!r});"
            "runpy.run_module('daedalus.integrations.hermes.worker',run_name='__main__')"
        )
        return [*config.sandbox.command_prefix, config.python_executable, "-I", "-c", bootstrap]

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    @staticmethod
    def _stdout_reader(stream: object, target: "queue.Queue[object]") -> None:
        try:
            while True:
                target.put(read_message(stream))  # type: ignore[arg-type]
        except EOFError:
            target.put(EOFError("Hermes worker stdout closed"))
        except BaseException as exc:
            target.put(exc)

    def execute(self, request: HermesRuntimeRequest) -> HermesRuntimeResult:
        checkout = verify_hermes_checkout(
            request.config.checkout_root,
            source=request.config.source,
            git_executable=self._git_executable,
        )
        workspace = Path(request.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise HermesRuntimeError("Hermes workspace is not a directory")
        runtime_root = Path(tempfile.mkdtemp(prefix="daedalus-hermes-runtime-"))
        process: subprocess.Popen[bytes] | None = None
        gateway_client: HermesToolGatewayClient | None = None
        stderr_reader: _BoundedStderr | None = None
        stderr_digest = canonical_sha256({"stderr": "not-started"})
        ledger = HermesEventLedger()
        observations: list[str] = []
        receipts: list[str] = []
        invocations: list[str] = []
        status = "process_error"
        response = ""
        messages_digest = canonical_sha256([])
        tool_call_count = 0
        terminal_error_type = ""
        try:
            ensure_disjoint_roots(request.config.checkout_root, workspace, runtime_root)
            environment = build_sanitized_environment(request.config, runtime_root=runtime_root)
            environment["DAEDALUS_HERMES_CHECKOUT"] = checkout.checkout_root
            command = self._worker_command(request.config)
            creationflags = 0
            popen_options: dict[str, object] = {}
            if os.name == "nt":
                creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            else:
                popen_options["start_new_session"] = True
            gateway_client = HermesToolGatewayClient(
                request.gateway,
                timeout_seconds=min(30.0, request.config.sandbox.max_wall_seconds),
            )
            gateway_client.connect()
            process = subprocess.Popen(
                command,
                cwd=str(workspace),
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                **popen_options,
            )
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            stderr_reader = _BoundedStderr(process.stderr, request.config.sandbox.max_output_bytes)
            stderr_reader.start()
            combined_system = "\n\n".join(
                section
                for section in (
                    request.system_prompt,
                    request.context.render(),
                    request.memory.render(),
                )
                if section
            )
            run_request = {
                "schema": HERMES_PROTOCOL_SCHEMA,
                "type": "run_request",
                "request_id": request.request_id,
                "task_id": request.task_id,
                "sequence": 0,
                "system_prompt": combined_system,
                "user_prompt": request.user_prompt,
                "model": request.config.model,
                "provider": request.config.provider,
                "base_url": request.config.base_url,
                "api_key_env": request.config.api_key_env,
                "max_iterations": request.config.sandbox.max_iterations,
                "max_wall_seconds": request.config.sandbox.max_wall_seconds,
                "max_tool_calls": request.config.sandbox.max_tool_calls,
                "tool_definitions": [tool.to_definition() for tool in request.tools],
                "context_digest": request.context.digest,
                "memory_digest": request.memory.digest,
                "workspace": str(workspace),
                "checkout_digest": checkout.digest,
                "run_agent_sha256": checkout.run_agent_sha256,
                "source_commit": checkout.commit,
            }
            write_message(process.stdin, run_request)
            output_queue: queue.Queue[object] = queue.Queue()
            stdout_thread = threading.Thread(
                target=self._stdout_reader,
                args=(process.stdout, output_queue),
                name="daedalus-hermes-stdout",
                daemon=True,
            )
            stdout_thread.start()
            deadline = time.monotonic() + request.config.sandbox.max_wall_seconds
            while True:
                if request.cancellation_marker and Path(request.cancellation_marker).exists():
                    status = "cancelled"
                    terminal_error_type = "CancellationRequested"
                    self._terminate(process)
                    break
                if time.monotonic() >= deadline:
                    status = "timed_out"
                    terminal_error_type = "TimeoutExpired"
                    self._terminate(process)
                    break
                try:
                    item = output_queue.get(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    if process.poll() is not None and output_queue.empty():
                        status = "process_error"
                        terminal_error_type = "WorkerExitedWithoutTerminalEvent"
                        break
                    continue
                if isinstance(item, BaseException):
                    if isinstance(item, EOFError) and ledger.terminal:
                        break
                    status = "protocol_error" if isinstance(item, (HermesProtocolError, HermesEventError)) else "process_error"
                    terminal_error_type = type(item).__name__
                    self._terminate(process)
                    break
                assert isinstance(item, Mapping)
                message = dict(item)
                message_type = str(message["type"])
                if message["request_id"] != request.request_id or message["task_id"] != request.task_id:
                    raise HermesProtocolError("Hermes worker task identity drifted")
                ledger.append_message(message)
                if message_type == "worker_started":
                    if message["checkout_digest"] != checkout.digest:
                        raise HermesProtocolError("Hermes worker checkout evidence drifted")
                    continue
                if message_type == "tool_call":
                    outcome = gateway_client.invoke(
                        call_id=str(message["call_id"]),
                        name=str(message["name"]),
                        arguments=message["arguments"],  # type: ignore[arg-type]
                    )
                    observations.append(outcome.observation_digest)
                    receipts.append(outcome.receipt_digest)
                    invocations.append(outcome.invocation_digest)
                    result_message = {
                        "schema": HERMES_PROTOCOL_SCHEMA,
                        "type": "tool_result",
                        "request_id": request.request_id,
                        "task_id": request.task_id,
                        "sequence": len(ledger.events),
                        "call_id": str(message["call_id"]),
                        "name": str(message["name"]),
                        **outcome.to_dict(),
                    }
                    ledger.append_message(result_message)
                    write_message(process.stdin, result_message)
                    continue
                if message_type == "final":
                    status = "completed"
                    response = str(message["response"])
                    messages_digest = str(message["messages_digest"])
                    tool_call_count = int(message["tool_call_count"])
                    break
                if message_type == "failure":
                    status = "failed"
                    terminal_error_type = str(message["error_type"])
                    break
            if process.poll() is None:
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._terminate(process)
            if status == "completed" and process.returncode not in {0, None}:
                status = "process_error"
                terminal_error_type = "NonZeroExitAfterFinal"
                response = ""
        except (HermesConfigurationError, HermesRuntimeError, HermesToolGatewayError, HermesProtocolError, HermesEventError) as exc:
            status = "protocol_error"
            terminal_error_type = type(exc).__name__
            if process is not None:
                self._terminate(process)
        except BaseException as exc:
            status = "process_error"
            terminal_error_type = type(exc).__name__
            if process is not None:
                self._terminate(process)
        finally:
            if gateway_client is not None:
                gateway_client.close()
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
            if stderr_reader is not None:
                stderr_digest = stderr_reader.finish()
            shutil.rmtree(runtime_root, ignore_errors=True)
        return HermesRuntimeResult(
            request_id=request.request_id,
            task_id=request.task_id,
            status=status,
            response=response,
            messages_digest=messages_digest,
            event_digest=ledger.digest,
            checkout_digest=checkout.digest,
            stderr_digest=stderr_digest,
            tool_call_count=tool_call_count,
            observation_digests=tuple(observations),
            receipt_digests=tuple(receipts),
            invocation_digests=tuple(invocations),
            terminal_error_type=terminal_error_type,
        )


def execute_from_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    request = HermesRuntimeRequest.from_metadata(metadata)
    return HermesRuntimeAdapter().execute(request).to_dict()
