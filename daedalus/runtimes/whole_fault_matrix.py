"""One whole runtime fault matrix across every collector column, and its verdict.

Each column issuer verifies only its own authority, so no single issuer can answer
the question the gate actually asks: is *every* required row of the canonical
catalog covered by a trusted observation at one exact revision?  This module
assembles the columns into one matrix, runs the canonical attested verification
over it, and gives the result a content-addressed contract identity so a gate
report can bind it instead of re-deriving it.

The module mints no trust of its own.  Observations come from each column's own
loader, trust comes from that column's attestation bundle, and the verdict comes
from :func:`verify_attested_runtime_fault_matrix`.  A verdict is an observation
record, never an approval: ``closed`` here means "every required row was observed,
trusted and matched", and it says nothing about whether the signing key material
is production custody.  That distinction is carried in ``key_class`` and is the
consumer's to enforce.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from daedalus.runtimes.fault_attestation_issuer import (
    build_matrix_from_run_directory,
)
from daedalus.runtimes.fault_attestations import (
    AttestedRuntimeFaultVerification,
    RuntimeFaultAttestation,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultCatalog,
    RuntimeFaultVerification,
    build_runtime_fault_matrix,
)
from daedalus.runtimes.fixture_fault_attestation_issuer import (
    build_matrix_from_fixture_run_directory,
)
from daedalus.spine.envelope import canonical_sha


VERDICT_FILENAME = "whole-matrix-verdict.json"
WHOLE_MATRIX_ID = "gate0-whole-runtime-fault-matrix"
PRODUCTION_KEY_CLASS = "production"

_MAX_VERDICT_BYTES = 4 * 1024 * 1024
_VERDICT_FIELDS = frozenset(
    {
        "source_revision",
        "catalog_sha256",
        "catalog_scenarios",
        "matrix_sha256",
        "observations",
        "columns",
        "closed",
        "blocker_count",
        "blockers_by_class",
        "verification",
    }
)
_COLUMN_FIELDS = frozenset({"issuer_id", "key_class", "observations", "attestations"})
_FAULT_VERIFICATION_FIELDS = frozenset(
    {
        "matrix_sha256",
        "catalog_sha256",
        "source_revision",
        "trusted_observation_sha256s",
        "blockers",
        "closed",
    }
)
_ATTESTED_FIELDS = frozenset(
    {"fault_verification", "attestation_sha256s", "verified_at", "closed"}
)


class WholeRuntimeFaultMatrixError(ValueError):
    """A whole-matrix verdict is malformed, internally inconsistent, or unreadable."""


def catalog_authorities(catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG) -> frozenset[str]:
    """The exact set of collector authorities the canonical catalog speaks about."""

    return frozenset(scenario.authority for scenario in catalog.scenarios)


def _exact_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WholeRuntimeFaultMatrixError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise WholeRuntimeFaultMatrixError(f"{label} keys must be strings")
    return value


def _exact_fields(payload: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(payload) != expected:
        raise WholeRuntimeFaultMatrixError(f"{label} fields are not exact")


def _exact_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise WholeRuntimeFaultMatrixError(f"{label} must be a non-negative integer")
    return value


def _exact_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise WholeRuntimeFaultMatrixError(f"{label} must be a boolean")
    return value


def _exact_text(value: Any, label: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WholeRuntimeFaultMatrixError(f"{label} must be a bounded non-empty string")
    return value


def _exact_rows(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise WholeRuntimeFaultMatrixError(f"{label} must be an array")
    rows = tuple(_exact_text(row, f"{label} row") for row in value)
    if len(rows) != len(set(rows)):
        raise WholeRuntimeFaultMatrixError(f"{label} must be unique")
    if list(rows) != sorted(rows):
        raise WholeRuntimeFaultMatrixError(f"{label} must be sorted")
    return rows


@dataclass(frozen=True)
class WholeMatrixColumn:
    """What one collector authority contributed, and under whose key custody."""

    authority: str
    issuer_id: str
    key_class: str
    observations: int
    attestations: int

    def __post_init__(self) -> None:
        if self.authority not in catalog_authorities():
            raise WholeRuntimeFaultMatrixError(
                f"unknown collector authority: {self.authority!r}"
            )
        object.__setattr__(self, "issuer_id", _exact_text(self.issuer_id, "issuer_id", maximum=128))
        object.__setattr__(self, "key_class", _exact_text(self.key_class, "key_class", maximum=64))
        object.__setattr__(
            self, "observations", _exact_int(self.observations, "column observations")
        )
        object.__setattr__(
            self, "attestations", _exact_int(self.attestations, "column attestations")
        )

    @property
    def production_key_material(self) -> bool:
        return self.key_class == PRODUCTION_KEY_CLASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "issuer_id": self.issuer_id,
            "key_class": self.key_class,
            "observations": self.observations,
            "attestations": self.attestations,
        }

    @classmethod
    def from_dict(cls, authority: str, payload: Mapping[str, Any]) -> "WholeMatrixColumn":
        body = _exact_mapping(payload, f"column {authority}")
        _exact_fields(body, _COLUMN_FIELDS, f"column {authority}")
        return cls(
            authority=authority,
            issuer_id=body["issuer_id"],
            key_class=body["key_class"],
            observations=_exact_int(body["observations"], "column observations"),
            attestations=_exact_int(body["attestations"], "column attestations"),
        )


def _fault_verification_from_dict(payload: Mapping[str, Any]) -> RuntimeFaultVerification:
    body = _exact_mapping(payload, "fault_verification")
    _exact_fields(body, _FAULT_VERIFICATION_FIELDS, "fault_verification")
    try:
        verification = RuntimeFaultVerification(
            matrix_sha256=body["matrix_sha256"],
            catalog_sha256=body["catalog_sha256"],
            source_revision=body["source_revision"],
            trusted_observation_sha256s=tuple(
                _exact_rows(body["trusted_observation_sha256s"], "trusted_observation_sha256s")
            ),
            blockers=_exact_rows(body["blockers"], "blockers"),
        )
    except ValueError as exc:
        raise WholeRuntimeFaultMatrixError(str(exc)) from exc
    if _exact_bool(body["closed"], "fault_verification.closed") != verification.closed:
        raise WholeRuntimeFaultMatrixError(
            "fault_verification closed flag contradicts its own blockers"
        )
    return verification


def _attested_from_dict(payload: Mapping[str, Any]) -> AttestedRuntimeFaultVerification:
    body = _exact_mapping(payload, "verification")
    _exact_fields(body, _ATTESTED_FIELDS, "verification")
    fault_verification = _fault_verification_from_dict(body["fault_verification"])
    try:
        attested = AttestedRuntimeFaultVerification(
            fault_verification=fault_verification,
            attestation_sha256s=tuple(
                _exact_rows(body["attestation_sha256s"], "attestation_sha256s")
            ),
            verified_at=_exact_text(body["verified_at"], "verified_at", maximum=64),
        )
    except ValueError as exc:
        raise WholeRuntimeFaultMatrixError(str(exc)) from exc
    if _exact_bool(body["closed"], "verification.closed") != attested.closed:
        raise WholeRuntimeFaultMatrixError(
            "verification closed flag contradicts its own fault verification"
        )
    return attested


@dataclass(frozen=True)
class WholeRuntimeFaultMatrixVerdict:
    """The revision-atomic verdict over every collector column at one revision."""

    source_revision: str
    catalog_sha256: str
    catalog_scenarios: int
    matrix_sha256: str
    observations: int
    columns: tuple[WholeMatrixColumn, ...]
    verification: AttestedRuntimeFaultVerification

    def __post_init__(self) -> None:
        if not isinstance(self.verification, AttestedRuntimeFaultVerification):
            raise WholeRuntimeFaultMatrixError(
                "verdict requires an exact attested runtime fault verification"
            )
        columns = tuple(sorted(self.columns, key=lambda column: column.authority))
        if not columns:
            raise WholeRuntimeFaultMatrixError("a whole matrix needs at least one column")
        authorities = tuple(column.authority for column in columns)
        if len(authorities) != len(set(authorities)):
            raise WholeRuntimeFaultMatrixError("each authority may contribute one column")
        issuers = tuple(column.issuer_id for column in columns)
        if len(issuers) != len(set(issuers)):
            raise WholeRuntimeFaultMatrixError(
                "the columns must not share one issuer identity"
            )
        object.__setattr__(self, "columns", columns)
        object.__setattr__(
            self, "catalog_scenarios", _exact_int(self.catalog_scenarios, "catalog_scenarios")
        )
        if self.catalog_scenarios < 1:
            raise WholeRuntimeFaultMatrixError("catalog_scenarios must be positive")
        object.__setattr__(self, "observations", _exact_int(self.observations, "observations"))

        fault = self.verification.fault_verification
        if self.source_revision != fault.source_revision:
            raise WholeRuntimeFaultMatrixError(
                "verdict revision contradicts its own verification"
            )
        if self.catalog_sha256 != fault.catalog_sha256:
            raise WholeRuntimeFaultMatrixError(
                "verdict catalog digest contradicts its own verification"
            )
        if self.matrix_sha256 != fault.matrix_sha256:
            raise WholeRuntimeFaultMatrixError(
                "verdict matrix digest contradicts its own verification"
            )
        if self.observations != sum(column.observations for column in columns):
            raise WholeRuntimeFaultMatrixError(
                "verdict observation count contradicts its columns"
            )
        if len(self.verification.attestation_sha256s) != sum(
            column.attestations for column in columns
        ):
            raise WholeRuntimeFaultMatrixError(
                "verdict attestation count contradicts its columns"
            )

    @property
    def closed(self) -> bool:
        """Every required row was observed, trusted and matched.  Not an approval."""

        return self.verification.closed

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.verification.blockers

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)

    @property
    def blockers_by_class(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for blocker in self.blockers:
            grouped.setdefault(blocker.split(":", 1)[0], []).append(blocker)
        return {name: tuple(sorted(rows)) for name, rows in sorted(grouped.items())}

    @property
    def key_classes(self) -> tuple[str, ...]:
        return tuple(sorted({column.key_class for column in self.columns}))

    @property
    def production_key_material(self) -> bool:
        """True only when every contributing column signed under production custody."""

        return all(column.production_key_material for column in self.columns)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "catalog_sha256": self.catalog_sha256,
            "catalog_scenarios": self.catalog_scenarios,
            "matrix_sha256": self.matrix_sha256,
            "observations": self.observations,
            "columns": {
                column.authority: column.to_dict() for column in self.columns
            },
            "closed": self.closed,
            "blocker_count": self.blocker_count,
            "blockers_by_class": {
                name: list(rows) for name, rows in self.blockers_by_class.items()
            },
            "verification": self.verification.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WholeRuntimeFaultMatrixVerdict":
        body = _exact_mapping(payload, "whole matrix verdict")
        _exact_fields(body, _VERDICT_FIELDS, "whole matrix verdict")
        columns_payload = _exact_mapping(body["columns"], "columns")
        columns = tuple(
            WholeMatrixColumn.from_dict(authority, columns_payload[authority])
            for authority in sorted(columns_payload)
        )
        verdict = cls(
            source_revision=_exact_text(body["source_revision"], "source_revision", maximum=64),
            catalog_sha256=_exact_text(body["catalog_sha256"], "catalog_sha256", maximum=64),
            catalog_scenarios=_exact_int(body["catalog_scenarios"], "catalog_scenarios"),
            matrix_sha256=_exact_text(body["matrix_sha256"], "matrix_sha256", maximum=64),
            observations=_exact_int(body["observations"], "observations"),
            columns=columns,
            verification=_attested_from_dict(body["verification"]),
        )
        if _exact_bool(body["closed"], "closed") != verdict.closed:
            raise WholeRuntimeFaultMatrixError(
                "verdict closed flag contradicts its own verification"
            )
        if _exact_int(body["blocker_count"], "blocker_count") != verdict.blocker_count:
            raise WholeRuntimeFaultMatrixError(
                "verdict blocker count contradicts its own blockers"
            )
        grouped = _exact_mapping(body["blockers_by_class"], "blockers_by_class")
        expected = verdict.blockers_by_class
        if set(grouped) != set(expected):
            raise WholeRuntimeFaultMatrixError(
                "verdict blocker classes contradict its own blockers"
            )
        for name in sorted(grouped):
            if _exact_rows(grouped[name], f"blockers_by_class[{name}]") != expected[name]:
                raise WholeRuntimeFaultMatrixError(
                    f"verdict blocker class {name} contradicts its own blockers"
                )
        if dict(body) != verdict.to_dict():
            raise WholeRuntimeFaultMatrixError("whole matrix verdict is non-canonical")
        return verdict


@dataclass(frozen=True)
class FaultAttestationBundle:
    """One column's attestation rows plus the identity and custody they claim."""

    authority: str
    issuer_id: str
    key_class: str
    attestations: tuple[RuntimeFaultAttestation, ...]

    def __post_init__(self) -> None:
        if self.authority not in catalog_authorities():
            raise WholeRuntimeFaultMatrixError(
                f"unknown collector authority: {self.authority!r}"
            )
        object.__setattr__(self, "issuer_id", _exact_text(self.issuer_id, "issuer_id", maximum=128))
        object.__setattr__(self, "key_class", _exact_text(self.key_class, "key_class", maximum=64))
        rows = tuple(self.attestations)
        if any(not isinstance(row, RuntimeFaultAttestation) for row in rows):
            raise WholeRuntimeFaultMatrixError(
                "an attestation bundle holds exact RuntimeFaultAttestation rows only"
            )
        if any(row.issuer_id != self.issuer_id for row in rows):
            raise WholeRuntimeFaultMatrixError(
                "every attestation in a bundle must carry the bundle issuer identity"
            )
        object.__setattr__(self, "attestations", rows)


