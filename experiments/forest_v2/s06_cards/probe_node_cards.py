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
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from node_cards import (  # noqa: E402
    DEFAULT_CONTENT_BUDGET,
    DEFAULT_NEIGHBOR_BUDGET,
    build_card,
    card_size_bytes,
    size_stats,
    validate_card,
)
from standin_source import iter_records, resolve_revision  # noqa: E402


def probe(
    root: Path,
    *,
    content_budget: int = DEFAULT_CONTENT_BUDGET,
    neighbor_budget: int = DEFAULT_NEIGHBOR_BUDGET,
) -> dict:
    revision = resolve_revision(root)
    provenance = {
        "source": "standin_ast_extractor",
        "extractor": "experiments.forest_v2.s06_cards.standin_source",
        "extractor_version": "1",
        "input_contract": "forest-v2-node-record/1",
        "upstream": "s01 (not available at build time; see s01_adapter.py)",
        "read_only": True,
        "promotes": "nothing",
    }

    cards: list[dict] = []
    rejected = 0
    for record in iter_records(root):
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

    violations = sum(1 for card in cards if validate_card(card))
    by_plane = Counter(card["plane"] for card in cards)
    by_kind = Counter(f"{card['plane']}:{card['content']['kind']}" for card in cards)
    node_ids = Counter(card["node_id"] for card in cards)
    duplicate_node_ids = sum(count - 1 for count in node_ids.values() if count > 1)

    content_truncated = sum(1 for card in cards if card["content"]["truncated"])
    neighbors_truncated = sum(1 for card in cards if card["neighborhood"]["truncated"])
    edge_total = sum(card["neighborhood"]["edge_total"] for card in cards)
    edges_kept = sum(len(card["neighborhood"]["edges"]) for card in cards)
    isolated = sum(1 for card in cards if card["neighborhood"]["edge_total"] == 0)

    per_plane_sizes = {
        plane: size_stats([c for c in cards if c["plane"] == plane])
        for plane in sorted(by_plane)
    }

    # The metadata floor: what a card costs before it carries any content or
    # any neighbourhood.  Reported so the size distribution cannot be read as
    # "content is expensive" when part of it is the envelope §6 demands.
    envelope = build_card(
        {
            "plane": "code",
            "kind": "function",
            "path": "x.py",
            "qualname": "x.f",
            "start_line": 1,
            "end_line": 1,
        },
        revision=revision,
        provenance=provenance,
    )

    return {
        "schema": "forest-v2-node-card-probe/1",
        "read_only": True,
        "revision": revision,
        "budgets": {
            "content_chars": content_budget,
            "neighbor_edges": neighbor_budget,
        },
        "totals": {
            "cards": len(cards),
            "records_rejected": rejected,
            "contract_violations": violations,
            "distinct_node_ids": len(node_ids),
            "duplicate_node_ids": duplicate_node_ids,
            "content_truncated": content_truncated,
            "neighborhood_truncated": neighbors_truncated,
            "neighborhood_edges_total": edge_total,
            "neighborhood_edges_kept": edges_kept,
            "cards_without_edges": isolated,
            "envelope_bytes": card_size_bytes(envelope),
        },
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
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    report = probe(
        root,
        content_budget=args.content_budget,
        neighbor_budget=args.neighbor_budget,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
