# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Adversarial integrity tests for the Latent Projection Index v2.

Every test here constructs a BAD state and asserts the index refuses it.  The
happy path is only asserted where it is needed to prove a guard is not simply
always-on (a guard that refuses everything is not a guard, it is an outage).

All embeddings come from :class:`FakeEmbeddingBackend`, a deterministic pure
function of (weights label, text).  No network, no Ollama.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from daedalus.memory.embeddings import (
    IDENTITY_DRIFT_TOLERANCE,
    AgentEvent,
    EmbeddingSpec,
    EmbeddingUnavailableError,
    EventVectorStore,
    JournalPosition,
    _cosine,
)


class FakeEmbeddingBackend:
    """Deterministic embeddings: a pure function of (weights, text).

    ``weights`` stands in for the actual model behind a tag.  Two backends with
    the same ``weights`` are the same coordinate system; two with different
    ``weights`` are different coordinate systems while being indistinguishable
    from their declared ``(provider, model)`` identity - which is exactly the
    situation ``model_revision`` is supposed to cover and cannot.
    """

    def __init__(
        self,
        *,
        weights: str = "v1",
        dimension: int = 8,
        provider: str = "ollama",
        scale: float = 1.0,
    ):
        self.provider = provider
        self.weights = weights
        self.dimension = dimension
        self.scale = scale
        self.calls: list[tuple[list[str], str, int | None]] = []

    def embed(self, texts, *, model, dimensions=None):
        self.calls.append((list(texts), model, dimensions))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(
                f"{self.weights}\0{text}\0{counter}".encode("utf-8")
            ).digest()
            for byte in digest:
                values.append(((byte - 127.5) / 127.5) * self.scale)
                if len(values) == self.dimension:
                    break
            counter += 1
        return values


class NudgedBackend(FakeEmbeddingBackend):
    """Same weights, but perturbed by ``epsilon`` on the first component.

    Used to prove the drift tolerance is not so tight that ordinary service
    nondeterminism trips it.
    """

    def __init__(self, *, epsilon: float, **kwargs):
        super().__init__(**kwargs)
        self.epsilon = epsilon

    def _vector(self, text: str) -> list[float]:
        values = super()._vector(text)
        values[0] += self.epsilon
        return values


class UnavailableBackend:
    provider = "ollama"

    def embed(self, texts, *, model, dimensions=None):
        raise EmbeddingUnavailableError("offline")


def _event(event_id: str, content: str) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        event_type="message",
        content=content,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _ingest(store: EventVectorStore, *events: AgentEvent, model: str = "nomic-embed-text"):
    return store.ingest_events_report(list(events), model=model)


# ---------------------------------------------------------------------------
# The coordinate-system claim
# ---------------------------------------------------------------------------


def test_moved_model_tag_without_revision_is_refused_not_silently_mixed(tmp_path: Path):
    """The exact case ``model_revision`` exists for, with no revision supplied.

    Before the identity anchor this produced one index_id, two coordinate
    systems, and a ``ready`` search that ranked them against each other.
    """

    db = tmp_path / "vectors.db"
    before = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v1"))
    first = _ingest(before, _event("old-1", "written before the pull"))
    assert first.status.code == "ready"
    assert first.projected == 1
    assert first.spec is not None
    index_id = first.spec.index_id
    before.close()

    # `ollama pull nomic-embed-text` moves the tag onto different weights.
    after = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v2"))

    drifted = _ingest(after, _event("new-1", "written after the pull"))
    assert drifted.status.code == "model_drift"
    assert drifted.status.available is False
    assert drifted.projected == 0
    assert drifted.status.index_id == index_id
    assert "no longer reproduces" in drifted.status.message

    # The refusal happened before any write: the drifted vector is not in the
    # index, so nothing can compare it against the v1 vectors later.
    assert after._projection_count(index_id) == 1
    assert (
        after._conn.execute(
            "SELECT COUNT(*) FROM projection_sources WHERE event_id = 'new-1'"
        ).fetchone()[0]
        == 0
    )

    searched = after.search_report("anything", model="nomic-embed-text")
    assert searched.status.code == "model_drift"
    assert searched.status.available is False
    assert searched.matches == []
    after.close()


