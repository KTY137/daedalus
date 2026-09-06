from __future__ import annotations

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.providers.claude_cli import (
    ClaudeCLIProvider,
    ClaudeProviderAuthorizationRequired,
    ClaudeWorkspaceGrant,
)
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation_abi import ProviderInvocationABIContract
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider_observation import ProviderObservationBindingLedger


_MEMBER_TYPES = {
    "runtime_authorization": RuntimeBoundEffectAuthorization,
    "effect_execution": EffectExecutionRequest,
    "workspace_grant": ClaudeWorkspaceGrant,
    "invocation_authority": ProviderInvocationObservationAuthority,
    "invocation_payload": ProviderInvocationPayload,
    "invocation_abi": ProviderInvocationABIContract,
    "executable_registry": ProviderExecutableObjectRegistry,
    "pre_admission": ProviderExecutablePreAdmissionReceipt,
    "observation_binding_ledger": ProviderObservationBindingLedger,
}


class _AmbientSubstitute:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"substituted authority member was accessed: {name}")


def _uninitialized_exact_members() -> dict[str, object]:
    return {
        name: object.__new__(exact_type)
        for name, exact_type in _MEMBER_TYPES.items()
    }


@pytest.mark.parametrize("member", tuple(_MEMBER_TYPES))
def test_direct_provider_rejects_substituted_member_before_property_access(
    member: str,
) -> None:
    kwargs = _uninitialized_exact_members()
    kwargs[member] = _AmbientSubstitute()

    with pytest.raises(
        ClaudeProviderAuthorizationRequired,
        match=rf"exact sealed invocation member types: .*{member}",
    ):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root="unused",
            paths=[],
            agent={"model_tier": "sonnet"},
            **kwargs,
        )
