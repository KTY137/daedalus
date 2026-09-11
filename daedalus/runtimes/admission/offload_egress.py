"""Provider endpoint and egress admission for offload Effect Leases.

This is production composition, not lease authority.  It resolves the same
declared endpoints and delegates Ollama admission to the existing provider
policy before returning one neutral observation to the kernel issuer.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from daedalus.kernel.offload_lease import EgressAdmissionObservation
from daedalus.providers.ollama import DEFAULT_HOST, ollama_endpoint_admission
from daedalus.spine.effect_boundary import GuardDecision


_LANE_ENDPOINTS = {
    "deepseek": "https://api.deepseek.com",
}


def resolve_lane_endpoint(lane: str, /) -> str:
    """Return the endpoint one declared dispatch lane speaks."""

    normalized = str(lane)
    if normalized == "ollama":
        return (os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    return _LANE_ENDPOINTS.get(normalized, "")


def admit_offload_egress(
    lanes: Sequence[str],
    /,
) -> EgressAdmissionObservation:
    """Resolve and admit the exact sorted lane set without widening it."""

    requested = tuple(sorted({str(lane) for lane in lanes if str(lane).strip()}))
    endpoints: list[str] = []
    reasons: list[str] = []
    allowed = True
    for lane in requested:
        endpoint = resolve_lane_endpoint(lane)
        if not endpoint:
            allowed = False
            reasons.append(
                f"lane {lane!r} declares no endpoint, so its egress cannot be leased"
            )
            continue
        if lane == "ollama":
            endpoint_allowed, _lane, evidence = ollama_endpoint_admission(endpoint)
            reasons.append(f"{lane}: {evidence}")
            if not endpoint_allowed:
                allowed = False
                continue
        else:
            reasons.append(
                f"{lane}: declared endpoint {endpoint} (no admission contract "
                f"implements this lane yet, so it is leased only as a declaration)"
            )
        endpoints.append(endpoint)
    if not endpoints:
        allowed = False
        reasons.append(
            "no admissible endpoint for this wave; a network-effect lease must "
            "name at least one"
        )
    return EgressAdmissionObservation(
        requested_lanes=requested,
        endpoints=tuple(endpoints),
        decision=GuardDecision(
            "provider.egress_policy",
            allowed,
            "; ".join(reasons),
        ),
    )


__all__ = ["admit_offload_egress", "resolve_lane_endpoint"]
