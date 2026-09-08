"""Receipt publication contracts using the real content-addressed store.

The small bodies here exercise the public receipt projection only. They are
not evidence of a mission, evaluator run, or independently verified packet.
The real-door tests in test_ignition_gate1 own those claims.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from daedalus.atomic import write_bytes_atomic
from daedalus.ignition import checks as ignition_checks
from daedalus.ignition import gate1
from daedalus.storage import ArtifactLocator, ArtifactStore, ArtifactStoreError


_MISSING = object()
_MISSION = "mission-gate1-voltage-ignition"
_SCHEMA = "daedalus-gate1-ignition-receipt/1"
_NONPASSING_STATUSES = [
    pytest.param(_MISSING, id="missing"),
    pytest.param(None, id="null"),
    pytest.param("unknown", id="unknown"),
    pytest.param("failed", id="failed"),
    pytest.param("inconclusive", id="inconclusive"),
]


def _receipt(*, status="passed", cost=1.0):
    packet = {"packet_sha256": "d" * 64}
    if status is not _MISSING:
        packet["evaluation_status"] = status
    return {
        "schema": _SCHEMA,
        "mission_id": _MISSION,
        "work_item_ids": ["wi-000-aaaaaaaaaaaa", "wi-001-bbbbbbbbbbbb"],
        "mission_sha256": "c" * 64,
        "collected_at": "2026-09-06T00:00:00Z",
        "blockers": [],
        "execution_blockers": [],
        "evidence_packet": packet,
        "checks": {"pytest": {"report_sha256": "e" * 64}},
        "fourfold": {"graph_delta_sha256": "f" * 64},
        "evaluator_bundle": {"digest": "1" * 64},
        "discrimination": {
            "before_state": {
                "conformance_test_sha256": ignition_checks.CONFORMANCE_TEST_SHA256
            }
        },
        "replay": {
            "base_revision": "a" * 40,
            "candidate_revision": "b" * 64,
            "fixture_tree_sha256": "9" * 64,
        },
        "cost": {"wall_clock_s": cost},
    }


def _noncanonical_bytes(body):
    # Deliberately distinguish retained raw bytes from a JSON reconstruction.
    return ("  " + json.dumps(body, indent=1) + "\r\n \r\n").encode("utf-8")


def _legacy_bytes():
    body = _receipt(status=_MISSING)
    body.pop("schema")
    body.pop("execution_blockers")
    return _noncanonical_bytes(body)


def _seed_latest(receipts: Path, raw: bytes) -> Path:
    path = receipts / _MISSION / "receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _store(receipts: Path) -> ArtifactStore:
    return ArtifactStore(receipts / _MISSION / "store")


def _resolve_previous(receipts, body, expected_bytes):
    reference = body["replay"]["previous_receipt"]
    assert set(reference) == {"sha256", "locator"}
    assert reference["sha256"] == hashlib.sha256(expected_bytes).hexdigest()
    summary = reference["locator"]
    store = _store(receipts)
    locator = store.load_locator(summary["locator_uri"].rsplit(":", 1)[-1])
    assert summary == locator.portable_summary()
    assert "local_paths" not in summary
    assert locator.artifact_sha256 == reference["sha256"]
    assert store.verify(locator) == locator
    assert store.get_bytes(locator.uri) == expected_bytes
    return locator


@pytest.fixture
def actual_puts(monkeypatch):
    """Observe actual return values without replacing storage or its checks."""
    observed: list[tuple[Path, bytes, ArtifactLocator]] = []
    real_put = ArtifactStore.put_bytes

    def observe(store, data, **kwargs):
        locator = real_put(store, data, **kwargs)
        observed.append((store.root, bytes(data), locator))
        return locator

    monkeypatch.setattr(ArtifactStore, "put_bytes", observe)
    return observed


def _published_locator(receipts, path, body, actual_puts):
    published = path.read_bytes()
    assert json.loads(published) == body
    store = _store(receipts)
    matches = [
        locator
        for root, data, locator in actual_puts
        if root == store.root and data == published
    ]
    assert matches, "final receipt bytes must reach the actual ArtifactStore"
    for locator in matches:
        assert store.verify(locator) == locator
        assert store.get_bytes(locator.uri) == published
        # Neither payload identity nor manifest identity can be embedded into
        # the exact current payload that they are supposed to identify.
        assert locator.artifact_sha256.encode("ascii") not in published
        assert locator.locator_uri.encode("ascii") not in published
    return matches[-1], published


@pytest.mark.parametrize(
    "prior_bytes",
    [
        pytest.param(b'{"broken":\r\n', id="malformed-json"),
        pytest.param(b"\xffbad receipt\r\n", id="malformed-utf8"),
        pytest.param(b'[1, "legacy"]\r\n', id="nonobject-json"),
        pytest.param(_legacy_bytes(), id="legacy-object"),
    ],
)
def test_exact_predecessor_bytes_are_retained_without_replay_authority(
    tmp_path, actual_puts, prior_bytes
):
    receipts = tmp_path / "receipts"
    _seed_latest(receipts, prior_bytes)

    path, body = gate1.write_receipt(_receipt(), receipts)

    _resolve_previous(receipts, body, prior_bytes)
    _published_locator(receipts, path, body, actual_puts)
    assert body["replay"]["previous_run_complete"] is False
    assert body["replay"]["replay_demonstrated"] is False
    assert body["blockers"]


def test_first_receipt_is_stored_as_published_without_a_self_locator(
    tmp_path, actual_puts
):
    receipts = tmp_path / "receipts"

    path, body = gate1.write_receipt(_receipt(), receipts)

    _published_locator(receipts, path, body, actual_puts)
    assert "previous_receipt" not in body["replay"]
    assert body["replay"]["is_replay"] is False
    assert body["replay"]["replay_demonstrated"] is False


def test_identical_finalized_payload_is_idempotent_and_changed_receipt_is_distinct(
    tmp_path, actual_puts
):
    receipts = tmp_path / "receipts"
    path, body = gate1.write_receipt(_receipt(), receipts)
    first, first_bytes = _published_locator(receipts, path, body, actual_puts)
    store = _store(receipts)
    before = {
        path.relative_to(store.root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in store.root.rglob("*")
        if path.is_file()
    }

    repeated = store.put_bytes(
        first_bytes,
        expected_sha256=first.artifact_sha256,
        media_type=first.to_dict()["media_type"],
        metadata=first.metadata,
        provenance=first.provenance,
    )

    assert repeated == first
    assert {
        path.relative_to(store.root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in store.root.rglob("*")
        if path.is_file()
    } == before
    path, changed_body = gate1.write_receipt(_receipt(cost=2.0), receipts)
    changed, changed_bytes = _published_locator(
        receipts, path, changed_body, actual_puts
    )
    assert changed_bytes != first_bytes
    assert changed.artifact_sha256 != first.artifact_sha256
    assert store.get_bytes(first.uri) == first_bytes
    assert store.get_bytes(changed.uri) == changed_bytes
    _resolve_previous(receipts, changed_body, first_bytes)


@pytest.mark.parametrize("status", _NONPASSING_STATUSES)
def test_unknown_or_negative_predecessor_is_incomplete_but_later_passed_run_recovers(
    tmp_path, status
):
    receipts = tmp_path / "receipts"
    _seed_latest(receipts, _noncanonical_bytes(_receipt(status=status)))

    _, following = gate1.write_receipt(_receipt(), receipts)

    assert following["replay"]["previous_run_complete"] is False
    assert following["replay"]["replay_demonstrated"] is False
    assert following["blockers"]
    assert following["execution_blockers"] == []

    _, recovered = gate1.write_receipt(_receipt(), receipts)

    assert recovered["replay"]["previous_run_complete"] is True
    assert recovered["replay"]["replay_demonstrated"] is True
    assert recovered["blockers"] == []


@pytest.mark.parametrize("status", _NONPASSING_STATUSES)
def test_unknown_or_negative_current_packet_never_demonstrates_replay(
    tmp_path, status
):
    receipts = tmp_path / "receipts"
    _seed_latest(receipts, _noncanonical_bytes(_receipt()))

    _, body = gate1.write_receipt(_receipt(status=status), receipts)

    assert body["replay"]["previous_run_complete"] is True
    assert body["replay"]["replay_demonstrated"] is False
    # The public result's blockers also drive the existing nonzero CLI exit.
    assert body["blockers"]


def test_passed_projection_can_complete_a_replay(tmp_path):
    receipts = tmp_path / "receipts"
    _seed_latest(receipts, _noncanonical_bytes(_receipt()))

    _, body = gate1.write_receipt(_receipt(), receipts)

    assert body["replay"]["previous_run_complete"] is True
    assert body["replay"]["replay_demonstrated"] is True
    assert body["blockers"] == []


@pytest.mark.parametrize(
    "fault", ["predecessor_cas", "finalized_receipt_cas", "atomic_latest"]
)
def test_publication_failure_preserves_previous_latest_and_store(
    tmp_path, monkeypatch, actual_puts, fault
):
    receipts = tmp_path / "receipts"
    prior_bytes = _noncanonical_bytes(_receipt())
    latest = _seed_latest(receipts, prior_bytes)
    store = _store(receipts)
    sentinel = b"previous evaluator output must survive publication failure\n"
    sentinel_locator = store.put_bytes(
        sentinel,
        provenance={
            "origin": "test.ignition-receipt-retention",
            "source_revision": "a" * 40,
            "created_at": "2026-09-06T00:00:00.000000+00:00",
            "input_digests": [hashlib.sha256(sentinel).hexdigest()],
            "trace_id": None,
        },
    )
    before = {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }
    actual_puts.clear()
    reached = []
    real_observed_put = ArtifactStore.put_bytes

    def is_finalized_receipt(data):
        if bytes(data) == prior_bytes:
            return False
        try:
            body = json.loads(data)
        except (ValueError, UnicodeError):
            return False
        return (
            isinstance(body, dict)
            and body.get("schema") == _SCHEMA
            and body.get("mission_id") == _MISSION
        )

    def fail_selected_put(target_store, data, **kwargs):
        selected = target_store.root == store.root and (
            (fault == "predecessor_cas" and bytes(data) == prior_bytes)
            or (fault == "finalized_receipt_cas" and is_finalized_receipt(data))
        )
        if selected:
            reached.append(fault)
            raise ArtifactStoreError(f"injected {fault}")
        return real_observed_put(target_store, data, **kwargs)

    def fail_latest(path, data, **kwargs):
        if Path(path).resolve() == latest.resolve():
            # A finalized, retrievable CAS object must already exist when the
            # latest-receipt replacement is attempted.
            assert any(
                root == store.root and payload == bytes(data)
                for root, payload, _ in actual_puts
            )
            reached.append(fault)
            raise OSError(f"injected {fault}")
        return write_bytes_atomic(path, data, **kwargs)

    monkeypatch.setattr(ArtifactStore, "put_bytes", fail_selected_put)
    if fault == "atomic_latest":
        # Old source has no atomic publication seam. Adding the future name
        # lets its real overwrite run and makes the red assertion meaningful.
        monkeypatch.setattr(gate1, "write_bytes_atomic", fail_latest, raising=False)

    with pytest.raises((ArtifactStoreError, OSError), match=f"injected {fault}"):
        gate1.write_receipt(_receipt(cost=2.0), receipts)

    assert reached == [fault]
    # Unchanged latest bytes cannot advertise an unresolved new reference.
    assert latest.read_bytes() == prior_bytes
    for relative, data in before.items():
        assert (store.root / relative).read_bytes() == data
    assert store.verify(sentinel_locator) == sentinel_locator
    assert store.get_bytes(sentinel_locator.uri) == sentinel
    if fault != "predecessor_cas":
        assert any(payload == prior_bytes for _, payload, _ in actual_puts)
    # Earlier successful CAS publications may remain as harmless orphans;
    # every actual returned locator must still resolve to its exact bytes.
    for root, payload, locator in actual_puts:
        actual_store = ArtifactStore(root)
        assert actual_store.verify(locator) == locator
        assert actual_store.get_bytes(locator.uri) == payload
