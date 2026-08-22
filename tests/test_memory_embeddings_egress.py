"""The embedding transport's outbound POST, and what decides it.

Written for the two evidenced openings the codex round-2 security seat named:

* ``daedalus/memory/embeddings.py`` POSTed to a CALLER-SELECTED host through a
  raw ``urllib`` request with no egress decision anywhere above it, and
* the host was absent from index identity, so a first write through the wrong
  endpoint silently defined the coordinate system every later write joined.

The instrument for the first is ``socket.socket.connect`` itself.  Asserting
that a mocked ``urlopen`` was not called would only prove that *this* transport
did not run; asserting that no socket connected proves that no bytes left the
process by any route the standard library offers.  The spy raises rather than
merely counting, so a regression cannot quietly open a real connection to a
real host while the test is deciding what to assert.
"""
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from daedalus.memory.embeddings import (
    AgentEvent,
    EmbeddingEgressRefused,
    EmbeddingSpec,
    EventVectorStore,
    OllamaEmbeddingBackend,
    _authorize_egress,
    index_identity,
)
from daedalus.providers.ollama import REMOTE_CONSENT_VAR
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Effect, Wiring

#: Off-machine. ``lane_for_host`` calls this ``untrusted`` and, without
#: exact-endpoint consent, the boundary refuses it.
REMOTE = "http://10.0.0.5:11434"
OTHER_REMOTE = "http://10.0.0.6:11434"
#: Two distinct loopback endpoints. Both are admitted by the egress decision,
#: which is what makes them the right probe for the *binding* tests: they
#: isolate "is this index bound to another host" from "may bytes go there".
HOST_A = "http://127.0.0.1:11434"
HOST_B = "http://127.0.0.2:11434"


@pytest.fixture
def refuse_all_connects(monkeypatch):
    """Make any real connection attempt loud, and record the attempts."""

    attempts: list[object] = []

    def spy(self, address):  # noqa: ANN001 - stdlib signature
        attempts.append(address)
        raise AssertionError(
            f"a socket connect reached {address!r}; the egress decision was "
            f"supposed to happen before this"
        )

    monkeypatch.setattr(socket.socket, "connect", spy)
    return attempts


@pytest.fixture(autouse=True)
def no_ambient_consent(monkeypatch):
    """The operator has not declared any remote endpoint unless a test says so."""

    monkeypatch.delenv(REMOTE_CONSENT_VAR, raising=False)


class ConstantBackend:
    """A backend seam that performs no egress and no arithmetic surprises."""

    provider = "ollama"

    def __init__(self, vector=(1.0, 0.0)):
        self.vector = list(vector)
        self.calls: list[list[str]] = []

    def embed(self, texts, *, model, dimensions=None):
        self.calls.append(list(texts))
        return [list(self.vector) for _ in texts]


# --------------------------------------------------------------------------- #
# 1. the decision happens above the socket                                     #
# --------------------------------------------------------------------------- #
def test_disallowed_host_is_refused_before_any_socket_connect(refuse_all_connects):
    backend = OllamaEmbeddingBackend(REMOTE)

    with pytest.raises(EmbeddingEgressRefused):
        backend.embed(["[action] listed directory"], model="nomic-embed-text")

    assert refuse_all_connects == [], (
        "the transport opened a socket to a host the egress policy refuses"
    )


def test_deny_receipt_names_the_host_and_the_contract(refuse_all_connects):
    backend = OllamaEmbeddingBackend(REMOTE)

    with pytest.raises(EmbeddingEgressRefused) as raised:
        backend.embed(["[action] listed directory"], model="nomic-embed-text")

    receipt = raised.value.receipt
    assert receipt["verdict"] == "deny"
    assert receipt["host"] == REMOTE, (
        "a refusal whose host a reader cannot see is a refusal nobody can fix"
    )
    assert receipt["lane"] == "untrusted"
    assert receipt["contract"] == "provider.egress_policy"
    assert receipt["entrypoint_id"] == "memory.embeddings"
    assert receipt["connected"] is False
    assert receipt["security_boundary_claimed"] is False
    assert REMOTE in receipt["evidence"]
    assert REMOTE_CONSENT_VAR in receipt["evidence"]
    assert len(receipt["receipt_sha256"]) == 64
    assert len(receipt["registry_sha256"]) == 64
    # the instance keeps the same receipt, so an operator can inspect the
    # refusal without catching the exception
    assert backend.last_egress_receipt is receipt
    assert refuse_all_connects == []