def test_pinned_revision_does_not_stop_a_second_host_but_the_binding_does(tmp_path: Path):
    """``host`` is not part of the spec; two hosts share one ``index_id``.

    That collision is still real -- putting the endpoint into
    :class:`EmbeddingSpec` would change every shipped ``index_id`` -- so the
    endpoint is bound at the index row instead.  Assert all three halves: the
    declared identity really does collide, the binding really does refuse, and
    the refusal is ``host_drift`` rather than ``model_drift``, because it is
    taken BEFORE the anchor is consulted.  Ordering is the point:
    :func:`test_a_byte_identical_mirror_is_still_a_second_host` covers the case
    the anchor provably cannot see.
    """

    db = tmp_path / "vectors.db"
    spec = EmbeddingSpec(
        provider="ollama",
        model="embeddinggemma:latest",
        model_revision="sha256:pinned-and-identical",
        dimension=8,
    )

    gpu = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="gpu-box"))
    written = gpu.ingest_events_report(
        [_event("from-gpu", "indexed on the gpu box")],
        spec=spec,
        host="http://gpu-box:11434",
    )
    assert written.projected == 1
    gpu.close()

    laptop = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="laptop"))
    report = laptop.ingest_events_report(
        [_event("from-laptop", "indexed on the laptop")],
        spec=spec,
        host="http://laptop:11434",
    )

    # The pinned revision did NOT partition these: same declared identity.
    assert report.status.index_id == spec.index_id
    # The endpoint binding did.
    assert report.status.code == "host_drift"
    assert "gpu-box" in report.status.message
    assert "laptop" in report.status.message
    assert report.projected == 0
    assert laptop._projection_count(spec.index_id) == 1
    assert laptop.index_status(spec).egress_host == "http://gpu-box:11434", (
        "a refused endpoint must not repoint the binding it was refused against"
    )
    laptop.close()


def test_a_byte_identical_mirror_is_still_a_second_host(tmp_path: Path):
    """The case the identity anchor cannot catch, and the binding must.

    Two machines serving the SAME weights reproduce each other's vectors
    exactly, so the anchor -- which asks "does this backend still produce our
    numbers" -- returns a clean pass.  It is nevertheless a different place for
    repository content to be sent, which is a question about a destination and
    not about arithmetic.  Before the endpoint was bound to the index, this
    ingest succeeded silently.
    """

    db = tmp_path / "vectors.db"
    spec = EmbeddingSpec(
        provider="ollama",
        model="embeddinggemma:latest",
        model_revision="sha256:pinned-and-identical",
        dimension=8,
    )

    first = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="same"))
    assert first.ingest_events_report(
        [_event("from-first", "indexed on the first box")],
        spec=spec,
        host="http://box-a:11434",
    ).projected == 1
    first.close()

    mirror = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="same"))
    report = mirror.ingest_events_report(
        [_event("from-mirror", "indexed on the mirror")],
        spec=spec,
        host="http://box-b:11434",
    )

    assert report.status.code == "host_drift"
    assert report.projected == 0
    # The anchor would have said yes: same weights, same vectors.
    assert mirror._verify_identity(
        spec,
        FakeEmbeddingBackend(weights="same"),
        endpoint="http://box-a:11434",
        force=True,
    ) is None
    mirror.close()


def test_two_specs_never_share_a_search(tmp_path: Path):
    """Distinct specs must partition, and a search must not fall back."""

    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v1"))
    left = _ingest(store, _event("left", "alpha content"), model="model-a")
    right = _ingest(store, _event("right", "beta content"), model="model-b")
    assert left.spec is not None and right.spec is not None
    assert left.spec.index_id != right.spec.index_id

    a_hits = store.search_report("alpha", model="model-a", limit=50)
    b_hits = store.search_report("alpha", model="model-b", limit=50)

    assert a_hits.status.code == "ready"
    assert [event.event_id for event, _ in a_hits.matches] == ["left"]
    assert b_hits.status.code == "ready"
    assert [event.event_id for event, _ in b_hits.matches] == ["right"]

    # A spec that was never written must refuse, not degrade to another index.
    unknown = store.search_report("alpha", model="model-c", limit=50)
    assert unknown.status.code == "index_unavailable"
    assert unknown.status.available is False
    assert unknown.matches == []
    store.close()


