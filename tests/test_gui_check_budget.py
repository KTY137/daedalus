"""Regression tests for the browser gate's bounded per-suite budget."""
from __future__ import annotations

import subprocess

import pytest

from tools import gui_check


def test_the_default_budget_is_unchanged_when_nothing_is_set():
    assert gui_check.suite_timeout_s({}) == 600.0
    assert gui_check.SUITE_TIMEOUT_DEFAULT_S == 600


def test_an_operator_can_declare_a_slower_but_still_bounded_budget():
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: "1200"}) == 1200.0
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: " 900.5 "}) == 900.5


@pytest.mark.parametrize(
    "value",
    ["", "   ", "off", "none", "0", "-1", "nan-ish", "1e"],
)
def test_invalid_or_non_positive_values_cannot_remove_the_bound(value: str):
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: value}) == 600.0


def test_timeout_message_is_actionable_and_reports_the_declared_budget():
    message = gui_check.timeout_message(600.0)
    assert "did not finish within 600s" in message
    assert "under load" in message
    assert "stuck" in message
    assert gui_check.SUITE_TIMEOUT_ENV in message
    assert gui_check.timeout_message(1200.0).startswith(
        "the browser suite did not finish within 1200s"
    )


def test_server_output_is_file_backed_instead_of_an_undrained_pipe(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed = {}

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        observed.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(gui_check.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        gui_check,
        "_wait_ready",
        lambda port, proc: (True, "<html>cockpit</html>", ""),
    )

    proc, body, entry, documented_error, output_file = gui_check._start_server(
        tmp_path,
        54321,
        False,
    )
    try:
        assert proc is not None
        assert body == "<html>cockpit</html>"
        assert entry == gui_check.SERVER_ENTRIES[0][0]
        assert documented_error == ""
        assert output_file is not None
        assert observed["stdout"] is output_file
        assert observed["stdout"] is not subprocess.PIPE
        assert observed["stderr"] is subprocess.STDOUT
        assert output_file.seekable()
        assert output_file.fileno() >= 0
    finally:
        if output_file is not None:
            output_file.close()
