"""One-shot loopback bridge from a sealed Hermes operation to Daedalus tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import threading
import time
from typing import Mapping

from .tool_provider import DaedalusToolProvider, ToolOutcome, canonical_sha256

GATEWAY_SCHEMA = "daedalus-hermes-tool-gateway/1"
_MAX_FRAME_BYTES = 2 * 1024 * 1024


class HermesToolGatewayError(RuntimeError):
    pass


def _send_frame(sock: socket.socket, value: Mapping[str, object]) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_FRAME_BYTES:
        raise HermesToolGatewayError("gateway frame exceeds the byte limit")
    sock.sendall(struct.pack("!I", len(encoded)) + encoded)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("gateway connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock: socket.socket) -> dict[str, object]:
    header = _read_exact(sock, 4)
    (size,) = struct.unpack("!I", header)
    if size <= 0 or size > _MAX_FRAME_BYTES:
        raise HermesToolGatewayError("gateway frame length is invalid")
    try:
        value = json.loads(_read_exact(sock, size).decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HermesToolGatewayError("gateway frame is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != GATEWAY_SCHEMA:
        raise HermesToolGatewayError("gateway schema mismatch")
    return value


@dataclass(frozen=True)
class HermesGatewayDescriptor:
    host: str
    port: int
    token_file: str
    request_id: str
    task_id: str
    tool_scope_digest: str
    max_calls: int
    expires_at_ns: int
    digest: str
    schema: str = GATEWAY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GATEWAY_SCHEMA or self.host not in {"127.0.0.1", "::1"}:
            raise HermesToolGatewayError("gateway descriptor is not loopback-only")
        if not 1 <= self.port <= 65535 or not 0 <= self.max_calls <= 4096:
            raise HermesToolGatewayError("gateway descriptor bounds are invalid")
        if not self.request_id or not self.task_id or len(self.tool_scope_digest) != 64:
            raise HermesToolGatewayError("gateway descriptor identity is incomplete")
        expected = canonical_sha256(self._unsigned())
        if self.digest != expected:
            raise HermesToolGatewayError("gateway descriptor digest mismatch")

    def _unsigned(self) -> dict[str, object]:
        return {"schema": self.schema, "host": self.host, "port": self.port, "token_file": self.token_file, "request_id": self.request_id, "task_id": self.task_id, "tool_scope_digest": self.tool_scope_digest, "max_calls": self.max_calls, "expires_at_ns": self.expires_at_ns}

    def to_dict(self) -> dict[str, object]:
        value = self._unsigned()
        value["digest"] = self.digest
        return value

    @classmethod
    def create(cls, *, host: str, port: int, token_file: str, request_id: str, task_id: str, tool_scope_digest: str, max_calls: int, expires_at_ns: int) -> "HermesGatewayDescriptor":
        unsigned = {"schema": GATEWAY_SCHEMA, "host": host, "port": port, "token_file": token_file, "request_id": request_id, "task_id": task_id, "tool_scope_digest": tool_scope_digest, "max_calls": max_calls, "expires_at_ns": expires_at_ns}
        return cls(**unsigned, digest=canonical_sha256(unsigned))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HermesGatewayDescriptor":
        exact = {"schema", "host", "port", "token_file", "request_id", "task_id", "tool_scope_digest", "max_calls", "expires_at_ns", "digest"}
        if set(value) != exact:
            raise HermesToolGatewayError("gateway descriptor fields are not exact")
        return cls(schema=str(value["schema"]), host=str(value["host"]), port=int(value["port"]), token_file=str(value["token_file"]), request_id=str(value["request_id"]), task_id=str(value["task_id"]), tool_scope_digest=str(value["tool_scope_digest"]), max_calls=int(value["max_calls"]), expires_at_ns=int(value["expires_at_ns"]), digest=str(value["digest"]))


class HermesToolGatewayServer:
    def __init__(self, provider: DaedalusToolProvider, *, control_root: str | Path, lifetime_seconds: float = 900.0) -> None:
        if not 0.5 <= lifetime_seconds <= 86_400:
            raise HermesToolGatewayError("gateway lifetime is outside the accepted range")
        self._provider = provider
        self._control_root = Path(control_root).expanduser().resolve(strict=False)
        self._lifetime_seconds = lifetime_seconds
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._descriptor: HermesGatewayDescriptor | None = None
        self._token_file: Path | None = None
        self._failure_type = ""
        self._closed = threading.Event()

    @property
    def descriptor(self) -> HermesGatewayDescriptor:
        if self._descriptor is None:
            raise HermesToolGatewayError("gateway has not been started")
        return self._descriptor

    @property
    def failure_type(self) -> str:
        return self._failure_type

    def start(self, *, max_calls: int) -> HermesGatewayDescriptor:
        if self._listener is not None:
            raise HermesToolGatewayError("gateway is already started")
        if not 0 <= max_calls <= 4096:
            raise HermesToolGatewayError("gateway max_calls is outside the accepted range")
        self._control_root.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(48)
        token_file = self._control_root / f"hermes-gateway-{secrets.token_hex(12)}.token"
        file_descriptor = os.open(str(token_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(file_descriptor, token.encode("ascii"))
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(min(self._lifetime_seconds, 30.0))
        expires_at_ns = time.time_ns() + int(self._lifetime_seconds * 1_000_000_000)
        descriptor = HermesGatewayDescriptor.create(host="127.0.0.1", port=int(listener.getsockname()[1]), token_file=str(token_file), request_id=self._provider.request_id, task_id=self._provider.task_id, tool_scope_digest=self._provider.scope_digest, max_calls=max_calls, expires_at_ns=expires_at_ns)
        self._listener, self._descriptor, self._token_file = listener, descriptor, token_file
        self._thread = threading.Thread(target=self._serve, args=(token,), name="daedalus-hermes-tool-gateway", daemon=True)
        self._thread.start()
        return descriptor

    def _serve(self, token: str) -> None:
        listener = self._listener
        descriptor = self._descriptor
        assert listener is not None and descriptor is not None
        try:
            client, _address = listener.accept()
            with client:
                client.settimeout(max(0.1, (descriptor.expires_at_ns - time.time_ns()) / 1_000_000_000))
                authentication = _recv_frame(client)
                required_auth = {"schema", "type", "token", "request_id", "task_id", "tool_scope_digest"}
                if set(authentication) != required_auth or authentication.get("type") != "authenticate":
                    raise HermesToolGatewayError("gateway authentication frame is not exact")
                if not secrets.compare_digest(str(authentication["token"]), token):
                    raise HermesToolGatewayError("gateway bearer authentication failed")
                if authentication["request_id"] != descriptor.request_id or authentication["task_id"] != descriptor.task_id:
                    raise HermesToolGatewayError("gateway task identity mismatch")
                if authentication["tool_scope_digest"] != descriptor.tool_scope_digest:
                    raise HermesToolGatewayError("gateway tool scope mismatch")
                _send_frame(client, {"schema": GATEWAY_SCHEMA, "type": "authenticated", "descriptor_digest": descriptor.digest})
                calls = 0
                while not self._closed.is_set():
                    if time.time_ns() > descriptor.expires_at_ns:
                        raise HermesToolGatewayError("gateway lifetime expired")
                    request = _recv_frame(client)
                    request_type = request.get("type")
                    if request_type == "close":
                        if set(request) != {"schema", "type"}:
                            raise HermesToolGatewayError("gateway close frame is not exact")
                        _send_frame(client, {"schema": GATEWAY_SCHEMA, "type": "closed"})
                        return
                    if set(request) != {"schema", "type", "call_id", "name", "arguments"} or request_type != "invoke":
                        raise HermesToolGatewayError("gateway invoke frame is not exact")
                    if calls >= descriptor.max_calls:
                        outcome = ToolOutcome(False, "tool refused: authenticated gateway call budget exhausted", canonical_sha256({"refusal": "tool_call_budget_exhausted"}), canonical_sha256({"refusal": "tool_call_budget_exhausted", "call_id": request["call_id"]}), canonical_sha256({"call_id": request["call_id"], "name": request["name"]}), "tool_call_budget_exhausted")
                    else:
                        arguments = request["arguments"]
                        if not isinstance(arguments, Mapping):
                            raise HermesToolGatewayError("gateway tool arguments must be an object")
                        outcome = self._provider.invoke(str(request["name"]), arguments)
                        calls += 1
                    _send_frame(client, {"schema": GATEWAY_SCHEMA, "type": "result", "call_id": str(request["call_id"]), **outcome.to_dict()})
        except BaseException as exc:
            if not self._closed.is_set():
                self._failure_type = type(exc).__name__
        finally:
            self._closed.set()
            try:
                listener.close()
            except OSError:
                pass

    def close(self) -> None:
        self._closed.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._token_file is not None:
            try:
                self._token_file.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "HermesToolGatewayServer":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


class HermesToolGatewayClient:
    def __init__(self, descriptor: HermesGatewayDescriptor, *, timeout_seconds: float = 30.0) -> None:
        self._descriptor = descriptor
        self._timeout_seconds = timeout_seconds
        self._socket: socket.socket | None = None

    def connect(self) -> None:
        if time.time_ns() > self._descriptor.expires_at_ns:
            raise HermesToolGatewayError("gateway descriptor is expired")
        token_path = Path(self._descriptor.token_file).expanduser().resolve(strict=True)
        token = token_path.read_text(encoding="ascii").strip()
        sock = socket.create_connection((self._descriptor.host, self._descriptor.port), timeout=self._timeout_seconds)
        sock.settimeout(self._timeout_seconds)
        _send_frame(sock, {"schema": GATEWAY_SCHEMA, "type": "authenticate", "token": token, "request_id": self._descriptor.request_id, "task_id": self._descriptor.task_id, "tool_scope_digest": self._descriptor.tool_scope_digest})
        response = _recv_frame(sock)
        if response != {"schema": GATEWAY_SCHEMA, "type": "authenticated", "descriptor_digest": self._descriptor.digest}:
            sock.close()
            raise HermesToolGatewayError("gateway authentication response is invalid")
        self._socket = sock

    def invoke(self, *, call_id: str, name: str, arguments: Mapping[str, object]) -> ToolOutcome:
        if self._socket is None:
            raise HermesToolGatewayError("gateway client is not connected")
        _send_frame(self._socket, {"schema": GATEWAY_SCHEMA, "type": "invoke", "call_id": call_id, "name": name, "arguments": dict(arguments)})
        response = _recv_frame(self._socket)
        exact = {"schema", "type", "call_id", "ok", "observation", "observation_digest", "receipt_digest", "invocation_digest", "refusal"}
        if set(response) != exact or response["type"] != "result" or response["call_id"] != call_id:
            raise HermesToolGatewayError("gateway result frame is invalid")
        return ToolOutcome(ok=bool(response["ok"]), observation=str(response["observation"]), observation_digest=str(response["observation_digest"]), receipt_digest=str(response["receipt_digest"]), invocation_digest=str(response["invocation_digest"]), refusal=str(response["refusal"]))

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            _send_frame(sock, {"schema": GATEWAY_SCHEMA, "type": "close"})
            _recv_frame(sock)
        except (OSError, EOFError, HermesToolGatewayError):
            pass
        finally:
            sock.close()

    def __enter__(self) -> "HermesToolGatewayClient":
        self.connect()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