@pytest.mark.parametrize(
    "field, value",
    [
        ("provider", "openai"),
        ("dimension", 4),
        ("projector_version", "agent-event-v99"),
    ],
)
def test_a_spec_that_lies_about_the_request_is_refused(field: str, value):
    """A caller cannot label vectors with an identity they were not made under.

    Only these three spec fields are independently checkable: ``provider`` is
    compared against the live backend, ``dimension`` against the vectors the
    backend actually returned, and ``projector_version`` against the projector
    that built the text.  See
    :func:`test_spec_overrides_loose_kwargs_rather_than_cross_checking_them`
    for why the remaining fields cannot disagree.
    """

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend(dimension=8))
    honest = {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "dimension": 8,
        "normalization": "l2",
        "projector_version": "agent-event-v1",
        "model_revision": None,
    }
    lying = EmbeddingSpec(**{**honest, field: value})

    report = store.ingest_events_report(
        [_event("e", "content")],
        spec=lying,
        model="nomic-embed-text",
    )

    assert report.projected == 0
    assert report.status.available is False
    assert (
        store._conn.execute("SELECT COUNT(*) FROM event_projections").fetchone()[0] == 0
    )
    store.close()


def test_spec_overrides_loose_kwargs_rather_than_cross_checking_them():
    """``spec`` is the authority; ``model``/``normalization``/``model_revision``
    kwargs are ignored when it is supplied.

    This is pinned deliberately.  The alternative reading - that the two are
    cross-checked - is what the ``_resolved_spec`` guards for those fields look
    like, but they are unreachable from the public API because the spec is
    copied over the kwargs first.  If anyone ever removes that copy, the kwargs
    would silently decide what gets embedded while the spec decides how the
    vectors are labelled: the exact mislabelling this index exists to prevent.
    """

    backend = FakeEmbeddingBackend(dimension=8)
    store = EventVectorStore(":memory:", backend=backend)
    spec = EmbeddingSpec(
        provider="ollama",
        model="the-spec-model",
        dimension=8,
        normalization="l2",
        model_revision="sha256:from-the-spec",
    )

    report = store.ingest_events_report(
        [_event("e", "content")],
        spec=spec,
        model="the-ignored-kwarg-model",
        normalization="none",
        model_revision="sha256:from-the-kwarg",
    )

    assert report.status.code == "ready"
    assert report.spec == spec
    # What was actually sent to the backend is the SPEC's model, so the label
    # and the vectors agree.
    assert [model for _texts, model, _dims in backend.calls] == ["the-spec-model"]
    stored = store._conn.execute(
        "SELECT model, model_revision, normalization FROM embedding_indexes"
    ).fetchone()
    assert stored["model"] == "the-spec-model"
    assert stored["model_revision"] == "sha256:from-the-spec"
    assert stored["normalization"] == "l2"
    store.close()


def test_identity_anchor_tolerates_ordinary_service_jitter():
    """The guard must not be a permanent outage: sub-tolerance noise passes."""

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend(weights="v1"))
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.close()

    jittered = EventVectorStore(":memory:", backend=NudgedBackend(epsilon=1e-7))
    # Rebuild the same state under the jittered backend to get an anchor, then
    # force a re-verification against it.
    _ingest(jittered, _event("e", "content"))
    assert jittered.verify_index_identity(spec).code == "ready"

    # And a pure rescale is explicitly NOT drift, because search is cosine.
    jittered._identity_verified.clear()
    jittered._backend_override = FakeEmbeddingBackend(weights="v1", scale=7.5)
    assert jittered.verify_index_identity(spec).code == "ready"
    jittered.close()


def test_drift_is_detected_across_a_reopen_not_just_within_one_process(tmp_path: Path):
    """The per-process verification cache must not become a bypass."""

    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v1"))
    report = _ingest(store, _event("e", "content"))
    assert report.spec is not None
    spec = report.spec
    # Within this process the index is already reconciled.
    assert spec.index_id in store._identity_verified
    store.close()

    for _ in range(3):
        reopened = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v2"))
        assert spec.index_id not in reopened._identity_verified
        assert reopened.search_report("q", spec=spec).status.code == "model_drift"
        reopened.close()


def test_anchor_provenance_marks_retrofitted_indexes_as_trust_on_first_use(
    tmp_path: Path,
):
    """A pre-anchor database gets an ADOPTED anchor, and says so."""

    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend(weights="v1"))
    report = _ingest(store, _event("e", "content"))
    assert report.spec is not None
    spec = report.spec
    assert store.anchor_provenance(spec) == "created"
    assert store.index_status(spec).identity_anchor == "created"

    # Simulate a database written before identity anchors existed.
    store._conn.execute("DELETE FROM index_identity_anchors")
    store._conn.commit()
    store._identity_verified.clear()
    assert store.anchor_provenance(spec) == "missing"

    # Drift that already happened is now invisible - the adopted anchor is
    # taken from whatever weights are live at adoption time.
    store._backend_override = FakeEmbeddingBackend(weights="v2")
    adopted = _ingest(store, _event("e2", "second content"))
    assert adopted.status.code == "ready"
    assert store.anchor_provenance(spec) == "adopted"

    status = store.index_status(spec)
    assert status.identity_anchor == "adopted"
    assert "identity anchor adopted" in status.status.message
    store.close()


