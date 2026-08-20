"""Descent prototype (H-DESC): one check assay per cover instead of all
pairwise K-assays.

The cover is a PARTITION of the schema fields. Every operator is assigned
to the cell its declared footprint touches; operators touching several
cells, the shared `layout` resource, wildcards or non-field resources are
DESCENT OBSTRUCTIONS — they are recorded with a reason and excluded from
the descent certificate, never silently dropped.

The gluing check: apply all local operators cell-by-cell (canonical cell
order), and again interleaved round-robin across cells. Tree-equal
endpoints certify ALL cross-cell pairs of local operators as commuting
with ONE measurement pair — the O(n^2) -> O(M) economics of H-DESC.
Within-cell pairs stay pairwise business (they conflict by declaration).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import assay


def _op_cells(op, partition) -> tuple:
    """Return (cells, reason). cells is the set of partition indices the
    declared footprint touches; reason is None for local ops or the
    obstruction explanation."""
    cells = set()
    reasons = []
    for res in sorted(op.reads | op.writes):
        if res == "field:*":
            reasons.append("field:* wildcard is not cell-local")
        elif res == "layout":
            reasons.append("layout is a shared resource across every cell")
        elif res.startswith("field:"):
            name = res[len("field:"):]
            hit = [i for i, cell in enumerate(partition) if name in cell]
            if hit:
                cells.add(hit[0])
            else:
                reasons.append(f"resource {res} not covered by the partition")
        else:
            reasons.append(f"resource {res} outside the field vocabulary")
    if reasons:
        return cells, "; ".join(reasons)
    if len(cells) > 1:
        return cells, f"footprint spans cells {sorted(cells)}"
    return cells, None


def assign_ops(ops: dict, partition) -> tuple:
    """Split ops into local ({name: cell_index}) and obstructions
    ([(name, reason), ...])."""
    local = {}
    obstructions = []
    for name, op in ops.items():
        cells, reason = _op_cells(op, partition)
        if reason is not None:
            obstructions.append((name, reason))
        elif not cells:
            obstructions.append((name, "empty footprint has no cell"))
        else:
            local[name] = cells.pop()
    return local, obstructions


def run_descent(fixture: Path, ops: dict, partition, out_dir: Path) -> dict:
    fixture = Path(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        raise FileExistsError(f"receipts already exist at {receipts_path}")
    chain = assay.ReceiptChain(receipts_path)
    chain.append(assay.provenance_record(fixture))
    work = out_dir / "work"

    local, obstructions = assign_ops(ops, partition)
    by_cell = {}
    for name, cell in local.items():
        by_cell.setdefault(cell, []).append(name)
    cell_order = sorted(by_cell)

    baseline = assay.run_word(fixture, [], work / "baseline", chain)
    runs_used = 1

    cell_results = {}
    for cell in cell_order:
        names = by_cell[cell]
        word = [ops[n] for n in names]
        res = assay.run_word(fixture, word, work / f"cell_{cell}", chain)
        runs_used += 1
        cell_results[str(cell)] = {
            "ops": names,
            "composable": res["composable"],
            "fail_reason": res["fail_reason"],
        }

    # gluing assay: cell-by-cell vs round-robin interleaving
    sequential = [ops[n] for cell in cell_order for n in by_cell[cell]]
    interleaved = []
    queues = {cell: list(by_cell[cell]) for cell in cell_order}
    while any(queues.values()):
        for cell in cell_order:
            if queues[cell]:
                interleaved.append(ops[queues[cell].pop(0)])
    glue_a = assay.run_word(fixture, sequential, work / "glue_sequential", chain)
    glue_b = assay.run_word(fixture, interleaved, work / "glue_interleaved", chain)
    runs_used += 2
    glue = {
        "sequential_word": glue_a["word"],
        "interleaved_word": glue_b["word"],
        "both_composable": bool(glue_a["composable"] and glue_b["composable"]),
        "tree_equal": bool(
            glue_a["composable"] and glue_b["composable"]
            and glue_a["tree_sha"] == glue_b["tree_sha"]),
    }

    cross_cell_pairs = 0
    cells = [by_cell[c] for c in cell_order]
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            cross_cell_pairs += len(cells[i]) * len(cells[j])

    analysis = {
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "fixture": fixture.name,
        "record": "descent",
        "partition": [list(cell) for cell in partition],
        "local_ops": {name: cell for name, cell in sorted(local.items())},
        "obstructions": sorted(obstructions),
        "cells": cell_results,
        "glue": glue,
        "descent_holds": glue["tree_equal"],
        "balance": {
            "descent_runs_used": runs_used,
            "cross_cell_pairs": cross_cell_pairs,
            # the pairwise matrix runs each unordered pair in both orders
            "pairwise_runs_replaced": 2 * cross_cell_pairs,
        },
    }
    analysis_sha = hashlib.sha256(assay._canonical(analysis).encode()).hexdigest()
    chain.append({
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "record": "analysis",
        "analysis_sha": analysis_sha,
    })
    analysis["receipt_head"] = chain.prev
    analysis["receipt_count"] = chain.seq
    with open(out_dir / "descent.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    return analysis
