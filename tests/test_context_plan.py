from __future__ import annotations

from pathlib import Path

from daedalus.orchestration.context_plan import (
    latent_memory_seed_scores,
    lexical_seed_scores,
    plan_context,
)
from daedalus.memory.embeddings import AgentEvent, EventVectorStore
from daedalus.structcore import build_index, build_knowledge_forest


class ConstantBackend:
    provider = "test"

    def embed(self, texts, *, model, dimensions=None):
        return [[1.0, 0.0] for _ in texts]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _index(tmp_path: Path) -> dict:
    _write(
        tmp_path,
        "payments/charge_engine.py",
        "def authorize_card(payment):\n    return payment.is_valid\n",
    )
    _write(
        tmp_path,
        "reports/monthly.py",
        "def render_monthly_report(rows):\n    return list(rows)\n",
    )
    _write(
        tmp_path,
        "tests/test_charge.py",
        "from payments.charge_engine import authorize_card\n\n"
        "def test_authorize_card():\n    assert authorize_card(type('P', (), {'is_valid': True})())\n",
    )
    return build_index(tmp_path)


def test_lexical_baseline_uses_path_and_symbol_evidence(tmp_path: Path) -> None:
    idx = _index(tmp_path)

    result = lexical_seed_scores(idx, "repair authorize card payments")

    assert result.projector_version == "path-symbol-bm25-v1"
    assert result.scores["payments/charge_engine.py"] == 1.0
    assert "authorize" in result.matched_terms["payments/charge_engine.py"]
    assert "payments" in result.matched_terms["payments/charge_engine.py"]


def test_context_plan_is_deterministic_budgeted_and_uses_measured_costs(
    tmp_path: Path,
) -> None:
    idx = _index(tmp_path)

    first = plan_context(
        tmp_path,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
    )
    second = plan_context(
        tmp_path,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
    )

    assert first.to_dict() == second.to_dict()
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.dss.context_plan.tokens_used <= 500
    selected = {item.node_id: item for item in first.dss.context_plan.selected}
    assert "payments/charge_engine.py" in selected
    assert selected["payments/charge_engine.py"].estimated_tokens == (
        idx["modules"]["payments/charge_engine.py"]["n_tokens"]
    )


def test_latent_memory_only_maps_hits_with_explicit_file_evidence(
    tmp_path: Path,
) -> None:
    idx = _index(tmp_path)
    forest = build_knowledge_forest(idx)
    db_path = tmp_path / "vectors.db"
    backend = ConstantBackend()
    store = EventVectorStore(db_path, backend=backend)
    store.ingest_events_report(
        [
            AgentEvent(
                "mapped",
                "agent_message",
                "Changed payments/charge_engine.py and verified it",
                metadata={"project": "demo", "trust": "verified"},
            ),
            AgentEvent(
                "unmapped",
                "agent_message",
                "Discussed the payment subsystem without naming a file",
                metadata={"project": "demo", "trust": "verified"},
            ),
        ],
        model="test-model",
    )
    store.close()

    result = latent_memory_seed_scores(
        forest,
        "payment fix",
        db_path=db_path,
        model="test-model",
        project="demo",
        backend=backend,
    )

    assert result.status == "ready"
    assert result.scores == {"payments/charge_engine.py": 1.0}
    assert [row["event_id"] for row in result.mapped_events] == ["mapped"]


def test_no_latent_index_is_reported_instead_of_read_as_no_matches(
    tmp_path: Path,
) -> None:
    idx = _index(tmp_path)
    forest = build_knowledge_forest(idx)

    result = latent_memory_seed_scores(
        forest,
        "anything",
        db_path=tmp_path / "missing.db",
        backend=ConstantBackend(),
    )

    assert result.status == "not_configured"
    assert result.scores == {}
