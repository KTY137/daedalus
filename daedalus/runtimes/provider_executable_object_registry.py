"""Canonical in-process admission for revision-bound provider executable objects.

The pre-admission packet proves *which* provider implementation and repository
targets are authorized to be considered. This module proves that the concrete
Python function objects already present in the process still correspond to
those exact targets, repository bytes, and a deliberately narrow ambient-global
dependency closure.

Admission itself does not import modules, execute provider code, start effects,
or grant provider authority. The Gate-1 broker may additionally consume the
registered objects through the narrow sealed-operation methods at the end of
this module, but only with an exact persisted STARTED receipt and the same
runtime/effect/payload subject. No caller-selected callable crosses that seam.
"""
from __future__ import annotations

import builtins
import dis
import hashlib
import inspect
import json
import marshal
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.schemas import _identifier, _revision, _sha256


_SCHEMA = "daedalus-provider-executable-object-admission/2"
_DEPENDENCY_SCHEMA = "daedalus-provider-executable-dependency-manifest/1"

# Capture the verifier's own primitives once.  A provider dependency mutation
# must not redirect the code which detects that mutation.  Keep the live
# namespace only as comparison material; cloned code always receives the
# detached snapshot.
_BUILTINS_LIVE = builtins.__dict__
_BUILTINS_NAMESPACE = MappingProxyType(_BUILTINS_LIVE.copy())
_ORIGINAL_IMPORT = builtins.__import__
_SHA256 = hashlib.sha256
_JSON_DUMPS = json.dumps
_MARSHAL_DUMPS = marshal.dumps
_SYS_MODULES = sys.modules
_EXACT_TYPE = _BUILTINS_NAMESPACE["type"]
_GETATTR = _BUILTINS_NAMESPACE["getattr"]
_ISINSTANCE = _BUILTINS_NAMESPACE["isinstance"]
_DICT = _BUILTINS_NAMESPACE["dict"]
_ID = _BUILTINS_NAMESPACE["id"]
_REPR = _BUILTINS_NAMESPACE["repr"]
_SET = _BUILTINS_NAMESPACE["set"]
_SORTED = _BUILTINS_NAMESPACE["sorted"]
_STATICMETHOD = _BUILTINS_NAMESPACE["staticmethod"]
_CLASSMETHOD = _BUILTINS_NAMESPACE["classmethod"]
_PROPERTY = _BUILTINS_NAMESPACE["property"]

# These are the interpreter leaves used by the pre-effect verifier before it
# has authenticated a provider dependency snapshot.  Their exact import-time
# identities are checked without calling any of them, so replacing (for
# example) ``builtins.type`` with a trap cannot redirect the detector itself.
_VERIFIER_BUILTIN_NAMES = (
    "dict",
    "getattr",
    "id",
    "isinstance",
    "len",
    "next",
    "sorted",
    "set",
    "staticmethod",
    "classmethod",
    "property",
    "str",
    "tuple",
    "type",
)

# Gate-1 exposes exactly these local-import leaves to a sealed provider
# operation.  The imported module itself is never placed in the operation's
# globals and the provider receives only the named frozen view.
_SEALED_IMPORT_MEMBERS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "hashlib": ("sha256",),
        "json": ("JSONDecodeError", "dumps", "loads"),
        "subprocess": ("run",),
    }
)
_TRUE_CLAIMS = (
    "pre_admission_authenticated",
    "repository_source_bytes_verified",
    "loaded_object_targets_verified",
    "loaded_object_bytecode_verified",
)
_FALSE_CLAIMS = (
    "provider_code_executed",
    "provider_execution_allowed",
    "effect_start_authorized",
    "callback_seam_removed",
    "broker_invocation_performed",
    "automatic_reexecution_allowed",
    "owner_approval_issued",
    "promotion_authorized",
    "gate_transition_authorized",
    "closed",
)


class ProviderExecutableObjectRegistryError(RuntimeError):
    """Base class for guarded provider executable-object admission failures."""


class ProviderExecutableObjectRegistryShapeError(ProviderExecutableObjectRegistryError):
    """A registry subject or receipt has a malformed/non-exact shape."""


class ProviderExecutableObjectRegistryBindingError(ProviderExecutableObjectRegistryError):
    """A loaded object differs from the authenticated repository subject."""


class ProviderSealedOutputEvidenceError(ProviderExecutableObjectRegistryError):
    """The provider returned, but its fixed evidence operation did not."""


def _verify_verifier_builtin_snapshot() -> None:
    """Refuse verifier-builtin substitution without invoking the substitute."""

    for name in _VERIFIER_BUILTIN_NAMES:
        if _BUILTINS_LIVE.get(name) is not _BUILTINS_NAMESPACE[name]:
            raise ProviderExecutableObjectRegistryBindingError(
                f"provider executable verifier builtin {name!r} changed after import"
            )


