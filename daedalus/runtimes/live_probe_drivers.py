# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The two live-runtime fault probes, and the evidence they are allowed to claim.

The canonical catalog carries exactly two ``live-runtime`` rows:

``runtime.live-envelope.expiry``
    Expired live evidence cannot authorize a production lease.

``runtime.live-envelope.binary-drift``
    Provider binary drift after conformance quarantines the exact envelope with
    no fallback.

Both expect ``refused-before-start``, and that is precisely why these drivers
are written defensively. A refusal is the cheapest observation in the system:
hand the lease boundary anything malformed and it refuses. Such a refusal would
satisfy the catalog's expected outcome while demonstrating nothing about the
guard the row is named after.

Every probe here therefore obeys three rules.

**Positive control first.** Before injecting any fault, the driver verifies that
the *unmodified* bundle is accepted at the production lease boundary
(:func:`~daedalus.runtimes.trust.verify_production_runtime_envelope`). If the
bundle would never have authorized a lease, the driver reports ``blocked``. It
does not report a pass for refusing what was already refusable.

**The refusal must be the named one.** After the fault, the driver requires not
merely *a* refusal but the refusal belonging to this row -- staleness for the
expiry row, binding quarantine plus trusted-set exclusion for the drift row. A
refusal for an unrelated reason is ``failed``, not ``passed``.

**Live evidence is not synthesizable here.** A ``live-runtime`` envelope exists
only when a really installed provider was really observed against every
conformance check. This module never mints one; it loads one that an operator
supplied and hard-refuses an ``offline-fixture`` bundle. On a host that cannot
produce live evidence, both rows are ``blocked`` with a named reason and the
facts that *were* measured are retained.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import platform
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.runtime_conformance import (
    RuntimeConformanceError,
    verify_current_conformance,
)
from daedalus.runtimes.fault_matrix import RuntimeFaultScenario
from daedalus.runtimes.host_fault_runner import HostFaultFact
from daedalus.runtimes.live_fault_collector import (
    LiveProbeExecutorBinding,
    LiveProbeResult,
)
from daedalus.runtimes.profiles import (
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
    bind_conformance_envelope,
)
from daedalus.runtimes.trust import verify_production_runtime_envelope
from daedalus.schemas import (
    ContractProvenance,
    RuntimeConformanceReceipt,
    RuntimeManifest,
)
from daedalus.spine.envelope import canonical_json

EXPIRY_LOCATOR = "live-probe:runtime-envelope-expiry"
BINARY_DRIFT_LOCATOR = "live-probe:runtime-binary-drift"

_LIVE_AUTHORITY = "live-runtime"
_SCHEMA = "daedalus-live-probe-observation/1"
_MAX_CONTRACT_BYTES = 4 * 1024 * 1024
_MAX_BINARY_BYTES = 512 * 1024 * 1024
_CONTROL_MARGIN = timedelta(seconds=1)


def _kernel_envelope_max_age() -> timedelta:
    """The staleness bound the kernel itself applies, read from the kernel.

    The expiry probe must age an envelope past the boundary the production path
    actually enforces. Hard-coding seven days here would let the probe and the
    kernel drift apart silently, and the probe would keep reporting a pass while
    testing the wrong instant.
    """

    default = inspect.signature(verify_current_conformance).parameters["max_age"].default
    if not isinstance(default, timedelta) or default <= timedelta(0):
        raise LiveProbeUnavailable(
            "kernel-max-age-unreadable",
            "verify_current_conformance does not expose a positive max_age default",
        )
    return default


class LiveProbeError(RuntimeError):
    """Base class for live probe driver failures."""


