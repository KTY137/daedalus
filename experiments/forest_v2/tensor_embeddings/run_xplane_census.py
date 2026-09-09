"""EXPERIMENT: the tensor arm census on the frozen s09 cross-plane corpus.

Read-only against the subject repository.  Prints one JSON object.

The tensor arms have previously been evaluated on one diagnostic case, which
``PERFORMANCE_NOTE.md`` labels not scientifically evaluable.  This runs the
same frozen arm census over the committed ``taskset_xplane.json`` -- 88 cases,
anchor ``d849c2a9``, subject the daedalus repository itself.

Protocol is frozen in ``docs/G2_TENSOR_CENSUS_01_PREREGISTRATION_20260909.md``.
Nothing here selects arms, tunes a kernel or touches the census: the arm list
comes from ``benchmark.DEFAULT_RETRIEVERS`` and a tree whose executable arms
differ from the frozen list already refuses to import.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from experiments.forest_v2.s09_eval import gitio  # noqa: E402
from experiments.forest_v2.s09_eval.contract import Candidate, QueryView  # noqa: E402
from experiments.forest_v2.tensor_embeddings.benchmark import (  # noqa: E402
    MAX_CONTENT_BYTES,
    MAX_FILE_BYTES,
    BenchmarkCase,
    run_benchmark,
)

SCHEMA = "forest_v2.tensor.xplane_census/1"


def fit_to_cap(raw: bytes, cap: int = MAX_CONTENT_BYTES) -> bytes:
    """Truncate ``raw`` so the *decoded then re-encoded* text still fits ``cap``.

    Cutting raw bytes at the cap is not enough.  ``Candidate.text`` decodes with
    ``errors="replace"``, so a cut landing mid-sequence turns a 1-3 byte partial
    into a 3-byte ``U+FFFD``; the encoder then re-encodes that text and rejects
    it for exceeding the very cap the caller thought it had respected.  That is
    what blocked the first run of this census: 30 of 88 cases raised
    ``role field content exceeds the frozen 65536-byte cap``.

    Shrinking on the decoded string and re-encoding to check is the only form
    that is correct for every input, so it is done that way rather than by
    subtracting a guess.
    """
    text = raw.decode("utf-8", "replace")
    encoded = text.encode("utf-8")
    while len(encoded) > cap and text:
        overflow = len(encoded) - cap
        # Each dropped character frees at least one byte and at most four.
        text = text[: max(0, len(text) - (overflow // 4 + 1))]
        encoded = text.encode("utf-8")
    return encoded


def build_cases(
    repo: Path, taskset_path: Path, limit: int | None, variant: str
) -> List[BenchmarkCase]:
    record = json.loads(taskset_path.read_text(encoding="utf-8"))
    rows = record["cases"][: limit or len(record["cases"])]
    cases: List[BenchmarkCase] = []
    for row in rows:
        parent = row["parent"]
        try:
            tree = gitio.list_tree(repo, parent)
        except gitio.GitError:
            continue
        eligible = [
            (path, blob, size)
            for path, (blob, size) in sorted(tree.items())
            if 0 < size <= MAX_FILE_BYTES
        ]
        if not eligible:
            continue
        blobs = gitio.read_blobs(repo, [blob for _p, blob, _s in eligible])
        universe = tuple(
            Candidate(
                path=path,
                blob=blob,
                size=size,
                raw=fit_to_cap(blobs[blob]),
                content_budget=MAX_CONTENT_BYTES,
            )
            for path, blob, size in eligible
            if blob in blobs and blobs[blob]
        )
        if not universe:
            continue
        text = row["query_scrubbed"] if variant == "scrubbed" else row["query_raw"]
        if not text.strip():
            continue
        known = {c.path for c in universe}
        gold = tuple(g for g in row["gold"] if g in known)
        if not gold:
            continue
        cases.append(
            BenchmarkCase(
                query=QueryView(
                    case_id=row["case_id"],
                    text=text,
                    variant=variant,
                    revision=parent,
                    repo=str(repo),
                ),
                universe=universe,
                gold=gold,
                # Recency is a caller-asserted input the harness requires; the
                # corpus does not carry one, so tree order is supplied and the
                # recency arm's score must be read as "tree order", not as a
                # recency prior. It is not one of the compared arms.
                recency_ranking=tuple(c.path for c in universe[:20]),
            )
        )
    return cases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tensor arm census on s09 xplane")
    parser.add_argument("repo")
    parser.add_argument("--taskset", default="experiments/forest_v2/s09_eval/taskset_xplane.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--variant", choices=("scrubbed", "raw"), default="scrubbed")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    cases = build_cases(Path(args.repo), Path(args.taskset), args.limit, args.variant)
    built = time.perf_counter() - t0
    if not cases:
        print(json.dumps({"schema": SCHEMA, "error": "no cases built"}))
        return 1
    t1 = time.perf_counter()
    report = run_benchmark(cases)
    elapsed = time.perf_counter() - t1

    out: Dict[str, object] = {
        "schema": SCHEMA,
        "variant": args.variant,
        "cases_built": len(cases),
        "mean_universe": round(
            sum(len(c.universe) for c in cases) / len(cases), 1
        ),
        "seconds_building": round(built, 2),
        "seconds_benchmark": round(elapsed, 2),
        "report": report,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
