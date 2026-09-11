"""Direct tests for the append primitive five subsystems now depend on.

``daedalus.journal_io.append_lines`` is reached from both memory journals,
``progress``, ``metrics``, ``kairos.archive`` and ``council.canary``. Until this
file existed it was only exercised THROUGH those callers, which is the shape
that lets a primitive's edge cases stay untested while every caller looks green:
each one drives the happy path and none drives the empty batch, the held lock,
or the short write.

The concurrency property itself is measured elsewhere
(``tests/test_journal_append_concurrency.py``, six real processes). This file
covers what a single caller can observe.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from daedalus.atomic import FileLockUnavailable
from daedalus.journal_io import (LOCK_TIMEOUT_SECONDS, ShortJournalWrite,
                                 append_lines)


def test_an_empty_batch_writes_nothing_and_creates_nothing(tmp_path: Path):
    """Not merely "returns 0": it must not create the file or the lock.

    A caller with nothing to say must not leave a journal behind that a health
    probe then reports as existing-but-empty -- ``present`` and ``absent`` are
    different answers and this is where the difference starts.
    """

    journal = tmp_path / "j.jsonl"
    assert append_lines(journal, []) == 0
    assert not journal.exists()
    assert not journal.with_name(journal.name + ".lock").exists()


def test_lines_get_exactly_one_newline_each(tmp_path: Path):
    """Callers differ on whether they pre-terminate; both must be safe."""

    journal = tmp_path / "j.jsonl"
    append_lines(journal, ["bare", "terminated\n", "bare again"])
    assert journal.read_bytes() == b"bare\nterminated\nbare again\n"


def test_a_batch_is_one_write_so_its_records_stay_contiguous(tmp_path: Path):
    """The reason canary passes its whole run at once rather than per line."""

    journal = tmp_path / "j.jsonl"
    calls: list[int] = []
    real_write = os.write

    def spy(fd, data):
        calls.append(len(data))
        return real_write(fd, data)

    with mock.patch("os.write", spy):
        append_lines(journal, ["a", "b", "c"])
    assert calls == [len("a\nb\nc\n")], (
        f"the batch was split into {len(calls)} operating-system writes; "
        f"another appender can land between them"
    )


def test_utf8_content_round_trips(tmp_path: Path):
    journal = tmp_path / "j.jsonl"
    payload = {"summary": "Umlaute: äöü — and an em dash", "n": 1}
    append_lines(journal, [json.dumps(payload, ensure_ascii=False)])
    assert json.loads(journal.read_text(encoding="utf-8")) == payload


def test_missing_parent_directories_are_created(tmp_path: Path):
    journal = tmp_path / "deep" / "deeper" / "j.jsonl"
    append_lines(journal, ["x"])
    assert journal.read_text(encoding="utf-8") == "x\n"


def test_appending_never_truncates_an_existing_journal(tmp_path: Path):
    journal = tmp_path / "j.jsonl"
    journal.write_text("pre-existing\n", encoding="utf-8")
    append_lines(journal, ["added"])
    assert journal.read_text(encoding="utf-8") == "pre-existing\nadded\n"


def test_the_lock_file_is_a_sibling_and_is_never_removed(tmp_path: Path):
    """Removing it is the split-inode race, not cleanup.

    ``daedalus.atomic.ExclusiveFileLock`` documents why the file is persistent;
    this asserts the caller does not undo that by tidying up after itself. A
    create/unlink lock deadlocks writers on Windows -- measured, see
    ``experiments/concurrency/probe_append_atomicity.py`` variant C.
    """

    journal = tmp_path / "j.jsonl"
    lock = journal.with_name(journal.name + ".lock")
    append_lines(journal, ["one"])
    assert lock.exists()
    append_lines(journal, ["two"])
    assert lock.exists()


def test_a_held_lock_raises_rather_than_writing_unserialised(tmp_path: Path,
                                                             monkeypatch):
    """The refusal is the point: an unserialised write is the defect."""

    from daedalus.atomic import ExclusiveFileLock
    import daedalus.journal_io as journal_io

    journal = tmp_path / "j.jsonl"
    append_lines(journal, ["first"])           # creates the lock file
    lock = journal.with_name(journal.name + ".lock")

    monkeypatch.setattr(journal_io, "LOCK_TIMEOUT_SECONDS", 0.2)
    with ExclusiveFileLock(lock, timeout_s=5.0, label="test holder"):
        with pytest.raises(FileLockUnavailable):
            append_lines(journal, ["second"])

    # Nothing was written while the lock was held, and the journal is usable
    # again once it is free -- a timeout must not poison the file.
    assert journal.read_text(encoding="utf-8") == "first\n"
    append_lines(journal, ["third"])
    assert journal.read_text(encoding="utf-8") == "first\nthird\n"


def test_a_short_write_raises_instead_of_reporting_success(tmp_path: Path):
    """A torn tail must reach the caller, not the next reader.

    ``os.write`` may legally write fewer bytes than it was given. Retrying the
    remainder would place it after whatever another appender added in between,
    producing one record that reads as two -- so the primitive refuses and says
    the journal has a torn tail.
    """

    journal = tmp_path / "j.jsonl"
    real_write = os.write

    def short(fd, data):
        return real_write(fd, data[: len(data) // 2])

    with mock.patch("os.write", short):
        with pytest.raises(ShortJournalWrite) as caught:
            append_lines(journal, ["a-fairly-long-line-to-halve"])
    assert "of" in str(caught.value)
    assert str(journal) in str(caught.value)


def test_the_timeout_is_bounded_and_stated(tmp_path: Path):
    """A lock without a bound is a hang; the bound is a number a reader can see."""

    assert 0 < LOCK_TIMEOUT_SECONDS <= 60


def test_the_lock_is_released_when_the_call_returns(tmp_path: Path):
    """Otherwise the second call in one process would deadlock on itself.

    Byte-range locks are per handle on Windows, so a leaked lock is not
    re-entrant -- it is a permanent stall for this process and every other one.
    """

    from daedalus.atomic import ExclusiveFileLock

    journal = tmp_path / "j.jsonl"
    append_lines(journal, ["one"])
    lock = journal.with_name(journal.name + ".lock")
    # If the previous call leaked the lock, this acquisition times out.
    with ExclusiveFileLock(lock, timeout_s=2.0, label="probe"):
        pass
    append_lines(journal, ["two"])
    assert journal.read_text(encoding="utf-8") == "one\ntwo\n"