def load_fault_attestation_bundle(path: str | Path, *, authority: str) -> FaultAttestationBundle:
    """Read one column's attestation bundle without granting it any authority."""

    payload = _read_json_object(Path(path), "attestation bundle")
    rows = payload.get("attestations")
    if not isinstance(rows, list):
        raise WholeRuntimeFaultMatrixError("attestation bundle must carry an attestations array")
    try:
        attestations = tuple(RuntimeFaultAttestation.from_dict(row) for row in rows)
    except (TypeError, ValueError) as exc:
        raise WholeRuntimeFaultMatrixError(f"attestation bundle is malformed: {exc}") from exc
    return FaultAttestationBundle(
        authority=authority,
        issuer_id=_exact_text(payload.get("issuer_id"), "issuer_id", maximum=128),
        key_class=_exact_text(payload.get("key_class"), "key_class", maximum=64),
        attestations=attestations,
    )


def _read_json_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WholeRuntimeFaultMatrixError(f"{label} could not be read") from exc
    if len(raw) > _MAX_VERDICT_BYTES:
        raise WholeRuntimeFaultMatrixError(f"{label} exceeds the maximum size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WholeRuntimeFaultMatrixError(f"{label} is malformed JSON") from exc
    if not isinstance(payload, dict):
        raise WholeRuntimeFaultMatrixError(f"{label} root must be an object")
    return payload


def load_whole_matrix_verdict(path: str | Path) -> WholeRuntimeFaultMatrixVerdict:
    """Load and fully re-validate a persisted whole-matrix verdict."""

    return WholeRuntimeFaultMatrixVerdict.from_dict(
        _read_json_object(Path(path), "whole matrix verdict")
    )


def verify_whole_runtime_fault_matrix(
    *,
    fixture_run_dir: str | Path,
    fixture_bundle: FaultAttestationBundle,
    fixture_secret: bytes,
    host_run_dir: str | Path,
    host_bundle: FaultAttestationBundle,
    host_secret: bytes,
    source_revision: str,
    now: datetime,
    catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG,
    matrix_id: str = WHOLE_MATRIX_ID,
) -> WholeRuntimeFaultMatrixVerdict:
    """Assemble both columns into one matrix and verify it as a whole.

    Each column keeps its own loader so that loader's artifact-binding refusals
    still apply, and each issuer is authorized for exactly one authority, so a
    fixture signature over a Linux-host row (or the reverse) is refused here
    rather than counted.
    """

    if fixture_bundle.issuer_id == host_bundle.issuer_id:
        raise WholeRuntimeFaultMatrixError(
            "the two columns must not share one issuer identity"
        )
    if fixture_bundle.authority == host_bundle.authority:
        raise WholeRuntimeFaultMatrixError(
            "the two columns must not claim the same authority"
        )

    fixture_matrix = build_matrix_from_fixture_run_directory(
        Path(fixture_run_dir), catalog=catalog, source_revision=source_revision
    )
    host_matrix = build_matrix_from_run_directory(
        Path(host_run_dir), catalog=catalog, source_revision=source_revision
    )
    observations = tuple(fixture_matrix.observations) + tuple(host_matrix.observations)
    if not observations:
        raise WholeRuntimeFaultMatrixError("a whole matrix needs at least one observation")
    matrix = build_runtime_fault_matrix(
        matrix_id=matrix_id,
        source_revision=source_revision,
        observations=observations,
        generated_at=max(row.observed_at for row in observations),
        catalog=catalog,
    )

    keyring: dict[tuple[str, str], bytes] = {}
    for bundle, secret in ((fixture_bundle, fixture_secret), (host_bundle, host_secret)):
        for row in bundle.attestations:
            keyring[(row.issuer_id, row.key_id)] = secret

    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=catalog,
        expected_source_revision=source_revision,
        attestations=fixture_bundle.attestations + host_bundle.attestations,
        keyring=keyring,
        issuer_authorities={
            fixture_bundle.issuer_id: (fixture_bundle.authority,),
            host_bundle.issuer_id: (host_bundle.authority,),
        },
        now=now,
    )

    columns = (
        WholeMatrixColumn(
            authority=fixture_bundle.authority,
            issuer_id=fixture_bundle.issuer_id,
            key_class=fixture_bundle.key_class,
            observations=len(fixture_matrix.observations),
            attestations=len(fixture_bundle.attestations),
        ),
        WholeMatrixColumn(
            authority=host_bundle.authority,
            issuer_id=host_bundle.issuer_id,
            key_class=host_bundle.key_class,
            observations=len(host_matrix.observations),
            attestations=len(host_bundle.attestations),
        ),
    )
    return WholeRuntimeFaultMatrixVerdict(
        source_revision=source_revision,
        catalog_sha256=catalog.digest,
        catalog_scenarios=len(catalog.scenarios),
        matrix_sha256=matrix.digest,
        observations=len(observations),
        columns=columns,
        verification=verification,
    )


def discover_whole_matrix_verdicts(
    repo_root: str | Path,
    *,
    pattern: str = "runs/gate0-matrix-*",
) -> tuple[Path, ...]:
    """Every persisted whole-matrix verdict under the repository, deterministically."""

    root = Path(repo_root)
    return tuple(
        sorted(
            candidate
            for candidate in root.glob(f"{pattern}/{VERDICT_FILENAME}")
            if candidate.is_file()
        )
    )


__all__ = [
    "FaultAttestationBundle",
    "PRODUCTION_KEY_CLASS",
    "VERDICT_FILENAME",
    "WHOLE_MATRIX_ID",
    "WholeMatrixColumn",
    "WholeRuntimeFaultMatrixError",
    "WholeRuntimeFaultMatrixVerdict",
    "catalog_authorities",
    "discover_whole_matrix_verdicts",
    "load_fault_attestation_bundle",
    "load_whole_matrix_verdict",
    "verify_whole_runtime_fault_matrix",
]
