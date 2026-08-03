"""Read-only command line verification for a retained Gate-0 release report.

The command never assembles evidence, issues credentials, writes a report,
merges, promotes, or mutates a repository.  It consumes one collector secret
from an explicitly named environment variable and emits only a canonical JSON
verification result.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from daedalus.spine.envelope import canonical_json

from .evidence_io import load_gate_evidence_index
from .release_io import load_gate0_release_report
from .release_verifier import gate0_release_verification_blockers
from .report import load_gate_report
from .trust_bundle import load_evidence_trust_bundle

_RESULT_SCHEMA = "daedalus-gate0-release-verification/1"


def _utc(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--now must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)


def _workflow_map(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        workflow_id, separator, repository_path = raw.partition("=")
        if not separator or not workflow_id.strip() or not repository_path.strip():
            raise ValueError("--workflow must use WORKFLOW_ID=REPOSITORY_PATH")
        workflow_id = workflow_id.strip()
        repository_path = repository_path.strip()
        if workflow_id in result:
            raise ValueError(f"duplicate workflow mapping {workflow_id!r}")
        result[workflow_id] = repository_path
    if not result:
        raise ValueError("at least one --workflow mapping is required")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m daedalus.gates.release_cli",
        description="Verify one retained Gate-0 release against current exact-head state.",
    )
    parser.add_argument("--release", required=True)
    parser.add_argument("--mechanical-report", required=True)
    parser.add_argument("--evidence-index", required=True)
    parser.add_argument("--trust-bundle", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--collector-id", required=True)
    parser.add_argument("--collector-key-id", required=True)
    parser.add_argument("--collector-secret-env", required=True)
    parser.add_argument("--workflow", action="append", default=[])
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--current-tree-revision", required=True)
    parser.add_argument("--now")
    return parser


def _error_result(exc: Exception) -> dict[str, object]:
    return {
        "contract_type": _RESULT_SCHEMA,
        "trusted": False,
        "blockers": [f"verification-input:{type(exc).__name__}"],
        "error": str(exc),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workflows = _workflow_map(args.workflow)
        secret = os.environ.get(args.collector_secret_env)
        if secret is None or len(secret.encode("utf-8")) < 32:
            raise ValueError(
                "collector secret environment variable is missing or shorter than 32 bytes"
            )
        release = load_gate0_release_report(args.release)
        mechanical_report = load_gate_report(args.mechanical_report)
        evidence_index = load_gate_evidence_index(args.evidence_index)
        trust_bundle = load_evidence_trust_bundle(args.trust_bundle)
        blockers = gate0_release_verification_blockers(
            release,
            mechanical_report,
            evidence_index,
            trust_bundle,
            repo_root=Path(args.repo_root),
            collector_keyring={(args.collector_id, args.collector_key_id): secret},
            expected_collector_id=args.collector_id,
            expected_workflow_paths=workflows,
            current_revision=args.current_revision,
            current_tree_revision=args.current_tree_revision,
            now=_utc(args.now),
        )
        result = {
            "contract_type": _RESULT_SCHEMA,
            "release_sha256": release.digest,
            "source_revision": release.source_revision,
            "source_tree_revision": release.source_tree_revision,
            "trusted": not blockers,
            "blockers": list(blockers),
        }
        print(canonical_json(result))
        return 0 if not blockers else 1
    except Exception as exc:  # noqa: BLE001 - malformed input is a deterministic refusal
        print(canonical_json(_error_result(exc)))
        return 2


if __name__ == "__main__":
    sys.exit(main())
