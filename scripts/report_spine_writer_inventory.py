from __future__ import annotations

import argparse
import sys
from pathlib import Path

from daedalus.spine.envelope import canonical_json
from daedalus.spine.writer_inventory import (
    WriterInventoryError,
    scan_event_store_writers,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report revision-bound production SpineLedger construction sites."
    )
    parser.add_argument(
        "repository",
        nargs="?",
        default=".",
        help="repository root containing the daedalus package",
    )
    parser.add_argument(
        "--source-revision",
        required=True,
        help="exact lowercase 40-hex repository revision",
    )
    parser.add_argument(
        "--require-closed",
        action="store_true",
        help="return nonzero when legacy or ambiguous production writers remain",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = scan_event_store_writers(
            Path(args.repository),
            source_revision=args.source_revision,
        )
    except WriterInventoryError as exc:
        sys.stderr.write(f"writer inventory refused: {exc}\n")
        return 2
    sys.stdout.write(canonical_json(report.to_dict()) + "\n")
    if args.require_closed and not report.closed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
