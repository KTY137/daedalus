"""EXPERIMENT s06 probe: how many Node Cards does one revision produce, and how big are they?

Read-only.  Builds a Node Card for every node record the stand-in extractor
emits over one tree and prints ONE JSON object with RAW counts: cards per
plane and kind, contract violations, content/neighborhood truncation, and the
size distribution in canonical bytes.  Nothing is written, imported from the
production packages, fetched, or promoted.

Usage:  python experiments/forest_v2/s06_cards/probe_node_cards.py [ROOT]
        python experiments/forest_v2/s06_cards/probe_node_cards.py --content-budget 400
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from node_cards import (  # noqa: E402
    DEFAULT_CONTENT_BUDGET,
    DEFAULT_NEIGHBOR_BUDGET,
    build_card,
    card_size_bytes,
    size_stats,
    tally,
)
from negative_fixtures import counter_liveness  # noqa: E402
from s01_upstream import load_upstream  # noqa: E402


def probe(
    root: Path,
    *,
    content_budget: int = DEFAULT_CONTENT_BUDGET,
    neighbor_budget: int = DEFAULT_NEIGHBOR_BUDGET,
    s01_path: Path | None = None,
    use_s01: bool = True,
) -> dict:
    upstream = load_upstream(root, s01_path=s01_path, use_s01=use_s01)
    revision = upstream.revision
    book = upstream.book

    cards: list[dict] = []
    rejected = 0
    for provenance, record in upstream.iter_records():
        try:
            cards.append(
                build_card(
                    record,
                    revision=revision,
                    provenance=provenance,
                    content_budget=content_budget,
                    neighbor_budget=neighbor_budget,
                )
            )
        except ValueError:
            rejected += 1

    counts = tally(cards, rejected=rejected, provenance_book=book)
    by_plane = counts.pop("_by_plane")
    by_kind = counts.pop("_by_kind")
    violation_reasons = counts.pop("_violation_reasons")

    per_plane_sizes = {
        plane: size_stats([c for c in cards if c["plane"] == plane])
        for plane in sorted(by_plane)
    }

    # The metadata floor: what a card costs before it carries any content or
    # any neighbourhood.  Reported so the size distribution cannot be read as
    # "content is expensive" when part of it is the envelope §6 demands.
    empty_record = {
        "plane": "code",
        "kind": "function",
        "path": "x.py",
        "qualname": "x.f",
        "start_line": 1,
        "end_line": 1,
    }
    envelope_ref = next(iter(book.as_dict()))
    envelope = build_card(empty_record, revision=revision, provenance=envelope_ref)
    # ...and how much of that floor is still the provenance pointer, so the
    # share cannot be quietly re-inflated later without the number moving.
    envelope_without_provenance = card_size_bytes(
        {k: v for k, v in envelope.items() if k != "provenance"}
    )

    counts["envelope_bytes"] = card_size_bytes(envelope)
    counts["envelope_bytes_without_provenance_ref"] = envelope_without_provenance

    return {
        "schema": "forest-v2-node-card-probe/2",
        "read_only": True,
        "revision": revision,
        "upstream": upstream.describe(),
        "budgets": {
            "content_chars": content_budget,
            "neighbor_edges": neighbor_budget,
        },
        "totals": counts,
        "contract_violation_reasons": dict(sorted(violation_reasons.items())),
        # Emitted ONCE per build.  Every card points here by content address.
        "provenance_book": book.as_dict(),
        "counter_liveness": counter_liveness(revision=revision),
        "cards_by_plane": dict(sorted(by_plane.items())),
        "cards_by_kind": dict(sorted(by_kind.items())),
        "size_all_planes": size_stats(cards),
        "size_by_plane": per_plane_sizes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=None)
    parser.add_argument("--content-budget", type=int, default=DEFAULT_CONTENT_BUDGET)
    parser.add_argument("--neighbor-budget", type=int, default=DEFAULT_NEIGHBOR_BUDGET)
    parser.add_argument(
        "--s01-path",
        default=None,
        help="slice s01's package directory; overrides F2_S01_PATH and the search",
    )
    parser.add_argument(
        "--no-s01",
        action="store_true",
        help="force the stand-in upstream and report the named gap",
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    report = probe(
        root,
        content_budget=args.content_budget,
        neighbor_budget=args.neighbor_budget,
        s01_path=Path(args.s01_path) if args.s01_path else None,
        use_s01=not args.no_s01,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
