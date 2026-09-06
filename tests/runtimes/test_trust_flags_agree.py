"""Operator-facing runtime trust claims must match enforced provider policy.

Daedalus exposes runtime metadata to the cockpit through ``RUNTIMES`` while
provider routing/egress uses the provider catalogue in ``daedalus.providers``.
Those are different id namespaces, so correspondence is explicit here.  A
runtime status row must never advertise a broader proprietary-source clearance
than the provider that actually executes the task.
"""
from __future__ import annotations

import pytest

from daedalus.providers import list_providers
from daedalus.runtime_registry import RUNTIMES


# runtime id -> provider metadata id.  Keep this explicit: string similarity is
# not authority, and the two Ollama runtime transports intentionally map to one
# provider policy.
RUNTIME_TO_PROVIDER: dict[str, str] = {
    "claude_code_cli": "claude_cli",
    "codex_cli": "codex_cli",
    "ollama_http": "ollama",
    "ollama_cli": "ollama",
    "anthropic_api": "anthropic_api",
    "openai_api": "openai_api",
}


def test_every_runtime_trust_claim_has_an_explicit_provider_mapping() -> None:
    unmapped = sorted({runtime.id for runtime in RUNTIMES} - set(RUNTIME_TO_PROVIDER))
    assert not unmapped, (
        "runtime rows missing an explicit provider-policy mapping: "
        f"{unmapped}"
    )


@pytest.mark.parametrize("runtime", RUNTIMES, ids=lambda runtime: runtime.id)
def test_runtime_trust_claim_matches_enforced_provider_policy(runtime) -> None:
    providers = {row["name"]: row for row in list_providers()}
    provider_id = RUNTIME_TO_PROVIDER[runtime.id]
    assert provider_id in providers, (
        f"runtime {runtime.id} maps to missing provider metadata {provider_id!r}"
    )

    enforced = bool(providers[provider_id]["trusted_with_ip"])
    published = bool(runtime.trusted_with_ip)
    assert published == enforced, (
        f"{runtime.id} publishes trusted_with_ip={published}, but provider "
        f"{provider_id} enforces trusted_with_ip={enforced}; the cockpit must "
        "not contradict the egress gate"
    )


def test_codex_is_not_advertised_as_trusted_with_proprietary_source() -> None:
    registry = {runtime.id: runtime for runtime in RUNTIMES}
    providers = {row["name"]: row for row in list_providers()}

    assert registry["codex_cli"].trusted_with_ip is False
    assert providers["codex_cli"]["trusted_with_ip"] is False
