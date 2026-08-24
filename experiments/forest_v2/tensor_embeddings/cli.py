"""Stdout-only command interface for the isolated tensor experiment.

Every command consumes canonicalizable JSON from stdin and emits one compact
JSON value to stdout.  There is deliberately no output-path argument and no
filesystem writer in this module.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, BinaryIO, Mapping, Sequence

from experiments.forest_v2.s09_eval.contract import Candidate, QueryView

from .benchmark import BenchmarkCase, run_benchmark, synthetic_role_binding_construct
from .contracts import canonical_json_bytes
from .encoding import (
    HASH_BACKEND_ID,
    HASH_FEATURE_FAMILY,
    MAX_ROLE_FIELD_BYTES,
    MAX_SOURCE_EVIDENCE_BYTES,
    HashingFillerBackend,
    RoleFields,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)
from .index import AUTHORITY, MAX_INDEX_DOCUMENTS, TensorIndex
from .retrievers import FROZEN_HASH_SEEDS, frozen_kernel
from .stats import SPEC_DIGEST


ENCODE_SCHEMA = "forest-v2.tensor-encode-output/1"
SEARCH_SCHEMA = "forest-v2.tensor-search-output/1"


class CLIInputError(ValueError):
    pass


def _mapping(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CLIInputError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        raise CLIInputError(
            f"{label} key mismatch; unknown={sorted(actual - keys)!r}, "
            f"missing={sorted(keys - actual)!r}"
        )
    return value


def _read_json(stream: BinaryIO) -> object:
    raw = stream.read()
    if not raw:
        raise CLIInputError("stdin JSON is required")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise CLIInputError("stdin is not UTF-8") from exc

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise CLIInputError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject(value: str) -> object:
        raise CLIInputError(f"non-finite JSON number {value} is forbidden")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)
    except CLIInputError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CLIInputError(f"invalid stdin JSON: {exc}") from exc


def _fields(value: object) -> RoleFields:
    data = _mapping(value, {"path", "symbol", "content", "neighbor"}, "fields")
    if any(type(data[name]) is not str for name in data):
        raise CLIInputError("all role fields must be strings")
    return RoleFields(
        path=data["path"],
        symbol=data["symbol"],
        content=data["content"],
        neighbor=data["neighbor"],
    )


def _encoded_from_record(value: object, encoder: TensorProductEncoder):
    data = _mapping(
        value,
        {"source_id", "source_digest", "revision", "plane", "fields"},
        "encoded source",
    )
    fields = _fields(data["fields"])
    # The CLI can verify the content address against the bytes it actually
    # receives.  This is still not a provenance claim; outputs remain
    # unverified proposals until an external source/preimage receipt binds it.
    if data["source_digest"] != canonical_source_digest(fields.content):
        raise CLIInputError("source_digest does not address fields.content")
    return encoder.encode_visible_fields(
        fields,
        source_id=data["source_id"],
        source_digest=data["source_digest"],
        revision=data["revision"],
        plane=data["plane"],
    )


def _encode_command(payload: object, seed: int, representation: str) -> object:
    encoder = TensorProductEncoder(default_spec(seed=seed))
    artifact = _encoded_from_record(payload, encoder)
    if representation == "cp":
        tensor = artifact.tensor
    elif representation == "dense":
        tensor = artifact.tensor.to_dense()
    elif representation == "tt":
        tensor = artifact.tensor.to_tensor_train()
    else:  # argparse constrains this; retained for direct callers
        raise CLIInputError("unsupported representation")
    return {
        "schema": ENCODE_SCHEMA,
        "authority": AUTHORITY,
        "source_id": artifact.source_id,
        "source_digest": artifact.source_digest,
        "source_binding": artifact.source_binding,
        "revision": artifact.revision,
        "plane": artifact.plane,
        "backend_id": artifact.backend_id,
        "spec": artifact.tensor.spec.to_dict(),
        "representation": representation,
        "dense_scalar_budget": artifact.tensor.spec.dense_scalar_count,
        "tensor": tensor.to_dict(),
    }


def _build_command(payload: object, seed: int, representation: str) -> object:
    data = _mapping(payload, {"documents"}, "build input")
    documents = data["documents"]
    if not isinstance(documents, list) or not documents:
        raise CLIInputError("documents must be a non-empty array")
    if len(documents) > MAX_INDEX_DOCUMENTS:
        raise CLIInputError("index document cap exceeded")
    encoder = TensorProductEncoder(default_spec(seed=seed))
    artifacts = [_encoded_from_record(item, encoder) for item in documents]
    return TensorIndex.build(artifacts, representation=representation).to_dict()


def _search_command(payload: object) -> object:
    data = _mapping(payload, {"index", "query", "mode", "limit", "explain_top"}, "search input")
    index = TensorIndex.from_dict(data["index"])
    query_data = _mapping(data["query"], {"id", "text", "revision"}, "query")
    if index.backend_id != HASH_BACKEND_ID:
        raise CLIInputError("CLI search only supports the frozen offline hashing backend")
    if index.experiment_spec_digest != SPEC_DIGEST:
        raise CLIInputError("index experiment spec digest is not frozen for this build")
    if index.spec.seed not in FROZEN_HASH_SEEDS or index.spec != default_spec(index.spec.seed):
        raise CLIInputError("index TensorSpec is outside the frozen 4x4x32 seed policy")
    if index.spec.dense_scalar_count != 512:
        raise CLIInputError("index violates the frozen 512-scalar budget")
    encoder = TensorProductEncoder(
        index.spec, HashingFillerBackend(index.spec.seed)
    )
    query = encoder.encode_query(
        query_data["text"], query_id=query_data["id"], revision=query_data["revision"]
    )
    mode = data["mode"]
    kernel = frozen_kernel(index.spec) if mode in {"structured", "maxsim"} else None
    hits = index.search(
        query,
        mode=mode,
        kernel=kernel,
        limit=data["limit"],
        explain_top=data["explain_top"],
    )
    return {
        "schema": SEARCH_SCHEMA,
        "authority": AUTHORITY,
        "index_id": index.index_id,
        "corpus_digest": index.corpus_digest,
        "query_tensor_id": query.tensor.tensor_id,
        "spec_id": index.spec.spec_id,
        "kernel_id": kernel.kernel_id if kernel is not None else None,
        "mode": mode,
        "dense_scalar_budget": index.spec.dense_scalar_count,
        "hits": [hit.to_dict() for hit in hits],
    }


def _benchmark_case(value: object) -> BenchmarkCase:
    data = _mapping(
        value,
        {
            "case_id",
            "query",
            "variant",
            "revision",
            "candidates",
            "gold",
            "recency_ranking",
        },
        "benchmark case",
    )
    rows = data["candidates"]
    if not isinstance(rows, list) or not rows:
        raise CLIInputError("benchmark candidates must be a non-empty array")
    if len(rows) > 65_536:
        raise CLIInputError("benchmark candidate cap exceeded")
    candidates = []
    for row in rows:
        item = _mapping(
            row,
            {"path", "blob", "size", "content", "content_budget"},
            "benchmark candidate",
        )
        if type(item["content"]) is not str:
            raise CLIInputError("benchmark candidate content must be text")
        if type(item["path"]) is not str or not item["path"]:
            raise CLIInputError("benchmark candidate path must be non-empty text")
        if type(item["blob"]) is not str or not item["blob"]:
            raise CLIInputError("benchmark candidate blob must be non-empty text")
        raw = item["content"].encode("utf-8")
        if isinstance(item["size"], bool) or type(item["size"]) is not int:
            raise CLIInputError("benchmark candidate size must be an integer")
        if item["size"] != len(raw) or not 0 < item["size"] <= 200_000:
            raise CLIInputError("benchmark candidate size must equal UTF-8 content bytes")
        if (
            isinstance(item["content_budget"], bool)
            or type(item["content_budget"]) is not int
            or not 0 < item["content_budget"] <= 65_536
        ):
            raise CLIInputError("content_budget must be within candidate size")
        candidates.append(
            Candidate(
                path=item["path"],
                blob=item["blob"],
                size=item["size"],
                raw=raw,
                content_budget=item["content_budget"],
            )
        )
    gold = data["gold"]
    if not isinstance(gold, list) or any(type(path) is not str for path in gold):
        raise CLIInputError("benchmark gold must be a string array")
    recency_ranking = data["recency_ranking"]
    if not isinstance(recency_ranking, list) or any(
        type(path) is not str for path in recency_ranking
    ):
        raise CLIInputError("benchmark recency_ranking must be a string array")
    for field in ("case_id", "query", "variant", "revision"):
        if type(data[field]) is not str or not data[field]:
            raise CLIInputError(f"benchmark {field} must be non-empty text")
    return BenchmarkCase(
        query=QueryView(
            case_id=data["case_id"],
            text=data["query"],
            variant=data["variant"],
            revision=data["revision"],
            repo="",
        ),
        universe=tuple(candidates),
        gold=tuple(gold),
        recency_ranking=tuple(recency_ranking),
    )


def _benchmark_command(payload: object) -> object:
    data = _mapping(payload, {"cases"}, "benchmark input")
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise CLIInputError("benchmark cases must be a non-empty array")
    # The in-process harness is diagnostic by contract and can never emit
    # ADVANCE/KILL from arbitrary stdin.
    return run_benchmark(tuple(_benchmark_case(case) for case in cases))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("encode", "build"):
        command = subparsers.add_parser(name, allow_abbrev=False)
        command.add_argument("--seed", type=int, choices=FROZEN_HASH_SEEDS, default=11)
        command.add_argument("--representation", choices=("cp", "dense", "tt"), default="cp")
    subparsers.add_parser("search", allow_abbrev=False)
    benchmark = subparsers.add_parser("benchmark", allow_abbrev=False)
    benchmark.add_argument("--synthetic", action="store_true")
    subparsers.add_parser("spec", allow_abbrev=False)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    source = stdin if stdin is not None else sys.stdin.buffer
    target = stdout if stdout is not None else sys.stdout.buffer
    if args.command == "spec":
        spec = default_spec()
        output = {
            "experiment_schema": "forest-v2.tensor-embedding-experiment/1",
            "classification": "EXPERIMENT",
            "active_gate": 0,
            "evaluation_mode": "diagnostic_and_structural_only",
            "scientific_verdicts": "forbidden_without_external_trust_anchor",
            "claim_interpretation": "frozen_kernel_prior_vs_plain_cosine_not_tensor_vs_vector_expressivity",
            "representation_null": "structured_contraction_equals_flattened_kronecker_bilinear",
            "tensor_vs_vector_superiority_claim": "forbidden_by_exact_bilinear_equivalence",
            "automatic_promotions": 0,
            "experiment_spec_digest": SPEC_DIGEST,
            "filler_backend": HashingFillerBackend(spec.seed).backend_id,
            "hash_feature_family": HASH_FEATURE_FAMILY,
            "spec": spec.to_dict(),
            "kernel": frozen_kernel(spec).to_dict(),
            "dense_scalar_budget": spec.dense_scalar_count,
            "max_candidates_per_case": MAX_INDEX_DOCUMENTS,
            "max_role_field_bytes": MAX_ROLE_FIELD_BYTES,
            "max_source_evidence_bytes": MAX_SOURCE_EVIDENCE_BYTES,
            "persisted_index_backend": HASH_BACKEND_ID,
            "persisted_index_kernel": "frozen_exact",
        }
    elif args.command == "benchmark" and args.synthetic:
        output = synthetic_role_binding_construct()
    else:
        payload = _read_json(source)
        if args.command == "encode":
            output = _encode_command(payload, args.seed, args.representation)
        elif args.command == "build":
            output = _build_command(payload, args.seed, args.representation)
        elif args.command == "search":
            output = _search_command(payload)
        elif args.command == "benchmark":
            output = _benchmark_command(payload)
        else:  # pragma: no cover - argparse guarantees the command
            raise CLIInputError("unknown command")
    target.write(canonical_json_bytes(output))
    return 0


__all__ = [
    "CLIInputError",
    "ENCODE_SCHEMA",
    "SEARCH_SCHEMA",
    "build_parser",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
