"""EXPERIMENT s06: Node Cards — the §6 card contract, built and measured.

Read-only, pure stdlib, no repository imports, no writes, no network, no
subprocess.  This module is the *contract half* of the slice: it turns node
records (the shape slice s01 is expected to emit) into Node Cards that carry
exactly the seven fields the master plan §6 demands:

    stable node identity, revision, plane, source locator, compact content,
    local neighborhood, provenance.

Two identities, deliberately separated
--------------------------------------
``node_id``  is the *stable* identity: plane, path, kind, qualname (plus an
             ordinal when one file declares the same qualname twice).  It
             survives a line shift, a reformat, or a docstring edit.
``card_id``  is the *content address of the card at one revision*: a sha256
             over the whole card except ``card_id`` itself.  It changes
             whenever the locator, the content, the neighborhood, or the
             provenance changes.

That split is the point of the slice.  §6 wants embeddings to consume cards
whose identity is stable enough to compare across revisions, while §5's
revision-atomicity wants a card that cannot silently claim to describe a
revision it was not built from.  One field cannot do both jobs; two can.

Provenance is carried BY REFERENCE
---------------------------------
``card["provenance"]`` is a ``sha256:`` content address, not a block.  The
build emits each distinct block once in a ``ProvenanceBook``.  Inlining the
block instead cost 281 canonical bytes in *every* card — for one corpus of
8,466 cards that was 2.3 MB of a single repeated literal, and it inflated the
"what does §6 charge before the first useful character" number by a third.
A reference that does not resolve is a contract violation, so the compression
does not buy itself with a dangling pointer.

Nothing here promotes anything.  A card is a *proposal carrier* — it never
becomes evidence, and it never receives a schema-free graph: plane, revision,
identity and provenance are mandatory and validated.

Input contract ``forest-v2-node-record/1``
------------------------------------------
A node record is a plain dict:

    required: plane, kind, path, qualname, start_line, end_line
    optional: ordinal (int, default 0), signature (str), doc (str),
              text (str, the full source slice), neighbors (list), extra (dict)

A neighbor is ``{"relation": str, "direction": "in"|"out", "node_id": str,
"kind": str, "name": str}``.  Records are producer-agnostic on purpose: s01's
extractor, the stand-in extractor in ``standin_source.py``, or a later Gate-2
Forest walker all satisfy the same shape.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable, Sequence

#: Bumped from /1 when provenance became a ref and content gained its budget.
#: A /1 consumer reading a /2 card would find a string where it expected a
#: dict, so this is a breaking change and says so.
CARD_SCHEMA = "forest-v2-node-card/2"
RECORD_SCHEMA = "forest-v2-node-record/1"

#: Planes the card contract accepts (master plan §5).  There is no fifth one.
PLANES = ("code", "type", "data", "knowledge")

REQUIRED_RECORD_FIELDS = ("plane", "kind", "path", "qualname", "start_line", "end_line")
REQUIRED_CARD_FIELDS = (
    "schema",
    "card_id",
    "node_id",
    "revision",
    "plane",
    "locator",
    "content",
    "neighborhood",
    "provenance",
)

#: Compact content budget, in characters of source text.  §6 says "compact
#: content", not "the file".  The budget is a parameter so the later
#: experiment can sweep it instead of inheriting a magic number.
DEFAULT_CONTENT_BUDGET = 800
#: Local neighborhood budget, in edges.  "Local" is a bound, not a vibe.
DEFAULT_NEIGHBOR_BUDGET = 8
DEFAULT_DOC_BUDGET = 200


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic serialisation used for every hash in this slice."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_of(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def provenance_ref(block: dict) -> str:
    """Content address of a provenance block.

    The card carries **this string**, never the block.  A build emits every
    distinct block once, in a ``ProvenanceBook``; 8,466 cards that share one
    origin then pay for that origin once instead of 8,466 times.

    This is the same discipline invariant 2 already demands of sources and
    candidate trees — the authoritative thing is content-addressed, and the
    thing that points at it carries the address, not a copy.
    """
    return sha256_of(block)


class ProvenanceBook:
    """``ref -> block``, emitted once per build.

    A card's provenance is only "by reference" in an honest sense if the
    reference **resolves**.  A dangling ref is strictly worse than the inlined
    literal it replaced: it looks like provenance and carries none.  So the
    book is not a convenience, it is the other half of the contract, and
    ``validate_card`` fails a card whose ref this book cannot answer.
    """

    def __init__(self, blocks: dict | None = None) -> None:
        self._blocks: dict[str, dict] = dict(blocks or {})

    def add(self, block: dict) -> str:
        """Register a block, return the ref a card should carry."""
        if not block:
            raise ValueError("refusing to register an empty provenance block")
        ref = provenance_ref(block)
        self._blocks[ref] = dict(block)
        return ref

    def get(self, ref: str) -> dict | None:
        return self._blocks.get(ref)

    def resolve(self, card: dict) -> dict | None:
        """The block a card points at, or None when the ref dangles."""
        return self._blocks.get(card.get("provenance", ""))

    def as_dict(self) -> dict:
        return {ref: dict(block) for ref, block in sorted(self._blocks.items())}

    def __len__(self) -> int:
        return len(self._blocks)

    def __contains__(self, ref: object) -> bool:
        return ref in self._blocks


def node_id(record: dict) -> str:
    """Stable identity.  Line numbers are deliberately NOT part of it."""
    plane = record["plane"]
    path = str(record["path"]).replace("\\", "/")
    ident = f"{plane}://{path}#{record['kind']}:{record['qualname']}"
    ordinal = int(record.get("ordinal", 0) or 0)
    return f"{ident}~{ordinal}" if ordinal else ident


def _compact_text(text: str, budget: int) -> dict:
    """Compact content plus the honesty fields: full-text digest and length."""
    full = text or ""
    body = full[:budget]
    return {
        "text": body,
        "text_sha256": sha256_text(full),
        "text_chars": len(full),
        "truncated": len(full) > budget,
        # The budget travels WITH the content, exactly as it already did with
        # the neighborhood.  Without it "the budget was respected" is a claim
        # about a number the card does not carry, so nothing can check it.
        "budget": budget,
    }


def _first_paragraph(doc: str, budget: int) -> str:
    head = (doc or "").strip().split("\n\n", 1)[0].strip()
    head = " ".join(head.split())
    return head[:budget]


def _normalise_neighbors(
    neighbors: Iterable[dict], budget: int
) -> tuple[list[dict], int, bool]:
    seen: dict[tuple, dict] = {}
    for raw in neighbors or ():
        entry = {
            "relation": str(raw.get("relation", "")),
            "direction": str(raw.get("direction", "out")),
            "node_id": str(raw.get("node_id", "")),
            "kind": str(raw.get("kind", "")),
            "name": str(raw.get("name", "")),
        }
        seen[(entry["relation"], entry["direction"], entry["node_id"])] = entry
    ordered = sorted(
        seen.values(), key=lambda e: (e["relation"], e["direction"], e["node_id"])
    )
    total = len(ordered)
    return ordered[:budget], total, total > budget


def validate_record(record: dict) -> list[str]:
    problems: list[str] = []
    for field in REQUIRED_RECORD_FIELDS:
        if field not in record or record[field] in (None, ""):
            problems.append(f"record missing field: {field}")
    plane = record.get("plane")
    if plane is not None and plane not in PLANES:
        problems.append(f"record plane not in {PLANES}: {plane!r}")
    start, end = record.get("start_line"), record.get("end_line")
    if isinstance(start, int) and isinstance(end, int) and end < start:
        problems.append(f"record end_line {end} before start_line {start}")
    return problems


def build_card(
    record: dict,
    *,
    revision: str,
    provenance: dict | str,
    content_budget: int = DEFAULT_CONTENT_BUDGET,
    neighbor_budget: int = DEFAULT_NEIGHBOR_BUDGET,
    doc_budget: int = DEFAULT_DOC_BUDGET,
) -> dict:
    """Build one Node Card.  Raises ValueError on a record that breaks contract.

    The card is deterministic: the same record, revision and provenance always
    produce the same ``card_id``.  No wall-clock timestamp is hashed into a
    card — a card that changed identity every run could not be compared across
    revisions, which is the only reason it exists.

    ``provenance`` is either the block (registered here, its ref stored) or an
    already-computed ref string.  Either way the card stores **the ref**.
    """
    problems = validate_record(record)
    if problems:
        raise ValueError("; ".join(problems))
    if isinstance(provenance, str):
        ref = provenance
    elif provenance:
        ref = provenance_ref(provenance)
    else:
        raise ValueError("card requires a provenance block or ref")

    neighborhood, neighbor_total, neighbor_truncated = _normalise_neighbors(
        record.get("neighbors", ()), neighbor_budget
    )
    content = _compact_text(record.get("text", ""), content_budget)
    content.update(
        {
            "kind": record["kind"],
            "name": str(record["qualname"]).rsplit(".", 1)[-1],
            "qualname": record["qualname"],
            "signature": record.get("signature", ""),
            "doc": _first_paragraph(record.get("doc", ""), doc_budget),
        }
    )

    card = {
        "schema": CARD_SCHEMA,
        "node_id": node_id(record),
        "revision": revision,
        "plane": record["plane"],
        "locator": {
            "path": str(record["path"]).replace("\\", "/"),
            "start_line": int(record["start_line"]),
            "end_line": int(record["end_line"]),
            "source_sha256": record.get("source_sha256", ""),
        },
        "content": content,
        "neighborhood": {
            "edges": neighborhood,
            "edge_total": neighbor_total,
            "truncated": neighbor_truncated,
            "budget": neighbor_budget,
        },
        "provenance": ref,
    }
    card["card_id"] = sha256_of(card)
    return card


def validate_card(card: dict, provenance_book: "ProvenanceBook | None" = None) -> list[str]:
    """Contract check.  Returns the list of violations; empty means valid.

    ``provenance_book`` is optional only because a caller may hold cards
    without the build that made them.  When it IS supplied the provenance ref
    must resolve inside it and the resolved block must content-address back to
    that ref — otherwise "provenance by reference" degrades into a pointer
    into nothing, which is worse than the literal it replaced.
    """
    problems: list[str] = []
    for field in REQUIRED_CARD_FIELDS:
        if field not in card:
            problems.append(f"card missing field: {field}")
    if problems:
        return problems
    if card["schema"] != CARD_SCHEMA:
        problems.append(f"unexpected schema: {card['schema']!r}")
    if card["plane"] not in PLANES:
        problems.append(f"plane not in {PLANES}: {card['plane']!r}")
    if not card["revision"]:
        problems.append("empty revision (a card must be revision-bound)")
    if not card["node_id"]:
        problems.append("empty node_id")

    # ---- provenance is a resolvable content address, not a blob ----------
    ref = card["provenance"]
    if not ref:
        problems.append("empty provenance")
    elif not isinstance(ref, str):
        problems.append(f"provenance must be a ref string, got {type(ref).__name__}")
    elif not _REF_RE.match(ref):
        problems.append(f"provenance is not a sha256 ref: {ref!r}")
    elif provenance_book is not None:
        block = provenance_book.get(ref)
        if block is None:
            problems.append(f"provenance ref does not resolve in this build: {ref}")
        elif provenance_ref(block) != ref:
            problems.append("provenance block does not content-address to its ref")

    locator = card.get("locator") or {}
    for field in ("path", "start_line", "end_line"):
        if field not in locator:
            problems.append(f"locator missing field: {field}")

    # ---- budgets are bounds, so overrunning one is a violation ----------
    content = card.get("content") or {}
    budget = content.get("budget")
    if not isinstance(budget, int):
        problems.append("content missing an integer budget")
    else:
        if len(content.get("text", "")) > budget:
            problems.append(
                f"content over budget: {len(content.get('text', ''))} > {budget}"
            )
        if bool(content.get("truncated")) != (int(content.get("text_chars", 0)) > budget):
            problems.append("content truncated flag disagrees with text_chars/budget")

    hood = card.get("neighborhood") or {}
    hood_budget = hood.get("budget")
    if not isinstance(hood_budget, int):
        problems.append("neighborhood missing an integer budget")
    else:
        if len(hood.get("edges", ())) > hood_budget:
            problems.append(
                f"neighborhood over budget: {len(hood.get('edges', ()))} > {hood_budget}"
            )
        if bool(hood.get("truncated")) != (int(hood.get("edge_total", 0)) > hood_budget):
            problems.append("neighborhood truncated flag disagrees with edge_total/budget")

    body = {k: v for k, v in card.items() if k != "card_id"}
    if card["card_id"] != sha256_of(body):
        problems.append("card_id does not address the card body")
    return problems


def card_size_bytes(card: dict) -> int:
    """RAW measured size: the canonical serialisation an embedder would ship."""
    return len(canonical_bytes(card))


def _percentile(values: Sequence[int], pct: float) -> int:
    """Nearest-rank percentile on an already sorted sequence."""
    if not values:
        return 0
    rank = max(1, min(len(values), int(round(pct / 100.0 * len(values) + 0.5))))
    return values[rank - 1]


def size_stats(cards: Sequence[dict]) -> dict:
    """RAW size distribution over canonical card bytes.  No smoothing."""
    sizes = sorted(card_size_bytes(c) for c in cards)
    if not sizes:
        return {"cards": 0}
    buckets = {"<=256": 0, "257-512": 0, "513-1024": 0, "1025-2048": 0, ">2048": 0}
    for size in sizes:
        if size <= 256:
            buckets["<=256"] += 1
        elif size <= 512:
            buckets["257-512"] += 1
        elif size <= 1024:
            buckets["513-1024"] += 1
        elif size <= 2048:
            buckets["1025-2048"] += 1
        else:
            buckets[">2048"] += 1
    total = sum(sizes)
    return {
        "cards": len(sizes),
        "bytes_total": total,
        "bytes_min": sizes[0],
        "bytes_p50": _percentile(sizes, 50),
        "bytes_p90": _percentile(sizes, 90),
        "bytes_p99": _percentile(sizes, 99),
        "bytes_max": sizes[-1],
        "bytes_mean": round(total / len(sizes), 1),
        "histogram_bytes": buckets,
    }


def tally(
    cards: Sequence[dict],
    *,
    rejected: int = 0,
    provenance_book: "ProvenanceBook | None" = None,
) -> dict:
    """The counting code path — used by the corpus run AND by the negative fixtures.

    This function exists so that ``records_rejected`` and ``contract_violations``
    are not merely *asserted* to be countable.  The negative fixtures feed
    broken input through **this** function, not through a parallel checker
    written to agree with it.  A counter that only ever sees clean input is a
    structural zero, not a measurement; a counter that has been shown to move
    here has been measured, and its zero over the real corpus then means
    something.
    """
    violations_by_card = [validate_card(card, provenance_book) for card in cards]
    violations = sum(1 for problems in violations_by_card if problems)
    violation_reasons = Counter(
        problem for problems in violations_by_card for problem in problems
    )

    # ``.get`` throughout: a negative fixture deliberately hands this function
    # cards with fields removed, and the counter must survive to count them.
    by_plane = Counter(card.get("plane", "?") for card in cards)
    by_kind = Counter(
        f"{card.get('plane', '?')}:{(card.get('content') or {}).get('kind', '?')}"
        for card in cards
    )
    node_ids = Counter(card.get("node_id", "") for card in cards)
    duplicate_node_ids = sum(count - 1 for count in node_ids.values() if count > 1)

    content_truncated = sum(
        1 for card in cards if (card.get("content") or {}).get("truncated")
    )
    hoods = [card.get("neighborhood") or {} for card in cards]
    neighbors_truncated = sum(1 for hood in hoods if hood.get("truncated"))
    edge_total = sum(int(hood.get("edge_total", 0)) for hood in hoods)
    edges_kept = sum(len(hood.get("edges", ())) for hood in hoods)
    isolated = sum(1 for hood in hoods if int(hood.get("edge_total", 0)) == 0)

    over_content = sum(
        1
        for card in cards
        if isinstance((card.get("content") or {}).get("budget"), int)
        and len((card.get("content") or {}).get("text", ""))
        > (card.get("content") or {})["budget"]
    )
    over_neighborhood = sum(
        1
        for hood in hoods
        if isinstance(hood.get("budget"), int)
        and len(hood.get("edges", ())) > hood["budget"]
    )
    dangling = 0
    if provenance_book is not None:
        dangling = sum(
            1 for card in cards if provenance_book.resolve(card) is None
        )

    return {
        "cards": len(cards),
        "records_rejected": rejected,
        "contract_violations": violations,
        "distinct_node_ids": len(node_ids),
        "duplicate_node_ids": duplicate_node_ids,
        "content_truncated": content_truncated,
        "content_over_budget": over_content,
        "neighborhood_truncated": neighbors_truncated,
        "neighborhood_over_budget": over_neighborhood,
        "neighborhood_edges_total": edge_total,
        "neighborhood_edges_kept": edges_kept,
        "cards_without_edges": isolated,
        "provenance_refs_dangling": dangling,
        "_by_plane": by_plane,
        "_by_kind": by_kind,
        "_violation_reasons": violation_reasons,
    }


def to_jsonl(cards: Iterable[dict]) -> str:
    """One card per line, canonical bytes — the interchange form for s06."""
    return "\n".join(canonical_bytes(card).decode("utf-8") for card in cards)
