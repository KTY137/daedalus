from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "experiments" / "tensor_embedding" / "arm_o_latent_ceiling.py"
CORPUS = ROOT / "experiments" / "tensor_embedding" / "arm_o_latent_ceiling_corpus.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("arm_o_latent_ceiling", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


O = _load_module()


def _row(item_id: str, bucket: str, status: str = "measured") -> dict:
    return {
        "id": item_id,
        "source": "fixture",
        "bucket": bucket,
        "status": status,
        "reason": "fixture reason",
        "evidence_refs": ["fixture:evidence"],
    }


def _corpus(items: list[dict], expected_total: int | None = None) -> dict:
    return {
        "schema": O.SCHEMA,
        "source_revision": "a" * 40,
        "expected_total": expected_total if expected_total is not None else len(items),
        "items": items,
    }


def test_committed_corpus_preserves_predictions_without_claiming_a_result() -> None:
    corpus = O.load(CORPUS)
    report = O.evaluate(corpus)
    assert corpus.expected_total == 1383
    assert len(corpus.rows) == 10
    assert report["prediction_rows"] == 10
    assert report["measured_rows"] == 0
    assert report["complete"] is False
    assert report["ceiling"] is None
    assert report["claim_boundary"]["predictions_are_evidence"] is False
    assert report["claim_boundary"]["partial_subset_can_license_infrastructure"] is False
    assert report["claim_boundary"]["embedding_or_tensor_backend_built"] is False


def test_complete_measured_corpus_computes_only_bucket_b_headroom() -> None:
    corpus = O.Corpus.parse(
        _corpus([
            _row("a1", "already_covered"),
            _row("a2", "already_covered"),
            _row("b1", "present_not_expressible"),
            _row("c1", "absent"),
        ])
    )
    report = O.evaluate(corpus)
    assert report["complete"] is True
    assert report["ceiling"] == 0.25
    assert report["measured_bucket_counts"] == {
        "already_covered": 2,
        "present_not_expressible": 1,
        "absent": 1,
    }
    assert report["decision"].startswith("LICENSE_ONE_EXPERIMENT")


def test_partial_measured_subset_cannot_publish_a_ceiling() -> None:
    corpus = O.Corpus.parse(
        _corpus([_row("b1", "present_not_expressible")], expected_total=100)
    )
    report = O.evaluate(corpus)
    assert report["measured_bucket_counts"]["present_not_expressible"] == 1
    assert report["complete"] is False
    assert report["ceiling"] is None
    assert report["decision"].startswith("INCOMPLETE")


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda payload: payload.update(schema="wrong"), "schema"),
        (lambda payload: payload.update(shadow="ignored"), "corpus fields"),
        (lambda payload: payload.update(source_revision="abc"), "source_revision"),
        (lambda payload: payload["items"].append(dict(payload["items"][0])), "duplicate item id"),
        (lambda payload: payload["items"][0].update(shadow="ignored"), "items\\[0\\] fields"),
        (lambda payload: payload["items"][0].update(bucket="maybe"), "bucket"),
        (lambda payload: payload["items"][0].update(status="inferred"), "status"),
        (lambda payload: payload["items"][0].update(evidence_refs=[]), "evidence_refs"),
    ],
)
def test_malformed_or_ambiguous_corpus_is_refused(mutator, match: str) -> None:
    payload = _corpus([_row("a", "already_covered")])
    mutator(payload)
    with pytest.raises(O.CeilingCorpusError, match=match):
        O.Corpus.parse(payload)


def test_thresholds_do_not_turn_midrange_or_tiny_headroom_into_a_win() -> None:
    close = O.evaluate(
        O.Corpus.parse(_corpus([
            *[_row(f"a{i}", "already_covered") for i in range(98)],
            _row("b", "present_not_expressible"),
            _row("c", "absent"),
        ]))
    )
    assert close["ceiling"] == 0.01
    assert close["decision"].startswith("CLOSE")

    ambiguous = O.evaluate(
        O.Corpus.parse(_corpus([
            *[_row(f"a{i}", "already_covered") for i in range(8)],
            _row("b", "present_not_expressible"),
            _row("c", "absent"),
        ]))
    )
    assert ambiguous["ceiling"] == 0.1
    assert ambiguous["decision"].startswith("AMBIGUOUS")


def test_main_returns_incomplete_code_for_prediction_only_corpus(capsys) -> None:
    assert O.main([str(CORPUS)]) == 3
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["complete"] is False
    assert rendered["ceiling"] is None
