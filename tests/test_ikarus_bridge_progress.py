"""Regression tests for honest Ikarus bridge progress projection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus import progress_sources as progress_sources


@pytest.fixture()
def bridge_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from daedalus import file_bridge

    archive = tmp_path / "archive"
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    for path in (archive, inbox, outbox):
        path.mkdir()

    monkeypatch.setattr(file_bridge, "ARCHIVE", archive)
    monkeypatch.setattr(file_bridge, "INBOX", inbox)
    monkeypatch.setattr(file_bridge, "OUTBOX", outbox)
    monkeypatch.setattr(file_bridge, "quarantined_requests", lambda: [])
    monkeypatch.setattr(file_bridge, "heartbeat_status", lambda **_: {})
    return archive, inbox


def _archive_request(archive: Path, key: str) -> None:
    (archive / f"{key}.json").write_text(
        json.dumps({"objective": "build", "lane": "local_only", "paths": []}),
        encoding="utf-8",
    )


def _write_report(inbox: Path, key: str, status: str | None) -> None:
    payload: dict[str, object] = {"request_sha256": "0" * 64}
    if status is not None:
        payload["bridge_status"] = status
    (inbox / f"{key}.report.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    ("status", "expected"),
    (("done", True), ("failed", False), (None, None)),
)
def test_archiving_preserves_report_verdict(
    bridge_dirs: tuple[Path, Path], status: str | None, expected: bool | None
) -> None:
    archive, inbox = bridge_dirs
    key = f"case-{status or 'unknown'}"
    _write_report(inbox, key, status)

    before = progress_sources.snapshot_from_bridge(key)
    assert before is not None
    assert before.succeeded is expected
    assert before.applied is None

    _archive_request(archive, key)
    after = progress_sources.snapshot_from_bridge(key)
    assert after is not None
    assert after.succeeded is expected
    assert after.applied is None


def test_archived_request_without_report_is_unproven(
    bridge_dirs: tuple[Path, Path],
) -> None:
    archive, _ = bridge_dirs
    key = "no-report"
    _archive_request(archive, key)

    snapshot = progress_sources.snapshot_from_bridge(key)

    assert snapshot is not None
    assert snapshot.terminal is True
    assert snapshot.succeeded is None
    assert snapshot.applied is None
