"""Issue signed attestations for retained deterministic-fixture observations.

This is the sibling of
:mod:`daedalus.runtimes.fault_attestation_issuer`, which owns the ``linux-host``
column. Same boundary, same validate-then-delegate discipline, different
authority and a different signing identity.

The separation is the point. The two issuers are not one issuer with a
parameter: each pins its own authority constant, each is expected to hold its
own key, and each refuses the other's rows by name. A compromised host runner
therefore cannot manufacture trust for a fixture row, and a compromised fixture
collector cannot manufacture trust for a host row. The refusal is enforced
twice: here at issuance, and again at verification, where
:func:`~daedalus.runtimes.fault_attestations.verify_attested_runtime_fault_matrix`
is given an ``issuer_authorities`` policy that scopes this issuer id to
``deterministic-fixture`` alone.

As with the host column, a signature means "this record is authentic", never
"this scenario passed". A ``failed`` or ``blocked`` observation is attested
unchanged and still yields its ``fault.failed`` / ``fault.blocked`` blocker.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.runtimes.fault_attestation_issuer import (
    FaultAttestationIssuerError,
    FaultAttestationRefusal,
    FaultAttestationRefusalRecord,
    _atomic_write,
    _key_class,
    _read_json_object,
    _secret_from_env,
    key_fingerprint,
    retained_scenario_ids,
)
from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestation,
    issue_runtime_fault_attestation,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultCatalog,
    RuntimeFaultMatrix,
    RuntimeFaultObservation,
    build_runtime_fault_matrix,
)
from daedalus.runtimes.fixture_fault_collector import (
    FixtureFaultCollectorError,
    FixtureFaultRun,
    load_fixture_fault_evidence_json,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-fixture-fault-attestation-bundle/1"
_AUTHORITY = "deterministic-fixture"
_KEY_CLASSES = frozenset({"production", "development"})
_MAX_WIRE_BYTES = 2 * 1024 * 1024
_MAX_VALIDITY = timedelta(days=7)
_DEFAULT_VALIDITY = timedelta(hours=24)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


def _revision(value: Any, name: str = "source_revision") -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a full lowercase Git/SHA revision")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _secret(value: bytes, name: str = "signing secret") -> bytes:
    if not isinstance(value, bytes):
        raise ValueError(f"{name} must be bytes")
    if len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 bytes")
    return value


def _as_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class FixtureFaultAttestationBundle:
    """Content-addressed issuance result: what was signed and what was refused."""

    schema: str
    issuer_id: str
    key_id: str
    key_class: str
    key_sha256: str
    catalog_sha256: str
    source_revision: str
    issued_at: str
    attestations: tuple[RuntimeFaultAttestation, ...]
    refusals: tuple[FaultAttestationRefusalRecord, ...]

    def __post_init__(self) -> None:
        if self.schema != _SCHEMA:
            raise ValueError(f"schema must be {_SCHEMA}")
        object.__setattr__(self, "issuer_id", _identifier(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "key_id", _identifier(self.key_id, "key_id"))
        object.__setattr__(self, "key_class", _key_class(self.key_class))
        object.__setattr__(self, "key_sha256", _sha256(self.key_sha256, "key_sha256"))
        object.__setattr__(
            self, "catalog_sha256", _sha256(self.catalog_sha256, "catalog_sha256")
        )
        object.__setattr__(self, "source_revision", _revision(self.source_revision))
        rows = tuple(sorted(self.attestations, key=lambda row: row.scenario_id))
        scenario_ids = tuple(row.scenario_id for row in rows)
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("bundle contains duplicate scenario attestations")
        if any(row.authority != _AUTHORITY for row in rows):
            raise ValueError(f"bundle must only carry {_AUTHORITY} attestations")
        if any(row.catalog_sha256 != self.catalog_sha256 for row in rows):
            raise ValueError("bundle attestations must share the exact catalog")
        if any(row.source_revision != self.source_revision for row in rows):
            raise ValueError("bundle attestations must share the exact source revision")
        if any(row.issuer_id != self.issuer_id or row.key_id != self.key_id for row in rows):
            raise ValueError("bundle attestations must share the exact issuer identity")
        object.__setattr__(self, "attestations", rows)
        refusals = tuple(sorted(self.refusals, key=lambda row: row.scenario_id))
        refused_ids = tuple(row.scenario_id for row in refusals)
        if len(refused_ids) != len(set(refused_ids)):
            raise ValueError("bundle contains duplicate refusals")
        if set(refused_ids) & set(scenario_ids):
            raise ValueError("a scenario cannot be both attested and refused")
        object.__setattr__(self, "refusals", refusals)

    @property
    def complete(self) -> bool:
        """True only when nothing was refused."""

        return not self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "key_class": self.key_class,
            "key_sha256": self.key_sha256,
            "catalog_sha256": self.catalog_sha256,
            "source_revision": self.source_revision,
            "issued_at": self.issued_at,
            "attestations": [row.to_dict() for row in self.attestations],
            "refusals": [row.to_dict() for row in self.refusals],
            "complete": self.complete,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class FixtureFaultAttestationIssuer:
    """Operator-held authority that signs validated deterministic-fixture rows.

    It refuses anything that is not an exact, catalog-consistent
    ``deterministic-fixture`` artifact triple at the expected source revision --
    including a perfectly valid ``linux-host`` run, which belongs to the other
    issuer and the other key.
    """

    issuer_id: str
    key_id: str
    secret: bytes = field(repr=False)
    catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG
    expected_source_revision: str = ""
    validity: timedelta = _DEFAULT_VALIDITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer_id", _identifier(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "key_id", _identifier(self.key_id, "key_id"))
        object.__setattr__(self, "secret", _secret(self.secret))
        if not isinstance(self.catalog, RuntimeFaultCatalog):
            raise ValueError("catalog must be a RuntimeFaultCatalog")
        object.__setattr__(
            self, "expected_source_revision", _revision(self.expected_source_revision)
        )
        if not isinstance(self.validity, timedelta):
            raise ValueError("validity must be a timedelta")
        if self.validity <= timedelta(0) or self.validity > _MAX_VALIDITY:
            raise ValueError("validity must be positive and at most seven days")

    @property
    def issuer_authorities(self) -> dict[str, tuple[str, ...]]:
        """The policy this issuer assumes, for the verifying side to mirror."""

        return {self.issuer_id: (_AUTHORITY,)}

    def _scenario(self, scenario_id: str):
        scenario = self.catalog.scenario_map.get(scenario_id)
        if scenario is None:
            raise FaultAttestationRefusal(
                "refusal.unknown-scenario",
                f"{scenario_id} is absent from catalog {self.catalog.catalog_id}",
            )
        if scenario.authority != _AUTHORITY:
            raise FaultAttestationRefusal(
                "refusal.foreign-authority",
                f"{scenario_id} is a {scenario.authority} scenario",
            )
        return scenario

    def issue(
        self,
        run: FixtureFaultRun,
        *,
        issued_at: datetime,
    ) -> RuntimeFaultAttestation:
        """Validate one complete retained run and sign it, or refuse by name."""

        if not isinstance(run, FixtureFaultRun):
            raise FaultAttestationRefusal(
                "refusal.artifact-malformed", "issuance requires a FixtureFaultRun"
            )
        observation = run.observation
        evidence = run.evidence
        scenario = self._scenario(observation.scenario_id)

        # FixtureFaultRun already bound raw -> evidence -> observation. What
        # remains is the binding to the canonical catalog and to the exact head.
        if observation.authority != _AUTHORITY:
            raise FaultAttestationRefusal(
                "refusal.foreign-authority",
                f"observation authority is {observation.authority}",
            )
        if observation.scenario_sha256 != scenario.digest:
            raise FaultAttestationRefusal(
                "refusal.scenario-drift",
                f"{scenario.scenario_id} was observed against a different scenario record",
            )
        if evidence.executor != scenario.executor:
            raise FaultAttestationRefusal(
                "refusal.executor-drift",
                f"{scenario.scenario_id} was executed by {evidence.executor!r}",
            )
        if observation.source_revision != self.expected_source_revision:
            raise FaultAttestationRefusal(
                "refusal.stale-revision",
                f"{scenario.scenario_id} was observed at {observation.source_revision}",
            )
        if (
            observation.status == "passed"
            and observation.observed_outcome != scenario.expected_outcome
        ):
            raise FaultAttestationRefusal(
                "refusal.outcome-contradicts-catalog",
                f"{scenario.scenario_id} reports {observation.observed_outcome!r} "
                f"but the catalog requires {scenario.expected_outcome!r}",
            )

        issued = _as_utc(issued_at, "issued_at")
        if issued < _parse_timestamp(observation.observed_at):
            raise FaultAttestationRefusal(
                "refusal.attestation-predates-observation",
                f"{scenario.scenario_id} was observed at {observation.observed_at}",
            )
        try:
            return issue_runtime_fault_attestation(
                observation,
                catalog=self.catalog,
                attestation_id="dff-" + observation.digest[:24],
                issuer_id=self.issuer_id,
                key_id=self.key_id,
                nonce="dfn-" + observation.digest[:24],
                issued_at=issued,
                expires_at=issued + self.validity,
                secret=self.secret,
            )
        except ValueError as exc:
            raise FaultAttestationRefusal(
                "refusal.attestation-rejected", f"{scenario.scenario_id}: {exc}"
            ) from exc


def load_fixture_fault_run(directory: Path, scenario_id: str) -> FixtureFaultRun:
    """Load one retained artifact triple and revalidate its internal binding."""

    base = Path(directory)
    evidence_payload = _read_json_object(
        base / f"{scenario_id}.evidence.json", "collector evidence"
    )
    observation_payload = _read_json_object(
        base / f"{scenario_id}.observation.json", "observation record"
    )
    raw_path = base / f"{scenario_id}.raw"
    if not raw_path.is_file() or raw_path.is_symlink():
        raise FaultAttestationRefusal(
            "refusal.artifact-missing", f"raw evidence is not a regular file: {raw_path.name}"
        )
    raw = raw_path.read_bytes()
    if len(raw) > _MAX_WIRE_BYTES:
        raise FaultAttestationRefusal(
            "refusal.artifact-oversized", f"raw evidence exceeds two MiB: {raw_path.name}"
        )
    try:
        evidence = load_fixture_fault_evidence_json(json.dumps(evidence_payload))
        observation = RuntimeFaultObservation.from_dict(observation_payload)
    except ValueError as exc:
        raise FaultAttestationRefusal(
            "refusal.artifact-malformed", f"{scenario_id}: {exc}"
        ) from exc
    try:
        return FixtureFaultRun(
            evidence=evidence, observation=observation, raw_evidence=raw
        )
    except (FixtureFaultCollectorError, ValueError) as exc:
        raise FaultAttestationRefusal(
            "refusal.run-binding-mismatch", f"{scenario_id}: {exc}"
        ) from exc


def issue_fixture_run_directory(
    directory: Path,
    *,
    issuer: FixtureFaultAttestationIssuer,
    key_class: str,
    issued_at: datetime,
) -> FixtureFaultAttestationBundle:
    """Attest every retained fixture row, recording each refusal by name."""

    issued = _as_utc(issued_at, "issued_at")
    attestations: list[RuntimeFaultAttestation] = []
    refusals: list[FaultAttestationRefusalRecord] = []
    for scenario_id in retained_scenario_ids(directory):
        try:
            run = load_fixture_fault_run(directory, scenario_id)
            attestations.append(issuer.issue(run, issued_at=issued))
        except FaultAttestationRefusal as exc:
            refusals.append(
                FaultAttestationRefusalRecord(
                    scenario_id=scenario_id, reason=exc.reason, detail=exc.detail
                )
            )
    return FixtureFaultAttestationBundle(
        schema=_SCHEMA,
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
        key_class=_key_class(key_class),
        key_sha256=key_fingerprint(issuer.secret),
        catalog_sha256=issuer.catalog.digest,
        source_revision=issuer.expected_source_revision,
        issued_at=issued.isoformat(timespec="microseconds"),
        attestations=tuple(attestations),
        refusals=tuple(refusals),
    )


def build_matrix_from_fixture_run_directory(
    directory: Path,
    *,
    catalog: RuntimeFaultCatalog,
    source_revision: str,
    matrix_id: str = "gate0-fixture-fault",
) -> RuntimeFaultMatrix:
    """Assemble the canonical matrix from retained observations, deterministically."""

    observations: list[RuntimeFaultObservation] = []
    for scenario_id in retained_scenario_ids(directory):
        payload = _read_json_object(
            Path(directory) / f"{scenario_id}.observation.json", "observation record"
        )
        try:
            observations.append(RuntimeFaultObservation.from_dict(payload))
        except ValueError as exc:
            raise FaultAttestationRefusal(
                "refusal.artifact-malformed", f"{scenario_id}: {exc}"
            ) from exc
    if not observations:
        raise FaultAttestationIssuerError("run directory retains no observations")
    return build_runtime_fault_matrix(
        matrix_id=matrix_id,
        source_revision=_revision(source_revision),
        observations=tuple(observations),
        generated_at=max(row.observed_at for row in observations),
        catalog=catalog,
        provenance_origin="daedalus.runtimes.fixture_fault_collector",
    )


def _load_bundle(payload: Mapping[str, Any]) -> tuple[
    tuple[RuntimeFaultAttestation, ...], str, str, str
]:
    if not isinstance(payload, Mapping):
        raise FaultAttestationIssuerError("attestation bundle must be an object")
    if payload.get("schema") != _SCHEMA:
        raise FaultAttestationIssuerError(f"attestation bundle schema must be {_SCHEMA}")
    rows = payload.get("attestations")
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise FaultAttestationIssuerError("attestation bundle attestations must be an array")
    return (
        tuple(RuntimeFaultAttestation.from_dict(row) for row in rows),
        _identifier(payload.get("issuer_id"), "issuer_id"),
        _identifier(payload.get("key_id"), "key_id"),
        _revision(payload.get("source_revision")),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Issue or verify signed attestations for retained deterministic-"
            "fixture runtime fault observations. This is an explicit operator "
            "step with its own authority and its own key; no collector calls it."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="sign every retained fixture observation")
    issue.add_argument("--run-dir", type=Path, required=True)
    issue.add_argument("--source-revision", required=True)
    issue.add_argument("--issuer-id", required=True)
    issue.add_argument("--key-id", required=True)
    issue.add_argument(
        "--fixture-key-env",
        required=True,
        help=(
            "name of the environment variable holding the fixture-column signing "
            "secret; deliberately not the Linux-host key parameter"
        ),
    )
    issue.add_argument(
        "--key-class",
        required=True,
        choices=sorted(_KEY_CLASSES),
        help="declare whether this key is a production or development key",
    )
    issue.add_argument("--validity-hours", type=int, default=24)
    issue.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify", help="verify a run directory against a bundle")
    verify.add_argument("--run-dir", type=Path, required=True)
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--source-revision", required=True)
    verify.add_argument("--fixture-key-env", required=True)

    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    if args.command == "issue":
        issuer = FixtureFaultAttestationIssuer(
            issuer_id=args.issuer_id,
            key_id=args.key_id,
            secret=_secret_from_env(args.fixture_key_env),
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=args.source_revision,
            validity=timedelta(hours=args.validity_hours),
        )
        bundle = issue_fixture_run_directory(
            args.run_dir, issuer=issuer, key_class=args.key_class, issued_at=now
        )
        _atomic_write(
            args.output, (canonical_json(bundle.to_dict()) + "\n").encode("utf-8")
        )
        print(
            canonical_json(
                {
                    "attested": len(bundle.attestations),
                    "refused": len(bundle.refusals),
                    "refusals": [row.to_dict() for row in bundle.refusals],
                    "bundle_sha256": bundle.digest,
                    "key_class": bundle.key_class,
                }
            )
        )
        return 0 if bundle.complete else 1

    payload = _read_json_object(args.bundle, "attestation bundle")
    attestations, issuer_id, _key_id, revision = _load_bundle(payload)
    if revision != _revision(args.source_revision):
        raise FaultAttestationIssuerError(
            "bundle source revision does not match the requested revision"
        )
    secret = _secret_from_env(args.fixture_key_env)
    matrix = build_matrix_from_fixture_run_directory(
        args.run_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision=revision
    )
    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=revision,
        attestations=attestations,
        keyring={(row.issuer_id, row.key_id): secret for row in attestations},
        issuer_authorities={issuer_id: (_AUTHORITY,)},
        now=now,
    )
    print(canonical_json(verification.to_dict()))
    return 0 if verification.closed else 1


__all__ = [
    "FixtureFaultAttestationBundle",
    "FixtureFaultAttestationIssuer",
    "build_matrix_from_fixture_run_directory",
    "issue_fixture_run_directory",
    "load_fixture_fault_run",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
