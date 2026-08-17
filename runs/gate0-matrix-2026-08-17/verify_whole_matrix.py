"""Verify one whole runtime fault matrix across both collector columns.

Each issuer verifies only its own column, so neither can answer the question the
gate actually asks: is *every* required row of the canonical catalog covered by a
trusted observation at one exact revision? This script assembles both columns
into a single matrix and runs the canonical attested verification over it. It
mints nothing: the observations come from the two collectors, the trust comes
from the two attestation bundles, and the verdict comes from
``verify_attested_runtime_fault_matrix``.

It is retained next to the evidence it produced so the verdict is reproducible.

Usage::

    python runs/gate0-matrix-<date>/verify_whole_matrix.py \
        --fixture-run-dir <dir> --fixture-bundle <file> --fixture-key-env <name> \
        --host-run-dir <dir> --host-bundle <file> --host-key-env <name> \
        --source-revision <sha> --output <file>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from daedalus.runtimes.fault_attestation_issuer import (  # noqa: E402
    build_matrix_from_run_directory,
)
from daedalus.runtimes.fault_attestations import (  # noqa: E402
    RuntimeFaultAttestation,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import (  # noqa: E402
    RUNTIME_FAULT_CATALOG,
    build_runtime_fault_matrix,
)
from daedalus.runtimes.fixture_fault_attestation_issuer import (  # noqa: E402
    build_matrix_from_fixture_run_directory,
)
from daedalus.spine.envelope import canonical_json  # noqa: E402


def _bundle(path: Path) -> tuple[tuple[RuntimeFaultAttestation, ...], str, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = tuple(
        RuntimeFaultAttestation.from_dict(row) for row in payload["attestations"]
    )
    return rows, str(payload["issuer_id"]), str(payload["key_class"])


def _secret(env_name: str) -> bytes:
    value = os.environ.get(env_name)
    if not value:
        raise SystemExit(f"environment variable {env_name} is unset or empty")
    return value.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-run-dir", type=Path, required=True)
    parser.add_argument("--fixture-bundle", type=Path, required=True)
    parser.add_argument("--fixture-key-env", required=True)
    parser.add_argument("--host-run-dir", type=Path, required=True)
    parser.add_argument("--host-bundle", type=Path, required=True)
    parser.add_argument("--host-key-env", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    revision = args.source_revision
    catalog = RUNTIME_FAULT_CATALOG

    # Reuse each column's own loader so its artifact-binding refusals still apply,
    # then keep only the observations and rebuild one matrix over both columns.
    fixture_matrix = build_matrix_from_fixture_run_directory(
        args.fixture_run_dir, catalog=catalog, source_revision=revision
    )
    host_matrix = build_matrix_from_run_directory(
        args.host_run_dir, catalog=catalog, source_revision=revision
    )
    observations = tuple(fixture_matrix.observations) + tuple(host_matrix.observations)
    matrix = build_runtime_fault_matrix(
        matrix_id="gate0-whole-runtime-fault-matrix",
        source_revision=revision,
        observations=observations,
        generated_at=max(row.observed_at for row in observations),
        catalog=catalog,
    )

    fixture_rows, fixture_issuer, fixture_key_class = _bundle(args.fixture_bundle)
    host_rows, host_issuer, host_key_class = _bundle(args.host_bundle)
    if fixture_issuer == host_issuer:
        raise SystemExit("the two columns must not share one issuer identity")

    fixture_secret = _secret(args.fixture_key_env)
    host_secret = _secret(args.host_key_env)
    keyring = {
        **{(row.issuer_id, row.key_id): fixture_secret for row in fixture_rows},
        **{(row.issuer_id, row.key_id): host_secret for row in host_rows},
    }

    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=catalog,
        expected_source_revision=revision,
        attestations=fixture_rows + host_rows,
        keyring=keyring,
        # Each issuer may speak only for its own column. A fixture signature over
        # a Linux-host row, or the reverse, is refused here rather than counted.
        issuer_authorities={
            fixture_issuer: ("deterministic-fixture",),
            host_issuer: ("linux-host",),
        },
        now=datetime.now(timezone.utc),
    )

    blockers = list(verification.fault_verification.blockers)
    by_class: dict[str, list[str]] = {}
    for blocker in blockers:
        by_class.setdefault(blocker.split(":", 1)[0], []).append(blocker)

    report = {
        "source_revision": revision,
        "catalog_sha256": catalog.digest,
        "catalog_scenarios": len(catalog.scenarios),
        "matrix_sha256": matrix.digest,
        "observations": len(observations),
        "columns": {
            "deterministic-fixture": {
                "issuer_id": fixture_issuer,
                "key_class": fixture_key_class,
                "observations": len(fixture_matrix.observations),
                "attestations": len(fixture_rows),
            },
            "linux-host": {
                "issuer_id": host_issuer,
                "key_class": host_key_class,
                "observations": len(host_matrix.observations),
                "attestations": len(host_rows),
            },
        },
        "closed": verification.fault_verification.closed,
        "blocker_count": len(blockers),
        "blockers_by_class": {
            name: sorted(rows) for name, rows in sorted(by_class.items())
        },
        "verification": verification.to_dict(),
    }
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "closed": report["closed"],
                "blocker_count": report["blocker_count"],
                "blockers_by_class": {
                    name: len(rows) for name, rows in sorted(by_class.items())
                },
                "matrix_sha256": report["matrix_sha256"],
            }
        )
    )
    return 0 if verification.fault_verification.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
