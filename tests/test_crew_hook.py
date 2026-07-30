"""
Tests for the live_agent_transcript_count hook.

The hook counts active agent transcripts in a directory by looking at file
modification times within a time window.  It MUST NEVER raise -- a hook that
raises breaks every prompt -- so every test here checks both the returned
value and the absence of exceptions.

The expected public API is:

    from daedalus.hooks.crew_hook import live_agent_transcript_count

    def live_agent_transcript_count(
        directory: str,
        window_seconds: float,
        min_count: int,
    ) -> int:
        ...
"""

import pytest
from unittest.mock import patch

# The function under test.  When the hook is written, uncomment this import.
# from daedalus.hooks.crew_hook import live_agent_transcript_count

# Provide a dummy for now so that the test file can at least be parsed.
# Once the real hook lands, remove this placeholder.
def live_agent_transcript_count(directory, window_seconds, min_count):
    # This dummy will be replaced by the actual import.
    raise NotImplementedError("Hook not implemented yet.")


class TestLiveAgentTranscriptCount:
    """Collects all tests for the live_agent_transcript_count hook."""

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_missing_directory(
        self, mock_getmtime, mock_listdir, mock_isdir, mock_time
    ):
        """Directory does not exist -> returns 0 without raising."""
        mock_isdir.return_value = False
        result = live_agent_transcript_count("/nonexistent", window_seconds=10, min_count=1)
        assert result == 0

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", side_effect=PermissionError)
    def test_unreadable_directory(
        self, mock_listdir, mock_isdir, mock_time
    ):
        """listdir raises PermissionError -> returns 0 without raising."""
        result = live_agent_transcript_count("/unreadable", window_seconds=10, min_count=1)
        assert result == 0

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_unreadable_file_inside_directory(
        self, mock_getmtime, mock_listdir, mock_isdir, mock_time
    ):
        """An unreadable file (OSError on getmtime) is skipped; others counted."""
        mock_listdir.return_value = ["good1", "bad", "good2"]
        # The second call to getmtime raises OSError; the first and third succeed.
        mock_getmtime.side_effect = [500.0, OSError("permission denied"), 600.0]
        result = live_agent_transcript_count("/dir", window_seconds=1000, min_count=1)
        assert result == 2

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_empty_window(self, mock_getmtime, mock_listdir, mock_isdir, mock_time):
        """window_seconds=0 must not raise.  Exact behaviour is undefined, but
        we check that a non-negative integer is returned.
        """
        mock_listdir.return_value = ["f1"]
        # f1 has mtime exactly at 'now'.
        mock_getmtime.return_value = 1000.0
        result = live_agent_transcript_count("/dir", window_seconds=0, min_count=1)
        assert isinstance(result, int)
        assert result >= 0

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_future_mtime(self, mock_getmtime, mock_listdir, mock_isdir, mock_time):
        """Files with mtime in the future (clock skew) are not counted, no error."""
        mock_listdir.return_value = ["future_file"]
        mock_getmtime.return_value = 2000.0  # later than 'now'
        result = live_agent_transcript_count("/dir", window_seconds=100, min_count=1)
        assert result == 0

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_at_minimum_threshold(self, mock_getmtime, mock_listdir, mock_isdir, mock_time):
        """When the count exactly meets min_count, the hook returns the count."""
        mock_listdir.return_value = ["a", "b", "c"]
        mock_getmtime.return_value = 500.0  # inside window (1000-100=900 to 1000)
        result = live_agent_transcript_count("/dir", window_seconds=100, min_count=3)
        assert result == 3

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_below_minimum_threshold(self, mock_getmtime, mock_listdir, mock_isdir, mock_time):
        """When count is below min_count, still returns the actual count, no error."""
        mock_listdir.return_value = ["a", "b", "c"]
        mock_getmtime.return_value = 500.0
        result = live_agent_transcript_count("/dir", window_seconds=100, min_count=5)
        assert result == 3

    @patch("time.time", return_value=1000.0)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.getmtime")
    def test_above_minimum_threshold(self, mock_getmtime, mock_listdir, mock_isdir, mock_time):
        """When count is above min_count, the actual count is returned."""
        mock_listdir.return_value = ["a", "b", "c", "d"]
        mock_getmtime.return_value = 500.0
        result = live_agent_transcript_count("/dir", window_seconds=100, min_count=2)
        assert result == 4


if __name__ == "__main__":
    pytest.main([__file__])