def test_unpinned_movable_tag_is_reported_as_unpinned():
    unpinned = EmbeddingSpec(provider="ollama", model="nomic-embed-text", dimension=8)
    pinned = EmbeddingSpec(
        provider="ollama",
        model="nomic-embed-text",
        dimension=8,
        model_revision="sha256:abc",
    )
    immutable_provider = EmbeddingSpec(
        provider="openai", model="text-embedding-3-small", dimension=8
    )

    assert unpinned.pins_model_revision is False
    assert pinned.pins_model_revision is True
    assert immutable_provider.pins_model_revision is True

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend(dimension=8))
    _ingest(store, _event("e", "content"))
    status = store.index_status(unpinned)
    assert status.revision_pinned is False
    assert "model_revision unpinned" in status.status.message
    store.close()


# ---------------------------------------------------------------------------
# Dimension handling
# ---------------------------------------------------------------------------


def test_mixed_width_vectors_in_one_index_are_refused_not_broadcast(tmp_path: Path):
    """A short vector must not be zero-padded or zip-truncated into a score."""

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend(dimension=8))
    written = _ingest(store, _event("good", "well formed"))
    assert written.spec is not None
    spec = written.spec

    store._conn.execute(
        """
        INSERT INTO projection_sources (
            source_hash, event_id, event_type, content, timestamp,
            metadata_json, created_at
        ) VALUES ('src:narrow', 'narrow', 'message', 'narrow', 't', '{}', 't')
        """
    )
    store._conn.execute(
        """
        INSERT INTO event_projections (
            projection_id, index_id, source_hash, projection_text,
            embedding, created_at
        ) VALUES ('prj:narrow', ?, 'src:narrow', 'narrow', ?, 't')
        """,
        (spec.index_id, struct.pack("<3f", 1.0, 0.0, 0.0)),
    )
    store._conn.commit()

    report = store.search_report("q", spec=spec, limit=50)

    assert report.status.code == "invalid_index"
    assert report.status.available is False
    assert report.matches == []
    assert "dimension" in report.status.message
    store.close()


def test_cosine_refuses_mismatched_widths_directly():
    with pytest.raises(ValueError, match="dimension mismatch"):
        _cosine([1.0, 0.0, 0.0], [1.0, 0.0])


def test_backend_that_changes_output_width_under_one_spec_is_refused(tmp_path: Path):
    """A model swapped for one with a different width must not create a
    second, incompatible population inside the same declared identity."""

    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend(dimension=8))
    written = _ingest(store, _event("wide", "content"))
    assert written.spec is not None
    store.close()

    narrowed = EventVectorStore(db, backend=FakeEmbeddingBackend(dimension=4))
    report = narrowed.ingest_events_report(
        [_event("narrow", "content")],
        spec=written.spec,
    )

    assert report.projected == 0
    assert report.status.available is False
    assert narrowed._projection_count(written.spec.index_id) == 1
    narrowed.close()


def test_dangling_identity_anchor_is_reported_as_a_corrupt_index(tmp_path: Path):
    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec

    store._conn.execute("PRAGMA foreign_keys = OFF")
    store._conn.execute(
        "UPDATE index_identity_anchors SET projection_id = 'prj:gone' WHERE index_id = ?",
        (spec.index_id,),
    )
    store._conn.commit()
    store._identity_verified.clear()

    report = store.search_report("q", spec=spec)
    assert report.status.code == "invalid_index"
    assert report.status.available is False
    assert report.matches == []
    store.close()


# ---------------------------------------------------------------------------
# Staleness relative to the authoritative journal
# ---------------------------------------------------------------------------


def test_search_without_a_journal_position_reports_unanchored_never_fresh():
    """The default answer to "is this index current?" must be "unknown"."""

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    _ingest(store, _event("e", "content"))

    report = store.search_report("q", model="nomic-embed-text")

    assert report.status.code == "ready"
    assert report.freshness == "unanchored"
    assert report.freshness != "fresh"
    assert store.index_status(
        EmbeddingSpec(provider="ollama", model="nomic-embed-text", dimension=8)
    ).freshness == "unanchored"
    store.close()


