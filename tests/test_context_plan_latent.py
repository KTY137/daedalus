# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The latent half of the context planner must be visible, not merely optional.

Every case here is deterministic: the embedding backends are fakes, no network
and no Ollama are touched.  The point of the file is that "nobody asked the
latent source", "the latent source could not be reached" and "the latent source
answered and found nothing" all produce an empty score map, and the plan must
tell them apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import daedalus.context_plan as context_plan
from daedalus.context_plan import (
    LatentSeedResult,
    fuse_seed_scores,
    latent_memory_seed_scores,
    lexical_seed_scores,
    plan_context,
)
from daedalus.memory.embeddings import (
    AgentEvent,
    EmbeddingUnavailableError,
    EventVectorStore,
)
from daedalus.structcore import build_index, build_knowledge_forest


MODEL = "test-model"
PROJECT = "demo"


class ConstantBackend:
    """Every text embeds to the same unit vector, so every event matches."""

    provider = "test"

    def embed(self, texts, *, model, dimensions=None):
        return [[1.0, 0.0] for _ in texts]


class UnreachableBackend:
    """Stands in for "Ollama is not running" -- the normal case on this box."""

    provider = "test-dead"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts, *, model, dimensions=None):
        self.calls += 1
        raise EmbeddingUnavailableError("connection refused (test)")


class ExplodingBackend:
    """Fails the test loudly if the latent path is walked when it must not be."""

    provider = "test-explode"

    def embed(self, texts, *, model, dimensions=None):
        raise AssertionError("the latent backend was consulted but must not be")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
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
    return tmp_path


@pytest.fixture()
def idx(repo: Path) -> dict:
    return build_index(repo)


def _seeded_db(tmp_path: Path, events: list[AgentEvent], name: str = "vectors.db") -> Path:
    db_path = tmp_path / name
    store = EventVectorStore(db_path, backend=ConstantBackend())
    report = store.ingest_events_report(events, model=MODEL)
    store.close()
    assert report.status.available, report.status.message
    return db_path


def _pathful_event() -> AgentEvent:
    return AgentEvent(
        "mapped",
        "agent_message",
        "Rewrote reports/monthly.py and verified the totals",
        metadata={"project": PROJECT, "trust": "verified"},
    )


def _pathless_event() -> AgentEvent:
    return AgentEvent(
        "unmapped",
        "agent_message",
        "Talked about the billing subsystem without naming any file",
        metadata={"project": PROJECT, "trust": "verified"},
    )


# --------------------------------------------------------------------------- #
# 1 -- latent OFF (the default)                                                #
# --------------------------------------------------------------------------- #

def test_latent_off_is_not_consulted_and_says_so(repo: Path, idx: dict, monkeypatch) -> None:
    calls: list[tuple] = []
    original = context_plan.latent_memory_seed_scores

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(context_plan, "latent_memory_seed_scores", spy)

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
        embedding_backend=ExplodingBackend(),
    )

    assert calls == [], "latent_memory_seed_scores ran with use_latent=False"

    latent = result.to_dict()["receipt"]["latent_source"]
    assert latent["requested"] is False
    assert latent["consulted"] is False
    assert latent["answered"] is False
    assert latent["status"] == "disabled"
    assert latent["reason"]


def test_latent_off_does_not_claim_a_weight_it_never_applied(
    repo: Path, idx: dict
) -> None:
    result = plan_context(repo, "repair authorize card payments", idx=idx, token_budget=500)
    payload = result.to_dict()

    # The configured weight stays visible -- it is a real setting -- but the
    # receipt must not let it be read as an influence on this plan.
    assert payload["seeds"]["latent_weight"] == 0.35
    assert payload["seeds"]["latent_applied"] is False
    assert payload["seeds"]["effective_latent_weight"] == 0.0
    assert payload["receipt"]["latent_source"]["declared_weight"] == 0.35
    assert payload["receipt"]["latent_source"]["effective_weight"] == 0.0
    assert payload["receipt"]["latent_source"]["influenced_files"] == 0


