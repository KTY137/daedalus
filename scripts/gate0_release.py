"""Owner-facing CLI over the sealed Gate-0 release receipt contract.

``issue`` re-verifies the exact retained evidence through
:func:`daedalus.gates.release.issue_gate0_release_receipt` and, only on
success, writes one signed release receipt to ``--output``.  ``verify``
authenticates one retained receipt read-only through
:func:`daedalus.gates.release.verify_gate0_release_receipt`.

The command adds no policy of its own: every decision is made by the
canonical release module.  The verifier signing secret is consumed only from
the ``DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET`` environment variable and is
never written to stdout, stderr, or any file.  Refusals exit 1 and never
touch the ``--output`` path.  Success is silent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from daedalus.gates import load_gate_evidence_index
from daedalus.gates.release import (
    Gate0ReleaseError,
    issue_gate0_release_receipt,
    load_gate0_release_receipt,
    load_strict_gate_report,
    verify_gate0_release_receipt,
)
from daedalus.gates.trust_bundle import (
    EvidenceTrustBundleError,
    load_evidence_trust_bundle,
)

_SECRET_ENV = "DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET"


def _keyring(
    values: Sequence[str],
    label: str,
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for raw in values:
        parts = raw.split(":", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError(f"{label} must use OWNER_ID:KEY_ID:SECRET")
        owner_id, key_id, secret = (
            parts[0].strip(),
            parts[1].strip(),
            parts[2],
        )
        if (owner_id, key_id) in result:
            raise ValueError(f"{label} repeats key {owner_id}:{key_id}")
        result[(owner_id, key_id)] = secret
    if not result:
        raise ValueError(f"at least one {label} is required")
    return result


def _workflow_map(
    values: Sequence[str],
    repo_root: Path,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        workflow_id, separator, repository_path = raw.partition(":")
        if (
            not separator
            or not workflow_id.strip()
            or not repository_path.strip()
        ):
            raise ValueError(
                "--expected-workflow must use WORKFLOW_ID:REPOSITORY_PATH"
            )
        workflow_id = workflow_id.strip()
        if workflow_id in result:
            raise ValueError(f"duplicate workflow mapping {workflow_id!r}")
        candidate = Path(repository_path.strip())
        if candidate.is_absolute():
            candidate = candidate.resolve().relative_to(repo_root.resolve())
        result[workflow_id] = candidate.as_posix()
    if not result:
        raise ValueError(
            "at least one --expected-workflow mapping is required"
        )
    return result


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--report", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--trust-bundle", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--collector-key",
        action="append",
        default=[],
        metavar="COLLECTOR_ID:KEY_ID:SECRET",
    )
    parser.add_argument("--expected-collector-id", required=True)
    parser.add_argument(
        "--expected-workflow",
        action="append",
        default=[],
        metavar="WORKFLOW_ID:REPOSITORY_PATH",
    )
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--current-tree-revision", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate0_release.py",
        description=(
            "Issue or verify one signed Gate-0 release receipt over exact "
            "retained evidence through the canonical release contract."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue")
    _add_shared_arguments(issue)
    issue.add_argument("--receipt-id", required=True)
    issue.add_argument("--verifier-id", required=True)
    issue.add_argument("--verifier-key-id", required=True)
    issue.add_argument("--verified-at", required=True)
    issue.add_argument("--output", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", required=True)
    _add_shared_arguments(verify)
    verify.add_argument(
        "--verifier-key",
        action="append",
        default=[],
        metavar="VERIFIER_ID:KEY_ID:SECRET",
    )
    verify.add_argument("--expected-verifier-id", required=True)
    verify.add_argument("--now", required=True)
    return parser


def _load_inputs(args: argparse.Namespace):
    report = load_strict_gate_report(Path(args.report))
    index = load_gate_evidence_index(Path(args.index))
    bundle = load_evidence_trust_bundle(Path(args.trust_bundle))
    return report, index, bundle


def _shared_values(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(args.repo_root)
    return {
        "repo_root": repo_root,
        "collector_keyring": _keyring(args.collector_key, "--collector-key"),
        "expected_collector_id": args.expected_collector_id,
        "expected_workflow_paths": _workflow_map(
            args.expected_workflow,
            repo_root,
        ),
        "current_revision": args.current_revision,
        "current_tree_revision": args.current_tree_revision,
    }


def _issue(args: argparse.Namespace) -> None:
    secret = os.environ.get(_SECRET_ENV, "")
    if not secret:
        raise ValueError(
            f"release verifier secret is not configured; export {_SECRET_ENV}"
        )
    report, index, bundle = _load_inputs(args)
    receipt = issue_gate0_release_receipt(
        report,
        index,
        bundle,
        **_shared_values(args),
        receipt_id=args.receipt_id,
        verifier_id=args.verifier_id,
        verifier_key_id=args.verifier_key_id,
        verifier_secret=secret,
        verified_at=_timestamp(args.verified_at, "--verified-at"),
    )
    payload = (
        json.dumps(
            receipt.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    )
    Path(args.output).write_text(payload, encoding="utf-8", newline="\n")


def _verify(args: argparse.Namespace) -> None:
    receipt = load_gate0_release_receipt(Path(args.receipt))
    report, index, bundle = _load_inputs(args)
    verify_gate0_release_receipt(
        receipt,
        report,
        index,
        bundle,
        **_shared_values(args),
        verifier_keyring=_keyring(args.verifier_key, "--verifier-key"),
        expected_verifier_id=args.expected_verifier_id,
        now=_timestamp(args.now, "--now"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "issue":
            _issue(args)
        else:
            _verify(args)
    except (
        Gate0ReleaseError,
        EvidenceTrustBundleError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
    ) as exc:
        sys.stderr.write(f"gate0 release {args.command} refused: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
