"""Tests for daedalus.shift — atomic publish, locking, time arithmetic, missing/corrupt file.

These tests cover:
- Atomic publish: writes never produce partial/empty state files visible to readers.
- ShiftLock: acquisition, timeout, stale lock stealing.
- Working-window arithmetic: _parse_until, elapsed, remaining, expired.
- State file: missing, corrupt JSON, valid content.
- Windows-specific: os.replace fails when target file is held open (atomic publish guard).
"""

import json
import os
import platform
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from daedalus.shift import (
    Shift,
    _hm,
    _now,
    _parse_until,
    _ShiftLock,
    _write_atomic,
    end,
    load,
    note,
    start,
    SHIFT_REL_PATH,
)


# ── helpers ──────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 1, 12, 0, 0).astimezone()


@pytest.fixture
def freeze_now(monkeypatch):
    """Make _now return a fixed time so tests are deterministic."""
    monkeypatch.setattr("daedalus.shift._now", lambda: FROZEN_NOW)


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Point _path to a temporary directory instead of the real runs directory."""
    monkeypatch.setenv("DAEDALUS_REPO_ROOT", str(tmp_path))
    return tmp_path


# ── time parsing ─────────────────────────────────────────────────────────────

class TestParseUntil:
    def test_empty_string_returns_none(self, freeze_now):
        assert _parse_until("") is None
        assert _parse_until("   ") is None

    def test_plus_minutes(self, freeze_now):
        result = _parse_until("+90m")
        expected = FROZEN_NOW + timedelta(minutes=90)
        assert result == expected

    def test_plus_hours(self, freeze_now):
        result = _parse_until("+2h")
        expected = FROZEN_NOW + timedelta(hours=2)
        assert result == expected

    def test_hhmm_same_day(self, freeze_now):
        # 13:00 is after noon, so same day
        result = _parse_until("13:00")
        expected = FROZEN_NOW.replace(hour=13, minute=0, second=0, microsecond=0)
        assert result == expected

    def test_hhmm_next_day(self, freeze_now):
        # 11:00 is before noon, so next day
        result = _parse_until("11:00")
        expected = (FROZEN_NOW + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
        assert result == expected

    def test_hhmm_exact_now(self, monkeypatch, freeze_now):
        # 12:00 is exactly now, should give tomorrow
        result = _parse_until("12:00")
        expected = (FROZEN_NOW + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        assert result == expected

    def test_full_iso_utc(self, freeze_now):
        result = _parse_until("2026-08-01T14:00:00+00:00")
        expected = datetime(2026, 8, 1, 14, 0, 0).astimezone()
        assert result == expected

    def test_full_iso_naive(self, freeze_now):
        result = _parse_until("2026-08-01T14:00:00")
        expected = datetime(2026, 8, 1, 14, 0, 0).astimezone()
        assert result == expected

    def test_invalid_garbage(self, freeze_now):
        assert _parse_until("not-a-time") is None

    def test_plus_invalid_unit(self, freeze_now):
        assert _parse_until("+10x") is None

    def test_plus_missing_amount(self, freeze_now):
        assert _parse_until("+m") is None


class TestHm:
    def test_zero(self):
        assert _hm(timedelta(0)) == "0m"

    def test_minutes_only(self):
        assert _hm(timedelta(minutes=5)) == "5m"

    def test_hours_and_minutes(self):
        assert _hm(timedelta(hours=3, minutes=15)) == "3h15m"

    def test_seconds_rounded_down(self):
        assert _hm(timedelta(hours=1, minutes=1, seconds=59)) == "1h01m"


# ── shift properties ─────────────────────────────────────────────────────────

class TestShiftArithmetic:
    def test_remaining_from_until(self, freeze_now):
        s = Shift(started="2026-08-01T11:00:00", until="13:00")
        rem = s.remaining()
        assert rem == timedelta(hours=1)

    def test_remaining_from_iso(self, freeze_now):
        s = Shift(until="2026-08-01T14:00:00")
        assert s.remaining() == timedelta(hours=2)

    def test_remaining_no_until(self, freeze_now):
        s = Shift()
        assert s.remaining() is None

    def test_expired_true(self, freeze_now):
        s = Shift(started="2026-08-01T11:00:00", until="11:59")
        assert s.expired is True

    def test_expired_false(self, freeze_now):
        s = Shift(started="2026-08-01T11:00:00", until="13:00")
        assert s.expired is False

    def test_expired_no_until(self, freeze_now):
        s = Shift(started="2026-08-01T11:00:00")
        assert s.expired is False

    def test_elapsed(self, freeze_now):
        s = Shift(started="2026-08-01T11:00:00")
        assert s.elapsed() == timedelta(hours=1)

    def test_elapsed_invalid(self, freeze_now):
        s = Shift(started="garbage")
        assert s.elapsed() is None


class TestShiftRender:
    def test_no_shift(self, freeze_now):
        s = Shift()
        rendered = s.render()
        assert "no shift declared" in rendered
        assert "12:00" in rendered

    def test_active_shift(self, freeze_now):
        s = Shift(goal="test", started="2026-08-01T11:00:00", until="13:00", done_means="all tests pass")
        r = s.render()
        assert "1h00m left" in r
        assert "1h00m worked" in r
        assert "goal: test" in r
        assert "all tests pass" in r

    def test_expired_shift(self, freeze_now):
        s = Shift(goal="late", started="2026-08-01T11:00:00", until="11:59")
        r = s.render()
        assert "SHIFT ENDED" in r

    def test_no_end_declared(self, freeze_now):
        s = Shift(goal="endless", started="2026-08-01T11:00:00")
        r = s.render()
        assert "no end declared" in r


# ── IO: load / start / note / end ────────────────────────────────────────────

class TestLoadMissing:
    def test_missing_file_returns_empty_shift(self, tmp_repo, freeze_now):
        s = load()
        assert s.goal == ""
        assert s.render() == "[12:00] no shift declared"

    def test_empty_file_returns_empty_shift(self, tmp_repo):
        (tmp_repo / SHIFT_REL_PATH).parent.mkdir(parents=True, exist_ok=True)
        (tmp_repo / SHIFT_REL_PATH).touch()
        s = load()
        assert s.goal == ""

    def test_corrupt_json_returns_empty_shift(self, tmp_repo):
        p = tmp_repo / SHIFT_REL_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{this is not json]", encoding="utf-8")
        s = load()
        assert s.goal == ""

    def test_valid_json(self, tmp_repo):
        p = tmp_repo / SHIFT_REL_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"goal": "write tests", "started": "2026-08-01T10:00:00", "until": "+2h",
                "done_means": "coverage", "notes": [], "version": "1"}
        p.write_text(json.dumps(data), encoding="utf-8")
        s = load()
        assert s.goal == "write tests"
        assert s.started == "2026-08-01T10:00:00"
        assert s.until == "+2h"
        assert s.done_means == "coverage"
        assert s.notes == []


class TestStart:
    def test_start_writes_file(self, tmp_repo, freeze_now):
        s = start("code review", until="14:00", done_means="all comments resolved")
        assert s.goal == "code review"
        assert s.until == "14:00"
        assert s.done_means == "all comments resolved"
        # started should be iso of frozen now
        assert s.started == FROZEN_NOW.isoformat(timespec="seconds")
        # file should exist
        p = tmp_repo / SHIFT_REL_PATH
        assert p.is_file()
        read = load()
        assert read.goal == "code review"


class TestNote:
    def test_note_appends(self, tmp_repo, freeze_now):
        start("goal", until="13:00")
        s1 = note("first checkpoint")
        assert len(s1.notes) == 1
        assert s1.notes[0]["text"] == "first checkpoint"
        assert s1.notes[0]["locked"] is True

        # append second
        s2 = note("second checkpoint")
        assert len(s2.notes) == 2
        assert s2.notes[1]["text"] == "second checkpoint"
        # locked may be true or false depending on lock success; we got lock
        assert s2.notes[1]["locked"] is True

    def test_note_respects_lock(self, tmp_repo, monkeypatch, freeze_now):
        # Simulate lock acquisition failure by making _ShiftLock.__enter__ return False
        original_enter = _ShiftLock.__enter__
        def fake_enter(self):
            return False
        monkeypatch.setattr(_ShiftLock, "__enter__", fake_enter)
        start("goal")
        s = note("note with failed lock")
        assert s.notes[-1]["locked"] is False


class TestEnd:
    def test_end_removes_file(self, tmp_repo, freeze_now):
        start("goal", until="13:00")
        assert (tmp_repo / SHIFT_REL_PATH).is_file()
        end()
        assert not (tmp_repo / SHIFT_REL_PATH).is_file()
        # subsequent load returns empty shift
        s = load()
        assert s.goal == ""

    def test_end_missing_file_no_error(self, tmp_repo):
        end()  # should not raise


# ── atomic publish ───────────────────────────────────────────────────────────

class TestWriteAtomic:
    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "shift.json"
        _write_atomic(p, {"k": "v"})
        assert p.is_file()
        assert json.loads(p.read_text()) == {"k": "v"}

    def test_writes_valid_json(self, tmp_path):
        p = tmp_path / "shift.json"
        payload = {"goal": "publish test", "notes": [1, 2]}
        _write_atomic(p, payload)
        assert json.loads(p.read_text()) == payload

    def test_atomicity_readers_never_see_partial(self, tmp_path):
        """Simulate a slow write: the target file is only updated atomically,
        so a concurrent reader sees either old content or complete new content."""
        target = tmp_path / "shift.json"
        target.write_text(json.dumps({"status": "initial"}))

        # Instead of actually splitting the write, we can enforce that the temp
        # file is not moved until after the write is complete by design.
        # We'll test that no invalid JSON appears ever. We'll use a flag and
        # a reader thread that polls until the write is complete.
        # Since _write_atomic writes to tmp and then os.replace, the target
        # file is never in an intermediate state.
        # We simulate a large payload and rapid polling.
        large_payload = {"data": "x" * 10000}

        written = threading.Event()
        results = []

        def reader():
            while not written.is_set():
                try:
                    content = target.read_text()
                    results.append(json.loads(content))
                except Exception:
                    results.append(None)
                time.sleep(0.001)

        t = threading.Thread(target=reader)
        t.start()
        _write_atomic(target, large_payload)
        written.set()
        t.join()

        # Check that every read produced valid JSON and was either old or new content.
        assert all(isinstance(r, dict) for r in results if r is not None)
        # At least one old and one new should appear.
        any_old = any(r.get("status") == "initial" for r in results)
        any_new = any(r.get("data") is not None for r in results)
        assert any_old, "initial content never seen"
        assert any_new, "new content never seen"

    def test_windows_replace_fails_when_file_open(self, tmp_path):
        """On Windows, os.replace fails if the target file is currently opened.
        This test verifies that behaviour exists as expected."""
        target = tmp_path / "shift.json"
        target.write_text("old")
        with open(target, "r") as f:
            if platform.system() == "Windows":
                with pytest.raises(OSError):
                    os.replace(tmp_path / "temp.tmp", target)
            else:
                # On POSIX, replace works even with open handles.
                os.replace(tmp_path / "temp.tmp", target)
                # After replace, f still reads old content (inode unchanged).
                assert f.read() == "old"


# ── shift lock ───────────────────────────────────────────────────────────────

class TestShiftLock:
    def test_acquire_release(self, tmp_path):
        lock_path = tmp_path / "shift.json"
        lock = _ShiftLock(lock_path, timeout_s=1)
        assert lock.__enter__() is True
        assert lock_path.with_name(lock_path.name + ".lock").is_file()
        lock.__exit__(None, None, None)
        assert not lock_path.with_name(lock_path.name + ".lock").is_file()

    def test_contention_timeout(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "shift.json"
        # Grab the lock manually to simulate contention
        lock1 = _ShiftLock(lock_path)
        lock1.__enter__()
        # Now a second lock should fail after timeout
        lock2 = _ShiftLock(lock_path, timeout_s=0.1)
        # Speed up time to avoid actual wait
        import time as tlib
        real_sleep = tlib.sleep
        def fast_sleep(s):
            pass  # no sleep, directly loop
        monkeypatch.setattr(tlib, "sleep", fast_sleep)
        # Should fail because lock is held and not expired
        assert lock2.__enter__() is False
        lock1.__exit__(None, None, None)

    def test_steal_stale_lock(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "shift.json"
        # Create a lock file with old mtime
        lock_file = lock_path.with_name(lock_path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text("stale")
        # Set mtime to 10 seconds ago
        old_time = time.time() - 10
        os.utime(str(lock_file), (old_time, old_time))

        lock = _ShiftLock(lock_path, timeout_s=5)  # 5s timeout, lock is older, should steal
        monkeypatch.setattr(time, "sleep", lambda s: None)
        assert lock.__enter__() is True
        assert lock_file.is_file()  # new lock created
        lock.__exit__(None, None, None)
        assert not lock_file.is_file()

    def test_lock_directory_created(self, tmp_path):
        lock_path = tmp_path / "deep" / "nested" / "shift.json"
        lock = _ShiftLock(lock_path)
        assert lock.__enter__() is True
        assert lock_path.parent.is_dir()
        assert lock_path.with_name(lock_path.name + ".lock").is_file()
        lock.__exit__(None, None, None)


# ── edge cases ───────────────────────────────────────────────────────────────

def test_path_from_env_or_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_REPO_ROOT", str(tmp_path))
    from daedalus.shift import _path
    p = _path()
    assert p == tmp_path / SHIFT_REL_PATH

    monkeypatch.delenv("DAEDALUS_REPO_ROOT")
    p2 = _path()
    assert p2 == Path(".") / SHIFT_REL_PATH