def test_search_over_a_stale_index_says_so_instead_of_ready():
    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.record_journal_watermark(spec, JournalPosition("events.local.jsonl", 12))

    stale = store.search_report(
        "q",
        spec=spec,
        journal=JournalPosition("events.local.jsonl", 9001),
        limit=50,
    )

    assert stale.status.code == "stale"
    assert stale.status.code != "ready"
    assert stale.freshness == "stale"
    # Results are valid, just incomplete - so they are still returned.
    assert [event.event_id for event, _ in stale.matches] == ["e"]
    assert "8989" in stale.status.message

    fresh = store.search_report(
        "q",
        spec=spec,
        journal=JournalPosition("events.local.jsonl", 12),
        limit=50,
    )
    assert fresh.status.code == "ready"
    assert fresh.freshness == "fresh"
    store.close()


def test_watermark_refuses_to_move_backwards():
    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.record_journal_watermark(spec, JournalPosition("journal", 500))

    with pytest.raises(ValueError, match="must not move backwards"):
        store.record_journal_watermark(spec, JournalPosition("journal", 499))

    assert store.journal_watermark(spec, "journal") == JournalPosition("journal", 500)
    store.record_journal_watermark(spec, JournalPosition("journal", 501))
    assert store.journal_watermark(spec, "journal").position == 501
    store.close()


def test_watermark_refuses_a_rewritten_journal_at_an_unchanged_position():
    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.record_journal_watermark(spec, JournalPosition("journal", 10, "sha256:aaa"))

    with pytest.raises(ValueError, match="not append-only"):
        store.record_journal_watermark(
            spec, JournalPosition("journal", 10, "sha256:bbb")
        )
    store.close()


@pytest.mark.parametrize(
    "observed, expected",
    [
        (JournalPosition("journal", 4, "sha256:aaa"), "journal_forked"),
        (JournalPosition("journal", 10, "sha256:zzz"), "journal_forked"),
    ],
)
def test_search_refuses_when_the_journal_forked_under_the_index(observed, expected):
    """Index ahead of the journal, or a different journal at the same position."""

    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.record_journal_watermark(spec, JournalPosition("journal", 10, "sha256:aaa"))

    assert store.journal_freshness(spec, observed).code == expected

    report = store.search_report("q", spec=spec, journal=observed, limit=50)
    assert report.status.code == expected
    assert report.status.available is False
    assert report.matches == []
    assert report.freshness == "forked"
    store.close()


def test_unknown_journal_id_is_unanchored_not_fresh():
    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    spec = written.spec
    store.record_journal_watermark(spec, JournalPosition("journal-a", 10))

    status = store.journal_freshness(spec, JournalPosition("journal-b", 10))

    assert status.code == "unanchored"
    assert store.search_report(
        "q", spec=spec, journal=JournalPosition("journal-b", 10)
    ).freshness == "unanchored"
    store.close()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"journal_id": "  ", "position": 1}, "journal_id must not be empty"),
        ({"journal_id": "j", "position": -1}, "must not be negative"),
        ({"journal_id": "j", "position": 1.5}, "must be an integer"),
        ({"journal_id": "j", "position": True}, "must be an integer"),
    ],
)
def test_journal_position_rejects_nonsense(kwargs, message):
    with pytest.raises(ValueError, match=message):
        JournalPosition(**kwargs)


# ---------------------------------------------------------------------------
# Failure states stay distinguishable
# ---------------------------------------------------------------------------


def test_an_offline_backend_is_not_reported_as_drift(tmp_path: Path):
    """An unreachable embedder must never be mistaken for a changed model."""

    db = tmp_path / "vectors.db"
    store = EventVectorStore(db, backend=FakeEmbeddingBackend())
    written = _ingest(store, _event("e", "content"))
    assert written.spec is not None
    store.close()

    offline = EventVectorStore(db, backend=UnavailableBackend())
    report = offline.search_report("q", spec=written.spec)

    assert report.status.code == "embedder_unavailable"
    assert report.status.code != "model_drift"
    assert report.status.available is False
    offline.close()


def test_verify_index_identity_reports_an_unanchored_index_explicitly():
    store = EventVectorStore(":memory:", backend=FakeEmbeddingBackend())
    spec = EmbeddingSpec(provider="ollama", model="nomic-embed-text", dimension=8)

    status = store.verify_index_identity(spec)

    assert status.code == "unanchored"
    assert "cannot be detected" in status.message
    store.close()
