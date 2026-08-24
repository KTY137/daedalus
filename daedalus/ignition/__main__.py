"""``python -m daedalus.ignition`` -- run the Gate-1 slice once, print the receipt head.

Read-only with respect to the repository except for the receipt directory and
its content-addressed store. It promotes nothing: the exit code reports whether
the slice reached a clean, packet-bearing result, not whether anything may be
merged.
"""
from __future__ import annotations

import argparse
import json
import sys

from daedalus.ignition.gate1 import (
    DEFAULT_FIXTURE,
    DEFAULT_RECEIPT_ROOT,
    run_gate1_ignition,
)

RECEIPT_HEAD_KEYS = (
    "schema",
    "gate",
    "collected_at",
    "mission_id",
    "mission_sha256",
    "work_item_ids",
    "check_kinds",
    "attempts",
    "evidence_packet",
    "promotion",
    "replay",
    "evaluator_bundle_artifact",
    "blockers",
    "blocker",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m daedalus.ignition")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--receipts", default=str(DEFAULT_RECEIPT_ROOT))
    parser.add_argument("--workspace", default=None,
                        help="scratch directory to keep instead of a temp dir")
    parser.add_argument("--collected-at", default=None,
                        help="freeze the UTC timestamp (for replay comparison)")
    parser.add_argument("--gate-timeout-s", type=int, default=300)
    args = parser.parse_args(argv)

    result = run_gate1_ignition(
        fixture_root=args.fixture,
        receipt_root=args.receipts,
        workspace=args.workspace,
        collected_at=args.collected_at,
        gate_timeout_s=args.gate_timeout_s,
    )
    head = {key: result.receipt[key] for key in RECEIPT_HEAD_KEYS if key in result.receipt}
    print(json.dumps(head, indent=2, sort_keys=True))
    print(f"\nreceipt: {result.receipt_path}", file=sys.stderr)
    return 1 if result.blockers or result.packet is None else 0


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())