def _stable_canonical_sha(value: Any) -> str:
    encoded = _JSON_DUMPS(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return _SHA256(encoded).hexdigest()


def _function_leaf_descriptor(value: types.FunctionType) -> dict[str, Any]:
    return {
        "kind": "python-function",
        "module": value.__module__,
        "qualname": value.__qualname__,
        "code_sha256": _code_sha256(value.__code__),
        "defaults": _dependency_state_descriptor(value.__defaults__),
        "kwdefaults": _dependency_state_descriptor(value.__kwdefaults__),
        "closure": (
            None
            if value.__closure__ is None
            else [
                _closure_cell_descriptor(cell.cell_contents)
                for cell in value.__closure__
            ]
        ),
    }


def _closure_cell_descriptor(value: Any) -> Any:
    value_type = _EXACT_TYPE(value)
    if value_type is types.FunctionType:
        return {
            "kind": "closure-function",
            "module": value.__module__,
            "qualname": value.__qualname__,
            "code_sha256": _code_sha256(value.__code__),
        }
    if _ISINSTANCE(value, type):
        return {
            "kind": "closure-type",
            "module": value.__module__,
            "qualname": value.__qualname__,
        }
    return _dependency_state_descriptor(value, depth=1)


def _dependency_state_descriptor(
    value: Any,
    *,
    seen: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Describe bounded executable state without calling dependency code."""

    if seen is None:
        seen = set()
    value_type = _EXACT_TYPE(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        return {"kind": "float", "value": _REPR(value)}
    if value_type is bytes:
        return {"kind": "bytes", "hex": value.hex()}
    if depth >= 8:
        return {
            "kind": "bounded-object",
            "module": _GETATTR(value_type, "__module__", None),
            "qualname": _GETATTR(value_type, "__qualname__", None),
        }
    identity = _ID(value)
    if identity in seen:
        return {
            "kind": "cycle",
            "module": _GETATTR(value_type, "__module__", None),
            "qualname": _GETATTR(value_type, "__qualname__", None),
        }
    nested_seen = _SET(seen)
    nested_seen.add(identity)
    if value_type is tuple or value_type is list:
        return {
            "kind": "tuple" if value_type is tuple else "list",
            "items": [
                _dependency_state_descriptor(
                    item,
                    seen=nested_seen,
                    depth=depth + 1,
                )
                for item in value
            ],
        }
    if value_type is dict:
        rows = [
            {
                "key": _dependency_state_descriptor(
                    key,
                    seen=nested_seen,
                    depth=depth + 1,
                ),
                "value": _dependency_state_descriptor(
                    item,
                    seen=nested_seen,
                    depth=depth + 1,
                ),
            }
            for key, item in value.items()
        ]
        return {
            "kind": "dict",
            "items": _SORTED(rows, key=lambda row: _REPR(row["key"])),
        }
    if value_type is types.FunctionType:
        return _function_leaf_descriptor(value)
    if value_type is types.MethodType:
        return {
            "kind": "python-method",
            "function": _function_leaf_descriptor(value.__func__),
            "self": _dependency_state_descriptor(
                value.__self__,
                seen=nested_seen,
                depth=depth + 1,
            ),
        }
    if value_type in {types.BuiltinFunctionType, types.BuiltinMethodType}:
        descriptor: dict[str, Any] = {
            "kind": "builtin-function",
            "module": _GETATTR(value, "__module__", None),
            "qualname": _GETATTR(
                value,
                "__qualname__",
                _GETATTR(value, "__name__", None),
            ),
        }
        bound_self = _GETATTR(value, "__self__", None)
        if bound_self is not None and not _ISINSTANCE(bound_self, types.ModuleType):
            descriptor["self"] = _dependency_state_descriptor(
                bound_self,
                seen=nested_seen,
                depth=depth + 1,
            )
        return descriptor
    if _ISINSTANCE(value, type):
        members: list[dict[str, Any]] = []
        for name, member in value.__dict__.items():
            member_type = _EXACT_TYPE(member)
            if member_type is types.FunctionType:
                member_descriptor: Any = _function_leaf_descriptor(member)
            elif member_type in {_STATICMETHOD, _CLASSMETHOD}:
                if _EXACT_TYPE(member.__func__) is types.FunctionType:
                    member_descriptor = _function_leaf_descriptor(member.__func__)
                else:
                    member_descriptor = _dependency_state_descriptor(
                        member.__func__,
                        seen=nested_seen,
                        depth=depth + 1,
                    )
            elif member_type is _PROPERTY:
                member_descriptor = {
                    "kind": "property",
                    "get": (
                        None
                        if member.fget is None
                        else _function_leaf_descriptor(member.fget)
                    ),
                    "set": (
                        None
                        if member.fset is None
                        else _function_leaf_descriptor(member.fset)
                    ),
                    "delete": (
                        None
                        if member.fdel is None
                        else _function_leaf_descriptor(member.fdel)
                    ),
                }
            else:
                continue
            members.append({"name": name, "descriptor": member_descriptor})
        return {
            "kind": "type",
            "module": value.__module__,
            "qualname": value.__qualname__,
            "members": _SORTED(members, key=lambda row: row["name"]),
        }
    if value_type is types.ModuleType:
        return {"kind": "module", "name": value.__name__}
    state = _GETATTR(value, "__dict__", None)
    return {
        "kind": "object",
        "module": _GETATTR(value_type, "__module__", None),
        "qualname": _GETATTR(value_type, "__qualname__", None),
        "state": (
            None
            if value_type is not dict and _EXACT_TYPE(state) is not dict
            else _dependency_state_descriptor(
                state,
                seen=nested_seen,
                depth=depth + 1,
            )
        ),
    }


def _dependency_value_descriptor(value: Any) -> dict[str, Any]:
    """Return inert identity evidence for one frozen dependency leaf."""

    if _EXACT_TYPE(value) is types.FunctionType:
        descriptor = _function_leaf_descriptor(value)
        descriptor["referenced_globals"] = [
            {
                "name": name,
                "descriptor": _dependency_state_descriptor(value.__globals__[name]),
            }
            for name in _referenced_global_names(value.__code__)
            if name in value.__globals__
        ]
        descriptor["referenced_builtins"] = [
            {
                "name": name,
                "descriptor": _dependency_state_descriptor(
                    value.__builtins__[name]
                ),
            }
            for name in _referenced_global_names(value.__code__)
            if name not in value.__globals__ and name in value.__builtins__
        ]
        return descriptor
    if _EXACT_TYPE(value) in {
        types.BuiltinFunctionType,
        types.BuiltinMethodType,
    }:
        return {
            "kind": "builtin-function",
            "module": _GETATTR(value, "__module__", None),
            "qualname": _GETATTR(
                value,
                "__qualname__",
                _GETATTR(value, "__name__", None),
            ),
        }
    if _ISINSTANCE(value, type):
        return _dependency_state_descriptor(value)
    raise ProviderExecutableObjectRegistryBindingError(
        "sealed imported dependency member has unsupported executable state"
    )


@dataclass(frozen=True)
class _SealedDependencyRecord:
    module_name: str
    module: types.ModuleType
    member_name: str
    member: Any
    descriptor: Mapping[str, Any]


@dataclass(frozen=True)
class _SealedBuiltinRecord:
    name: str
    value: Any


class _FrozenModuleView:
    """Read-only, finite module projection returned by the sealed importer."""

    __slots__ = ("_module_name", "_members", "_locked")

    def __init__(self, module_name: str, members: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_members", MappingProxyType(dict(members)))
        object.__setattr__(self, "_locked", True)

    def __getattr__(self, name: str) -> Any:
        members = object.__getattribute__(self, "_members")
        try:
            return members[name]
        except KeyError as exc:
            module_name = object.__getattribute__(self, "_module_name")
            raise AttributeError(
                f"sealed module {module_name!r} has no admitted member {name!r}"
            ) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_locked", False):
            raise AttributeError("sealed module views are immutable")
        object.__setattr__(self, name, value)


@dataclass(frozen=True)
class _NativeCompletedProcess:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class _NativeRunTimeout(TimeoutError):
    def __init__(
        self,
        command: tuple[str, ...],
        timeout: int | float,
        stdout: str,
        stderr: str,
    ) -> None:
        super().__init__(f"sealed native runner timed out after {timeout} seconds")
        self.cmd = command
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


class _NativeWindowsStartupInfo:
    """Minimal private STARTUPINFO projection consumed by ``_winapi``."""

    __slots__ = (
        "dwFlags",
        "hStdInput",
        "hStdOutput",
        "hStdError",
        "wShowWindow",
        "lpAttributeList",
    )

    def __init__(
        self,
        stdin: int,
        stdout: int,
        stderr: int,
        flags: int,
    ) -> None:
        self.dwFlags = flags
        self.hStdInput = stdin
        self.hStdOutput = stdout
        self.hStdError = stderr
        self.wShowWindow = 0
        self.lpAttributeList = {"handle_list": [stdin, stdout, stderr]}


def _native_run_shape(
    command,
    cwd,
    text,
    encoding,
    errors,
    capture_output,
    timeout,
    check,
):
    if type(command) not in (list, tuple) or not command:
        raise ValueError("sealed native runner requires a non-empty argv")
    argv = tuple(command)
    if any(type(item) is not str or not item for item in argv):
        raise ValueError("sealed native runner argv must contain exact non-empty strings")
    if type(cwd) is not str or not cwd:
        raise ValueError("sealed native runner requires an exact cwd string")
    if text is not True or encoding != "utf-8" or errors != "replace":
        raise ValueError("sealed native runner requires fixed UTF-8 text mode")
    if capture_output is not True or check is not False:
        raise ValueError("sealed native runner requires capture_output and check=false")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("sealed native runner timeout must be positive or null")
    return argv


def _native_windows_list2cmdline(argv):
    result = []
    for argument in argv:
        if result:
            result.append(" ")
        quote = not argument or " " in argument or "\t" in argument
        if quote:
            result.append('"')
        backslashes = 0
        for character in argument:
            if character == "\\":
                backslashes += 1
                continue
            if character == '"':
                result.append("\\" * (backslashes * 2 + 1))
                result.append('"')
            else:
                if backslashes:
                    result.append("\\" * backslashes)
                result.append(character)
            backslashes = 0
        if backslashes:
            result.append("\\" * (backslashes * (2 if quote else 1)))
        if quote:
            result.append('"')
    return "".join(result)


def _native_resolve_executable(name, cwd, path_entries, extensions, access, stat):
    separators = ("/", "\\") if extensions else ("/",)
    path_separator = "\\" if extensions else "/"
    explicit = any(separator in name for separator in separators)
    absolute = any(name.startswith(prefix) for prefix in ("/", "\\")) or (
        bool(extensions) and len(name) >= 2 and name[1] == ":"
    )
    directories = (cwd,) if explicit else path_entries
    basename = name
    for separator in separators:
        basename = basename.rsplit(separator, 1)[-1]
    suffixes = ("",) if not extensions or "." in basename else extensions
    for directory in directories:
        if explicit:
            base = name
            if not absolute:
                base = cwd.rstrip("/\\") + path_separator + name
        else:
            directory_absolute = directory.startswith(("/", "\\")) or (
                bool(extensions) and len(directory) >= 2 and directory[1] == ":"
            )
            if not directory_absolute:
                directory = (
                    cwd
                    if directory in ("", ".")
                    else cwd.rstrip("/\\") + path_separator + directory
                )
            base = directory.rstrip("/\\") + path_separator + name
        for suffix in suffixes:
            candidate = base + suffix
            try:
                details = stat(candidate)
            except OSError:
                continue
            if details.st_mode & 0o170000 == 0o100000 and access(candidate, 1):
                return candidate
    raise FileNotFoundError(name)


def _native_windows_drain(handle, chunks, peek, read, broken_pipe_error):
    try:
        peeked = peek(handle, 0)
        available = peeked[0] if len(peeked) == 2 else peeked[1]
    except broken_pipe_error:
        return False
    if not available:
        return False
    try:
        data, _error = read(handle, min(available, 65536), False)
    except broken_pipe_error:
        return False
    if not data:
        return False
    chunks.append(data)
    return True


def _native_windows_run(
    command,
    *,
    cwd,
    text,
    encoding,
    errors,
    capture_output,
    timeout,
    check,
):
    argv = _NATIVE_RUN_SHAPE(
        command,
        cwd,
        text,
        encoding,
        errors,
        capture_output,
        timeout,
        check,
    )
    executable = _NATIVE_RESOLVE_EXECUTABLE(
        argv[0],
        cwd,
        _NATIVE_PATH_ENTRIES,
        _NATIVE_EXECUTABLE_EXTENSIONS,
        _NATIVE_ACCESS,
        _NATIVE_STAT,
    )
    stdin_source = stdin_eof_write = stdin_handle = None
    stdout_read = stdout_source = stdout_write = None
    stderr_read = stderr_source = stderr_write = None
    process_handle = thread_handle = None
    process_reaped = False
    stdin_owned = False
    try:
        stdin_source = _NATIVE_GET_STD_HANDLE(_NATIVE_STD_INPUT_HANDLE)
        if stdin_source is None:
            stdin_source, stdin_eof_write = _NATIVE_CREATE_PIPE(None, 0)
            stdin_owned = True
        stdout_read, stdout_source = _NATIVE_CREATE_PIPE(None, 0)
        stderr_read, stderr_source = _NATIVE_CREATE_PIPE(None, 0)
        current = _NATIVE_GET_CURRENT_PROCESS()
        stdin_handle = _NATIVE_DUPLICATE_HANDLE(
            current,
            stdin_source,
            current,
            0,
            True,
            _NATIVE_DUPLICATE_SAME_ACCESS,
        )
        if stdin_owned:
            _NATIVE_CLOSE_HANDLE(stdin_source)
            stdin_source = None
        stdout_write = _NATIVE_DUPLICATE_HANDLE(
            current,
            stdout_source,
            current,
            0,
            True,
            _NATIVE_DUPLICATE_SAME_ACCESS,
        )
        stderr_write = _NATIVE_DUPLICATE_HANDLE(
            current,
            stderr_source,
            current,
            0,
            True,
            _NATIVE_DUPLICATE_SAME_ACCESS,
        )
        _NATIVE_CLOSE_HANDLE(stdout_source)
        stdout_source = None
        _NATIVE_CLOSE_HANDLE(stderr_source)
        stderr_source = None
        if stdin_eof_write is not None:
            _NATIVE_CLOSE_HANDLE(stdin_eof_write)
            stdin_eof_write = None
        startup = _NATIVE_STARTUP_INFO(
            stdin_handle,
            stdout_write,
            stderr_write,
            _NATIVE_STARTF_USESTDHANDLES,
        )
        process_handle, thread_handle, _pid, _tid = _NATIVE_CREATE_PROCESS(
            executable,
            _NATIVE_LIST2CMDLINE(argv),
            None,
            None,
            True,
            _NATIVE_CREATE_NO_WINDOW | _NATIVE_EXTENDED_STARTUPINFO_PRESENT,
            _NATIVE_ENVIRONMENT,
            cwd,
            startup,
        )
        _NATIVE_CLOSE_HANDLE(thread_handle)
        thread_handle = None
        _NATIVE_CLOSE_HANDLE(stdout_write)
        stdout_write = None
        _NATIVE_CLOSE_HANDLE(stderr_write)
        stderr_write = None
        _NATIVE_CLOSE_HANDLE(stdin_handle)
        stdin_handle = None
        stdout_chunks = []
        stderr_chunks = []
        deadline = None if timeout is None else _NATIVE_MONOTONIC() + timeout
        timed_out = False
        while True:
            process_was_reaped = process_reaped
            stdout_progress = _NATIVE_WINDOWS_DRAIN(
                stdout_read,
                stdout_chunks,
                _NATIVE_PEEK_NAMED_PIPE,
                _NATIVE_READ_FILE,
                _NATIVE_BROKEN_PIPE_ERROR,
            )
            stderr_progress = _NATIVE_WINDOWS_DRAIN(
                stderr_read,
                stderr_chunks,
                _NATIVE_PEEK_NAMED_PIPE,
                _NATIVE_READ_FILE,
                _NATIVE_BROKEN_PIPE_ERROR,
            )
            state = _NATIVE_WAIT_FOR_SINGLE_OBJECT(process_handle, 10)
            if state == _NATIVE_WAIT_OBJECT_0:
                process_reaped = True
            elif state != _NATIVE_WAIT_TIMEOUT:
                raise RuntimeError("sealed native runner received an invalid wait state")
            if deadline is not None and _NATIVE_MONOTONIC() >= deadline:
                timed_out = True
                if not process_reaped:
                    _NATIVE_TERMINATE_PROCESS(process_handle, 1)
                    _NATIVE_WAIT_FOR_SINGLE_OBJECT(
                        process_handle,
                        _NATIVE_INFINITE,
                    )
                    process_reaped = True
                break
            if (
                process_was_reaped
                and not stdout_progress
                and not stderr_progress
            ):
                break
        stdout = b"".join(stdout_chunks).decode(encoding, errors)
        stderr = b"".join(stderr_chunks).decode(encoding, errors)
        if timed_out:
            raise _NATIVE_TIMEOUT_ERROR(argv, timeout, stdout, stderr)
        return _NATIVE_COMPLETED_PROCESS(
            argv,
            _NATIVE_GET_EXIT_CODE_PROCESS(process_handle),
            stdout,
            stderr,
        )
    finally:
        if process_handle is not None and not process_reaped:
            try:
                _NATIVE_CLEANUP_TERMINATE(process_handle, 1)
            except OSError:
                pass
            try:
                _NATIVE_CLEANUP_WAIT(process_handle, _NATIVE_INFINITE)
            except OSError:
                pass
        if stdin_owned and stdin_source is not None:
            try:
                _NATIVE_CLOSE_HANDLE(stdin_source)
            except OSError:
                pass
        for handle in (
            thread_handle,
            process_handle,
            stdin_handle,
            stdin_eof_write,
            stdout_read,
            stdout_source,
            stdout_write,
            stderr_read,
            stderr_source,
            stderr_write,
        ):
            if handle is not None:
                try:
                    _NATIVE_CLOSE_HANDLE(handle)
                except OSError:
                    pass


def _native_posix_raise_exec_error(
    error_data,
    cwd,
    executable,
    fork_exec_abi,
    strerror,
):
    try:
        exception_name, hex_errno, message = error_data.split(b":", 2)
    except ValueError as exc:
        raise OSError(
            f"sealed native runner received malformed child exec evidence: "
            f"{error_data!r}"
        ) from exc
    if exception_name == b"OSError" and hex_errno:
        errno_number = int(hex_errno, 16)
        if message == b"noexec:chdir" or (
            fork_exec_abi == 21 and message == b"noexec"
        ):
            filename = cwd
        elif message == b"noexec":
            filename = None
        else:
            filename = executable
        if filename is None:
            raise OSError(errno_number, strerror(errno_number))
        raise OSError(errno_number, strerror(errno_number), filename)
    raise OSError(
        f"sealed native runner child could not exec the admitted argv: "
        f"{error_data!r}"
    )


def _native_posix_fork_exec_abi(version: tuple[int, int]) -> int:
    if version == (3, 10):
        return 21
    if version in {(3, 11), (3, 12), (3, 13)}:
        return 23
    raise ProviderExecutableObjectRegistryBindingError(
        "sealed POSIX provider execution is not admitted for unknown "
        f"CPython fork_exec ABI {version!r}"
    )


def _native_posix_run(
    command,
    *,
    cwd,
    text,
    encoding,
    errors,
    capture_output,
    timeout,
    check,
):
    argv = _NATIVE_RUN_SHAPE(
        command,
        cwd,
        text,
        encoding,
        errors,
        capture_output,
        timeout,
        check,
    )
    executable = _NATIVE_RESOLVE_EXECUTABLE(
        argv[0],
        cwd,
        _NATIVE_PATH_ENTRIES,
        (),
        _NATIVE_ACCESS,
        _NATIVE_STAT,
    )
    stdout_read = stdout_write = None
    stderr_read = stderr_write = None
    error_read = error_write = None
    pid = None
    child_reaped = False
    open_fds = {}
    closed_fds = set()
    try:
        stdout_read, stdout_write = _NATIVE_PIPE()
        stderr_read, stderr_write = _NATIVE_PIPE()
        error_read, error_write = _NATIVE_PIPE()
        while error_write < 3:
            replacement = _NATIVE_DUP(error_write)
            _NATIVE_CLOSE(error_write)
            error_write = replacement
        executable_bytes = executable.encode(
            _NATIVE_FILESYSTEM_ENCODING,
            "surrogateescape",
        )
        if _NATIVE_FORK_EXEC_ABI == 21:
            pid = _NATIVE_FORK_EXEC(
                argv,
                (executable_bytes,),
                True,
                (error_write,),
                cwd,
                _NATIVE_ENVIRONMENT_LIST,
                -1,
                -1,
                stdout_read,
                stdout_write,
                stderr_read,
                stderr_write,
                error_read,
                error_write,
                True,
                False,
                None,
                None,
                None,
                -1,
                None,
            )
        else:
            pid = _NATIVE_FORK_EXEC(
                argv,
                (executable_bytes,),
                True,
                (error_write,),
                cwd,
                _NATIVE_ENVIRONMENT_LIST,
                -1,
                -1,
                stdout_read,
                stdout_write,
                stderr_read,
                stderr_write,
                error_read,
                error_write,
                True,
                False,
                -1,
                None,
                None,
                None,
                -1,
                None,
                True,
            )
        _NATIVE_CLOSE(stdout_write)
        stdout_write = None
        _NATIVE_CLOSE(stderr_write)
        stderr_write = None
        _NATIVE_CLOSE(error_write)
        error_write = None
        _NATIVE_SET_BLOCKING(stdout_read, False)
        _NATIVE_SET_BLOCKING(stderr_read, False)
        _NATIVE_SET_BLOCKING(error_read, False)
        stdout_chunks = []
        stderr_chunks = []
        error_chunks = []
        open_fds = {
            stdout_read: stdout_chunks,
            stderr_read: stderr_chunks,
            error_read: error_chunks,
        }
        deadline = None if timeout is None else _NATIVE_MONOTONIC() + timeout
        status = None
        timed_out = False
        while status is None or open_fds:
            if open_fds:
                try:
                    readable, _writable, _exceptional = _NATIVE_SELECT(
                        list(open_fds),
                        [],
                        [],
                        0.01,
                    )
                except InterruptedError:
                    readable = []
                for descriptor in readable:
                    try:
                        data = _NATIVE_READ(descriptor, 65536)
                    except (BlockingIOError, InterruptedError):
                        data = None
                    if data:
                        open_fds[descriptor].append(data)
                    elif data == b"":
                        _NATIVE_CLOSE(descriptor)
                        closed_fds.add(descriptor)
                        del open_fds[descriptor]
            if status is None:
                try:
                    waited, child_status = _NATIVE_WAITPID(pid, _NATIVE_WNOHANG)
                except InterruptedError:
                    waited = 0
                if waited == pid:
                    status = child_status
                    child_reaped = True
            if deadline is not None and _NATIVE_MONOTONIC() >= deadline:
                timed_out = True
                if status is None:
                    try:
                        _NATIVE_KILL(pid, _NATIVE_SIGKILL)
                    except ProcessLookupError:
                        pass
                    while True:
                        try:
                            _waited, status = _NATIVE_WAITPID(pid, 0)
                            child_reaped = True
                            break
                        except InterruptedError:
                            continue
                    continue
                break
        if error_chunks:
            _NATIVE_RAISE_EXEC_ERROR(
                b"".join(error_chunks),
                cwd,
                executable,
                _NATIVE_FORK_EXEC_ABI,
                _NATIVE_STRERROR,
            )
        stdout = b"".join(stdout_chunks).decode(encoding, errors)
        stderr = b"".join(stderr_chunks).decode(encoding, errors)
        if timed_out:
            raise _NATIVE_TIMEOUT_ERROR(argv, timeout, stdout, stderr)
        return _NATIVE_COMPLETED_PROCESS(
            argv,
            _NATIVE_WAITSTATUS_TO_EXITCODE(status),
            stdout,
            stderr,
        )
    finally:
        if pid not in (None, 0) and not child_reaped:
            try:
                _NATIVE_CLEANUP_KILL(pid, _NATIVE_SIGKILL)
            except OSError:
                pass
            while True:
                try:
                    _NATIVE_CLEANUP_WAITPID(pid, 0)
                    break
                except InterruptedError:
                    continue
                except (ChildProcessError, OSError):
                    break
        descriptors = {
            descriptor
            for descriptor in (
                stdout_read,
                stdout_write,
                stderr_read,
                stderr_write,
                error_read,
                error_write,
                *tuple(open_fds),
            )
            if descriptor is not None and descriptor not in closed_fds
        }
        for descriptor in descriptors:
            try:
                _NATIVE_CLOSE(descriptor)
            except OSError:
                pass


class _SealedImporter:
    """Import callable which never consults ambient builtins or sys.modules."""

    __slots__ = ("_modules",)

    def __init__(self, modules: Mapping[str, _FrozenModuleView]) -> None:
        self._modules = MappingProxyType(dict(modules))

    def __call__(
        self,
        name: str,
        globals: Mapping[str, Any] | None = None,
        locals: Mapping[str, Any] | None = None,
        fromlist: tuple[str, ...] | list[str] | None = (),
        level: int = 0,
    ) -> _FrozenModuleView:
        del globals, locals
        if type(name) is not str or type(level) is not int or level != 0:
            raise ImportError("sealed provider imports must be exact and absolute")
        if fromlist not in (None, (), []):
            raise ImportError("sealed provider from-imports are not admitted")
        module = self._modules.get(name)
        if module is None:
            raise ImportError(f"sealed provider import {name!r} is not admitted")
        return module


@dataclass(frozen=True)
class _SealedProviderOperation:
    invoke: types.FunctionType
    output_digests: types.FunctionType
    dependency_manifest_sha256: str
    dependency_records: tuple[_SealedDependencyRecord, ...]
    builtin_records: tuple[_SealedBuiltinRecord, ...]
    original_import: Any


def _target(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise ProviderExecutableObjectRegistryShapeError(
            f"{label} must be a bounded exact target string"
        )
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ProviderExecutableObjectRegistryShapeError(
            f"{label} contains a forbidden character"
        )
    return value


def _canonical_pre_admission(
    value: ProviderExecutablePreAdmissionReceipt,
) -> ProviderExecutablePreAdmissionReceipt:
    if type(value) is not ProviderExecutablePreAdmissionReceipt:
        raise ProviderExecutableObjectRegistryShapeError(
            "pre_admission must be exact ProviderExecutablePreAdmissionReceipt"
        )
    try:
        rebuilt = ProviderExecutablePreAdmissionReceipt.from_dict(value.to_dict())
    except Exception as exc:
        raise ProviderExecutableObjectRegistryBindingError(
            "pre_admission is not canonical"
        ) from exc
    if rebuilt != value:
        raise ProviderExecutableObjectRegistryBindingError(
            "pre_admission changed during canonical reconstruction"
        )
    return rebuilt


def _canonical_function_target(function: types.FunctionType, label: str) -> str:
    if type(function) is not types.FunctionType:
        raise ProviderExecutableObjectRegistryShapeError(
            f"{label} must be an exact Python function"
        )
    module = getattr(function, "__module__", None)
    qualname = getattr(function, "__qualname__", None)
    if type(module) is not str or not (
        module == "daedalus" or module.startswith("daedalus.")
    ):
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function module is not a Daedalus module"
        )
    if type(qualname) is not str or not qualname or "<locals>" in qualname:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function qualified name is not a stable repository target"
        )
    return f"{module}:{qualname}"


def _repository_source_path(
    repository_root: Path,
    target: str,
) -> Path:
    module_name, separator, _qualname = target.partition(":")
    if separator != ":" or not (
        module_name == "daedalus" or module_name.startswith("daedalus.")
    ):
        raise ProviderExecutableObjectRegistryShapeError(
            "provider executable target is not a canonical Daedalus target"
        )
    relative = Path(*module_name.split("."))
    candidates = (
        repository_root / relative.with_suffix(".py"),
        repository_root / relative / "__init__.py",
    )
    existing: list[Path] = []
    for candidate in candidates:
        if candidate.is_file():
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ProviderExecutableObjectRegistryBindingError(
                    "provider source path could not be resolved"
                ) from exc
            try:
                resolved.relative_to(repository_root)
            except ValueError as exc:
                raise ProviderExecutableObjectRegistryBindingError(
                    "provider source path escapes repository root"
                ) from exc
            existing.append(resolved)
    if len(existing) != 1:
        raise ProviderExecutableObjectRegistryBindingError(
            "provider target must resolve to exactly one repository source file"
        )
    return existing[0]


def _function_source_path(
    function: types.FunctionType,
    expected: Path,
    label: str,
) -> None:
    code_filename = function.__code__.co_filename
    source_filename = inspect.getsourcefile(function)
    filenames = tuple(
        name for name in (source_filename, code_filename) if type(name) is str and name
    )
    if not filenames:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function has no source filename"
        )
    for filename in filenames:
        try:
            actual = Path(filename).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                f"{label} function source filename could not be resolved"
            ) from exc
        if actual != expected:
            raise ProviderExecutableObjectRegistryBindingError(
                f"{label} function source file differs from authenticated repository source"
            )


def _normalize_code(code: types.CodeType) -> types.CodeType:
    constants = tuple(
        _normalize_code(item) if type(item) is types.CodeType else item
        for item in code.co_consts
    )
    return code.replace(
        co_consts=constants,
        co_filename="<daedalus-provider-target>",
    )


def _code_sha256(code: types.CodeType) -> str:
    if type(code) is not types.CodeType:
        raise ProviderExecutableObjectRegistryShapeError(
            "provider target bytecode must be an exact code object"
        )
    normalized = _normalize_code(code)
    return _SHA256(_MARSHAL_DUMPS(normalized)).hexdigest()


def _descend_code(container: types.CodeType, name: str) -> types.CodeType:
    matches = tuple(
        item
        for item in container.co_consts
        if type(item) is types.CodeType and item.co_name == name
    )
    if len(matches) != 1:
        raise ProviderExecutableObjectRegistryBindingError(
            f"provider source contains {len(matches)} bytecode targets named {name!r}"
        )
    return matches[0]


def _compiled_target_code(source: bytes, target: str) -> types.CodeType:
    _module, _separator, qualname = target.partition(":")
    try:
        root = compile(
            source,
            "<daedalus-provider-target>",
            "exec",
            dont_inherit=True,
            optimize=0,
        )
    except (SyntaxError, ValueError) as exc:
        raise ProviderExecutableObjectRegistryBindingError(
            "authenticated provider repository source does not compile"
        ) from exc
    code = root
    for part in qualname.split("."):
        code = _descend_code(code, part)
    return code


def _verify_function_state(function: types.FunctionType, label: str) -> None:
    if function.__closure__ is not None:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function closures are not admissible"
        )
    if function.__defaults__ is not None:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function positional defaults are not admissible"
        )
    if function.__kwdefaults__ not in (None, {}):
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function keyword defaults are not admissible"
        )


def _verify_sealed_signature(
    function: types.FunctionType,
    expected_names: tuple[str, ...],
    label: str,
) -> None:
    """Require the fixed payload ABI used by the D4 broker operation."""

    try:
        parameters = tuple(inspect.signature(function).parameters.values())
    except (TypeError, ValueError) as exc:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} sealed-operation signature could not be inspected"
        ) from exc
    if len(parameters) != len(expected_names):
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} must accept exactly {len(expected_names)} sealed arguments"
        )
    for parameter, expected_name in zip(parameters, expected_names):
        if parameter.name != expected_name or parameter.kind not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            raise ProviderExecutableObjectRegistryBindingError(
                f"{label} sealed-operation parameter must be {expected_name!r}"
            )
    if function.__defaults__ is not None:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function positional defaults are not admissible"
        )
    if function.__kwdefaults__ not in (None, {}):
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function keyword defaults are not admissible"
        )


def _walk_code_objects(code: types.CodeType):
    yield code
    for value in code.co_consts:
        if type(value) is types.CodeType:
            yield from _walk_code_objects(value)


def _referenced_global_names(code: types.CodeType) -> tuple[str, ...]:
    names: set[str] = set()
    for nested in _walk_code_objects(code):
        try:
            instructions = dis.get_instructions(nested)
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider bytecode globals could not be inspected"
            ) from exc
        for instruction in instructions:
            if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                continue
            if type(instruction.argval) is not str or not instruction.argval:
                raise ProviderExecutableObjectRegistryBindingError(
                    "provider bytecode contains a malformed ambient global reference"
                )
            names.add(instruction.argval)
    return tuple(sorted(names))


def _referenced_global_attribute_names(
    code: types.CodeType,
    global_name: str,
) -> tuple[str, ...]:
    """Return direct attributes loaded from one named module global."""

    names: set[str] = set()
    for nested in _walk_code_objects(code):
        try:
            instructions = tuple(dis.get_instructions(nested))
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider bytecode dependency attributes could not be inspected"
            ) from exc
        for index, instruction in enumerate(instructions[:-1]):
            if (
                instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}
                and instruction.argval == global_name
            ):
                following = instructions[index + 1]
                if (
                    following.opname in {"LOAD_ATTR", "LOAD_METHOD"}
                    and type(following.argval) is str
                    and following.argval
                ):
                    names.add(following.argval)
    return tuple(sorted(names))


def _class_dependency_functions(dependency_type: type) -> tuple[types.FunctionType, ...]:
    functions: list[types.FunctionType] = []
    for member in dependency_type.__dict__.values():
        member_type = _EXACT_TYPE(member)
        if member_type is types.FunctionType:
            functions.append(member)
        elif member_type in {_STATICMETHOD, _CLASSMETHOD}:
            if _EXACT_TYPE(member.__func__) is types.FunctionType:
                functions.append(member.__func__)
        elif member_type is _PROPERTY:
            functions.extend(
                function
                for function in (member.fget, member.fset, member.fdel)
                if _EXACT_TYPE(function) is types.FunctionType
            )
    return tuple(functions)


def _imported_module_names(code: types.CodeType) -> tuple[str, ...]:
    names: set[str] = set()
    for nested in _walk_code_objects(code):
        try:
            instructions = dis.get_instructions(nested)
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider bytecode imports could not be inspected"
            ) from exc
        for instruction in instructions:
            if instruction.opname == "IMPORT_FROM":
                raise ProviderExecutableObjectRegistryBindingError(
                    "sealed provider from-imports are not admissible"
                )
            if instruction.opname != "IMPORT_NAME":
                continue
            if type(instruction.argval) is not str or not instruction.argval:
                raise ProviderExecutableObjectRegistryBindingError(
                    "provider bytecode contains a malformed import reference"
                )
            names.add(instruction.argval)
    return tuple(sorted(names))


def _repository_function_closure(
    roots: tuple[types.FunctionType, ...],
) -> tuple[types.FunctionType, ...]:
    found: dict[int, types.FunctionType] = {}

    def visit(function: types.FunctionType) -> None:
        identity = id(function)
        if identity in found:
            return
        found[identity] = function
        for name in _referenced_global_names(function.__code__):
            dependency = function.__globals__.get(name)
            if (
                type(dependency) is types.FunctionType
                and dependency.__module__ == function.__module__
            ):
                visit(dependency)

    for root in roots:
        visit(root)
    return tuple(found.values())


def _clone_dependency_function(
    function: types.FunctionType,
    memo: dict[int, types.FunctionType],
    *,
    overrides: Mapping[int, Any] | None = None,
) -> types.FunctionType:
    identity = id(function)
    existing = memo.get(identity)
    if existing is not None:
        return existing

    namespace: dict[str, Any] = {
        "__name__": function.__module__,
        "__package__": function.__module__.rpartition(".")[0],
        # CPython's IMPORT_NAME fast path requires a real dict here.  This is a
        # detached private snapshot, never the live builtins namespace.
        "__builtins__": dict(_BUILTINS_NAMESPACE),
    }
    sealed_cells = None
    if function.__closure__ is not None:
        cells = []
        for cell in function.__closure__:
            value = cell.cell_contents
            replacement = None if overrides is None else overrides.get(_ID(value))
            if replacement is not None:
                value = replacement
            elif _EXACT_TYPE(value) is types.FunctionType:
                value = _clone_dependency_function(
                    value,
                    memo,
                    overrides=overrides,
                )
            cells.append((lambda retained: lambda: retained)(value).__closure__[0])
        sealed_cells = tuple(cells)
    clone = types.FunctionType(
        function.__code__,
        namespace,
        function.__name__,
        function.__defaults__,
        sealed_cells,
    )
    clone.__kwdefaults__ = (
        None if function.__kwdefaults__ is None else dict(function.__kwdefaults__)
    )
    memo[identity] = clone
    for name in _referenced_global_names(function.__code__):
        if name not in function.__globals__:
            continue
        value = function.__globals__[name]
        replacement = None if overrides is None else overrides.get(_ID(value))
        if replacement is not None:
            value = replacement
        elif (
            _EXACT_TYPE(value) is types.FunctionType
            and value.__module__ == function.__module__
        ):
            value = _clone_dependency_function(
                value,
                memo,
                overrides=overrides,
            )
        namespace[name] = value
    return clone


def _clone_dependency_class(
    dependency_type: type,
    function_memo: dict[int, types.FunctionType],
    *,
    overrides: Mapping[int, Any],
) -> type:
    """Clone the executable surface of one admitted stdlib dependency type."""

    namespace: dict[str, Any] = {
        "__module__": dependency_type.__module__,
        "__doc__": dependency_type.__doc__,
    }
    for name, member in dependency_type.__dict__.items():
        if name in {"__dict__", "__weakref__", "__module__", "__doc__"}:
            continue
        member_type = _EXACT_TYPE(member)
        if member_type is types.FunctionType:
            member = _clone_dependency_function(
                member,
                function_memo,
                overrides=overrides,
            )
        elif member_type is _STATICMETHOD:
            if _EXACT_TYPE(member.__func__) is types.FunctionType:
                member = _STATICMETHOD(
                    _clone_dependency_function(
                        member.__func__,
                        function_memo,
                        overrides=overrides,
                    )
                )
        elif member_type is _CLASSMETHOD:
            if _EXACT_TYPE(member.__func__) is types.FunctionType:
                member = _CLASSMETHOD(
                    _clone_dependency_function(
                        member.__func__,
                        function_memo,
                        overrides=overrides,
                    )
                )
        elif member_type is _PROPERTY:
            member = _PROPERTY(
                None
                if member.fget is None
                else _clone_dependency_function(
                    member.fget,
                    function_memo,
                    overrides=overrides,
                ),
                None
                if member.fset is None
                else _clone_dependency_function(
                    member.fset,
                    function_memo,
                    overrides=overrides,
                ),
                None
                if member.fdel is None
                else _clone_dependency_function(
                    member.fdel,
                    function_memo,
                    overrides=overrides,
                ),
                member.__doc__,
            )
        namespace[name] = member
    return _EXACT_TYPE(
        dependency_type.__name__,
        dependency_type.__bases__,
        namespace,
    )


def _bind_native_leaf(
    template: types.FunctionType,
    bindings: Mapping[str, Any],
    memo: dict[int, types.FunctionType],
) -> types.FunctionType:
    identity = _ID(template)
    existing = memo.get(identity)
    if existing is not None:
        return existing
    namespace: dict[str, Any] = {
        "__name__": __name__,
        "__package__": __package__,
        "__builtins__": _DICT(_BUILTINS_NAMESPACE),
    }
    clone = types.FunctionType(
        template.__code__,
        namespace,
        template.__name__,
        template.__defaults__,
        None,
    )
    clone.__kwdefaults__ = (
        None if template.__kwdefaults__ is None else _DICT(template.__kwdefaults__)
    )
    clone.__qualname__ = template.__qualname__
    memo[identity] = clone
    for name in _referenced_global_names(template.__code__):
        if name in bindings:
            namespace[name] = bindings[name]
            continue
        helper = template.__globals__.get(name)
        if (
            _EXACT_TYPE(helper) is types.FunctionType
            and helper.__module__ == template.__module__
        ):
            namespace[name] = _bind_native_leaf(helper, bindings, memo)
            continue
        if name in _BUILTINS_NAMESPACE:
            continue
        raise ProviderExecutableObjectRegistryBindingError(
            f"sealed native runner global {name!r} is unresolved"
        )
    return clone


def _sealed_module_overrides(
    module_name: str,
    module: types.ModuleType,
    function_memo: dict[int, types.FunctionType],
) -> dict[int, Any]:
    """Detach the bounded mutable objects reached by admitted stdlib leaves."""

    overrides: dict[int, Any] = {}
    if module_name == "subprocess":
        run = module.run
        if (
            _EXACT_TYPE(run) is types.FunctionType
            and run.__module__ == "subprocess"
            and run.__qualname__ == "run"
        ):
            def build_native_subprocess_run() -> types.FunctionType:
                os_module = _ORIGINAL_IMPORT("os", {}, {}, (), 0)
                time_module = _ORIGINAL_IMPORT("time", {}, {}, (), 0)
                environment = _DICT(os_module.environ)
                path_separator = ";" if sys.platform == "win32" else ":"
                path_entries = tuple(
                    entry.strip('"')
                    for entry in environment.get("PATH", "").split(path_separator)
                )
                common: dict[str, Any] = {
                    "_NATIVE_RUN_SHAPE": _native_run_shape,
                    "_NATIVE_RESOLVE_EXECUTABLE": _native_resolve_executable,
                    "_NATIVE_PATH_ENTRIES": path_entries,
                    "_NATIVE_ACCESS": os_module.access,
                    "_NATIVE_STAT": os_module.stat,
                    "_NATIVE_ENVIRONMENT": environment,
                    "_NATIVE_MONOTONIC": time_module.monotonic,
                    "_NATIVE_COMPLETED_PROCESS": _NativeCompletedProcess,
                    "_NATIVE_TIMEOUT_ERROR": _NativeRunTimeout,
                }
                if sys.platform == "win32":
                    winapi = _ORIGINAL_IMPORT("_winapi", {}, {}, (), 0)
                    bindings = {
                        **common,
                        "_NATIVE_EXECUTABLE_EXTENSIONS": ("", ".com", ".exe"),
                        "_NATIVE_LIST2CMDLINE": _native_windows_list2cmdline,
                        "_NATIVE_WINDOWS_DRAIN": _native_windows_drain,
                        "_NATIVE_CREATE_PIPE": winapi.CreatePipe,
                        "_NATIVE_GET_CURRENT_PROCESS": winapi.GetCurrentProcess,
                        "_NATIVE_DUPLICATE_HANDLE": winapi.DuplicateHandle,
                        "_NATIVE_DUPLICATE_SAME_ACCESS": winapi.DUPLICATE_SAME_ACCESS,
                        "_NATIVE_CLOSE_HANDLE": winapi.CloseHandle,
                        "_NATIVE_STARTUP_INFO": _NativeWindowsStartupInfo,
                        "_NATIVE_GET_STD_HANDLE": winapi.GetStdHandle,
                        "_NATIVE_STD_INPUT_HANDLE": winapi.STD_INPUT_HANDLE,
                        "_NATIVE_STARTF_USESTDHANDLES": winapi.STARTF_USESTDHANDLES,
                        "_NATIVE_CREATE_PROCESS": winapi.CreateProcess,
                        "_NATIVE_CREATE_NO_WINDOW": winapi.CREATE_NO_WINDOW,
                        "_NATIVE_EXTENDED_STARTUPINFO_PRESENT": 0x00080000,
                        "_NATIVE_PEEK_NAMED_PIPE": winapi.PeekNamedPipe,
                        "_NATIVE_READ_FILE": winapi.ReadFile,
                        "_NATIVE_BROKEN_PIPE_ERROR": BrokenPipeError,
                        "_NATIVE_TERMINATE_PROCESS": winapi.TerminateProcess,
                        "_NATIVE_CLEANUP_TERMINATE": winapi.TerminateProcess,
                        "_NATIVE_WAIT_FOR_SINGLE_OBJECT": winapi.WaitForSingleObject,
                        "_NATIVE_CLEANUP_WAIT": winapi.WaitForSingleObject,
                        "_NATIVE_WAIT_TIMEOUT": winapi.WAIT_TIMEOUT,
                        "_NATIVE_WAIT_OBJECT_0": winapi.WAIT_OBJECT_0,
                        "_NATIVE_INFINITE": winapi.INFINITE,
                        "_NATIVE_GET_EXIT_CODE_PROCESS": winapi.GetExitCodeProcess,
                    }
                    template = _native_windows_run
                else:
                    posixsubprocess_module = _ORIGINAL_IMPORT(
                        "_posixsubprocess", {}, {}, (), 0
                    )
                    select_module = _ORIGINAL_IMPORT("select", {}, {}, (), 0)
                    filesystem_encoding = sys.getfilesystemencoding()
                    environment_list = tuple(
                        key.encode(filesystem_encoding, "surrogateescape")
                        + b"="
                        + value.encode(filesystem_encoding, "surrogateescape")
                        for key, value in environment.items()
                    )
                    bindings = {
                        **common,
                        "_NATIVE_PIPE": os_module.pipe,
                        "_NATIVE_CLOSE": os_module.close,
                        "_NATIVE_DUP": os_module.dup,
                        "_NATIVE_FILESYSTEM_ENCODING": filesystem_encoding,
                        "_NATIVE_FORK_EXEC": posixsubprocess_module.fork_exec,
                        "_NATIVE_FORK_EXEC_ABI": _native_posix_fork_exec_abi(
                            sys.version_info[:2]
                        ),
                        "_NATIVE_ENVIRONMENT_LIST": environment_list,
                        "_NATIVE_SET_BLOCKING": os_module.set_blocking,
                        "_NATIVE_SELECT": select_module.select,
                        "_NATIVE_READ": os_module.read,
                        "_NATIVE_KILL": os_module.kill,
                        "_NATIVE_CLEANUP_KILL": os_module.kill,
                        "_NATIVE_SIGKILL": 9,
                        "_NATIVE_WAITPID": os_module.waitpid,
                        "_NATIVE_CLEANUP_WAITPID": os_module.waitpid,
                        "_NATIVE_WNOHANG": os_module.WNOHANG,
                        "_NATIVE_RAISE_EXEC_ERROR": _native_posix_raise_exec_error,
                        "_NATIVE_STRERROR": os_module.strerror,
                        "_NATIVE_WAITSTATUS_TO_EXITCODE": (
                            os_module.waitstatus_to_exitcode
                        ),
                    }
                    template = _native_posix_run
                return _bind_native_leaf(template, bindings, {})

            overrides[_ID(run)] = build_native_subprocess_run()
    elif module_name == "json":
        decoder_module = _ORIGINAL_IMPORT(
            "json.decoder",
            {},
            {},
            ("JSONDecoder",),
            0,
        )
        scanner_module = _ORIGINAL_IMPORT(
            "json.scanner",
            {},
            {},
            ("py_make_scanner",),
            0,
        )
        original_decode_error = module.JSONDecodeError
        original_encoder = module.JSONEncoder
        original_decoder = module.JSONDecoder
        sealed_decode_error = _clone_dependency_class(
            original_decode_error,
            function_memo,
            overrides=overrides,
        )
        overrides[_ID(original_decode_error)] = sealed_decode_error
        frozen_backslash = MappingProxyType(_DICT(decoder_module.BACKSLASH))
        frozen_constants = MappingProxyType(_DICT(decoder_module._CONSTANTS))
        scanner_overrides: dict[int, Any] = {
            **overrides,
            _ID(decoder_module.BACKSLASH): frozen_backslash,
            _ID(decoder_module._CONSTANTS): frozen_constants,
        }
        sealed_scanstring = _clone_dependency_function(
            decoder_module.py_scanstring,
            function_memo,
            overrides=scanner_overrides,
        )
        if sealed_scanstring.__defaults__ is not None:
            sealed_scanstring.__defaults__ = tuple(
                scanner_overrides.get(_ID(value), value)
                for value in sealed_scanstring.__defaults__
            )
        sealed_make_scanner = _clone_dependency_function(
            scanner_module.py_make_scanner,
            function_memo,
            overrides=scanner_overrides,
        )
        sealed_scanner = _FrozenModuleView(
            "json.scanner",
            {"make_scanner": sealed_make_scanner},
        )
        overrides.update(
            {
                _ID(decoder_module.BACKSLASH): frozen_backslash,
                _ID(decoder_module._CONSTANTS): frozen_constants,
                _ID(decoder_module.scanstring): sealed_scanstring,
                _ID(decoder_module.scanner): sealed_scanner,
            }
        )
        sealed_encoder = _clone_dependency_class(
            original_encoder,
            function_memo,
            overrides=overrides,
        )
        overrides[_ID(original_encoder)] = sealed_encoder
        sealed_decoder = _clone_dependency_class(
            original_decoder,
            function_memo,
            overrides=overrides,
        )
        overrides[_ID(original_decoder)] = sealed_decoder
        overrides[_ID(module._default_encoder)] = sealed_encoder()
        overrides[_ID(module._default_decoder)] = sealed_decoder()
    return overrides


def _clone_repository_function(
    function: types.FunctionType,
    *,
    importer: _SealedImporter,
    memo: dict[int, types.FunctionType],
) -> types.FunctionType:
    identity = id(function)
    existing = memo.get(identity)
    if existing is not None:
        return existing
    builtin_snapshot = dict(_BUILTINS_NAMESPACE)
    builtin_snapshot["__import__"] = importer
    namespace: dict[str, Any] = {
        "__name__": function.__module__,
        "__package__": function.__module__.rpartition(".")[0],
        "__builtins__": builtin_snapshot,
    }
    clone = types.FunctionType(
        function.__code__,
        namespace,
        function.__name__,
        None,
        None,
    )
    clone.__qualname__ = function.__qualname__
    memo[identity] = clone
    for name in _referenced_global_names(function.__code__):
        if name not in function.__globals__:
            continue
        helper = function.__globals__[name]
        if type(helper) is not types.FunctionType or helper.__module__ != function.__module__:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed repository global {name!r} is not a same-module helper"
            )
        namespace[name] = _clone_repository_function(
            helper,
            importer=importer,
            memo=memo,
        )
    return clone


def _build_sealed_operation(
    invoke: types.FunctionType,
    output_digests: types.FunctionType,
) -> _SealedProviderOperation:
    functions = _repository_function_closure((invoke, output_digests))
    imports = tuple(
        sorted(
            {
                module_name
                for function in functions
                for module_name in _imported_module_names(function.__code__)
            }
        )
    )
    unknown = tuple(name for name in imports if name not in _SEALED_IMPORT_MEMBERS)
    if unknown:
        raise ProviderExecutableObjectRegistryBindingError(
            "sealed provider imports are not admitted: " + ", ".join(unknown)
        )

    dependency_memo: dict[int, types.FunctionType] = {}
    module_views: dict[str, _FrozenModuleView] = {}
    records: list[_SealedDependencyRecord] = []
    manifest_imports: list[dict[str, Any]] = []
    for module_name in imports:
        try:
            module = _ORIGINAL_IMPORT(module_name, {}, {}, (), 0)
        except (ImportError, TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed provider dependency {module_name!r} could not be resolved"
            ) from exc
        if type(module) is not types.ModuleType or module.__name__ != module_name:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed provider dependency {module_name!r} is not an exact module"
            )
        module_overrides = _sealed_module_overrides(
            module_name,
            module,
            dependency_memo,
        )
        members: dict[str, Any] = {}
        member_rows: list[dict[str, Any]] = []
        for member_name in _SEALED_IMPORT_MEMBERS[module_name]:
            try:
                member = getattr(module, member_name)
            except AttributeError as exc:
                raise ProviderExecutableObjectRegistryBindingError(
                    f"sealed provider dependency {module_name}.{member_name} is missing"
                ) from exc
            descriptor = _dependency_value_descriptor(member)
            sealed_member = module_overrides.get(_ID(member))
            if sealed_member is None:
                sealed_member = (
                    _clone_dependency_function(
                        member,
                        dependency_memo,
                        overrides=module_overrides,
                    )
                    if type(member) is types.FunctionType
                    else member
                )
            manifest_descriptor: Mapping[str, Any] = descriptor
            if sealed_member is not member:
                manifest_descriptor = {
                    "ambient_member": descriptor,
                    "sealed_execution_leaf": _dependency_value_descriptor(
                        sealed_member
                    ),
                }
            members[member_name] = sealed_member
            records.append(
                _SealedDependencyRecord(
                    module_name=module_name,
                    module=module,
                    member_name=member_name,
                    member=member,
                    descriptor=MappingProxyType(dict(descriptor)),
                )
            )
            member_rows.append(
                {"name": member_name, "descriptor": manifest_descriptor}
            )
        module_views[module_name] = _FrozenModuleView(module_name, members)
        manifest_imports.append(
            {"module": module_name, "members": member_rows}
        )

    builtin_names = {
        name
        for function in functions
        for name in _referenced_global_names(function.__code__)
        if name not in function.__globals__
    }
    builtin_names.add("__import__")
    builtin_records: list[_SealedBuiltinRecord] = []
    builtin_rows: list[dict[str, Any]] = []
    for name in sorted(builtin_names):
        if name not in _BUILTINS_NAMESPACE:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed provider builtin {name!r} is unresolved"
            )
        value = _BUILTINS_NAMESPACE[name]
        builtin_records.append(_SealedBuiltinRecord(name=name, value=value))
        builtin_rows.append(
            {
                "name": name,
                "module": getattr(value, "__module__", "builtins"),
                "qualname": getattr(value, "__qualname__", name),
            }
        )

    manifest = {
        "schema": _DEPENDENCY_SCHEMA,
        "invoke_target": f"{invoke.__module__}:{invoke.__qualname__}",
        "output_digests_target": (
            f"{output_digests.__module__}:{output_digests.__qualname__}"
        ),
        "imports": manifest_imports,
        "builtins": builtin_rows,
        "python_cache_tag": getattr(sys.implementation, "cache_tag", None),
    }
    importer = _SealedImporter(module_views)
    repository_memo: dict[int, types.FunctionType] = {}
    return _SealedProviderOperation(
        invoke=_clone_repository_function(
            invoke,
            importer=importer,
            memo=repository_memo,
        ),
        output_digests=_clone_repository_function(
            output_digests,
            importer=importer,
            memo=repository_memo,
        ),
        dependency_manifest_sha256=_stable_canonical_sha(manifest),
        dependency_records=tuple(records),
        builtin_records=tuple(builtin_records),
        original_import=_ORIGINAL_IMPORT,
    )


def _verify_sealed_dependency_snapshot(operation: _SealedProviderOperation) -> None:
    _verify_verifier_builtin_snapshot()
    if builtins.__import__ is not operation.original_import:
        raise ProviderExecutableObjectRegistryBindingError(
            "sealed provider import authority changed after admission"
        )
    for record in operation.builtin_records:
        if _BUILTINS_LIVE.get(record.name) is not record.value:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed provider builtin {record.name!r} changed after admission"
            )
    for record in operation.dependency_records:
        if _SYS_MODULES.get(record.module_name) is not record.module:
            raise ProviderExecutableObjectRegistryBindingError(
                f"sealed provider module {record.module_name!r} changed after admission"
            )
        if _GETATTR(record.module, record.member_name, None) is not record.member:
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed provider dependency "
                f"{record.module_name}.{record.member_name} changed after admission"
            )
        if _dependency_value_descriptor(record.member) != record.descriptor:
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed provider dependency "
                f"{record.module_name}.{record.member_name} state changed after admission"
            )


def _verify_builtin_reference(function: types.FunctionType, name: str, label: str) -> None:
    if function.__builtins__ is not builtins.__dict__:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function does not use the canonical builtins namespace"
        )
    value = builtins.__dict__.get(name)
    if value is None and name not in builtins.__dict__:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} references unresolved ambient name {name!r}"
        )
    if isinstance(value, type):
        if value.__module__ != "builtins" or value.__name__ != name:
            raise ProviderExecutableObjectRegistryBindingError(
                f"{label} builtin reference {name!r} is not canonical"
            )
        return
    if type(value) is types.BuiltinFunctionType:
        if value.__module__ != "builtins" or value.__name__ != name:
            raise ProviderExecutableObjectRegistryBindingError(
                f"{label} builtin reference {name!r} is not canonical"
            )
        return
    raise ProviderExecutableObjectRegistryBindingError(
        f"{label} builtin reference {name!r} has unsupported ambient state"
    )


def _verify_function_ambient_dependencies(
    function: types.FunctionType,
    *,
    source: bytes,
    source_path: Path,
    label: str,
    visiting: set[int] | None = None,
) -> None:
    """Refuse executable semantics that depend on mutable ambient module state.

    Admissible global resolution is intentionally narrow: canonical builtins or
    direct same-module helper functions whose source, bytecode and own ambient
    dependencies can be re-proved from the same authenticated source bytes.
    Module objects, mutable containers, imported callables, aliases, constants,
    and arbitrary objects fail closed. This is evidence hardening, not a loader:
    execution remains forbidden until a later packet seals the namespace used by
    the broker.
    """

    if type(function) is not types.FunctionType:
        raise ProviderExecutableObjectRegistryShapeError(
            f"{label} must be an exact Python function"
        )
    if function.__builtins__ is not builtins.__dict__:
        raise ProviderExecutableObjectRegistryBindingError(
            f"{label} function does not use the canonical builtins namespace"
        )

    active = set() if visiting is None else visiting
    identity = id(function)
    if identity in active:
        return
    active.add(identity)
    try:
        for name in _referenced_global_names(function.__code__):
            if name not in function.__globals__:
                _verify_builtin_reference(function, name, label)
                continue

            dependency = function.__globals__[name]
            if type(dependency) is not types.FunctionType:
                raise ProviderExecutableObjectRegistryBindingError(
                    f"{label} ambient global {name!r} is not an admissible "
                    "same-module helper function"
                )
            if dependency.__module__ != function.__module__:
                raise ProviderExecutableObjectRegistryBindingError(
                    f"{label} ambient helper {name!r} comes from another module"
                )
            if dependency.__qualname__ != name:
                raise ProviderExecutableObjectRegistryBindingError(
                    f"{label} ambient helper {name!r} is rebound or aliased"
                )

            dependency_label = f"{label} ambient helper {name!r}"
            dependency_target = _canonical_function_target(
                dependency,
                dependency_label,
            )
            _verify_function_state(dependency, dependency_label)
            _function_source_path(dependency, source_path, dependency_label)
            expected_dependency = _compiled_target_code(source, dependency_target)
            if _code_sha256(dependency.__code__) != _code_sha256(expected_dependency):
                raise ProviderExecutableObjectRegistryBindingError(
                    f"{dependency_label} loaded bytecode differs from authenticated "
                    "repository source"
                )
            _verify_function_ambient_dependencies(
                dependency,
                source=source,
                source_path=source_path,
                label=dependency_label,
                visiting=active,
            )
    finally:
        active.remove(identity)


@dataclass(frozen=True)
class ProviderExecutableObjectAdmissionReceipt:
    """Evidence that exact loaded functions match one pre-admitted source subject."""

    pre_admission_sha256: str
    source_revision: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    invoke_target: str
    invoke_source_sha256: str
    invoke_code_sha256: str
    output_digests_target: str
    output_digests_source_sha256: str
    output_digests_code_sha256: str
    dependency_manifest_sha256: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
                "execution_id",
                "idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in (
                "pre_admission_sha256",
                "invoke_source_sha256",
                "invoke_code_sha256",
                "output_digests_source_sha256",
                "output_digests_code_sha256",
                "dependency_manifest_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "invoke_target",
                _target(self.invoke_target, "invoke_target"),
            )
            object.__setattr__(
                self,
                "output_digests_target",
                _target(self.output_digests_target, "output_digests_target"),
            )
        except ProviderExecutableObjectRegistryError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryShapeError(
                "provider executable object admission receipt is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "pre_admission_sha256": self.pre_admission_sha256,
            "source_revision": self.source_revision,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "invoke_target": self.invoke_target,
            "invoke_source_sha256": self.invoke_source_sha256,
            "invoke_code_sha256": self.invoke_code_sha256,
            "output_digests_target": self.output_digests_target,
            "output_digests_source_sha256": self.output_digests_source_sha256,
            "output_digests_code_sha256": self.output_digests_code_sha256,
            "dependency_manifest_sha256": self.dependency_manifest_sha256,
            **{field: True for field in _TRUE_CLAIMS},
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableObjectAdmissionReceipt":
        fields = {
            "pre_admission_sha256",
            "source_revision",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "invoke_target",
            "invoke_source_sha256",
            "invoke_code_sha256",
            "output_digests_target",
            "output_digests_source_sha256",
            "output_digests_code_sha256",
            "dependency_manifest_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *_TRUE_CLAIMS,
            *_FALSE_CLAIMS,
        }:
            raise ProviderExecutableObjectRegistryShapeError(
                "provider executable object admission fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderExecutableObjectRegistryShapeError(
                "provider executable object admission schema is wrong"
            )
        for field in _TRUE_CLAIMS:
            if payload[field] is not True:
                raise ProviderExecutableObjectRegistryShapeError(
                    f"provider executable object admission lost claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderExecutableObjectRegistryShapeError(
                    f"provider executable object admission escalated claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderExecutableObjectRegistryError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryShapeError(
                "provider executable object admission is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return _stable_canonical_sha(self.to_dict())


@dataclass(frozen=True)
class _RegisteredProviderExecutableObjects:
    pre_admission: ProviderExecutablePreAdmissionReceipt
    invoke: types.FunctionType
    output_digests: types.FunctionType
    sealed_operation: _SealedProviderOperation
    admission: ProviderExecutableObjectAdmissionReceipt


class ProviderExecutableObjectRegistry:
    """Fail-closed registry for pre-admitted, already-loaded provider functions."""

    @staticmethod
    def _verify_verifier_environment() -> None:
        _verify_verifier_builtin_snapshot()

    def _matching_entry_before_canonicalization(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
    ) -> _RegisteredProviderExecutableObjects | None:
        """Find an exact equal receipt without invoking canonical JSON/hash code."""

        match = None
        for candidate in self._entries.values():
            if candidate.pre_admission == pre_admission:
                if match is not None and match is not candidate:
                    raise ProviderExecutableObjectRegistryBindingError(
                        "equal pre-admission subjects have ambiguous executable entries"
                    )
                match = candidate
        return match

    def __init__(self, repository_root: Path) -> None:
        if not isinstance(repository_root, Path):
            raise ProviderExecutableObjectRegistryShapeError(
                "repository_root must be pathlib.Path"
            )
        try:
            root = repository_root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                "repository_root could not be resolved"
            ) from exc
        if not root.is_dir():
            raise ProviderExecutableObjectRegistryBindingError(
                "repository_root must resolve to a directory"
            )
        self._repository_root = root
        self._entries: dict[str, _RegisteredProviderExecutableObjects] = {}

    def _verify_pair(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
        invoke: types.FunctionType,
        output_digests: types.FunctionType,
        *,
        dependency_manifest_sha256: str,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        subject = _canonical_pre_admission(pre_admission)
        invoke_target = _canonical_function_target(invoke, "invoke")
        output_target = _canonical_function_target(output_digests, "output_digests")
        if invoke_target != subject.invoke_target:
            raise ProviderExecutableObjectRegistryBindingError(
                "invoke function target differs from pre-admission"
            )
        if output_target != subject.output_digests_target:
            raise ProviderExecutableObjectRegistryBindingError(
                "output_digests function target differs from pre-admission"
            )

        _verify_function_state(invoke, "invoke")
        _verify_function_state(output_digests, "output_digests")

        invoke_path = _repository_source_path(self._repository_root, invoke_target)
        output_path = _repository_source_path(self._repository_root, output_target)
        _function_source_path(invoke, invoke_path, "invoke")
        _function_source_path(output_digests, output_path, "output_digests")

        if output_path == invoke_path and (
            subject.invoke_source_sha256 != subject.output_digests_source_sha256
        ):
            raise ProviderExecutableObjectRegistryBindingError(
                "same provider source file has contradictory authenticated digests"
            )

        try:
            invoke_source = invoke_path.read_bytes()
            output_source = (
                invoke_source if output_path == invoke_path else output_path.read_bytes()
            )
        except OSError as exc:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider repository source bytes could not be read"
            ) from exc
        invoke_source_sha = _SHA256(invoke_source).hexdigest()
        output_source_sha = _SHA256(output_source).hexdigest()
        if invoke_source_sha != subject.invoke_source_sha256:
            raise ProviderExecutableObjectRegistryBindingError(
                "invoke repository source digest differs from pre-admission"
            )
        if output_source_sha != subject.output_digests_source_sha256:
            raise ProviderExecutableObjectRegistryBindingError(
                "output_digests repository source digest differs from pre-admission"
            )

        _verify_function_ambient_dependencies(
            invoke,
            source=invoke_source,
            source_path=invoke_path,
            label="invoke",
        )
        _verify_function_ambient_dependencies(
            output_digests,
            source=output_source,
            source_path=output_path,
            label="output_digests",
        )

        expected_invoke = _compiled_target_code(invoke_source, invoke_target)
        expected_output = _compiled_target_code(output_source, output_target)
        expected_invoke_sha = _code_sha256(expected_invoke)
        expected_output_sha = _code_sha256(expected_output)
        actual_invoke_sha = _code_sha256(invoke.__code__)
        actual_output_sha = _code_sha256(output_digests.__code__)
        if actual_invoke_sha != expected_invoke_sha:
            raise ProviderExecutableObjectRegistryBindingError(
                "invoke loaded bytecode differs from authenticated repository source"
            )
        if actual_output_sha != expected_output_sha:
            raise ProviderExecutableObjectRegistryBindingError(
                "output_digests loaded bytecode differs from authenticated repository source"
            )

        return ProviderExecutableObjectAdmissionReceipt(
            pre_admission_sha256=_stable_canonical_sha(subject.to_dict()),
            source_revision=subject.source_revision,
            provider_id=subject.provider_id,
            adapter_id=subject.adapter_id,
            implementation_id=subject.implementation_id,
            entrypoint_id=subject.entrypoint_id,
            runtime_id=subject.runtime_id,
            execution_id=subject.execution_id,
            idempotency_key=subject.idempotency_key,
            invoke_target=subject.invoke_target,
            invoke_source_sha256=subject.invoke_source_sha256,
            invoke_code_sha256=actual_invoke_sha,
            output_digests_target=subject.output_digests_target,
            output_digests_source_sha256=subject.output_digests_source_sha256,
            output_digests_code_sha256=actual_output_sha,
            dependency_manifest_sha256=dependency_manifest_sha256,
        )

    def register(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
        *,
        invoke: types.FunctionType,
        output_digests: types.FunctionType,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        preliminary = self._verify_pair(
            pre_admission,
            invoke,
            output_digests,
            dependency_manifest_sha256="0" * 64,
        )
        sealed_operation = _build_sealed_operation(invoke, output_digests)
        admission = ProviderExecutableObjectAdmissionReceipt.from_dict(
            {
                **preliminary.to_dict(),
                "dependency_manifest_sha256": (
                    sealed_operation.dependency_manifest_sha256
                ),
            }
        )
        key = admission.pre_admission_sha256
        existing = self._entries.get(key)
        if existing is not None:
            if existing.invoke is not invoke or existing.output_digests is not output_digests:
                raise ProviderExecutableObjectRegistryBindingError(
                    "pre-admission is already bound to different executable objects"
                )
            if existing.admission != admission:
                raise ProviderExecutableObjectRegistryBindingError(
                    "registered executable-object evidence changed"
                )
            return admission
        self._entries[key] = _RegisteredProviderExecutableObjects(
            pre_admission=pre_admission,
            invoke=invoke,
            output_digests=output_digests,
            sealed_operation=sealed_operation,
            admission=admission,
        )
        return admission

    def verify_registered(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        _verify_verifier_builtin_snapshot()
        if _EXACT_TYPE(pre_admission) is not ProviderExecutablePreAdmissionReceipt:
            raise ProviderExecutableObjectRegistryShapeError(
                "pre_admission must be exact ProviderExecutablePreAdmissionReceipt"
            )
        matching_entry = self._matching_entry_before_canonicalization(pre_admission)
        if matching_entry is not None:
            _verify_sealed_dependency_snapshot(matching_entry.sealed_operation)
        subject = _canonical_pre_admission(pre_admission)
        subject_digest = _stable_canonical_sha(subject.to_dict())
        entry = self._entries.get(subject_digest)
        if entry is None:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider executable objects are not registered for pre-admission"
            )
        _verify_sealed_dependency_snapshot(entry.sealed_operation)
        if entry.pre_admission != subject:
            raise ProviderExecutableObjectRegistryBindingError(
                "registered pre-admission subject changed"
            )
        current = self._verify_pair(
            subject,
            entry.invoke,
            entry.output_digests,
            dependency_manifest_sha256=(
                entry.sealed_operation.dependency_manifest_sha256
            ),
        )
        if current != entry.admission:
            raise ProviderExecutableObjectRegistryBindingError(
                "registered executable-object evidence changed"
            )
        return current

    def _verify_sealed_operation(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
        payload: ProviderInvocationPayload,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        """Verify the fixed payload ABI without executing registered code."""

        _verify_verifier_builtin_snapshot()
        if _EXACT_TYPE(pre_admission) is not ProviderExecutablePreAdmissionReceipt:
            raise ProviderExecutableObjectRegistryShapeError(
                "pre_admission must be exact ProviderExecutablePreAdmissionReceipt"
            )
        matching_entry = self._matching_entry_before_canonicalization(pre_admission)
        if matching_entry is not None:
            _verify_sealed_dependency_snapshot(matching_entry.sealed_operation)
        subject = _canonical_pre_admission(pre_admission)
        if type(payload) is not ProviderInvocationPayload:
            raise ProviderExecutableObjectRegistryShapeError(
                "payload must be exact ProviderInvocationPayload"
            )
        if (
            payload.provider_id != subject.provider_id
            or payload.adapter_id != subject.adapter_id
            or payload.invocation_subject_sha256
            != subject.invocation_subject_sha256
        ):
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed payload differs from executable pre-admission subject"
            )
        admission = self.verify_registered(subject)
        entry = self._entries.get(_stable_canonical_sha(subject.to_dict()))
        if entry is None:  # verify_registered already refuses; retain fail-closed shape.
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed provider executable objects disappeared after verification"
            )
        _verify_sealed_signature(entry.invoke, ("payload",), "invoke")
        _verify_sealed_signature(
            entry.output_digests,
            ("value", "payload"),
            "output_digests",
        )
        return admission

    def _execute_sealed_operation(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
        payload: ProviderInvocationPayload,
        *,
        authorization: RuntimeBoundEffectAuthorization,
        execution: EffectExecutionRequest,
        start_receipt: LeasedEffectStartReceipt,
    ) -> tuple[Any, Any]:
        """Execute one fixed operation only after its exact durable Effect start."""

        if type(authorization) is not RuntimeBoundEffectAuthorization:
            raise ProviderExecutableObjectRegistryShapeError(
                "authorization must be exact RuntimeBoundEffectAuthorization"
            )
        if type(execution) is not EffectExecutionRequest:
            raise ProviderExecutableObjectRegistryShapeError(
                "execution must be exact EffectExecutionRequest"
            )
        if type(start_receipt) is not LeasedEffectStartReceipt:
            raise ProviderExecutableObjectRegistryShapeError(
                "start_receipt must be exact LeasedEffectStartReceipt"
            )
        ProviderExecutableObjectRegistry._verify_sealed_operation(
            self,
            pre_admission,
            payload,
        )
        subject = _canonical_pre_admission(pre_admission)
        mismatches = sorted(
            name
            for name, (actual, expected) in {
                "entrypoint_id": (
                    subject.entrypoint_id,
                    authorization.request.entrypoint_id,
                ),
                "runtime_id": (subject.runtime_id, authorization.capability.runtime_id),
                "execution_id": (subject.execution_id, execution.execution_id),
                "idempotency_key": (
                    subject.idempotency_key,
                    execution.idempotency_key,
                ),
                "lease_sha256": (
                    subject.lease_sha256,
                    authorization.capability.lease.digest,
                ),
                "source_revision": (
                    subject.source_revision,
                    authorization.capability.source_revision,
                ),
                "start_execution_id": (
                    start_receipt.execution_id,
                    execution.execution_id,
                ),
                "start_idempotency_key": (
                    start_receipt.idempotency_key,
                    execution.idempotency_key,
                ),
                "start_execution_request_sha256": (
                    start_receipt.execution_request_sha256,
                    execution.digest,
                ),
                "start_lease_sha256": (
                    start_receipt.lease_sha256,
                    authorization.capability.lease.digest,
                ),
            }.items()
            if actual != expected
        )
        if mismatches:
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed operation start subject mismatch: " + ", ".join(mismatches)
            )
        authorization.verify()
        if authorization.effect_ledger.execution_state(execution.execution_id) != "STARTED":
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed operation requires the exact persisted STARTED execution"
            )
        entry = self._entries.get(_stable_canonical_sha(subject.to_dict()))
        if entry is None:
            raise ProviderExecutableObjectRegistryBindingError(
                "sealed provider executable objects disappeared before execution"
            )
        body = payload.to_dict()["body"]
        value = entry.sealed_operation.invoke(body)
        try:
            output_digests = entry.sealed_operation.output_digests(value, body)
        except BaseException as exc:
            raise ProviderSealedOutputEvidenceError(
                "sealed provider output-evidence operation failed after invocation"
            ) from exc
        return value, output_digests


__all__ = [
    "ProviderExecutableObjectAdmissionReceipt",
    "ProviderExecutableObjectRegistry",
    "ProviderExecutableObjectRegistryBindingError",
    "ProviderExecutableObjectRegistryError",
    "ProviderExecutableObjectRegistryShapeError",
    "ProviderSealedOutputEvidenceError",
]
