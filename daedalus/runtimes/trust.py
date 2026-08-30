# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""External trust anchor for production runtime-conformance evidence.

A caller can construct canonical contracts in memory, so an ``authority``
string is not authentication. Production lease issuance must additionally
receive the exact *envelope* digest from an independently protected source such
as an exact-head gate report, signed live-probe index, or owner-controlled
configuration. Trusting only a probe identity would still permit a different
receipt to be repackaged around the same binary and environment.
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
    trusted_envelope_sha256s: Iterable[str],
    now,
) -> None:
    """Require an externally trusted exact envelope, then verify all bindings."""

    trusted = {
        _sha256(value, "trusted_envelope_sha256")
        for value in trusted_envelope_sha256s
    }
    if envelope.digest not in trusted:
        raise RuntimeConformanceError(
            "runtime conformance envelope is not present in the trusted evidence set"
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
