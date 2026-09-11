# test_shift.py -- Tests for Daedalus shift module.
#
# This module tests:
# - Atomic publish (including failure resilience)
# - Lock file separate from state file (Windows rename safety)
# - Working-window boundary arithmetic (midnight crossing)
# - Behaviour when the state file is missing or corrupt
#
# All tests are deterministic: they use temporary fixtures and mock or
# control time to avoid reliance on wall-clock.

import os
import time
import datetime
import tempfile
import contextlib

import pytest

# Import the module under test.  These imports are expected to match the
# public API of daedalus.shift.  If they don't, the tests will fail early
# with an ImportError, which is desirable.
from daedalus.shift import (
    ShiftManager,
    WorkingWindow,
    StateCorruptError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir(tmp_path):
    """Provide a clean temporary directory for file operations."""
    return str(tmp_path)


@pytest.fixture
def state_path(temp_dir):
    """Return a stable state file path inside temp_dir."""
    return os.path.join(temp_dir, "state.json")


@pytest.fixture
def lock_path(state_path):
    """Return the corresponding lock file path.

    The daedalus.shift module uses a lock file alongside the state file;
    we assume the convention is the same basename with a '.lock' suffix.
    """
    return state_path + ".lock"


# ---------------------------------------------------------------------------
# Atomic publish tests
# ---------------------------------------------------------------------------

class TestAtomicPublish:
    """Tests for the atomic publish behaviour of ShiftManager."""

    def test_publish_writes_file_atomically(self, temp_dir, state_path):
        """publish() must leave a complete file or nothing at all.

        If the operation is interrupted, no partial file may remain.
        We simulate this by verifying that a file appears only after
        the publish call returns successfully.
        """
        mgr = ShiftManager()
        data = {"version": 1, "tasks": []}
        mgr.publish(data, state_path)

        # The file must exist and contain the serialised data.
        assert os.path.exists(state_path)
        with open(state_path, "r") as f:
            content = f.read()
        assert '"version": 1' in content

        # No temporary file (e.g. .tmp) should be left behind.
        sibling_files = os.listdir(temp_dir)
        temp_siblings = [f for f in sibling_files if f.endswith(".tmp")]
        assert len(temp_siblings) == 0, (
            "Temporary file left behind -- publish was not atomic or did not "
            "clean up"
        )

    def test_failed_publish_preserves_previous_state(
        self, state_path, lock_path
    ):
        """If publish fails, the previous state file must remain untouched.

        This guarantees that a crash during publish does not corrupt the
        persisted state.
        """
        # Write initial state.
        mgr = ShiftManager()
        initial = {"version": 1}
        mgr.publish(initial, state_path)

        # Simulate a failure by making the lock file unwritable.
        # We do this by creating a directory with the same name, so that
        # the code trying to create the lock file will fail.
        os.makedirs(lock_path, exist_ok=True)

        new_data = {"version": 2}
        with pytest.raises(OSError):
            mgr.publish(new_data, state_path)

        # State file must still contain version 1.
        with open(state_path, "r") as f:
            content = f.read()
        assert '"version": 1' in content
        assert '"version": 2' not in content

    # NEW test that exposes incomplete cleanup on rename failure.
    def test_rename_failure_cleans_up_temp_file(self, state_path, tmp_path):
        """When the final rename (e.g. os.replace) fails, no temporary
        file should be left behind and the original state must survive.

        This test mocks the rename step to force an error and then asserts
        cleanup happened.
        """
        from unittest.mock import patch
        mgr = ShiftManager()
        initial = {"version": 1}
        mgr.publish(initial, state_path)

        # The exact name of the temporary file is internal, but we can
        # discover .tmp files before and after to ensure none linger.
        before_files = set(os.listdir(tmp_path))

        # Patch os.replace to simulate a crash during the atomic rename.
        with patch("os.replace", side_effect=PermissionError("simulated")):
            new_data = {"version": 2}
            with pytest.raises(PermissionError):
                mgr.publish(new_data, state_path)

        # Original state should be untouched.
        with open(state_path, "r") as f:
            content = f.read()
        assert '"version": 1' in content
        assert '"version": 2' not in content

        # No new .tmp files must persist.
        after_files = set(os.listdir(tmp_path))
        new_tmp_files = [
            f for f in (after_files - before_files) if f.endswith(".tmp")
        ]
        assert len(new_tmp_files) == 0, (
            "Temporary file left behind after rename failure"
        )


# ---------------------------------------------------------------------------
# Lock file separate from state file (Windows rename safety)
# ---------------------------------------------------------------------------

class TestLockFileSeparation:
    """Lock file must not prevent replacement of the state file.

    On Windows, if an open handle exists on a file, that file cannot
    be renamed or deleted.  By using a separate lock file, the atomic
    rename of a temporary file onto the state file path succeeds even
    while the lock file is held open.
    """

    def test_can_replace_state_while_lock_held_open(
        self, state_path, lock_path
    ):
        """Publishing must succeed even when an external process holds
        the lock file open.

        This simulates a Windows scenario where another process (or
        thread) may have the lock file open, but the state file itself
        is not locked.  The publish should proceed and replace the
        state file.
        """
        mgr = ShiftManager()

        # Create an initial state and publish it.
        initial = {"version": 1}
        mgr.publish(initial, state_path)

        # Open a handle on the lock file.  We open in 'w' mode and
        # keep the file descriptor alive (not closing it) to emulate
        # an open handle.
        with open(lock_path, "w") as held_lock:
            # Write something so the lock file exists.
            held_lock.write("lock content")
            held_lock.flush()

            # Now publish a new state.  This should succeed because
            # the state file is replaced via a temporary file rename,
            # not by directly modifying the state file.
            new_data = {"version": 2}
            mgr.publish(new_data, state_path)

            # The fresh state file must contain version 2.
            with open(state_path, "r") as f:
                content = f.read()
            assert '"version": 2' in content

            # The lock file handle is still open; after the with block
            # it will be closed (this is just to demonstrate that it
            # did not block the publish).

    def test_lock_file_exists_but_not_open(self, state_path, lock_path):
        """Even when the lock file exists (no open handles), publish
        works correctly.
        """
        mgr = ShiftManager()

        # Manually create a lock file as a plain file.
        with open(lock_path, "w") as f:
            f.write("stale lock")

        # Publishing should not be hindered.
        data = {"version": 3}
        mgr.publish(data, state_path)

        assert os.path.exists(state_path)
        with open(state_path, "r") as f:
            content = f.read()
        assert '"version": 3' in content


# ---------------------------------------------------------------------------
# Working-window boundary arithmetic (including midnight crossing)
# ---------------------------------------------------------------------------

class TestWorkingWindowBoundaries:
    """Tests for the WorkingWindow class, focusing on edge cases
    like midnight crossings.
    """

    # Use fixed datetimes to ensure determinism.
    # Window open 22:00, close 02:00 next day.
    midnight_window = WorkingWindow(
        start_time=datetime.time(22, 0),
        end_time=datetime.time(2, 0),
    )

    def test_window_midnight_inside_both_sides(self):
        """A moment inside a window that crosses midnight must be
        correctly identified on both calendar days."""
        # 23:30 on 2024-05-10 -> should be inside.
        dt_inside1 = datetime.datetime(2024, 5, 10, 23, 30)
        assert self.midnight_window.contains(dt_inside1)

        # 01:30 on 2024-05-11 -> should be inside (following day of window).
        dt_inside2 = datetime.datetime(2024, 5, 11, 1, 30)
        assert self.midnight_window.contains(dt_inside2)

    def test_window_midnight_outside_both_sides(self):
        """Moments outside the midnight-crossing window must be
        correctly rejected."""
        # 21:59 on 2024-05-10 -> before window.
        dt_before = datetime.datetime(2024, 5, 10, 21, 59)
        assert not self.midnight_window.contains(dt_before)

        # 02:01 on 2024-05-11 -> after window.
        dt_after = datetime.datetime(2024, 5, 11, 2, 1)
        assert not self.midnight_window.contains(dt_after)

    def test_window_midnight_boundary_start_equal(self):
        """Start boundary is inclusive."""
        dt_start = datetime.datetime(2024, 5, 10, 22, 0)
        assert self.midnight_window.contains(dt_start)

    def test_window_midnight_boundary_end_equal(self):
        """End boundary is exclusive (consistent with [start, end))."""
        dt_end = datetime.datetime(2024, 5, 11, 2, 0)
        assert not self.midnight_window.contains(dt_end)

    def test_window_same_day(self):
        """A non-midnight window should work correctly."""
        window = WorkingWindow(
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        # 12:00 is inside.
        assert window.contains(datetime.datetime(2024, 5, 10, 12, 0))
        # 08:59 is outside.
        assert not window.contains(datetime.datetime(2024, 5, 10, 8, 59))
        # 17:00 is outside (exclusive end).
        assert not window.contains(datetime.datetime(2024, 5, 10, 17, 0))


# ---------------------------------------------------------------------------
# Missing or corrupt state file
# ---------------------------------------------------------------------------

class TestMissingOrCorruptState:
    """ShiftManager must handle absent or malformed state files
    gracefully."""

    def test_missing_state_returns_default(self, state_path):
        """When no state file exists, the manager should assume a safe
        default state (e.g., empty)."""
        mgr = ShiftManager()
        # The state file does not exist yet; reading should not crash.
        state = mgr.load(state_path)
        # The default is expected to be an empty dict or some sensible value.
        assert isinstance(state, dict)
        assert len(state) == 0, "Default state should be empty"

    def test_corrupt_state_raises_exception(self, state_path):
        """A state file containing invalid data must raise
        StateCorruptError, not silently return garbage."""
        # Write an invalid JSON file.
        with open(state_path, "w") as f:
            f.write("{not valid json")

        mgr = ShiftManager()
        with pytest.raises(StateCorruptError):
            mgr.load(state_path)

    def test_empty_state_file_raises_or_defaults(self, state_path):
        """An empty file could be considered corrupt or fall back to
        default.  This test documents the decision: an empty file should
        not crash but may return default.

        (The exact behaviour is under design; this test will be updated
        once the decision is made.)
        """
        # Create an empty file.
        with open(state_path, "w"):
            pass

        mgr = ShiftManager()
        # The current expected behaviour: empty file is treated as corrupt.
        with pytest.raises(StateCorruptError):
            mgr.load(state_path)

    def test_state_file_with_unexpected_structure(self, state_path):
        """If the state file contains valid JSON but the schema is
        wrong, a StateCorruptError must be raised."""
        with open(state_path, "w") as f:
            f.write('{"version": "not an integer"}')

        mgr = ShiftManager()
        with pytest.raises(StateCorruptError):
            mgr.load(state_path)


# ---------------------------------------------------------------------------
# Additional deterministic tests (no random, no wall clock)
# ---------------------------------------------------------------------------

class TestDeterministicBehaviour:
    """Ensure that core operations are deterministic, i.e., two runs
    on the same input produce exactly the same output and side effects."""

    def test_publish_deterministic_contents(self, state_path):
        """Publishing the same data twice must produce identical
        file contents (bit-for-bit) and no extra side effects."""
        mgr = ShiftManager()
        data = {"key": "value", "list": [1, 2, 3]}

        # First publish
        mgr.publish(data, state_path)
        with open(state_path, "rb") as f:
            first_bytes = f.read()

        # Remove state file and publish again
        os.remove(state_path)
        mgr.publish(data, state_path)
        with open(state_path, "rb") as f:
            second_bytes = f.read()

        # Contents must be exactly equal.
        assert first_bytes == second_bytes, (
            "Publish is not deterministic"
        )

    def test_window_contains_deterministic(self):
        """WorkingWindow.contains on the same datetime always
        returns the same answer."""
        window = WorkingWindow(
            start_time=datetime.time(22, 0),
            end_time=datetime.time(2, 0),
        )
        dt = datetime.datetime(2024, 5, 10, 23, 0)
        result1 = window.contains(dt)
        result2 = window.contains(dt)
        assert result1 == result2

    def test_load_deterministic(self, state_path):
        """Loading the same state file twice gives the same object."""
        mgr = ShiftManager()
        data = {"version": 42}
        mgr.publish(data, state_path)

        state1 = mgr.load(state_path)
        state2 = mgr.load(state_path)
        assert state1 == state2
