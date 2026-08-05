"""Read-only structural verification for authenticated provider targets.

The provider executable-target manifest authenticates *which* local Python
objects and source digests belong to one invocation identity.  This module
proves that both objects exist uniquely in the selected repository tree and
retains the exact structural result in a deterministic receipt.

Structural verification is deliberately weaker than executable admission.  No
module is imported, no decorator is evaluated, and no provider or output
materializer is called.  The receipt therefore cannot grant provider execution,
start an effect, or substitute for a revision/HEAD binding or runtime
conformance receipt.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.gates.python_target_structure import (
    PythonTargetStructure,
    PythonTargetStructureError,
    resolve_python_target_structure,
)
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetProjection,
)
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


class ProviderExecutableStructureError(RuntimeError):
    """Base class for provider target structural-verification failures."""


class ProviderExecutableStructureShapeError(ProviderExecutableStructureError):
    """A verification subject or receipt is malformed."""


class ProviderExecutableStructureBindingError(ProviderExecutableStructureError):
    """Repository structure differs from the authenticated target subject."""


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProviderExecutableStructureShapeError(
            f"{label} must be a strict integer >= {minimum}"
        )
    return value


def _strict_role(value: Any) -> str:
    if value not in {"invoke", "output_digests"}:
        raise ProviderExecutableStructureShapeError(
            "provider target role must be invoke or output_digests"
        )
    return value


@dataclass(frozen=True)
class VerifiedProviderExecutableTarget:
    """One exact non-executing Python target structure."""

    role: str
    target: str
    source_path: str
    source_sha256: str
    source_size: int
    definition_kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    chain_kinds: tuple[str, ...]
    structure_sha256: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "role", _strict_role(self.role))
            object.__setattr__(
                self,
                "source_sha256",
                _sha256(self.source_sha256, "source_sha256"),
            )
            object.__setattr__(
                self,
                "structure_sha256",
                _sha256(self.structure_sha256, "structure_sha256"),
            )
            _strict_int(self.source_size, "source_size")
            _strict_int(self.line, "line", minimum=1)
            _strict_int(self.column, "column")
            _strict_int(self.end_line, "end_line", minimum=1)
            _strict_int(self.end_column, "end_column")
        except ProviderExecutableStructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "verified provider target identity is malformed"
            ) from exc
        if not isinstance(self.target, str) or not self.target:
            raise ProviderExecutableStructureShapeError("target must be non-empty")
        if not isinstance(self.source_path, str) or not self.source_path:
            raise ProviderExecutableStructureShapeError(
                "source_path must be non-empty"
            )
        if self.definition_kind not in {"function", "async_function", "class"}:
            raise ProviderExecutableStructureShapeError(
                "definition_kind is unsupported"
            )
        if type(self.chain_kinds) is not tuple or not self.chain_kinds:
            raise ProviderExecutableStructureShapeError(
                "chain_kinds must be a non-empty exact tuple"
            )
        if any(
            kind not in {"function", "async_function", "class"}
            for kind in self.chain_kinds
        ):
            raise ProviderExecutableStructureShapeError(
                "chain_kinds contains an unsupported definition kind"
            )
        if self.chain_kinds[-1] != self.definition_kind:
            raise ProviderExecutableStructureShapeError(
                "definition_kind differs from the chain terminal"
            )
        if self.end_line < self.line:
            raise ProviderExecutableStructureShapeError(
                "target definition end precedes its start"
            )
        if self.structure_sha256 != canonical_sha(self._structure_subject()):
            raise ProviderExecutableStructureBindingError(
                "target structure digest differs from retained fields"
            )

    def _structure_subject(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "definition_kind": self.definition_kind,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
            "chain_kinds": list(self.chain_kinds),
            "structural_target_verified": True,
            "behavior_verified": False,
            "executed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            **self._structure_subject(),
            "structure_sha256": self.structure_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "VerifiedProviderExecutableTarget":
        expected = {
            "role",
            "target",
            "source_path",
            "source_sha256",
            "source_size",
            "definition_kind",
            "line",
            "column",
            "end_line",
            "end_column",
            "chain_kinds",
            "structure_sha256",
            "structural_target_verified",
            "behavior_verified",
            "executed",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableStructureShapeError(
                "verified provider target fields are not exact"
            )
        if payload["structural_target_verified"] is not True:
            raise ProviderExecutableStructureShapeError(
                "verified provider target must retain structural verification"
            )
        if payload["behavior_verified"] is not False:
            raise ProviderExecutableStructureShapeError(
                "structural receipt cannot claim behavior verification"
            )
        if payload["executed"] is not False:
            raise ProviderExecutableStructureShapeError(
                "structural receipt cannot claim target execution"
            )
        chain = payload["chain_kinds"]
        if not isinstance(chain, list):
            raise ProviderExecutableStructureShapeError(
                "chain_kinds must be a JSON list"
            )
        try:
            return cls(
                role=payload["role"],
                target=payload["target"],
                source_path=payload["source_path"],
                source_sha256=payload["source_sha256"],
                source_size=payload["source_size"],
                definition_kind=payload["definition_kind"],
                line=payload["line"],
                column=payload["column"],
                end_line=payload["end_line"],
                end_column=payload["end_column"],
                chain_kinds=tuple(chain),
                structure_sha256=payload["structure_sha256"],
            )
        except ProviderExecutableStructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "verified provider target is malformed"
            ) from exc


@dataclass(frozen=True)
class ProviderExecutableStructureReceipt:
    """Deterministic receipt for two exact structurally verified targets."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    source_revision: str
    identity_sha256: str
    target_projection_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    invoke: VerifiedProviderExecutableTarget
    output_digests: VerifiedProviderExecutableTarget

    def __post_init__(self) -> None:
        try:
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in (
                "identity_sha256",
                "target_projection_sha256",
                "target_manifest_sha256",
                "target_descriptor_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "provider executable structure receipt identity is malformed"
            ) from exc
        if type(self.invoke) is not VerifiedProviderExecutableTarget:
            raise ProviderExecutableStructureShapeError(
                "invoke target must be exact VerifiedProviderExecutableTarget"
            )
        if type(self.output_digests) is not VerifiedProviderExecutableTarget:
            raise ProviderExecutableStructureShapeError(
                "output target must be exact VerifiedProviderExecutableTarget"
            )
        if self.invoke.role != "invoke":
            raise ProviderExecutableStructureBindingError(
                "invoke receipt has the wrong target role"
            )
        if self.output_digests.role != "output_digests":
            raise ProviderExecutableStructureBindingError(
                "output receipt has the wrong target role"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-executable-structure-receipt/1",
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "source_revision": self.source_revision,
            "identity_sha256": self.identity_sha256,
            "target_projection_sha256": self.target_projection_sha256,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_descriptor_sha256": self.target_descriptor_sha256,
            "invoke": self.invoke.to_dict(),
            "output_digests": self.output_digests.to_dict(),
            "targets_structurally_verified": True,
            "repository_bytes_executed": False,
            "provider_execution_allowed": False,
            "source_revision_verified_against_git_head": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableStructureReceipt":
        fields = {
            "schema",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "source_revision",
            "identity_sha256",
            "target_projection_sha256",
            "target_manifest_sha256",
            "target_descriptor_sha256",
            "invoke",
            "output_digests",
            "targets_structurally_verified",
            "repository_bytes_executed",
            "provider_execution_allowed",
            "source_revision_verified_against_git_head",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise ProviderExecutableStructureShapeError(
                "provider executable structure receipt fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-executable-structure-receipt/1":
            raise ProviderExecutableStructureShapeError(
                "provider executable structure receipt schema does not match"
            )
        if payload["targets_structurally_verified"] is not True:
            raise ProviderExecutableStructureShapeError(
                "structure receipt must retain structural verification"
            )
        if payload["repository_bytes_executed"] is not False:
            raise ProviderExecutableStructureShapeError(
                "structure receipt cannot claim repository byte execution"
            )
        if payload["provider_execution_allowed"] is not False:
            raise ProviderExecutableStructureShapeError(
                "structure receipt cannot authorize provider execution"
            )
        if payload["source_revision_verified_against_git_head"] is not False:
            raise ProviderExecutableStructureShapeError(
                "structure receipt cannot claim Git HEAD verification"
            )
        try:
            return cls(
                provider_id=payload["provider_id"],
                adapter_id=payload["adapter_id"],
                implementation_id=payload["implementation_id"],
                entrypoint_id=payload["entrypoint_id"],
                runtime_id=payload["runtime_id"],
                source_revision=payload["source_revision"],
                identity_sha256=payload["identity_sha256"],
                target_projection_sha256=payload["target_projection_sha256"],
                target_manifest_sha256=payload["target_manifest_sha256"],
                target_descriptor_sha256=payload["target_descriptor_sha256"],
                invoke=VerifiedProviderExecutableTarget.from_dict(payload["invoke"]),
                output_digests=VerifiedProviderExecutableTarget.from_dict(
                    payload["output_digests"]
                ),
            )
        except ProviderExecutableStructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "provider executable structure receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _retain_structure(
    role: str,
    structure: PythonTargetStructure,
) -> VerifiedProviderExecutableTarget:
    if type(structure) is not PythonTargetStructure:
        raise ProviderExecutableStructureShapeError(
            "resolved target structure type is not exact"
        )
    subject = {
        "target": structure.target,
        "source_path": structure.source_path,
        "source_sha256": structure.source_sha256,
        "source_size": structure.source_size,
        "definition_kind": structure.definition_kind,
        "line": structure.line,
        "column": structure.column,
        "end_line": structure.end_line,
        "end_column": structure.end_column,
        "chain_kinds": list(structure.chain_kinds),
        "structural_target_verified": True,
        "behavior_verified": False,
        "executed": False,
    }
    return VerifiedProviderExecutableTarget(
        role=role,
        target=structure.target,
        source_path=structure.source_path,
        source_sha256=structure.source_sha256,
        source_size=structure.source_size,
        definition_kind=structure.definition_kind,
        line=structure.line,
        column=structure.column,
        end_line=structure.end_line,
        end_column=structure.end_column,
        chain_kinds=structure.chain_kinds,
        structure_sha256=canonical_sha(subject),
    )


def verify_provider_executable_structure(
    repository_root: Path,
    projection: ProviderExecutableTargetProjection,
) -> ProviderExecutableStructureReceipt:
    """Resolve both exact targets without importing or executing either module."""

    if type(repository_root) is not Path:
        raise ProviderExecutableStructureShapeError(
            "repository_root must be exact pathlib.Path"
        )
    if type(projection) is not ProviderExecutableTargetProjection:
        raise ProviderExecutableStructureShapeError(
            "projection must be exact ProviderExecutableTargetProjection"
        )
    try:
        invoke = resolve_python_target_structure(
            repository_root,
            projection.invoke_target,
            expected_source_sha256=projection.invoke_source_sha256,
        )
        output = resolve_python_target_structure(
            repository_root,
            projection.output_digests_target,
            expected_source_sha256=projection.output_digests_source_sha256,
        )
    except PythonTargetStructureError as exc:
        raise ProviderExecutableStructureBindingError(
            "provider executable target structure did not verify"
        ) from exc
    retained_invoke = _retain_structure("invoke", invoke)
    retained_output = _retain_structure("output_digests", output)
    if retained_invoke.target != projection.invoke_target:
        raise ProviderExecutableStructureBindingError(
            "invoke target differs from authenticated projection"
        )
    if retained_output.target != projection.output_digests_target:
        raise ProviderExecutableStructureBindingError(
            "output target differs from authenticated projection"
        )
    if retained_invoke.source_sha256 != projection.invoke_source_sha256:
        raise ProviderExecutableStructureBindingError(
            "invoke source digest differs from authenticated projection"
        )
    if retained_output.source_sha256 != projection.output_digests_source_sha256:
        raise ProviderExecutableStructureBindingError(
            "output source digest differs from authenticated projection"
        )
    return ProviderExecutableStructureReceipt(
        provider_id=projection.provider_id,
        adapter_id=projection.adapter_id,
        implementation_id=projection.implementation_id,
        entrypoint_id=projection.entrypoint_id,
        runtime_id=projection.runtime_id,
        source_revision=projection.source_revision,
        identity_sha256=projection.identity_sha256,
        target_projection_sha256=projection.digest,
        target_manifest_sha256=projection.target_manifest_sha256,
        target_descriptor_sha256=projection.target_descriptor_sha256,
        invoke=retained_invoke,
        output_digests=retained_output,
    )


def verify_provider_executable_structure_receipt(
    repository_root: Path,
    projection: ProviderExecutableTargetProjection,
    receipt: ProviderExecutableStructureReceipt,
) -> None:
    """Rebuild the exact read-only receipt and refuse any detached field."""

    if type(receipt) is not ProviderExecutableStructureReceipt:
        raise ProviderExecutableStructureShapeError(
            "receipt must be exact ProviderExecutableStructureReceipt"
        )
    rebuilt = verify_provider_executable_structure(repository_root, projection)
    if rebuilt.to_dict() != receipt.to_dict():
        raise ProviderExecutableStructureBindingError(
            "provider executable structure receipt differs from live structure"
        )


__all__ = [
    "ProviderExecutableStructureBindingError",
    "ProviderExecutableStructureError",
    "ProviderExecutableStructureReceipt",
    "ProviderExecutableStructureShapeError",
    "VerifiedProviderExecutableTarget",
    "verify_provider_executable_structure",
    "verify_provider_executable_structure_receipt",
]
