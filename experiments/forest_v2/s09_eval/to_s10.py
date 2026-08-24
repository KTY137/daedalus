"""Adapter: turn a completed s09 harness run into an s10 kill-input.

The gap this closes, in the forest_v2 README's own words (s10's "Honest
caveats"): *"The input contract is s10's, not s09's... the adapter that
emits this schema from an s09 run does not exist yet."* This module is that
adapter.

**Direction, and why it is one-way.** ``s10_kill/schema.py`` documents the
target contract as deliberately data-only: *"No import edge exists in
either direction [between the s09 harness and the s10 evaluator], so
neither side can quietly reach into the other's internals."*
``s10_kill/__init__.py`` states the same thing as a design constraint on
that package, and ``s10_kill/test_s10_boundary.py`` enforces it mechanically
(every file under ``s10_kill/``, tests included, must import only the
standard library -- a static AST check, not a docstring promise). That
settles which side this adapter lives on: it cannot live in ``s10_kill/``
without breaking that check the moment it imports anything from
``s09_eval``. It lives here instead, and this module's own production code
keeps the same discipline in the direction it *can* choose: it does not
import ``experiments.forest_v2.s10_kill``. The schema id and the two role
strings this module emits are hand-tracked constants below, not an import
of ``s10_kill.schema.SCHEMA_ID`` / ``KNOWN_ROLES`` -- so the harness side
of the boundary stays exactly as decoupled as it was before this file
existed. ``test_to_s10.py`` breaks that rule on purpose, in one disclosed
place, to validate the emitted JSON against the real evaluator contract
instead of trusting a hand-copied schema never to drift -- see that file's
docstring. This mirrors the disclosed, one-place coupling s06 already
carries to s01 (README, slice s06, "Honest caveats").

**What this adapter refuses to do.** It does not fabricate a ``full`` or
``fusion`` arm. No cross-plane fusion retriever exists anywhere in this
program (s07, s08, s09 all ship none -- ``s10_kill/measured_inputs.py``
records the same fact about s08, independently). It does not force an
honest baseline into a role that misdescribes its mechanism: of the five
baselines ``s09_eval/retrievers.py`` ships, only two have an s10 role that
actually names what they measure (``bm25``: a lexical baseline;
``random_uniform``: a random selection control). The other three
(``recency_prior``, ``path_lexical``, ``bm25_content_only``) are left out,
by name, with the reason -- see ``EXCLUDED_ARMS`` below. Declaring them
under a role that fits the schema but not the mechanism would repeat
exactly the substituted-comparator defect the README spends pages warning
about (``test_no_arm_of_a_measured_run_is_labelled_fusion`` and the
joint-BM25-index-labelled-fusion near-miss in slice s10).

**Where the scores come from.** Every value in the emitted document is read
from ``raw['per_case']`` -- the harness's own ``metrics.score_case`` output,
produced by an actual ``retriever.rank(query, universe)`` call under the
harness's budget-equality rules (``contract.py``). This module never
computes a score from the gold set directly and never invents a case,
retriever or plane label that is not already present in its input.

**No single corpus census.** ``s10_kill.schema.Corpus`` models one static
index (s08 built exactly one). s09's harness does not: every case is scored
against its *own* pre-image tree (``harness.build_universe``), so there is
no single "the corpus" to report a documents-per-plane count for without
inventing an aggregate the harness never computed. ``corpus`` is left
``None`` in every document this module emits, for that reason, not by
oversight.

**This module writes files.** ``main`` (and its helper ``load_and_write``)
write the adapted JSON to disk, unless ``--no-write`` is passed -- the same
undeclared-entrypoint situation slice s09's own ``harness.py`` and
``taskset.py`` are already in (see the README's Boundary note). Writes are
confined to ``experiments/forest_v2/s09_eval/results/``; nothing here opens
a network connection, spends anything, or calls a model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from s09_eval import gitio, taskset, taskset_xplane
else:
    from . import gitio, taskset, taskset_xplane

RESULTS_DIR = Path(__file__).resolve().parent / "results"

#: Tracks ``s10_kill.schema.SCHEMA_ID`` by value, deliberately not by import
#: -- see the module docstring for why. ``test_to_s10.py`` is what notices
#: if the two ever drift apart.
SCHEMA_ID = "forest_v2.s10.kill-input/1"

#: The metric every arm is scored on. Continuous in [0, 1], zero for a case
#: with no hit inside the harness's largest cutoff (``metrics.score_case``)
#: -- the same value the harness's own MRR line and paired comparisons are
#: built from, so this adapter introduces no second definition of "score".
PRIMARY_METRIC = "reciprocal_rank"

IMPLEMENTATION = "experiments/forest_v2/s09_eval/retrievers.py"

#: retriever name (as ``raw['retrievers']`` names it) -> (s10 role, s10
#: retriever.mechanism). Only these two of s09's five baselines have an s10
#: role that actually names their mechanism; see the module docstring.
INCLUDED_ARMS: Dict[str, Tuple[str, str]] = {
    "bm25": ("bm25", "lexical"),
    "random_uniform": ("random_priority", "random"),
}

#: The other three s09 baselines, and why each is left out rather than
#: force-fit into a role the schema would accept but that would misdescribe
#: the mechanism.
EXCLUDED_ARMS: Dict[str, str] = {
    "recency_prior": (
        "s09's own README calls this the strongest baseline measured in the "
        "program ('leads every column'), and it is query-blind by design -- "
        "but s10's role vocabulary (full/fusion/code_only/bm25/rewired/"
        "separate_indices/graph_priority/random_priority/evaluator_only/"
        "token_matched) has no slot for a query-blind churn prior. Forcing it "
        "into any of those roles would misdescribe the mechanism, so it is "
        "left out and named here instead of silently dropped."
    ),
    "path_lexical": (
        "scores path-token overlap with the query only; not restricted to one "
        "Project-Twin plane and not a fusion mechanism, so it has no honest "
        "s10 role either."
    ),
    "bm25_content_only": (
        "the same BM25 index as 'bm25' with path tokens stripped from the "
        "document -- a second real, measured arm, but s10 has no role for "
        "'this role's own document-composition ablation', and giving it the "
        "same role as 'bm25' at the same variant would collide in "
        "ResultSet.find() (which treats >1 arm per (role, variant) as an "
        "error, not a coin flip)."
    ),
}

#: Every s09 baseline ranks over the SAME unrestricted, multi-suffix
#: candidate universe (contract.Budget.text_suffixes), never one Project-Twin
#: plane alone, so "which planes can this arm ever return" is a fixed,
#: honest fact for all five of them: whichever planes taskset.plane_of() maps
#: an eligible suffix to. That set is {code, data, knowledge} -- not "type":
#: no retriever anywhere in this program (s07, s08, s09) has ever returned a
#: type-plane document, because the Type plane has no file-level node in
#: Forest v2 as built so far (s02, s08 and s09-continuation-2 record the same
#: gap independently). Declaring "type" here would be an undischarged claim.
RETURNS_PLANES: Tuple[str, ...] = ("code", "data", "knowledge")

#: Restated, not imported, for the same reason as SCHEMA_ID above.
NO_FUSION_ARM_ANYWHERE = (
    "no cross-plane fusion retriever exists anywhere in this program: s07 "
    "ships a lexical index only, s08 ships LexicalRetriever / "
    "CodeGraphRetriever / FourPlaneNoFusionRetriever / UnionNoFusionRetriever "
    "/ SinglePlaneOracleRetriever (none of them combines per-plane scores), "
    "s09 ships random_uniform / path_lexical / bm25 / bm25_content_only / "
    "recency_prior. s10_kill/measured_inputs.py records the identical fact "
    "about s08 independently; this is not a new finding, it is the same one "
    "confirmed a third time."
)


class AdapterError(ValueError):
    """The input could not be honestly adapted -- never silently guessed."""


def _case_order(raw: Mapping[str, object]) -> List[str]:
    """Case ids in first-seen order from ``per_case`` -- stable, not sorted."""
    seen: List[str] = []
    known = set()
    for row in raw.get("per_case", []):
        cid = row["case_id"]
        if cid not in known:
            known.add(cid)
            seen.append(cid)
    return seen


def _arm_scores(raw: Mapping[str, object], retriever: str, variant: str) -> Dict[str, float]:
    """Per-case ``PRIMARY_METRIC`` values, read straight from the harness's own output.

    Never computed from the gold set: every value here already passed
    through ``metrics.score_case`` inside an actual harness run.
    """
    out: Dict[str, float] = {}
    for row in raw.get("per_case", []):
        if row["retriever"] != retriever or row["variant"] != variant:
            continue
        out[row["case_id"]] = float(row[PRIMARY_METRIC])
    return out


def build_arm(
    raw: Mapping[str, object], retriever: str, variant: str, role: str, mechanism: str
) -> Dict[str, object]:
    scores = _arm_scores(raw, retriever, variant)
    if not scores:
        raise AdapterError(
            f"{retriever!r} has no per_case rows for variant {variant!r} in this run"
        )
    return {
        "arm_id": f"{retriever}/{variant}",
        "role": role,
        "variant": variant,
        "notes": (
            f"s09_eval baseline {retriever!r}, real harness output (not a rebuild "
            f"from aggregates); {PRIMARY_METRIC} per case under the harness's "
            f"budget-equality rules, identical candidate universe and content cap "
            f"as every other arm in the same run"
        ),
        "returns_planes": list(RETURNS_PLANES),
        "returned_plane_counts": None,  # not measured: the harness records
        # hit counts and reciprocal rank per case, not the returned path
        # list itself, so which plane each returned document belonged to
        # was never captured. Declared absent rather than guessed.
        "retriever": {
            "implementation": f"{IMPLEMENTATION}::{retriever}",
            "mechanism": mechanism,
            "combines_planes": [],
        },
        "scores": {PRIMARY_METRIC: scores},
    }


def gold_planes_for_cases(gold_by_case: Mapping[str, Sequence[str]]) -> Dict[str, str]:
    """One Project-Twin plane per case, only where the gold set names exactly one.

    s10's schema carries a single plane label per case
    (``schema.py: gold_planes: Mapping[str, str]``). A case whose gold set
    spans more than one Twin plane -- the exact thing the cross-plane corpus
    (``taskset_xplane.py``) exists to supply -- cannot be represented by that
    field without collapsing it to a wrong single label, so such a case is
    left undeclared here rather than guessed. ``plane_range.py``'s crosstab
    then reports it as "no declared gold plane", which is the honest state,
    not a defect of this adapter. This is a real, reportable friction
    between s09's richer per-case plane composition and s10's per-case
    single-label schema -- not smoothed over here.
    """
    out: Dict[str, str] = {}
    for case_id, gold in gold_by_case.items():
        planes = taskset_xplane.twin_planes(gold)
        if len(planes) == 1:
            out[case_id] = planes[0]
    return out


def build_kill_input(
    raw: Mapping[str, object],
    *,
    run_id: str,
    source: str,
    gold_planes: Optional[Mapping[str, str]] = None,
    seeds: int = 1,
) -> Dict[str, object]:
    """The whole ``forest_v2.s10.kill-input/1`` document for one s09 run.

    Only arms named in ``INCLUDED_ARMS`` are emitted, and only for
    (retriever, variant) pairs actually present in ``raw``. A run missing
    every included retriever raises rather than emitting an arms-less
    document ``schema.py`` would refuse anyway (``arms`` must be non-empty).
    """
    if raw.get("schema") != "forest_v2.s09.results/1":
        raise AdapterError(
            f"expected an s09 results document (schema 'forest_v2.s09.results/1'), "
            f"got {raw.get('schema')!r}"
        )
    cases = _case_order(raw)
    if not cases:
        raise AdapterError("raw run carries no per_case rows -- nothing to adapt")

    have_retrievers = set(raw.get("retrievers", []))
    have_variants = sorted({row["variant"] for row in raw.get("per_case", [])})

    arms: List[Dict[str, object]] = []
    for retriever, (role, mechanism) in sorted(INCLUDED_ARMS.items()):
        if retriever not in have_retrievers:
            continue
        for variant in have_variants:
            arms.append(build_arm(raw, retriever, variant, role, mechanism))

    if not arms:
        raise AdapterError(
            f"none of the arms this adapter knows how to label honestly "
            f"({sorted(INCLUDED_ARMS)}) are present in this run's retrievers "
            f"({sorted(have_retrievers)})"
        )

    declared_gold_planes = dict(gold_planes or {})
    return {
        "schema": SCHEMA_ID,
        "run_id": run_id,
        "source": source,
        "seeds": seeds,
        "primary_metric": PRIMARY_METRIC,
        "cases": cases,
        "case_groups": {},
        "gold_planes": declared_gold_planes,
        "corpus": None,
        "arms": arms,
    }


# --------------------------------------------------------------------- CLI


def _load_gold_planes(kind: str, path: Optional[Path]) -> Dict[str, str]:
    if kind == "none":
        return {}
    if kind == "taskset":
        _, cases = taskset.load(path or taskset.DEFAULT_PATH)
    elif kind == "taskset_xplane":
        _, cases = taskset_xplane.load(path or taskset_xplane.DEFAULT_PATH)
    else:  # pragma: no cover - argparse already restricts choices
        raise AdapterError(f"unknown --gold-planes-from {kind!r}")
    gold_by_case = {c.case_id: c.gold for c in cases}
    return gold_planes_for_cases(gold_by_case)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--raw", required=True,
        help="an s09 harness results JSON (schema forest_v2.s09.results/1)",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--gold-planes-from", choices=("taskset", "taskset_xplane", "none"), default="none",
        help="derive gold_planes from a frozen task set's own gold answer key "
             "(never from the harness output, which does not carry it)",
    )
    parser.add_argument("--taskset", default=None, help="path override for --gold-planes-from")
    parser.add_argument("--source", default="", help="override the auto-generated source note")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    gold_planes = _load_gold_planes(
        args.gold_planes_from, Path(args.taskset) if args.taskset else None
    )

    try:
        head = gitio.rev_parse(Path(args.repo), "HEAD")
    except gitio.GitError:  # pragma: no cover - defensive
        head = "unknown"

    excluded_note = "; ".join(f"{name}: {reason}" for name, reason in EXCLUDED_ARMS.items())
    source = args.source or (
        f"real s09_eval harness run, input {args.raw}, adapted at repo HEAD {head} "
        f"by experiments/forest_v2/s09_eval/to_s10.py; excluded arms and why -- "
        f"{excluded_note}; {NO_FUSION_ARM_ANYWHERE}"
    )

    doc = build_kill_input(raw, run_id=args.run_id, source=source, gold_planes=gold_planes)

    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.no_write:
        print(text)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