# --------------------------------------------------------------------------- #
# 2 -- latent ON, backend answers                                              #
# --------------------------------------------------------------------------- #

def test_latent_on_with_an_answering_backend_is_credited_in_the_receipt(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    db_path = _seeded_db(tmp_path, [_pathful_event()])

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        project=PROJECT,
        token_budget=500,
        use_latent=True,
        vector_db=db_path,
        embedding_model=MODEL,
        embedding_backend=ConstantBackend(),
    )
    payload = result.to_dict()
    latent = payload["receipt"]["latent_source"]

    assert latent["requested"] is True
    assert latent["consulted"] is True
    assert latent["answered"] is True
    assert latent["status"] == "ready"
    assert latent["candidates"] == 1
    assert latent["mapped_events"] == 1
    assert latent["seed_files"] == 1
    assert latent["influenced_files"] == 1
    assert latent["index_id"]
    assert latent["effective_weight"] == 0.35

    # The latent-only file carries seed mass the lexical side never gave it.
    assert payload["seeds"]["latent_influenced"] == ["reports/monthly.py"]
    assert "reports/monthly.py" not in payload["seeds"]["lexical"]["scores"]
    assert "reports/monthly.py" in payload["seeds"]["scores"]


def test_latent_answer_with_no_path_evidence_is_answered_but_empty(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    """"Answered, found nothing" must not look like "never asked"."""
    db_path = _seeded_db(tmp_path, [_pathless_event()])

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        project=PROJECT,
        token_budget=500,
        use_latent=True,
        vector_db=db_path,
        embedding_model=MODEL,
        embedding_backend=ConstantBackend(),
    )
    latent = result.to_dict()["receipt"]["latent_source"]

    assert latent["consulted"] is True
    assert latent["answered"] is True
    assert latent["status"] == "ready"
    assert latent["candidates"] == 1, "the index returned a hit it could not map"
    assert latent["seed_files"] == 0
    assert latent["influenced_files"] == 0
    assert latent["effective_weight"] == 0.0


# --------------------------------------------------------------------------- #
# 3 -- latent ON, nothing reachable                                            #
# --------------------------------------------------------------------------- #

def test_unreachable_backend_is_named_not_silently_zero(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    db_path = _seeded_db(tmp_path, [_pathful_event()])
    backend = UnreachableBackend()

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        project=PROJECT,
        token_budget=500,
        use_latent=True,
        vector_db=db_path,
        embedding_model=MODEL,
        embedding_backend=backend,
    )
    payload = result.to_dict()
    latent = payload["receipt"]["latent_source"]

    assert backend.calls == 1
    assert latent["requested"] is True
    assert latent["consulted"] is True
    assert latent["answered"] is False
    assert latent["status"] == "embedder_unavailable"
    assert "unavailable" in latent["reason"]
    assert latent["seed_files"] == 0
    assert latent["effective_weight"] == 0.0

    # It fails open on the plan and closed on the claim: the lexical plan is
    # still produced and still budgeted.
    assert payload["dss"]["context_plan"]["selected"]
    assert payload["dss"]["context_plan"]["tokens_used"] <= 500


def test_missing_vector_index_reports_not_configured_with_the_path(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    missing = tmp_path / "absent" / "vectors.db"

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
        use_latent=True,
        vector_db=missing,
        embedding_backend=ExplodingBackend(),
    )
    latent = result.to_dict()["receipt"]["latent_source"]

    assert latent["requested"] is True
    assert latent["consulted"] is False, "no index exists, so nothing was queried"
    assert latent["answered"] is False
    assert latent["status"] == "not_configured"
    assert "vectors.db" in latent["reason"]