def test_loopback_host_starts_at_the_canonical_boundary():
    receipt = _authorize_egress(HOST_A)

    assert receipt.entrypoint_id == "memory.embeddings"
    assert receipt.requested_effects == (Effect.NETWORK_EGRESS.value,)
    decisions = {row.contract: row for row in receipt.guard_decisions}
    assert decisions["provider.egress_policy"].allowed is True
    assert "trusted" in decisions["provider.egress_policy"].evidence


def test_consent_admits_the_named_endpoint_and_only_that_one(monkeypatch):
    monkeypatch.setenv(REMOTE_CONSENT_VAR, REMOTE)

    receipt = _authorize_egress(REMOTE)
    assert receipt.entrypoint_id == "memory.embeddings"

    # Consent is bound to ONE endpoint. Repointing the host revokes it.
    with pytest.raises(EmbeddingEgressRefused) as raised:
        _authorize_egress(OTHER_REMOTE)
    assert raised.value.receipt["host"] == OTHER_REMOTE


def test_the_guard_is_the_first_statement_in_the_transport():
    """A source-order check, because ordering is the whole property here.

    The runtime tests above go red if the guard is deleted.  This one goes red
    if the guard is merely *moved* below the request construction, which is a
    change no assertion about the refusal path can see.
    """
    source = Path(
        EventVectorStore.__module__.replace(".", "/") + ".py"
    )
    module = ast.parse(
        (Path(__file__).resolve().parents[1] / source).read_text(encoding="utf-8")
    )
    embed = next(
        node
        for cls in module.body
        if isinstance(cls, ast.ClassDef) and cls.name == "OllamaEmbeddingBackend"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "embed"
    )
    called: list[tuple[int, str]] = []
    for node in ast.walk(embed):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            called.append((node.lineno, name))
    guard_line = min(line for line, name in called if name == "_authorize_egress")
    urlopen_line = min(line for line, name in called if name == "urlopen")
    assert guard_line < urlopen_line, (
        "the egress decision must precede the request, not follow it"
    )


# --------------------------------------------------------------------------- #
# 2. the endpoint is part of index identity                                    #
# --------------------------------------------------------------------------- #
def test_a_second_endpoint_is_rejected_before_anything_is_persisted(tmp_path):
    """Init through host A, reopen through host B, same dims: refused.

    This is the trust-on-first-use hole in the module docstring made
    unreachable.  Both hosts are loopback, so the egress decision admits both
    and the only thing that can refuse the second one is the binding.
    """

    db = tmp_path / "projections.sqlite3"
    spec = EmbeddingSpec(model="nomic-embed-text", dimension=2)
    backend = ConstantBackend()

    store = EventVectorStore(db, backend=backend)
    first = store.ingest_events_report(
        [AgentEvent(event_id="e1", event_type="action", content="Listed directory")],
        host=HOST_A,
        spec=spec,
    )
    assert first.status.code == "ready"
    assert first.projected == 1
    bound = store.index_status(spec)
    assert bound.egress_host == HOST_A
    assert bound.egress_host_provenance == "created"
    assert bound.identity_id == index_identity(spec, HOST_A)
    store.close()

    reopened = EventVectorStore(db, backend=backend)
    calls_before = len(backend.calls)
    second = reopened.ingest_events_report(
        [AgentEvent(event_id="e2", event_type="action", content="Read file")],
        host=HOST_B,
        spec=spec,
    )

    assert second.status.code == "host_drift"
    assert second.status.available is False
    assert HOST_A in second.status.message
    assert HOST_B in second.status.message
    assert second.projected == 0
    assert len(backend.calls) == calls_before, (
        "the refusal must land before the projection text is embedded anywhere"
    )
    assert reopened.index_status(spec).projection_count == 1, (
        "a refused endpoint wrote into the index anyway"
    )
    assert reopened.index_status(spec).egress_host == HOST_A, (
        "the refused endpoint overwrote the binding it was refused against"
    )

    # Reading is refused on the same grounds, and before the query is sent.
    search = reopened.search_report("List dir", host=HOST_B, spec=spec)
    assert search.status.code == "host_drift"
    assert search.matches == []
    reopened.close()


