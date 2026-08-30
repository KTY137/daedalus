#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Emit the provider-observation persistence inventory as canonical JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from daedalus.gates.provider_observation_persistence_inventory import (
    ProviderObservationPersistenceInventoryError,
    scan_provider_observation_persistence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report unguarded provider-observation persistence surfaces."
    )
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = scan_provider_observation_persistence(
            args.repository_root,
            source_revision=args.source_revision,
        )
    except ProviderObservationPersistenceInventoryError as exc:
        print(
            json.dumps(
                {
                    "schema": "daedalus-gate0-provider-observation-persistence-inventory-error/1",
                    "closed": False,
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0 if report.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
