"""Verify one whole runtime fault matrix across both collector columns.

The combiner itself now lives in
``daedalus.runtimes.whole_fault_matrix.verify_whole_runtime_fault_matrix``, so
the gate report can bind the same verdict this run produced instead of trusting
a script that lives beside its own evidence.  This file is retained because the
receipt's reproduction steps name it, and it is a thin delegate: it parses the
same flags, reads the two development secrets from the environment, and writes
the same canonical artifact.  It mints nothing.

Usage::

    python runs/gate0-matrix-<date>/verify_whole_matrix.py \
        --fixture-run-dir <dir> --fixture-bundle <file> --fixture-key-env <name> \
        --host-run-dir <dir> --host-bundle <file> --host-key-env <name> \
        --source-revision <sha> --output <file>
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from daedalus.runtimes.whole_fault_matrix import (  # noqa: E402
    load_fault_attestation_bundle,
    verify_whole_runtime_fault_matrix,
)
from daedalus.spine.envelope import canonical_json  # noqa: E402


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

    verdict = verify_whole_runtime_fault_matrix(
        fixture_run_dir=args.fixture_run_dir,
        fixture_bundle=load_fault_attestation_bundle(
            args.fixture_bundle, authority="deterministic-fixture"
        ),
        fixture_secret=_secret(args.fixture_key_env),
        host_run_dir=args.host_run_dir,
        host_bundle=load_fault_attestation_bundle(
            args.host_bundle, authority="linux-host"
        ),
        host_secret=_secret(args.host_key_env),
        source_revision=args.source_revision,
        now=datetime.now(timezone.utc),
    )

    args.output.write_text(canonical_json(verdict.to_dict()) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "closed": verdict.closed,
                "blocker_count": verdict.blocker_count,
                "blockers_by_class": {
                    name: len(rows)
                    for name, rows in verdict.blockers_by_class.items()
                },
                "matrix_sha256": verdict.matrix_sha256,
            }
        )
    )
    return 0 if verdict.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