def test_empty_index_reports_index_unavailable(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    db_path = tmp_path / "empty.db"
    EventVectorStore(db_path, backend=ConstantBackend()).close()

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
        use_latent=True,
        vector_db=db_path,
        embedding_backend=ExplodingBackend(),
    )
    latent = result.to_dict()["receipt"]["latent_source"]

    assert latent["requested"] is True
    assert latent["consulted"] is False
    assert latent["status"] == "index_unavailable"


def test_a_broken_index_is_recorded_instead_of_killing_the_plan(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database" * 64)

    result = plan_context(
        repo,
        "repair authorize card payments",
        idx=idx,
        token_budget=500,
        use_latent=True,
        vector_db=corrupt,
        embedding_backend=ConstantBackend(),
    )
    payload = result.to_dict()
    latent = payload["receipt"]["latent_source"]

    assert latent["status"] == "error"
    assert latent["requested"] is True
    assert latent["answered"] is False
    assert "DatabaseError" in latent["reason"]
    assert payload["dss"]["context_plan"]["selected"], "the lexical plan must survive"


def test_programmer_error_still_raises(repo: Path, idx: dict, tmp_path: Path) -> None:
    """Containment covers the environment, not bad arguments."""
    forest = build_knowledge_forest(idx)
    with pytest.raises(ValueError):
        latent_memory_seed_scores(
            forest,
            "anything",
            db_path=tmp_path / "missing.db",
            limit=0,
            backend=ConstantBackend(),
        )


# --------------------------------------------------------------------------- #
# 4 -- fusion arithmetic and receipt integrity                                 #
# --------------------------------------------------------------------------- #

def test_empty_latent_side_does_not_dilute_the_lexical_ranking(idx: dict) -> None:
    lexical = lexical_seed_scores(idx, "repair authorize card payments")
    assert lexical.scores

    for status in ("disabled", "not_configured", "embedder_unavailable", "ready"):
        fused = fuse_seed_scores(lexical, LatentSeedResult(status, "", {}, ()))
        assert dict(fused.scores) == dict(lexical.scores), status
        assert fused.latent_influenced == ()
        assert fused.effective_latent_weight == 0.0


def test_each_latent_state_produces_a_distinct_receipt(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    def sha(**kwargs) -> str:
        return plan_context(
            repo,
            "repair authorize card payments",
            idx=idx,
            token_budget=500,
            **kwargs,
        ).receipt_sha256

    seeded = _seeded_db(tmp_path, [_pathful_event()])
    digests = {
        "off": sha(),
        "not_configured": sha(
            use_latent=True,
            vector_db=tmp_path / "absent.db",
            embedding_backend=ConstantBackend(),
        ),
        "unavailable": sha(
            project=PROJECT,
            use_latent=True,
            vector_db=seeded,
            embedding_model=MODEL,
            embedding_backend=UnreachableBackend(),
        ),
        "ready": sha(
            project=PROJECT,
            use_latent=True,
            vector_db=seeded,
            embedding_model=MODEL,
            embedding_backend=ConstantBackend(),
        ),
    }

    assert len(set(digests.values())) == len(digests), digests


def test_receipt_stays_deterministic_and_keeps_the_acceptance_shape(
    repo: Path, idx: dict, tmp_path: Path
) -> None:
    db_path = _seeded_db(tmp_path, [_pathful_event()])
    kwargs = dict(
        idx=idx,
        project=PROJECT,
        token_budget=500,
        use_latent=True,
        vector_db=db_path,
        embedding_model=MODEL,
    )
    first = plan_context(
        repo, "repair authorize card payments", embedding_backend=ConstantBackend(), **kwargs
    ).to_dict()
    second = plan_context(
        repo, "repair authorize card payments", embedding_backend=ConstantBackend(), **kwargs
    ).to_dict()

    assert first == second
    # The shape `daedalus context --json` is accepted on.
    assert first["receipt"]["receipt_sha256"]
    assert first["dss"]["context_plan"]["selected"]
    assert first["dss"]["context_plan"]["tokens_used"] <= 500