def test_the_bound_endpoint_survives_a_reopen_and_still_admits_itself(tmp_path):
    db = tmp_path / "projections.sqlite3"
    spec = EmbeddingSpec(model="nomic-embed-text", dimension=2)
    backend = ConstantBackend()

    store = EventVectorStore(db, backend=backend)
    store.ingest_events_report(
        [AgentEvent(event_id="e1", event_type="action", content="Listed directory")],
        host=HOST_A,
        spec=spec,
    )
    store.close()

    reopened = EventVectorStore(db, backend=backend)
    again = reopened.ingest_events_report(
        [AgentEvent(event_id="e2", event_type="action", content="Read file")],
        host=HOST_A,
        spec=spec,
    )
    assert again.status.code == "ready"
    assert reopened.index_status(spec).projection_count == 2
    reopened.close()


def test_a_pre_binding_database_adopts_one_endpoint_and_says_so(tmp_path):
    """The one remaining TOFU window is reported, not hidden."""

    db = tmp_path / "projections.sqlite3"
    spec = EmbeddingSpec(model="nomic-embed-text", dimension=2)
    backend = ConstantBackend()

    store = EventVectorStore(db, backend=backend)
    store.ingest_events_report(
        [AgentEvent(event_id="e1", event_type="action", content="Listed directory")],
        host=HOST_A,
        spec=spec,
    )
    # Simulate a database written before the endpoint column existed.
    with store._conn:
        store._conn.execute(
            "UPDATE embedding_indexes SET egress_host = NULL, "
            "egress_host_provenance = NULL"
        )
    store.close()

    reopened = EventVectorStore(db, backend=backend)
    adopted = reopened.ingest_events_report(
        [AgentEvent(event_id="e2", event_type="action", content="Read file")],
        host=HOST_B,
        spec=spec,
    )
    assert adopted.status.code == "ready", (
        "an unbound legacy index must still be usable; it just cannot claim "
        "to know which endpoint wrote it"
    )
    status = reopened.index_status(spec)
    assert status.egress_host == HOST_B
    assert status.egress_host_provenance == "adopted"
    assert "endpoint binding adopted" in status.status.message
    reopened.close()


def test_index_identity_folds_the_endpoint_in_while_index_id_does_not():
    spec = EmbeddingSpec(model="nomic-embed-text", dimension=2)

    assert index_identity(spec, HOST_A) != index_identity(spec, REMOTE), (
        "two endpoints serving one tag are two coordinate systems"
    )
    assert index_identity(spec, HOST_A + "/") == index_identity(spec, HOST_A)
    # index_id deliberately does NOT move: changing it would orphan every
    # shipped index. The binding, not the hash, is the enforcement.
    assert spec.index_id == EmbeddingSpec(**spec.to_dict()).index_id


# --------------------------------------------------------------------------- #
# 3. the registry row is the thing that cannot rot silently                    #
# --------------------------------------------------------------------------- #
def test_registry_row_pins_both_halves_of_the_guard():
    row = REGISTRY_BY_ID["memory.embeddings"]

    assert row.wiring is Wiring.CENTRAL
    assert row.effects == (Effect.NETWORK_EGRESS,)
    assert row.guard_contracts == ("provider.egress_policy",)
    anchors = {(anchor.target, anchor.call) for anchor in row.anchors}
    assert (
        "daedalus.memory.embeddings:OllamaEmbeddingBackend.embed",
        "_authorize_egress",
    ) in anchors, "the transport must be pinned to calling the guard"
    assert (
        "daedalus.memory.embeddings:_authorize_egress",
        "begin_effect",
    ) in anchors, "the guard must be pinned to starting at the boundary"
