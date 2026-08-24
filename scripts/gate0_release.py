"""Owner-facing audit CLI over the retired Gate-0 release receipt contract.

Invoked as ``python -m scripts.gate0_release``, both subcommands strictly parse
their retained historical inputs and then enter the canonical retirement
barrier. They do not verify trust, consume a signing secret, issue a receipt, or
live-validate an old receipt. Refusals exit 1 and never touch ``--output``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from daedalus.gates import load_gate_evidence_index
from daedalus.gates.release import (
    Gate0ReleaseError,
    assert_gate0_release_available,
    load_gate0_release_receipt,
    load_strict_gate_report,
)
from daedalus.gates.trust_bundle import (
    EvidenceTrustBundleError,
    load_evidence_trust_bundle,
)

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
            "Inspect the retired Gate-0 release contract. Issue and live "
            "verification remain blocked pending authenticated GateReportV3 "
            "repository-write admission binding."
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


def _issue(args: argparse.Namespace) -> None:
    _load_inputs(args)
    assert_gate0_release_available()


def _verify(args: argparse.Namespace) -> None:
    load_gate0_release_receipt(Path(args.receipt))
    _load_inputs(args)
    assert_gate0_release_available()


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
