"""Versioned runtime profiles and authority-labelled conformance bindings."""

from .profiles import (
    REQUIRED_GATE0_RUNTIME_IDS,
    RUNTIME_PROFILE_SCHEMA,
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
    RuntimeProfile,
    bind_conformance_envelope,
    build_probe_identity,
    load_runtime_profiles,
    materialize_runtime_manifest,
    verify_runtime_envelope,
)

__all__ = [
    "REQUIRED_GATE0_RUNTIME_IDS",
    "RUNTIME_PROFILE_SCHEMA",
    "RuntimeConformanceEnvelope",
    "RuntimeProbeIdentity",
    "RuntimeProfile",
    "bind_conformance_envelope",
    "build_probe_identity",
    "load_runtime_profiles",
    "materialize_runtime_manifest",
    "verify_runtime_envelope",
]
