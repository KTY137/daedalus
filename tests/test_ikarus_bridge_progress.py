"""Regression tests for honest Ikarus bridge progress projection."""
from __future__ import annotations

import json
import os
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


def _write_project_report(
    inbox: Path,
    key: str,
    project: str | None,
    *,
    arrived_ns: int,
) -> Path:
    request = {"lane": "local_only"}
    if project is not None:
        request["project"] = project
    path = inbox / f"{key}.report.json"
    path.write_text(
        json.dumps(
            {
                "bridge_status": "done",
                "lane": "local_only",
                "request": request,
                "report": {"summary": f"finished {key}"},
            }
        ),
        encoding="utf-8",
    )
    os.utime(path, ns=(arrived_ns, arrived_ns))
    return path


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


def test_stream_state_keeps_report_evidence_on_exact_project(
    bridge_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from daedalus import file_bridge

    _, inbox = bridge_dirs
    _write_project_report(inbox, "alpha-finished", "alpha", arrived_ns=1_000_000_000)
    monkeypatch.setattr(
        file_bridge,
        "heartbeat_status",
        lambda **_: {"state": "busy", "current": {"file": "alpha-running.json"}},
    )

    before = file_bridge.stream_state("alpha")
    assert before["reports_total"] == 1
    assert before["latest_report"]["name"] == "alpha-finished.report.json"
    assert before["latest_report"]["project"] == "alpha"
    assert before["in_flight"] == 1
    assert type(before["in_flight"]) is int

    # A later report from beta must not advance alpha's report counter/event.
    _write_project_report(inbox, "beta-finished", "beta", arrived_ns=2_000_000_000)
    after_foreign = file_bridge.stream_state("alpha")
    assert after_foreign["reports_total"] == before["reports_total"]
    assert after_foreign["latest_report"] == before["latest_report"]

    beta = file_bridge.stream_state("beta")
    assert beta["reports_total"] == 1
    assert beta["latest_report"]["name"] == "beta-finished.report.json"

    global_view = file_bridge.stream_state()
    assert global_view["reports_total"] == 2
    assert global_view["latest_report"]["name"] == "beta-finished.report.json"

    monkeypatch.setattr(file_bridge, "heartbeat_status", lambda **_: {})
    idle = file_bridge.stream_state("alpha")
    assert idle["in_flight"] == 0
    assert type(idle["in_flight"]) is int


def test_project_stream_does_not_claim_unattributed_legacy_report(
    bridge_dirs: tuple[Path, Path],
) -> None:
    from daedalus import file_bridge

    _, inbox = bridge_dirs
    _write_project_report(inbox, "alpha-finished", "alpha", arrived_ns=1_000_000_000)
    _write_project_report(inbox, "legacy-finished", None, arrived_ns=2_000_000_000)

    alpha = file_bridge.stream_state("alpha")
    assert alpha["reports_total"] == 1
    assert alpha["latest_report"]["name"] == "alpha-finished.report.json"

    global_view = file_bridge.stream_state()
    assert global_view["reports_total"] == 2
    assert global_view["latest_report"]["name"] == "legacy-finished.report.json"
    assert global_view["latest_report"]["project"] == ""
