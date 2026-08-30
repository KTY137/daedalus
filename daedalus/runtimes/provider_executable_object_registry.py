# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Guarded in-process admission for revision-bound provider executable objects.

The pre-admission packet proves *which* provider implementation and repository
targets are authorized to be considered. This module proves that the concrete
Python function objects already present in the process still correspond to
those exact targets, repository bytes, and a deliberately narrow ambient-global
dependency closure.

It intentionally does not import modules, execute provider code, start effects,
or grant provider authority. A later broker packet must still construct a
sealed execution namespace before these objects can become executable; until
then, an admission receipt remains evidence only.
"""
from __future__ import annotations

import builtins
import dis
import hashlib
import inspect
import marshal
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


_SCHEMA = "daedalus-provider-executable-object-admission/1"
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
    return hashlib.sha256(marshal.dumps(normalized)).hexdigest()


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
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class _RegisteredProviderExecutableObjects:
    pre_admission: ProviderExecutablePreAdmissionReceipt
    invoke: types.FunctionType
    output_digests: types.FunctionType
    admission: ProviderExecutableObjectAdmissionReceipt


class ProviderExecutableObjectRegistry:
    """Fail-closed registry for pre-admitted, already-loaded provider functions."""

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
        invoke_source_sha = hashlib.sha256(invoke_source).hexdigest()
        output_source_sha = hashlib.sha256(output_source).hexdigest()
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
            pre_admission_sha256=subject.digest,
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
        )

    def register(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
        *,
        invoke: types.FunctionType,
        output_digests: types.FunctionType,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        admission = self._verify_pair(pre_admission, invoke, output_digests)
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
            admission=admission,
        )
        return admission

    def verify_registered(
        self,
        pre_admission: ProviderExecutablePreAdmissionReceipt,
    ) -> ProviderExecutableObjectAdmissionReceipt:
        subject = _canonical_pre_admission(pre_admission)
        entry = self._entries.get(subject.digest)
        if entry is None:
            raise ProviderExecutableObjectRegistryBindingError(
                "provider executable objects are not registered for pre-admission"
            )
        if entry.pre_admission != subject:
            raise ProviderExecutableObjectRegistryBindingError(
                "registered pre-admission subject changed"
            )
        current = self._verify_pair(
            subject,
            entry.invoke,
            entry.output_digests,
        )
        if current != entry.admission:
            raise ProviderExecutableObjectRegistryBindingError(
                "registered executable-object evidence changed"
            )
        return current


__all__ = [
    "ProviderExecutableObjectAdmissionReceipt",
    "ProviderExecutableObjectRegistry",
    "ProviderExecutableObjectRegistryBindingError",
    "ProviderExecutableObjectRegistryError",
    "ProviderExecutableObjectRegistryShapeError",
]
