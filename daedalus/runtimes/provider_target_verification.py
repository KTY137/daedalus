# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Read-only structural verification for signed provider executable targets.

Exact CAS-backed Python source bytes are parsed without importing or executing
them. The result is a signed inert receipt; persistence and guarded loading are
separate reviewed packets.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import hmac
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.source_trees import (
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
)
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetError,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
    project_provider_executable_targets,
)
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderInvocationRegistryManifest,
)
from daedalus.runtimes.provider_observation import _normalize_keyring
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    ProviderTargetVerificationBindingError,
    ProviderTargetVerificationError,
    ProviderTargetVerificationSignatureError,
    ProviderTargetVerificationSourceError,
    VerifiedPythonTarget,
    _verification_signature,
)
from daedalus.schemas import _identifier


def _target_parts(target: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(target, str) or target.count(":") != 1:
        raise ProviderTargetVerificationSourceError(
            "target must contain one module/qualified-name separator"
        )
    module, qualified = target.split(":", 1)
    module_parts = tuple(module.split("."))
    qualified_parts = tuple(qualified.split("."))
    if (
        not module_parts
        or module_parts[0] != "daedalus"
        or any(
            not part
            or not part.isidentifier()
            or part.lower() != part
            for part in module_parts
        )
        or not qualified_parts
        or any(not part or not part.isidentifier() for part in qualified_parts)
    ):
        raise ProviderTargetVerificationSourceError(
            "target is not a canonical Daedalus Python target"
        )
    return module, qualified_parts


def _module_paths(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def _entry_for_module(
    manifest: SourceTreeManifest,
    module: str,
) -> SourceTreeEntry:
    candidates = set(_module_paths(module))
    matches = tuple(
        entry for entry in manifest.entries if entry.path in candidates
    )
    if len(matches) != 1:
        raise ProviderTargetVerificationSourceError(
            "target module must resolve to exactly one source-tree file"
        )
    return matches[0]


def _definition_children(
    body: list[ast.stmt],
    name: str,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, ...]:
    return tuple(
        node
        for node in body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
        and node.name == name
    )


def _resolve_definition(
    tree: ast.Module,
    qualified_parts: tuple[str, ...],
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]:
    body = tree.body
    class_depth = 0
    for index, part in enumerate(qualified_parts):
        matches = _definition_children(body, part)
        if len(matches) != 1:
            raise ProviderTargetVerificationSourceError(
                "target qualified name is missing or structurally ambiguous"
            )
        current = matches[0]
        final = index == len(qualified_parts) - 1
        if final:
            if isinstance(current, ast.ClassDef):
                raise ProviderTargetVerificationSourceError(
                    "target must resolve to a function or method"
                )
            if isinstance(current, ast.AsyncFunctionDef):
                return current, "async_method" if class_depth else "async_function"
            return current, "method" if class_depth else "function"
        if not isinstance(current, ast.ClassDef):
            raise ProviderTargetVerificationSourceError(
                "non-final target owner must be an exact class definition"
            )
        class_depth += 1
        body = current.body
    raise ProviderTargetVerificationSourceError(
        "target qualified name is empty"
    )


def _verify_one_target(
    *,
    target: str,
    expected_source_sha256: str,
    source_store: SourceTreeStore,
    source_manifest: SourceTreeManifest,
    max_source_bytes: int,
) -> VerifiedPythonTarget:
    module, qualified_parts = _target_parts(target)
    entry = _entry_for_module(source_manifest, module)
    if entry.blob_sha256 != expected_source_sha256:
        raise ProviderTargetVerificationSourceError(
            "target source digest differs from signed descriptor"
        )
    if entry.size > max_source_bytes:
        raise ProviderTargetVerificationSourceError(
            "target source exceeds verification read bound"
        )
    try:
        payload = source_store.read_bytes(
            ArtifactRef.from_sha256(entry.blob_sha256),
            max_bytes=entry.size,
        )
    except SourceTreeStoreError as exc:
        raise ProviderTargetVerificationSourceError(
            "target source bytes are unavailable or corrupt"
        ) from exc
    if len(payload) != entry.size:
        raise ProviderTargetVerificationSourceError(
            "target source size differs from source-tree manifest"
        )
    if hashlib.sha256(payload).hexdigest() != entry.blob_sha256:
        raise ProviderTargetVerificationSourceError(
            "target source bytes differ from their content address"
        )
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderTargetVerificationSourceError(
            "target source must be strict UTF-8"
        ) from exc
    try:
        tree = ast.parse(source, filename=entry.path, mode="exec")
    except (SyntaxError, ValueError, MemoryError) as exc:
        raise ProviderTargetVerificationSourceError(
            "target source is not a parseable Python module"
        ) from exc
    node, node_kind = _resolve_definition(tree, qualified_parts)
    end_line = getattr(node, "end_lineno", None)
    if not isinstance(end_line, int):
        raise ProviderTargetVerificationSourceError(
            "target definition has no exact source extent"
        )
    return VerifiedPythonTarget(
        target=target,
        repository_path=entry.path,
        source_sha256=entry.blob_sha256,
        source_size=entry.size,
        qualified_name=".".join(qualified_parts),
        node_kind=node_kind,
        line=node.lineno,
        end_line=end_line,
    )


def _validate_max_source_bytes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderTargetVerificationBindingError(
            "max_source_bytes must be a positive integer"
        )
    return value


def _structural_projection(
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    target_manifest: ProviderExecutableTargetManifest,
    source_store: SourceTreeStore,
    source_tree_ref: ArtifactRef,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at,
    max_source_bytes: int,
) -> tuple[
    ProviderExecutableTargetProjection,
    SourceTreeManifest,
    VerifiedPythonTarget,
    VerifiedPythonTarget,
]:
    if type(source_store) is not SourceTreeStore:
        raise ProviderTargetVerificationBindingError(
            "source_store must be exact SourceTreeStore"
        )
    if type(source_tree_ref) is not ArtifactRef:
        raise ProviderTargetVerificationBindingError(
            "source_tree_ref must be exact ArtifactRef"
        )
    maximum = _validate_max_source_bytes(max_source_bytes)
    try:
        projection = project_provider_executable_targets(
            target_authority,
            invocation_authority,
            identity_registry,
            execution,
            target_manifest,
            target_contract_id=target_contract_id,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            at=at,
        )
    except ProviderExecutableTargetError as exc:
        raise ProviderTargetVerificationBindingError(
            "signed provider target authority did not authenticate"
        ) from exc
    try:
        source_manifest = source_store.load_tree(source_tree_ref)
    except SourceTreeStoreError as exc:
        raise ProviderTargetVerificationSourceError(
            "source tree manifest is unavailable or corrupt"
        ) from exc
    if type(source_manifest) is not SourceTreeManifest:
        raise ProviderTargetVerificationSourceError(
            "source tree store returned a non-exact manifest"
        )
    if source_manifest.digest != source_tree_ref.sha256:
        raise ProviderTargetVerificationSourceError(
            "source tree manifest differs from its exact content address"
        )
    if source_manifest.source_revision != projection.source_revision:
        raise ProviderTargetVerificationBindingError(
            "source tree revision differs from signed provider target"
        )
    invoke = _verify_one_target(
        target=projection.invoke_target,
        expected_source_sha256=projection.invoke_source_sha256,
        source_store=source_store,
        source_manifest=source_manifest,
        max_source_bytes=maximum,
    )
    output = _verify_one_target(
        target=projection.output_digests_target,
        expected_source_sha256=projection.output_digests_source_sha256,
        source_store=source_store,
        source_manifest=source_manifest,
        max_source_bytes=maximum,
    )
    return projection, source_manifest, invoke, output


def _receipt_values(
    *,
    verifier_id: str,
    verifier_key_id: str,
    source_tree_ref: ArtifactRef,
    source_manifest: SourceTreeManifest,
    target_authority: ProviderExecutableTargetAuthority,
    target_projection: ProviderExecutableTargetProjection,
    invoke: VerifiedPythonTarget,
    output_digests: VerifiedPythonTarget,
) -> dict[str, Any]:
    try:
        normalized_verifier = _identifier(verifier_id, "verifier_id")
        normalized_key = _identifier(verifier_key_id, "verifier_key_id")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetVerificationBindingError(
            "verification identity is malformed"
        ) from exc
    return {
        "verifier_id": normalized_verifier,
        "verifier_key_id": normalized_key,
        "source_revision": target_projection.source_revision,
        "source_tree_id": source_manifest.tree_id,
        "source_tree_sha256": source_tree_ref.sha256,
        "source_tree_locator": source_tree_ref.locator,
        "target_authority_sha256": target_authority.digest,
        "target_projection_sha256": target_projection.digest,
        "target_manifest_sha256": target_projection.target_manifest_sha256,
        "target_descriptor_sha256": target_projection.target_descriptor_sha256,
        "provider_id": target_projection.provider_id,
        "adapter_id": target_projection.adapter_id,
        "implementation_id": target_projection.implementation_id,
        "entrypoint_id": target_projection.entrypoint_id,
        "runtime_id": target_projection.runtime_id,
        "execution_id": target_authority.execution_id,
        "idempotency_key": target_authority.idempotency_key,
        "lease_sha256": target_authority.lease_sha256,
        "invoke": invoke,
        "output_digests": output_digests,
    }


def _verifier_keys(
    keyring: Mapping[str, bytes | str],
) -> dict[str, bytes]:
    try:
        return dict(
            _normalize_keyring(
                keyring,
                label="verifier_keyring",
            )
        )
    except (TypeError, ValueError) as exc:
        raise ProviderTargetVerificationBindingError(
            "verification keyring is malformed"
        ) from exc


def issue_provider_target_verification_receipt(
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    target_manifest: ProviderExecutableTargetManifest,
    source_store: SourceTreeStore,
    source_tree_ref: ArtifactRef,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    verifier_id: str,
    verifier_key_id: str,
    verifier_keyring: Mapping[str, bytes | str],
    at,
    max_source_bytes: int = 4 * 1024 * 1024,
) -> ProviderExecutableTargetVerificationReceipt:
    """Verify exact source bytes and issue one signed inert receipt."""

    projection, source_manifest, invoke, output = _structural_projection(
        target_authority,
        invocation_authority,
        identity_registry,
        execution,
        target_manifest,
        source_store,
        source_tree_ref,
        target_contract_id=target_contract_id,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        at=at,
        max_source_bytes=max_source_bytes,
    )
    values = _receipt_values(
        verifier_id=verifier_id,
        verifier_key_id=verifier_key_id,
        source_tree_ref=source_tree_ref,
        source_manifest=source_manifest,
        target_authority=target_authority,
        target_projection=projection,
        invoke=invoke,
        output_digests=output,
    )
    secret = _verifier_keys(verifier_keyring).get(values["verifier_key_id"])
    if secret is None:
        raise ProviderTargetVerificationBindingError(
            "verification receipt key is unknown"
        )
    placeholder = ProviderExecutableTargetVerificationReceipt(
        **values,
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_verification_signature(
            placeholder.signing_digest,
            secret,
            "verifier_keyring secret",
        ),
    )


def verify_provider_target_verification_receipt(
    receipt: ProviderExecutableTargetVerificationReceipt,
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    target_manifest: ProviderExecutableTargetManifest,
    source_store: SourceTreeStore,
    source_tree_ref: ArtifactRef,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    verifier_id: str,
    verifier_keyring: Mapping[str, bytes | str],
    at,
    max_source_bytes: int = 4 * 1024 * 1024,
) -> ProviderExecutableTargetProjection:
    """Authenticate a receipt, re-read exact bytes, and return inert identity."""

    if type(receipt) is not ProviderExecutableTargetVerificationReceipt:
        raise ProviderTargetVerificationBindingError(
            "receipt must be exact ProviderExecutableTargetVerificationReceipt"
        )
    try:
        expected_verifier = _identifier(verifier_id, "verifier_id")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetVerificationBindingError(
            "verification verifier identity is malformed"
        ) from exc
    if receipt.verifier_id != expected_verifier:
        raise ProviderTargetVerificationBindingError(
            "verification receipt verifier identity mismatch"
        )
    secret = _verifier_keys(verifier_keyring).get(receipt.verifier_key_id)
    if secret is None:
        raise ProviderTargetVerificationSignatureError(
            "verification receipt key is unknown"
        )
    expected_signature = _verification_signature(
        receipt.signing_digest,
        secret,
        "verifier_keyring secret",
    )
    if not hmac.compare_digest(receipt.signature_sha256, expected_signature):
        raise ProviderTargetVerificationSignatureError(
            "verification receipt signature mismatch"
        )

    projection, source_manifest, invoke, output = _structural_projection(
        target_authority,
        invocation_authority,
        identity_registry,
        execution,
        target_manifest,
        source_store,
        source_tree_ref,
        target_contract_id=target_contract_id,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        at=at,
        max_source_bytes=max_source_bytes,
    )
    expected = ProviderExecutableTargetVerificationReceipt(
        **_receipt_values(
            verifier_id=expected_verifier,
            verifier_key_id=receipt.verifier_key_id,
            source_tree_ref=source_tree_ref,
            source_manifest=source_manifest,
            target_authority=target_authority,
            target_projection=projection,
            invoke=invoke,
            output_digests=output,
        ),
        signature_sha256=receipt.signature_sha256,
    )
    if receipt != expected:
        raise ProviderTargetVerificationBindingError(
            "verification receipt differs from exact source-tree evidence"
        )
    return projection


__all__ = [
    "issue_provider_target_verification_receipt",
    "verify_provider_target_verification_receipt",
]
