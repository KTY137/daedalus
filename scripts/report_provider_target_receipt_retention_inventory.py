"""Emit the provider-target receipt-retention inventory as canonical JSON."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from daedalus.gates.provider_target_receipt_retention_inventory import (
    ProviderTargetReceiptRetentionInventoryError,
    scan_provider_target_receipt_retention,
)
from daedalus.spine.envelope import canonical_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        report = scan_provider_target_receipt_retention(
            args.repository_root,
            source_revision=args.source_revision,
        )
    except ProviderTargetReceiptRetentionInventoryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(canonical_json(report.to_dict()))
    return 0 if report.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
