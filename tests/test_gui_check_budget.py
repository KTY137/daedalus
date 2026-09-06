"""The browser gate's per-suite budget, and why it is overridable.

`tools/gui_check.py` is the documented way to run the browser acceptance
suite -- `playwright.config.ts` says "Run it through the harness, never by
hand". Its per-suite budget was a hard-coded 600s, sized for a machine
running only this.

[MEASURED 2026-09-03] the shell suite took 13.9 minutes on this box while
parallel agent sessions held ~87 python processes. The harness therefore
reported ``VERDICT: FAIL -- the cockpit does not do what it says`` for a
suite whose 45 specs were, in the same minutes, all green. A FAIL that
means "the machine was busy" is exactly the kind of number this repository
refuses to report, and the practical consequence was that the browser gate
could not be run here at all.

The override does not weaken the gate: the default is unchanged, a timeout
is still a FAIL, and a value that is not a positive number is IGNORED
rather than obeyed -- otherwise a typo would be a way to remove the bound.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from tools import gui_check


def test_the_default_budget_is_unchanged_when_nothing_is_set():
    assert gui_check.suite_timeout_s({}) == 600.0
    assert gui_check.SUITE_TIMEOUT_DEFAULT_S == 600


def test_an_operator_can_say_how_slow_their_box_is():
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: "1800"}) == 1800.0
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: " 900.5 "}) == 900.5


@pytest.mark.parametrize("value", ["", "   ", "off", "none", "0", "-1", "nan-ish", "1e"])
def test_a_value_that_is_not_a_positive_number_cannot_remove_the_bound(value: str):
    """A typo must not be a way to disable the timeout. Every one of these
    falls back to the default rather than becoming "no limit"."""
    assert gui_check.suite_timeout_s({gui_check.SUITE_TIMEOUT_ENV: value}) == 600.0


def test_the_timeout_message_tells_the_operator_what_to_do():
    """A verdict that cannot be acted on costs the next person an hour.

    The first version of this test asserted against the module's SOURCE and
    passed for the wrong reason -- the name appears there inside an f-string
    placeholder, not in anything a human ever reads. It asserts the produced
    message now.
    """
    message = gui_check.timeout_message(600.0)
    assert "did not finish within 600s" in message
    # both causes named, so nobody has to guess which one they have
    assert "under load" in message
    assert "stuck" in message
    # and the lever is in the sentence, not only in the source
    assert gui_check.SUITE_TIMEOUT_ENV in message
    assert gui_check.timeout_message(1800.0).startswith(
        "the browser suite did not finish within 1800s"
    )


def test_the_growing_shell_is_split_into_serial_bounded_invocations():
    plan = gui_check._suite_plan()

    assert [label for label, _ in plan] == [
        "shell-1/4",
        "shell-2/4",
        "shell-3/4",
        "shell-4/4",
        "loop-ui",
    ]
    for current, (_, arguments) in enumerate(plan[:-1], 1):
        assert arguments == [
            "--grep-invert",
            "@loopui",
            "--shard",
            f"{current}/{gui_check.SHELL_SHARDS}",
        ]
    assert plan[-1][1] == ["--grep", "@loopui"]


def test_the_outer_budget_covers_every_bounded_phase():
    assert gui_check.aggregate_timeout_s({}) == 3370
    assert gui_check.aggregate_timeout_s(
        {gui_check.SUITE_TIMEOUT_ENV: "900"}
    ) == 4870


def test_the_live_browser_fixture_names_this_checkout_and_is_removed(tmp_path):
    root = tmp_path / "specimen"
    root.mkdir()

    name, path = gui_check._acceptance_project_target(root)
    gui_check._install_acceptance_project(root, name, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert name.startswith("000_gui_acceptance_")
    assert payload["name"] == name
    assert payload["repo_root"] == str(root.resolve())
    assert path.parent == (root / "projects").resolve()
    assert gui_check._remove_acceptance_project(path) == ""
    assert not path.exists()
    assert (root / "projects").is_dir()


def test_fixture_cleanup_preserves_an_existing_project_registry(tmp_path):
    root = tmp_path / "specimen"
    registry = root / "projects"
    registry.mkdir(parents=True)
    retained = registry / "owner.json"
    retained.write_text("{}\n", encoding="utf-8")

    name, path = gui_check._acceptance_project_target(root)
    gui_check._install_acceptance_project(root, name, path)

    assert gui_check._remove_acceptance_project(path) == ""
    assert retained.read_text(encoding="utf-8") == "{}\n"


def test_fixture_target_is_known_before_an_interrupted_atomic_publish(
    tmp_path, monkeypatch
):
    root = tmp_path / "specimen"
    root.mkdir()
    name, path = gui_check._acceptance_project_target(root)
    publish = gui_check.publish_bytes_once

    def publish_then_interrupt(target, data):
        assert publish(target, data) is True
        raise KeyboardInterrupt

    monkeypatch.setattr(gui_check, "publish_bytes_once", publish_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        try:
            gui_check._install_acceptance_project(root, name, path)
        finally:
            assert gui_check._remove_acceptance_project(path) == ""
    assert not path.exists()


def test_fixture_cleanup_reports_a_locked_row_without_raising(tmp_path, monkeypatch):
    path = tmp_path / "owned.json"
    path.write_text("{}\n", encoding="utf-8")

    def locked(*_args, **_kwargs):
        raise OSError(32, "sharing violation")

    monkeypatch.setattr(gui_check.Path, "unlink", locked)
    detail = gui_check._remove_acceptance_project(path, retry_s=0)
    assert "could not remove acceptance-project row" in detail


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


def test_playwright_budget_reaches_declared_cold_scan_waits_and_fails_fast():
    config = (
        gui_check.ROOT / "apps" / "web" / "playwright.config.ts"
    ).read_text(encoding="utf-8")

    assert "timeout: 360_000" in config
    assert "maxFailures: 1" in config
