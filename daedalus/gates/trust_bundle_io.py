# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Strict untrusted-wire boundary for authenticated evidence trust bundles.

The contract constructor intentionally canonicalizes anchor and digest order for
already typed internal values.  An untrusted signed wire must be stricter: the
submitted representation is reconstructed and then compared with the complete
canonical ``to_dict()`` form before it may reach signature verification.

During the strangler migration :mod:`daedalus.gates` installs these functions as
the compatibility parser/loader attributes on :mod:`daedalus.gates.trust_bundle`
so existing import paths retain their names without preserving the permissive
wire behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .trust_bundle import EvidenceTrustBundle


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_evidence_trust_bundle(
    payload: Mapping[str, Any],
) -> EvidenceTrustBundle:
    """Parse only the exact canonical signed trust-bundle wire."""

    if not isinstance(payload, Mapping):
        raise ValueError("Evidence trust bundle must be an object")
    if not isinstance(payload.get("provenance"), Mapping):
        raise ValueError("provenance must be an object")
    wire = dict(payload)
    bundle = EvidenceTrustBundle.from_dict(wire)
    if wire != bundle.to_dict():
        raise ValueError(
            "Evidence trust bundle must use its exact canonical wire form"
        )
    return bundle


def load_evidence_trust_bundle(path: str | Path) -> EvidenceTrustBundle:
    """Load strict UTF-8 JSON and reject duplicate keys recursively."""

    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("Evidence trust bundle must be an object")
    return parse_evidence_trust_bundle(payload)


__all__ = ["load_evidence_trust_bundle", "parse_evidence_trust_bundle"]
