"""Authenticated read-only structural verification for provider targets.

The signed target authority authenticates which local Python objects and source
digests belong to one provider invocation.  This module replays that complete
authentication before reading repository bytes, proves that both objects exist
uniquely in the selected tree, and retains the result in a deterministic
receipt.

Structural verification is deliberately weaker than executable admission.  No
module is imported, no decorator is evaluated, and no provider or output
materializer is called.  The receipt cannot grant effect or provider-execution
authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.runtimes.contracts.ports import PythonTargetStructureResolver
from daedalus.runtimes.contracts.python_targets import (
    PythonTargetStructure,
    PythonTargetStructureError,
)
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider.executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetError,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
    project_provider_executable_targets,
)
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider.invocation_registry import (
    ProviderInvocationRegistryManifest,
)
from daedalus.kernel.contracts.base import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


class ProviderExecutableStructureError(RuntimeError):
    """Base class for provider target structural-verification failures."""


class ProviderExecutableStructureShapeError(ProviderExecutableStructureError):
    """A verification subject or receipt is malformed."""


class ProviderExecutableStructureBindingError(ProviderExecutableStructureError):
    """Authenticated authority or repository structure differs from the subject."""


def _strict_int(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProviderExecutableStructureShapeError(
            f"{label} must be a strict integer >= {minimum}"
        )
    return value


def _strict_role(value: Any) -> str:
    if value not in {"invoke", "output_digests"}:
        raise ProviderExecutableStructureShapeError(
            "target role must be invoke or output_digests"
        )
    return value


def _target_subject(structure: PythonTargetStructure) -> dict[str, Any]:
    return {
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
        object.__setattr__(self, "role", _strict_role(self.role))
        try:
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
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "verified target digest fields are malformed"
            ) from exc
        for value, label, minimum in (
            (self.source_size, "source_size", 0),
            (self.line, "line", 1),
            (self.column, "column", 0),
            (self.end_line, "end_line", 1),
            (self.end_column, "end_column", 0),
        ):
            _strict_int(value, label, minimum)
        if not isinstance(self.target, str) or not self.target:
            raise ProviderExecutableStructureShapeError(
                "target must be non-empty"
            )
        if not isinstance(self.source_path, str) or not self.source_path:
            raise ProviderExecutableStructureShapeError(
                "source_path must be non-empty"
            )
        allowed = {"function", "async_function", "class"}
        if self.definition_kind not in allowed:
            raise ProviderExecutableStructureShapeError(
                "definition_kind is unsupported"
            )
        if type(self.chain_kinds) is not tuple or not self.chain_kinds:
            raise ProviderExecutableStructureShapeError(
                "chain_kinds must be a non-empty exact tuple"
            )
        if any(kind not in allowed for kind in self.chain_kinds):
            raise ProviderExecutableStructureShapeError(
                "chain_kinds contains an unsupported kind"
            )
        if self.chain_kinds[-1] != self.definition_kind:
            raise ProviderExecutableStructureBindingError(
                "definition_kind differs from the chain terminal"
            )
        if self.end_line < self.line:
            raise ProviderExecutableStructureBindingError(
                "target definition end precedes its start"
            )
        if self.structure_sha256 != canonical_sha(self._subject()):
            raise ProviderExecutableStructureBindingError(
                "target structure digest differs from retained fields"
            )

    def _subject(self) -> dict[str, Any]:
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
            **self._subject(),
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
                "target must retain structural verification"
            )
        if (
            payload["behavior_verified"] is not False
            or payload["executed"] is not False
        ):
            raise ProviderExecutableStructureShapeError(
                "structural target cannot claim behavior or execution"
            )
        if not isinstance(payload["chain_kinds"], list):
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
                chain_kinds=tuple(payload["chain_kinds"]),
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
    """Deterministic receipt for authenticated, structurally verified targets."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    source_revision: str
    target_contract_id: str
    lease_sha256: str
    target_authority_sha256: str
    invocation_authority_sha256: str
    invocation_contract_sha256: str
    identity_sha256: str
    identity_registry_sha256: str
    identity_descriptor_sha256: str
    target_projection_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
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
                "execution_id",
                "idempotency_key",
                "target_contract_id",
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
                "lease_sha256",
                "target_authority_sha256",
                "invocation_authority_sha256",
                "invocation_contract_sha256",
                "identity_sha256",
                "identity_registry_sha256",
                "identity_descriptor_sha256",
                "target_projection_sha256",
                "target_manifest_sha256",
                "target_descriptor_sha256",
                "adapter_artifact_sha256",
                "adapter_config_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "structure receipt identity is malformed"
            ) from exc
        if type(self.invoke) is not VerifiedProviderExecutableTarget:
            raise ProviderExecutableStructureShapeError(
                "invoke must be an exact verified target"
            )
        if type(self.output_digests) is not VerifiedProviderExecutableTarget:
            raise ProviderExecutableStructureShapeError(
                "output_digests must be an exact verified target"
            )
        if (
            self.invoke.role != "invoke"
            or self.output_digests.role != "output_digests"
        ):
            raise ProviderExecutableStructureBindingError(
                "verified targets have incorrect roles"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-executable-structure-receipt/2",
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "source_revision": self.source_revision,
            "target_contract_id": self.target_contract_id,
            "lease_sha256": self.lease_sha256,
            "target_authority_sha256": self.target_authority_sha256,
            "invocation_authority_sha256": self.invocation_authority_sha256,
            "invocation_contract_sha256": self.invocation_contract_sha256,
            "identity_sha256": self.identity_sha256,
            "identity_registry_sha256": self.identity_registry_sha256,
            "identity_descriptor_sha256": self.identity_descriptor_sha256,
            "target_projection_sha256": self.target_projection_sha256,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_descriptor_sha256": self.target_descriptor_sha256,
            "adapter_artifact_sha256": self.adapter_artifact_sha256,
            "adapter_config_sha256": self.adapter_config_sha256,
            "invoke": self.invoke.to_dict(),
            "output_digests": self.output_digests.to_dict(),
            "target_authority_authenticated": True,
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
        expected = {
            "schema",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "source_revision",
            "target_contract_id",
            "lease_sha256",
            "target_authority_sha256",
            "invocation_authority_sha256",
            "invocation_contract_sha256",
            "identity_sha256",
            "identity_registry_sha256",
            "identity_descriptor_sha256",
            "target_projection_sha256",
            "target_manifest_sha256",
            "target_descriptor_sha256",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "invoke",
            "output_digests",
            "target_authority_authenticated",
            "targets_structurally_verified",
            "repository_bytes_executed",
            "provider_execution_allowed",
            "source_revision_verified_against_git_head",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableStructureShapeError(
                "structure receipt fields are not exact"
            )
        if payload["schema"] != (
            "daedalus-provider-executable-structure-receipt/2"
        ):
            raise ProviderExecutableStructureShapeError(
                "structure receipt schema does not match"
            )
        if payload["target_authority_authenticated"] is not True:
            raise ProviderExecutableStructureShapeError(
                "structure receipt must retain target-authority authentication"
            )
        if payload["targets_structurally_verified"] is not True:
            raise ProviderExecutableStructureShapeError(
                "structure receipt must retain target verification"
            )
        if (
            payload["repository_bytes_executed"] is not False
            or payload["provider_execution_allowed"] is not False
            or payload["source_revision_verified_against_git_head"] is not False
        ):
            raise ProviderExecutableStructureShapeError(
                "structure receipt contains an authority escalation"
            )
        try:
            return cls(
                provider_id=payload["provider_id"],
                adapter_id=payload["adapter_id"],
                implementation_id=payload["implementation_id"],
                entrypoint_id=payload["entrypoint_id"],
                runtime_id=payload["runtime_id"],
                execution_id=payload["execution_id"],
                idempotency_key=payload["idempotency_key"],
                source_revision=payload["source_revision"],
                target_contract_id=payload["target_contract_id"],
                lease_sha256=payload["lease_sha256"],
                target_authority_sha256=payload[
                    "target_authority_sha256"
                ],
                invocation_authority_sha256=payload[
                    "invocation_authority_sha256"
                ],
                invocation_contract_sha256=payload[
                    "invocation_contract_sha256"
                ],
                identity_sha256=payload["identity_sha256"],
                identity_registry_sha256=payload[
                    "identity_registry_sha256"
                ],
                identity_descriptor_sha256=payload[
                    "identity_descriptor_sha256"
                ],
                target_projection_sha256=payload[
                    "target_projection_sha256"
                ],
                target_manifest_sha256=payload["target_manifest_sha256"],
                target_descriptor_sha256=payload[
                    "target_descriptor_sha256"
                ],
                adapter_artifact_sha256=payload[
                    "adapter_artifact_sha256"
                ],
                adapter_config_sha256=payload["adapter_config_sha256"],
                invoke=VerifiedProviderExecutableTarget.from_dict(
                    payload["invoke"]
                ),
                output_digests=VerifiedProviderExecutableTarget.from_dict(
                    payload["output_digests"]
                ),
            )
        except ProviderExecutableStructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableStructureShapeError(
                "structure receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _retain(
    role: str,
    structure: PythonTargetStructure,
) -> VerifiedProviderExecutableTarget:
    if type(structure) is not PythonTargetStructure:
        raise ProviderExecutableStructureShapeError(
            "resolved target structure type is not exact"
        )
    subject = _target_subject(structure)
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


def _authenticate_projection(
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at: Any,
) -> ProviderExecutableTargetProjection:
    exact_subjects = (
        (
            target_authority,
            ProviderExecutableTargetAuthority,
            "target_authority",
        ),
        (
            invocation_authority,
            ProviderInvocationObservationAuthority,
            "invocation_authority",
        ),
        (
            identity_registry,
            ProviderInvocationRegistryManifest,
            "identity_registry",
        ),
        (execution, EffectExecutionRequest, "execution"),
        (manifest, ProviderExecutableTargetManifest, "manifest"),
    )
    for value, expected, label in exact_subjects:
        if type(value) is not expected:
            raise ProviderExecutableStructureShapeError(
                f"{label} must be exact {expected.__name__}"
            )
    try:
        projection = project_provider_executable_targets(
            target_authority,
            invocation_authority,
            identity_registry,
            execution,
            manifest,
            target_contract_id=target_contract_id,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            at=at,
        )
    except ProviderExecutableTargetError as exc:
        raise ProviderExecutableStructureBindingError(
            "provider executable target authority did not authenticate"
        ) from exc
    if type(projection) is not ProviderExecutableTargetProjection:
        raise ProviderExecutableStructureBindingError(
            "authenticated target projection type is not exact"
        )
    return projection


def verify_provider_executable_structure(
    repository_root: Path,
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at: Any,
    target_resolver: PythonTargetStructureResolver,
) -> ProviderExecutableStructureReceipt:
    """Authenticate target authority, then resolve exact repository structure."""

    if not isinstance(repository_root, Path):
        raise ProviderExecutableStructureShapeError(
            "repository_root must be pathlib.Path"
        )
    if not callable(target_resolver):
        raise ProviderExecutableStructureShapeError(
            "target_resolver must be an injected gate port"
        )
    projection = _authenticate_projection(
        target_authority,
        invocation_authority,
        identity_registry,
        execution,
        manifest,
        target_contract_id=target_contract_id,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        at=at,
    )
    try:
        invoke = target_resolver(
            repository_root,
            projection.invoke_target,
            expected_source_sha256=projection.invoke_source_sha256,
        )
        output = target_resolver(
            repository_root,
            projection.output_digests_target,
            expected_source_sha256=projection.output_digests_source_sha256,
        )
    except PythonTargetStructureError as exc:
        raise ProviderExecutableStructureBindingError(
            "provider executable target structure did not verify"
        ) from exc
    retained_invoke = _retain("invoke", invoke)
    retained_output = _retain("output_digests", output)
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
    if (
        retained_output.source_sha256
        != projection.output_digests_source_sha256
    ):
        raise ProviderExecutableStructureBindingError(
            "output source digest differs from authenticated projection"
        )
    return ProviderExecutableStructureReceipt(
        provider_id=projection.provider_id,
        adapter_id=projection.adapter_id,
        implementation_id=projection.implementation_id,
        entrypoint_id=projection.entrypoint_id,
        runtime_id=projection.runtime_id,
        execution_id=target_authority.execution_id,
        idempotency_key=target_authority.idempotency_key,
        source_revision=projection.source_revision,
        target_contract_id=target_authority.target_contract_id,
        lease_sha256=target_authority.lease_sha256,
        target_authority_sha256=target_authority.digest,
        invocation_authority_sha256=invocation_authority.digest,
        invocation_contract_sha256=(
            invocation_authority.invocation_contract_sha256
        ),
        identity_sha256=projection.identity_sha256,
        identity_registry_sha256=projection.identity_registry_sha256,
        identity_descriptor_sha256=projection.identity_descriptor_sha256,
        target_projection_sha256=projection.digest,
        target_manifest_sha256=projection.target_manifest_sha256,
        target_descriptor_sha256=projection.target_descriptor_sha256,
        adapter_artifact_sha256=projection.adapter_artifact_sha256,
        adapter_config_sha256=projection.adapter_config_sha256,
        invoke=retained_invoke,
        output_digests=retained_output,
    )


def verify_provider_executable_structure_receipt(
    repository_root: Path,
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    receipt: ProviderExecutableStructureReceipt,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at: Any,
    target_resolver: PythonTargetStructureResolver,
) -> None:
    """Re-authenticate and rebuild the receipt; refuse every detached field."""

    if type(receipt) is not ProviderExecutableStructureReceipt:
        raise ProviderExecutableStructureShapeError(
            "receipt must be exact ProviderExecutableStructureReceipt"
        )
    rebuilt = verify_provider_executable_structure(
        repository_root,
        target_authority,
        invocation_authority,
        identity_registry,
        execution,
        manifest,
        target_contract_id=target_contract_id,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        at=at,
        target_resolver=target_resolver,
    )
    if rebuilt.to_dict() != receipt.to_dict():
        raise ProviderExecutableStructureBindingError(
            "structure receipt differs from authenticated live structure"
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