class LiveProbeUnavailable(LiveProbeError):
    """This host cannot run the probe; the row is blocked with a named reason."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class LiveEnvelopeBundle:
    """A complete, self-consistent ``live-runtime`` conformance bundle.

    The four contracts travel together because the lease boundary verifies all
    of them against each other. Construction refuses anything that is not live
    evidence, so an ``offline-fixture`` bundle cannot be laundered into the
    live column by renaming a directory.
    """

    envelope: RuntimeConformanceEnvelope
    identity: RuntimeProbeIdentity
    receipt: RuntimeConformanceReceipt
    manifest: RuntimeManifest

    def __post_init__(self) -> None:
        if self.envelope.authority != _LIVE_AUTHORITY:
            raise LiveProbeUnavailable(
                "envelope-not-live",
                f"envelope authority is {self.envelope.authority!r}, "
                f"and only {_LIVE_AUTHORITY!r} evidence can authorize a production lease",
            )
        if self.identity.authority != _LIVE_AUTHORITY:
            raise LiveProbeUnavailable(
                "identity-not-live",
                f"probe identity authority is {self.identity.authority!r}",
            )
        if self.envelope.status != "passed":
            raise LiveProbeUnavailable(
                "envelope-not-passed",
                f"envelope status is {self.envelope.status!r}; a failed envelope "
                "would be refused for its status rather than for the injected fault",
            )

    @property
    def finished_at(self) -> datetime:
        return datetime.fromisoformat(
            self.receipt.finished_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)


def _read_contract_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise LiveProbeUnavailable(
            "live-bundle-incomplete", f"{label} is not a regular file: {path.name}"
        )
    raw = path.read_bytes()
    if len(raw) > _MAX_CONTRACT_BYTES:
        raise LiveProbeUnavailable(
            "live-bundle-oversized", f"{label} exceeds the maximum contract size"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveProbeUnavailable(
            "live-bundle-malformed", f"{label} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise LiveProbeUnavailable(
            "live-bundle-malformed", f"{label} root must be an object"
        )
    return payload


def load_live_envelope_bundle(directory: Path | str | None) -> LiveEnvelopeBundle:
    """Load the one live bundle an operator placed in ``directory``.

    The layout matches what the conformance producer already writes:
    ``<name>-envelope.json``, ``<name>-probe-identity.json``,
    ``<name>-manifest.json`` and ``<name>-receipt.json``.
    """

    if directory is None:
        raise LiveProbeUnavailable(
            "live-envelope-unavailable",
            "no live conformance envelope was supplied to this collector run",
        )
    base = Path(directory)
    if not base.is_dir() or base.is_symlink():
        raise LiveProbeUnavailable(
            "live-envelope-unavailable",
            f"live envelope directory is not a real directory: {base}",
        )
    envelopes = sorted(
        path
        for path in base.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.name.endswith("-envelope.json")
    )
    if not envelopes:
        raise LiveProbeUnavailable(
            "live-envelope-unavailable",
            f"no *-envelope.json is present in {base}",
        )
    if len(envelopes) > 1:
        raise LiveProbeUnavailable(
            "live-envelope-ambiguous",
            "a live probe run binds exactly one envelope; found: "
            + ", ".join(path.name for path in envelopes),
        )
    envelope_path = envelopes[0]
    stem = envelope_path.name[: -len("-envelope.json")]
    try:
        envelope = RuntimeConformanceEnvelope.from_dict(
            _read_contract_json(envelope_path, "envelope")
        )
        identity = RuntimeProbeIdentity.from_dict(
            _read_contract_json(base / f"{stem}-probe-identity.json", "probe identity")
        )
        receipt = RuntimeConformanceReceipt.from_dict(
            _read_contract_json(base / f"{stem}-receipt.json", "conformance receipt")
        )
        manifest = RuntimeManifest.from_dict(
            _read_contract_json(base / f"{stem}-manifest.json", "runtime manifest")
        )
    except LiveProbeUnavailable:
        raise
    except (TypeError, ValueError) as exc:
        raise LiveProbeUnavailable(
            "live-bundle-malformed", f"{stem}: {exc}"
        ) from exc
    return LiveEnvelopeBundle(
        envelope=envelope, identity=identity, receipt=receipt, manifest=manifest
    )


def measure_file_sha256(path: Path | str) -> str:
    """Measure the exact on-disk identity of one real file."""

    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise LiveProbeUnavailable(
            "provider-binary-unavailable",
            f"provider binary is not a regular file: {target}",
        )
    size = target.stat().st_size
    if size > _MAX_BINARY_BYTES:
        raise LiveProbeUnavailable(
            "provider-binary-oversized",
            f"provider binary exceeds the measurable bound: {size} bytes",
        )
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_control_accepts(bundle: LiveEnvelopeBundle, *, now: datetime) -> None:
    """The unmodified bundle must authorize a lease, or nothing else is provable."""

    try:
        verify_production_runtime_envelope(
            bundle.envelope,
            bundle.identity,
            bundle.receipt,
            bundle.manifest,
            trusted_envelope_sha256s={bundle.envelope.digest},
            now=now,
        )
    except RuntimeConformanceError as exc:
        raise LiveProbeUnavailable(
            "control-rejected",
            "the unmodified live bundle was already refused at the lease boundary, "
            f"so the injected fault would prove nothing: {exc}",
        ) from exc


def _refusal(
    bundle: LiveEnvelopeBundle, identity: RuntimeProbeIdentity, *, now: datetime
) -> str | None:
    """Return the lease-boundary refusal message, or ``None`` if it was accepted."""

    try:
        verify_production_runtime_envelope(
            bundle.envelope,
            identity,
            bundle.receipt,
            bundle.manifest,
            trusted_envelope_sha256s={bundle.envelope.digest},
            now=now,
        )
    except RuntimeConformanceError as exc:
        return str(exc)
    return None


def _result(
    scenario: RuntimeFaultScenario,
    *,
    status: str,
    observed_outcome: str | None,
    detail_code: str | None,
    facts: Mapping[str, str],
) -> LiveProbeResult:
    payload = {
        "schema": _SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.digest,
        "executor": scenario.executor,
        "status": status,
        "observed_outcome": observed_outcome,
        "detail_code": detail_code,
        "facts": dict(sorted(facts.items())),
    }
    return LiveProbeResult(
        status=status,
        observed_outcome=observed_outcome,
        detail_code=detail_code,
        raw_evidence=canonical_json(payload).encode("utf-8"),
        facts=tuple(HostFaultFact(name, value) for name, value in sorted(facts.items())),
    )


def _host_facts() -> dict[str, str]:
    return {
        "host-platform": platform.system().lower() or "unknown",
        "host-release": platform.release() or "unknown",
    }


def probe_envelope_expiry(
    scenario: RuntimeFaultScenario,
    *,
    live_envelope_dir: Path | str | None,
) -> LiveProbeResult:
    """Age a real live envelope past the kernel's own bound and observe the refusal.

    The instant is controlled rather than the clock, so the probe measures the
    comparison the kernel performs instead of waiting a week. What is *not*
    simulated is the envelope: it must be live evidence that genuinely
    authorized a lease one microsecond earlier.
    """

    facts = _host_facts()
    try:
        max_age = _kernel_envelope_max_age()
        facts["kernel-max-age-seconds"] = str(int(max_age.total_seconds()))
        bundle = load_live_envelope_bundle(live_envelope_dir)
        facts["runtime-id"] = bundle.envelope.runtime_id
        facts["envelope-sha256"] = bundle.envelope.digest
        facts["envelope-authority"] = bundle.envelope.authority
        facts["receipt-finished-at"] = bundle.receipt.finished_at

        fresh = bundle.finished_at + _CONTROL_MARGIN
        _assert_control_accepts(bundle, now=fresh)
        facts["control"] = "accepted-when-fresh"

        expired = bundle.finished_at + max_age + _CONTROL_MARGIN
        facts["expired-instant"] = expired.isoformat(timespec="microseconds")
        message = _refusal(bundle, bundle.identity, now=expired)
    except LiveProbeUnavailable as exc:
        facts["blocked-reason"] = exc.reason
        facts["blocked-detail"] = exc.detail[:400]
        return _result(
            scenario,
            status="blocked",
            observed_outcome=None,
            detail_code=exc.reason,
            facts=facts,
        )

    if message is None:
        facts["refusal"] = "none"
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="expiry-not-enforced",
            facts=facts,
        )
    facts["refusal-message"] = message[:400]
    if "stale" not in message:
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="refusal-reason-mismatch",
            facts=facts,
        )
    return _result(
        scenario,
        status="passed",
        observed_outcome="refused-before-start",
        detail_code=None,
        facts=facts,
    )


def _drifted_identity(
    identity: RuntimeProbeIdentity, drifted_executable_sha256: str
) -> RuntimeProbeIdentity:
    """The identity an operator would measure after the binary changed."""

    return RuntimeProbeIdentity(
        probe_id=identity.probe_id,
        runtime_id=identity.runtime_id,
        authority=identity.authority,
        runtime_manifest_sha256=identity.runtime_manifest_sha256,
        profile_sha256=identity.profile_sha256,
        adapter_sha256=identity.adapter_sha256,
        executable_sha256=drifted_executable_sha256,
        environment_sha256=identity.environment_sha256,
        fixture_suite_sha256=identity.fixture_suite_sha256,
        source_revision=identity.source_revision,
        collected_at=identity.collected_at,
        provenance=ContractProvenance(
            origin=identity.provenance.origin,
            source_revision=identity.source_revision,
            created_at=identity.collected_at,
            input_digests=tuple(
                sorted(
                    {
                        identity.runtime_manifest_sha256,
                        identity.profile_sha256,
                        identity.adapter_sha256,
                        drifted_executable_sha256,
                        identity.environment_sha256,
                        identity.fixture_suite_sha256,
                    }
                )
            ),
            trace_id=identity.provenance.trace_id,
        ),
    )


def _forged_envelope(
    bundle: LiveEnvelopeBundle, drifted: RuntimeProbeIdentity
) -> RuntimeConformanceEnvelope:
    """What an attacker would repackage around the drifted binary.

    ``authority`` is a string a caller can type, so the envelope below is
    syntactically perfect live evidence. Only the externally held trusted set
    stands between it and a production lease -- which is exactly the property
    the drift row has to demonstrate.
    """

    return RuntimeConformanceEnvelope(
        envelope_id=bundle.envelope.envelope_id,
        runtime_id=bundle.envelope.runtime_id,
        authority=_LIVE_AUTHORITY,
        status="passed",
        runtime_manifest_sha256=bundle.manifest.digest,
        probe_identity_sha256=drifted.digest,
        conformance_receipt_sha256=bundle.receipt.digest,
        source_revision=bundle.envelope.source_revision,
        created_at=bundle.envelope.created_at,
        provenance=ContractProvenance(
            origin="runtimes.conformance-envelope",
            source_revision=bundle.envelope.source_revision,
            created_at=bundle.envelope.created_at,
            input_digests=tuple(
                sorted({bundle.manifest.digest, drifted.digest, bundle.receipt.digest})
            ),
            trace_id=bundle.envelope.envelope_id,
        ),
    )


def drift_binary_copy(provider_binary: Path | str) -> tuple[str, str]:
    """Measure a real provider binary, then re-measure a mutated isolated copy.

    The installed binary is never written to. The drift is applied to a copy in
    a temporary directory, so the measurement is of real bytes really changing
    while the host's provider stays intact.
    """

    original = measure_file_sha256(provider_binary)
    workspace = Path(tempfile.mkdtemp(prefix="live-probe-drift-"))
    try:
        copy = workspace / Path(provider_binary).name
        shutil.copyfile(Path(provider_binary), copy)
        copied = measure_file_sha256(copy)
        if copied != original:
            raise LiveProbeUnavailable(
                "binary-copy-unstable",
                "the isolated copy does not match the installed provider binary",
            )
        with copy.open("ab") as handle:
            handle.write(b"\x00daedalus-live-probe-drift")
        drifted = measure_file_sha256(copy)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    if drifted == original:
        raise LiveProbeUnavailable(
            "binary-drift-unobservable",
            "mutating the provider image did not change its measured identity",
        )
    return original, drifted


def probe_binary_drift(
    scenario: RuntimeFaultScenario,
    *,
    live_envelope_dir: Path | str | None,
    provider_binary: Path | str | None,
) -> LiveProbeResult:
    """Change the provider binary identity after conformance and observe quarantine.

    Three refusals must all hold before this row may pass:

    1. a fresh envelope cannot be *bound* around the drifted binary, because the
       runtime manifest never bound that executable digest;
    2. the exact original envelope no longer verifies against the drifted
       identity;
    3. a repackaged envelope carrying the drifted identity is not in the trusted
       evidence set, so there is no fallback to a second, weaker acceptance.
    """

    facts = _host_facts()
    try:
        if provider_binary is None:
            raise LiveProbeUnavailable(
                "provider-binary-unavailable",
                "no provider binary was supplied to re-measure after conformance",
            )
        original, drifted_sha = drift_binary_copy(provider_binary)
        facts["provider-binary"] = Path(provider_binary).name
        facts["measured-executable-sha256"] = original
        facts["drifted-executable-sha256"] = drifted_sha
        facts["binary-drift-observed"] = "true"

        bundle = load_live_envelope_bundle(live_envelope_dir)
        facts["runtime-id"] = bundle.envelope.runtime_id
        facts["envelope-sha256"] = bundle.envelope.digest
        facts["envelope-authority"] = bundle.envelope.authority
        if bundle.identity.executable_sha256 != original:
            raise LiveProbeUnavailable(
                "binary-identity-unbound",
                "the supplied live envelope does not describe the supplied provider "
                f"binary ({bundle.identity.executable_sha256} != {original})",
            )
        facts["envelope-binds-measured-binary"] = "true"

        fresh = bundle.finished_at + _CONTROL_MARGIN
        _assert_control_accepts(bundle, now=fresh)
        facts["control"] = "accepted-before-drift"

        drifted_identity = _drifted_identity(bundle.identity, drifted_sha)
    except LiveProbeUnavailable as exc:
        facts["blocked-reason"] = exc.reason
        facts["blocked-detail"] = exc.detail[:400]
        return _result(
            scenario,
            status="blocked",
            observed_outcome=None,
            detail_code=exc.reason,
            facts=facts,
        )

    # (1) No fresh envelope may be minted around the drifted binary.
    try:
        bind_conformance_envelope(
            bundle.manifest,
            drifted_identity,
            bundle.receipt,
            envelope_id=bundle.envelope.envelope_id,
            created_at=bundle.envelope.created_at,
        )
    except (RuntimeConformanceError, ValueError) as exc:
        facts["rebind-refusal"] = str(exc)[:300]
    else:
        facts["rebind-refusal"] = "none"
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="drift-rebind-permitted",
            facts=facts,
        )

    # (2) The exact original envelope must quarantine the drifted identity.
    quarantine = _refusal(bundle, drifted_identity, now=fresh)
    if quarantine is None:
        facts["quarantine-refusal"] = "none"
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="drift-not-quarantined",
            facts=facts,
        )
    facts["quarantine-refusal"] = quarantine[:300]
    if "probe_identity_sha256" not in quarantine:
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="refusal-reason-mismatch",
            facts=facts,
        )

    # (3) A repackaged envelope must find no fallback into the trusted set.
    forged = _forged_envelope(bundle, drifted_identity)
    if forged.digest == bundle.envelope.digest:
        facts["fallback-refusal"] = "forgery-collides-with-trusted-envelope"
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="drift-forgery-indistinguishable",
            facts=facts,
        )
    try:
        verify_production_runtime_envelope(
            forged,
            drifted_identity,
            bundle.receipt,
            bundle.manifest,
            trusted_envelope_sha256s={bundle.envelope.digest},
            now=fresh,
        )
    except RuntimeConformanceError as exc:
        facts["fallback-refusal"] = str(exc)[:300]
    else:
        facts["fallback-refusal"] = "none"
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="drift-fallback-accepted",
            facts=facts,
        )
    if "trusted evidence set" not in facts["fallback-refusal"]:
        return _result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="refusal-reason-mismatch",
            facts=facts,
        )

    return _result(
        scenario,
        status="passed",
        observed_outcome="refused-before-start",
        detail_code=None,
        facts=facts,
    )


def _implementation_sha256(locator: str) -> str:
    """Identity of the driver implementation that produced an observation."""

    source = Path(__file__).read_bytes()
    return hashlib.sha256(source + b"\0" + locator.encode("utf-8")).hexdigest()


def build_live_probe_executors(
    *,
    live_envelope_dir: Path | str | None = None,
    provider_binary: Path | str | None = None,
) -> dict[str, LiveProbeExecutorBinding]:
    """Bind both live probes to their exact catalog locators.

    Both bindings are always returned. A host without live evidence still runs
    the probes; they report ``blocked`` with a named reason and retain whatever
    they did manage to measure. Returning no binding at all would produce the
    same blocked row with a *less* specific reason, and would lose the facts.
    """

    return {
        EXPIRY_LOCATOR: LiveProbeExecutorBinding(
            locator=EXPIRY_LOCATOR,
            implementation_sha256=_implementation_sha256(EXPIRY_LOCATOR),
            execute=lambda scenario: probe_envelope_expiry(
                scenario, live_envelope_dir=live_envelope_dir
            ),
        ),
        BINARY_DRIFT_LOCATOR: LiveProbeExecutorBinding(
            locator=BINARY_DRIFT_LOCATOR,
            implementation_sha256=_implementation_sha256(BINARY_DRIFT_LOCATOR),
            execute=lambda scenario: probe_binary_drift(
                scenario,
                live_envelope_dir=live_envelope_dir,
                provider_binary=provider_binary,
            ),
        ),
    }


def default_provider_binary() -> Path | None:
    """The installed provider executable this host could re-measure, if any."""

    for name in ("ollama", "claude", "codex"):
        found = shutil.which(name)
        if found:
            candidate = Path(found)
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


__all__ = [
    "BINARY_DRIFT_LOCATOR",
    "EXPIRY_LOCATOR",
    "LiveEnvelopeBundle",
    "LiveProbeError",
    "LiveProbeUnavailable",
    "build_live_probe_executors",
    "default_provider_binary",
    "drift_binary_copy",
    "load_live_envelope_bundle",
    "measure_file_sha256",
    "probe_binary_drift",
    "probe_envelope_expiry",
]
