"""External trust anchor for production runtime-conformance evidence.

A caller can construct canonical contracts in memory, so an ``authority``
string is not authentication. Production lease issuance must additionally
receive the exact probe-identity digest from an independently protected source
such as an exact-head gate report, signed live-probe index, or owner-controlled
configuration. This module performs that final allow-list check before the
structural verifier runs.
"""
from __future__ import annotations

from collections.abc import Iterable

from daedalus.kernel.runtime_conformance import RuntimeConformanceError
from daedalus.schemas import (
    RuntimeConformanceReceipt,
    RuntimeManifest,
    _sha256,
)

from .profiles import (
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
    verify_runtime_envelope,
)


def verify_production_runtime_envelope(
    envelope: RuntimeConformanceEnvelope,
    identity: RuntimeProbeIdentity,
    receipt: RuntimeConformanceReceipt,
    manifest: RuntimeManifest,
    *,
    trusted_probe_sha256s: Iterable[str],
    now,
) -> None:
    """Require an externally trusted live-probe digest, then verify bindings."""

    trusted = {
        _sha256(value, "trusted_probe_sha256")
        for value in trusted_probe_sha256s
    }
    if identity.digest not in trusted:
        raise RuntimeConformanceError(
            "live runtime probe identity is not present in the trusted probe set"
        )
    verify_runtime_envelope(
        envelope,
        identity,
        receipt,
        manifest,
        now=now,
        require_live=True,
    )


__all__ = ["verify_production_runtime_envelope"]
