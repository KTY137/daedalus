"""Arm O: evidence-first ceiling for shared latent/Tensor retrieval.

This experiment intentionally does *not* build an embedding index or tensor
backend.  It answers the cheaper prerequisite question from
``docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md``: how many measured
failures contain repository evidence that the deterministic Fourfold brief
cannot express?

Only independently classified ``measured`` rows contribute to a result.  A
prediction is retained as provenance but never silently upgraded into evidence.
A final ceiling is emitted only when the frozen corpus is complete; partial
classification reports progress and bucket counts but ``ceiling`` remains
``None`` so a convenient subset cannot license infrastructure.

Run::

    python experiments/tensor_embedding/arm_o_latent_ceiling.py \
      experiments/tensor_embedding/arm_o_latent_ceiling_corpus.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "daedalus-tensor-latent-ceiling-corpus/1"
REPORT_SCHEMA = "daedalus-tensor-latent-ceiling-report/1"
BUCKETS = ("already_covered", "present_not_expressible", "absent")
STATUSES = ("prediction", "measured")


class CeilingCorpusError(ValueError):
    """The frozen ceiling corpus is malformed or cannot support a claim."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CeilingCorpusError(f"{field} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise CeilingCorpusError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class Row:
    item_id: str
    source: str
    bucket: str
    status: str
    reason: str
    evidence_refs: tuple[str, ...]

    @classmethod
    def parse(cls, raw: Mapping[str, Any], index: int) -> "Row":
        where = f"items[{index}]"
        item_id = _nonempty_string(raw.get("id"), f"{where}.id")
        source = _nonempty_string(raw.get("source"), f"{where}.source")
        bucket = _nonempty_string(raw.get("bucket"), f"{where}.bucket")
        status = _nonempty_string(raw.get("status"), f"{where}.status")
        reason = _nonempty_string(raw.get("reason"), f"{where}.reason")
        if bucket not in BUCKETS:
            raise CeilingCorpusError(
                f"{where}.bucket must be one of {', '.join(BUCKETS)}"
            )
        if status not in STATUSES:
            raise CeilingCorpusError(
                f"{where}.status must be one of {', '.join(STATUSES)}"
            )
        refs = raw.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise CeilingCorpusError(f"{where}.evidence_refs must be non-empty")
        normalized: list[str] = []
        for ref_index, ref in enumerate(refs):
            normalized.append(
                _nonempty_string(ref, f"{where}.evidence_refs[{ref_index}]")
            )
        if len(set(normalized)) != len(normalized):
            raise CeilingCorpusError(f"{where}.evidence_refs contains duplicates")
        return cls(item_id, source, bucket, status, reason, tuple(normalized))


@dataclass(frozen=True)
class Corpus:
    source_revision: str
    expected_total: int
    rows: tuple[Row, ...]
    corpus_sha256: str

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "Corpus":
        if raw.get("schema") != SCHEMA:
            raise CeilingCorpusError(f"schema must be {SCHEMA!r}")
        revision = _nonempty_string(raw.get("source_revision"), "source_revision")
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
            raise CeilingCorpusError("source_revision must be a full 40-hex Git SHA")
        expected = _positive_int(raw.get("expected_total"), "expected_total")
        items = raw.get("items")
        if not isinstance(items, list):
            raise CeilingCorpusError("items must be an array")
        rows: list[Row] = []
        seen: set[str] = set()
        for index, raw_row in enumerate(items):
            if not isinstance(raw_row, Mapping):
                raise CeilingCorpusError(f"items[{index}] must be an object")
            row = Row.parse(raw_row, index)
            if row.item_id in seen:
                raise CeilingCorpusError(f"duplicate item id {row.item_id!r}")
            seen.add(row.item_id)
            rows.append(row)
        if len(rows) > expected:
            raise CeilingCorpusError(
                f"items has {len(rows)} rows but expected_total is {expected}"
            )
        return cls(
            source_revision=revision.lower(),
            expected_total=expected,
            rows=tuple(rows),
            corpus_sha256=_sha256(raw),
        )


def load(path: str | Path) -> Corpus:
    corpus_path = Path(path)
    try:
        raw_text = corpus_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CeilingCorpusError(f"cannot read corpus {corpus_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CeilingCorpusError("corpus root must be an object")
    return Corpus.parse(payload)


def evaluate(corpus: Corpus) -> dict[str, Any]:
    measured = tuple(row for row in corpus.rows if row.status == "measured")
    predictions = tuple(row for row in corpus.rows if row.status == "prediction")
    counts = Counter(row.bucket for row in measured)
    measured_n = len(measured)
    complete = measured_n == corpus.expected_total
    ceiling: float | None = None
    if complete:
        if measured_n <= 0:
            raise CeilingCorpusError("a complete corpus cannot be empty")
        ceiling = counts["present_not_expressible"] / measured_n
        if not math.isfinite(ceiling):
            raise CeilingCorpusError("computed ceiling is non-finite")

    if ceiling is None:
        decision = "INCOMPLETE: classify the frozen corpus before licensing latent infrastructure"
    elif ceiling <= 0.03:
        decision = "CLOSE: <=3% headroom; do not build latent/Tensor retrieval infrastructure"
    elif ceiling >= 0.20:
        decision = "LICENSE_ONE_EXPERIMENT: >=20% headroom; freeze one budget-equal latent-only-variable trial"
    else:
        decision = "AMBIGUOUS: 3-20% headroom; extend evidence/ablation before infrastructure"

    return {
        "schema": REPORT_SCHEMA,
        "source_revision": corpus.source_revision,
        "corpus_sha256": corpus.corpus_sha256,
        "expected_total": corpus.expected_total,
        "rows_present": len(corpus.rows),
        "measured_rows": measured_n,
        "prediction_rows": len(predictions),
        "complete": complete,
        "measured_bucket_counts": {bucket: counts[bucket] for bucket in BUCKETS},
        "ceiling": None if ceiling is None else round(ceiling, 6),
        "decision": decision,
        "claim_boundary": {
            "predictions_are_evidence": False,
            "partial_subset_can_license_infrastructure": False,
            "embedding_or_tensor_backend_built": False,
            "production_promotion_authorized": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = evaluate(load(args.corpus))
    except CeilingCorpusError as exc:
        print(f"REFUSED: {exc}")
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if report["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
