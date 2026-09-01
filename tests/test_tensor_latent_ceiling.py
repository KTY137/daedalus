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


def _corpus(
    items: list[dict],
    expected_total: int | None = None,
    source_revision: str | None = None,
) -> dict:
    return {
        "schema": O.SCHEMA,
        "source_revision": source_revision or O.FROZEN_SOURCE_REVISION,
        "expected_total": expected_total if expected_total is not None else len(items),
        "items": items,
    }


def _complete_corpus(b_count: int, c_count: int = 0):
    a_count = O.FROZEN_EXPECTED_TOTAL - b_count - c_count
    assert a_count >= 0
    items = [
        *[_row(f"a{i}", "already_covered") for i in range(a_count)],
        *[_row(f"b{i}", "present_not_expressible") for i in range(b_count)],
        *[_row(f"c{i}", "absent") for i in range(c_count)],
    ]
    return O.Corpus.parse(_corpus(items, expected_total=O.FROZEN_EXPECTED_TOTAL))


def test_committed_corpus_preserves_predictions_without_claiming_a_result() -> None:
    corpus = O.load(CORPUS)
    report = O.evaluate(corpus)
    assert corpus.source_revision == O.FROZEN_SOURCE_REVISION
    assert corpus.expected_total == O.FROZEN_EXPECTED_TOTAL == 1383
    assert len(corpus.rows) == 10
    assert report["prediction_rows"] == 10
    assert report["measured_rows"] == 0
    assert report["complete"] is False
    assert report["ceiling"] is None
    assert report["claim_boundary"]["predictions_are_evidence"] is False
    assert report["claim_boundary"]["partial_subset_can_license_infrastructure"] is False
    assert report["claim_boundary"]["embedding_or_tensor_backend_built"] is False


def test_complete_measured_corpus_computes_only_bucket_b_headroom() -> None:
    corpus = _complete_corpus(b_count=346, c_count=1)
    report = O.evaluate(corpus)
    assert report["complete"] is True
    assert report["ceiling"] == round(346 / O.FROZEN_EXPECTED_TOTAL, 6)
    assert report["measured_bucket_counts"] == {
        "already_covered": 1036,
        "present_not_expressible": 346,
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


def test_changed_denominator_cannot_publish_a_ceiling_via_direct_evaluation() -> None:
    corpus = O.Corpus.parse(
        _corpus([_row("b1", "present_not_expressible")], expected_total=1)
    )
    report = O.evaluate(corpus)
    assert report["measured_rows"] == 1
    assert report["complete"] is False
    assert report["ceiling"] is None
    assert report["decision"].startswith("INCOMPLETE")


def test_changed_source_revision_cannot_publish_a_ceiling_via_direct_evaluation() -> None:
    frozen = _complete_corpus(b_count=346, c_count=1)
    changed = O.Corpus(
        source_revision="b" * 40,
        expected_total=frozen.expected_total,
        rows=frozen.rows,
        corpus_sha256=frozen.corpus_sha256,
    )
    report = O.evaluate(changed)
    assert report["measured_rows"] == O.FROZEN_EXPECTED_TOTAL
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


@pytest.mark.parametrize(
    "target,replacement,match",
    [
        (
            f'"schema":"{O.SCHEMA}"',
            f'"schema":"shadow","schema":"{O.SCHEMA}"',
            "duplicate JSON object key 'schema'",
        ),
        (
            '"id":"a"',
            '"id":"shadow","id":"a"',
            "duplicate JSON object key 'id'",
        ),
    ],
)
def test_load_refuses_duplicate_json_object_keys(
    tmp_path: Path, target: str, replacement: str, match: str
) -> None:
    rendered = json.dumps(
        _corpus([_row("a", "already_covered")], expected_total=O.FROZEN_EXPECTED_TOTAL),
        separators=(",", ":"),
    )
    ambiguous = rendered.replace(target, replacement, 1)
    assert ambiguous != rendered
    path = tmp_path / "ambiguous.json"
    path.write_text(ambiguous, encoding="utf-8")
    with pytest.raises(O.CeilingCorpusError, match=match):
        O.load(path)


def test_load_refuses_changed_frozen_source_revision(tmp_path: Path) -> None:
    path = tmp_path / "changed-source-revision.json"
    path.write_text(
        json.dumps(
            _corpus(
                [_row("b", "present_not_expressible")],
                expected_total=O.FROZEN_EXPECTED_TOTAL,
                source_revision="b" * 40,
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(O.CeilingCorpusError, match="source_revision must remain frozen"):
        O.load(path)


def test_load_refuses_changed_frozen_denominator(tmp_path: Path) -> None:
    path = tmp_path / "changed-denominator.json"
    path.write_text(
        json.dumps(_corpus([_row("b", "present_not_expressible")], expected_total=1)),
        encoding="utf-8",
    )
    with pytest.raises(O.CeilingCorpusError, match="expected_total must remain frozen at 1383"):
        O.load(path)


def test_thresholds_do_not_turn_midrange_or_tiny_headroom_into_a_win() -> None:
    close = O.evaluate(_complete_corpus(b_count=13, c_count=1))
    assert close["ceiling"] == round(13 / O.FROZEN_EXPECTED_TOTAL, 6)
    assert close["decision"].startswith("CLOSE")

    ambiguous = O.evaluate(_complete_corpus(b_count=138, c_count=1))
    assert ambiguous["ceiling"] == round(138 / O.FROZEN_EXPECTED_TOTAL, 6)
    assert ambiguous["decision"].startswith("AMBIGUOUS")


def test_main_returns_incomplete_code_for_prediction_only_corpus(capsys) -> None:
    assert O.main([str(CORPUS)]) == 3
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["complete"] is False
    assert rendered["ceiling"] is None
