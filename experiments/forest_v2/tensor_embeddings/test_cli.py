"""The experiment CLI is stdin/read-only and stdout-only."""
from __future__ import annotations

import ast
import builtins
import hashlib
import io
import json
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings import cli
from experiments.forest_v2.tensor_embeddings.contracts import canonical_json_bytes
from experiments.forest_v2.tensor_embeddings.encoding import (
    TensorProductEncoder,
    default_spec,
)
from experiments.forest_v2.tensor_embeddings.index import IndexContractError, TensorIndex


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _run(argv, payload=None):
    stdin = io.BytesIO(b"" if payload is None else canonical_json_bytes(payload))
    stdout = io.BytesIO()
    assert cli.main(argv, stdin=stdin, stdout=stdout) == 0
    raw = stdout.getvalue()
    parsed = json.loads(raw)
    assert raw == canonical_json_bytes(parsed)
    return parsed


def _source(source_id: str, content: str, plane: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_digest": _digest(content),
        "revision": "r1",
        "plane": plane,
        "fields": {
            "path": source_id,
            "symbol": "parse_record" if plane == "code" else "",
            "content": content,
            "neighbor": "",
        },
    }


def test_spec_and_synthetic_commands_need_no_input() -> None:
    spec = _run(["spec"])
    assert spec["classification"] == "EXPERIMENT"
    assert spec["active_gate"] == 0
    assert spec["evaluation_mode"] == "diagnostic_and_structural_only"
    assert spec["scientific_verdicts"] == "forbidden_without_external_trust_anchor"
    assert spec["automatic_promotions"] == 0
    assert spec["max_candidates_per_case"] == 65_536
    assert spec["max_role_field_bytes"] == 65_536
    assert spec["max_source_evidence_bytes"] == 262_144
    assert spec["dense_scalar_budget"] == 512
    construct = _run(["benchmark", "--synthetic"])
    assert construct["cosine_tie"] is True
    assert construct["structured_separates"] is True


@pytest.mark.parametrize("representation", ("cp", "dense", "tt"))
def test_encode_supports_all_exact_storage_forms(representation: str) -> None:
    output = _run(
        ["encode", "--representation", representation],
        _source("src/parser.py", "def parse_record(value): return value", "code"),
    )
    assert output["authority"] == "unverified-retrieval-proposal"
    assert output["source_binding"] == "visible_content_sha256_verified"
    assert output["representation"] == representation
    assert output["dense_scalar_budget"] == 512


def test_build_then_search_roundtrip_uses_only_json_streams() -> None:
    documents = [
        _source("src/parser.py", "def parse_record(value): return value", "code"),
        _source("docs/parser.md", "Parser record format guide", "knowledge"),
    ]
    index = _run(["build", "--representation", "tt"], {"documents": documents})
    output = _run(
        ["search"],
        {
            "index": index,
            "query": {"id": "q1", "text": "parse record", "revision": "r1"},
            "mode": "structured",
            "limit": 2,
            "explain_top": 4,
        },
    )
    assert output["authority"] == "unverified-retrieval-proposal"
    assert output["dense_scalar_budget"] == 512
    assert len(output["hits"]) == 2
    assert all(hit["authority"] == output["authority"] for hit in output["hits"])


def test_benchmark_command_cannot_self_certify_arbitrary_stdin_as_held_out() -> None:
    content = "def parse_record(value): return value"
    payload = {
        "cases": [
            {
                "case_id": "smoke-1",
                "query": "parse record",
                "variant": "raw",
                "revision": "r1",
                "candidates": [
                    {
                        "path": "src/parser.py",
                        "blob": "blob-1",
                        "size": len(content.encode()),
                        "content": content,
                        "content_budget": len(content.encode()),
                    }
                ],
                "gold": ["src/parser.py"],
                "recency_ranking": ["src/parser.py"],
            }
        ]
    }
    report = _run(["benchmark"], payload)
    assert report["status"] == "VALID"
    assert report["conclusion"] == "INCONCLUSIVE"
    assert not any(item["superiority_claim"] for item in report["comparisons"])


def test_cli_has_no_output_path_or_write_flag_and_no_filesystem_writer(monkeypatch) -> None:
    parser = cli.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    # Include subparser actions in the scan.
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for subparser in choices.values():
                option_strings.update(
                    option
                    for subaction in subparser._actions
                    for option in subaction.option_strings
                )
    assert "--out" not in option_strings
    assert "--output" not in option_strings
    assert "--write" not in option_strings

    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    forbidden_imports = {"subprocess", "socket", "requests", "urllib"}
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            (alias.name if isinstance(node, ast.Import) else (node.module or "")).split(".")[0]
            in forbidden_imports
            for alias in node.names
        )
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"open", "Path"}
        for node in ast.walk(tree)
    )

    def forbidden_open(*args, **kwargs):
        raise AssertionError("CLI attempted a filesystem open")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    assert _run(["spec"])["dense_scalar_budget"] == 512


def test_duplicate_json_keys_and_unknown_fields_refuse() -> None:
    with pytest.raises(cli.CLIInputError, match="duplicate JSON key"):
        cli.main(
            ["encode"],
            stdin=io.BytesIO(b'{"source_id":"a","source_id":"b"}'),
            stdout=io.BytesIO(),
        )
    payload = _source("src/a.py", "def a(): pass", "code")
    payload["surprise"] = True
    with pytest.raises(cli.CLIInputError, match="key mismatch"):
        _run(["encode"], payload)


def test_cli_verifies_visible_source_digest() -> None:
    payload = _source("src/a.py", "def a(): pass", "code")
    payload["source_digest"] = "sha256:" + "0" * 64
    with pytest.raises(cli.CLIInputError, match="does not address"):
        _run(["encode"], payload)


def test_index_refuses_content_valid_but_unfrozen_tensor_spec() -> None:
    encoder = TensorProductEncoder(default_spec(seed=11, feature_dimension=16))
    artifact = encoder.encode_candidate(
        "src/a.py",
        "def a(): pass",
        blob=_digest("def a(): pass"),
        revision="r1",
    )
    with pytest.raises(IndexContractError, match="4x4x32"):
        TensorIndex.build((artifact,))
