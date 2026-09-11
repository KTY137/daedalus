from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, DESKTOP_TOOLS
from daedalus.runtimes.computer_desktop import DesktopAdapter


class FakeDesktop:
    session_id = "fixture"

    def __init__(self):
        self.frame = {"window_id": "fixture", "origin_x": -200, "origin_y": 20,
                      "width": 100, "height": 60, "dpi": 144}
        self.png = b"fixture pixels"
        self.inputs = []
        self.captures = 0

    def snapshot(self, applications):
        return dict(self.frame)

    def capture(self, frame):
        self.captures += 1
        return self.png

    def input(self, kind, value):
        self.inputs.append((kind, value))


def adapter(tmp_path, checkpoint=lambda: None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    policy = ComputerPolicy(workspace, tools=DESKTOP_TOOLS,
                            applications=(("fixture", (str((tmp_path / "owner-app" / "fixture-editor.exe").resolve()),)),))
    result = DesktopAdapter(policy, checkpoint, tmp_path / "control")
    result._host = FakeDesktop()
    return result


def test_capture_is_private_and_click_maps_negative_monitor_coordinates(tmp_path):
    use = adapter(tmp_path)
    observation = use.execute("desktop.observe", {})
    assert "png" not in observation and "image" not in observation
    png, frame = use.capture_png(observation["observation_id"])
    assert png == b"fixture pixels" and frame["dpi"] == 144
    result = use.execute("desktop.click", {"observation_id": observation["observation_id"],
                         "x": 7, "y": 8, "expected": "fixture selection"})
    assert use._host.inputs == [("click", (-193, 28))]
    assert result["postcondition_verified"] is False
    with pytest.raises(ComputerRefused, match="fresh"):
        use.execute("desktop.click", {"observation_id": observation["observation_id"],
                    "x": 7, "y": 8, "expected": "fixture selection"})


@pytest.mark.parametrize("change", ["pixels", "focus", "age"])
def test_changed_or_stale_observation_performs_zero_input(tmp_path, change):
    use = adapter(tmp_path)
    observation = use.execute("desktop.observe", {})
    if change == "pixels":
        use._host.png = b"changed pixels"
    elif change == "focus":
        use._host.frame["window_id"] = "other"
    else:
        use._observation["created"] -= 31
    with pytest.raises(ComputerRefused):
        use.execute("desktop.type", {"observation_id": observation["observation_id"],
                    "text": "unsafe repeat", "expected": "fixture text"})
    assert use._host.inputs == []


def test_focus_change_during_capture_discards_image(tmp_path):
    use = adapter(tmp_path)
    def capture(frame):
        use._host.frame["window_id"] = "foreign"
        return b"pixels"
    use._host.capture = capture
    with pytest.raises(ComputerRefused, match="during capture"):
        use.execute("desktop.observe", {})
    assert use._png is None


def test_cancel_mid_typing_prevents_next_input_and_replay(tmp_path):
    cancelled = False
    def checkpoint():
        if cancelled:
            raise RuntimeError("cancelled")
    use = adapter(tmp_path, checkpoint)
    observation = use.execute("desktop.observe", {})
    def input(kind, value):
        nonlocal cancelled
        use._host.inputs.append((kind, value))
        cancelled = True
    use._host.input = input
    with pytest.raises(RuntimeError, match="cancelled"):
        use.execute("desktop.type", {"observation_id": observation["observation_id"],
                    "text": "AB", "expected": "two characters"})
    assert use._host.inputs == [("text", "A")]
    assert use._observation is None


def test_unknown_input_outcome_consumes_token(tmp_path):
    use = adapter(tmp_path)
    observation = use.execute("desktop.observe", {})
    def input(kind, value):
        raise RuntimeError("unknown outcome")
    use._host.input = input
    with pytest.raises(RuntimeError, match="unknown"):
        use.execute("desktop.key", {"observation_id": observation["observation_id"],
                    "key": "TAB", "expected": "next control"})
    assert use._observation is None


def test_fixed_launch_args_and_denial_precede_process_creation(tmp_path, monkeypatch):
    use = adapter(tmp_path)
    calls = []
    monkeypatch.setattr("daedalus.runtimes.computer_desktop.subprocess.Popen", lambda *a, **k: calls.append(a))
    with pytest.raises(ComputerRefused, match="fixed"):
        use.execute("app.launch", {"application": "fixture", "args": ["-c", "unapproved"]})
    assert calls == []


def test_policy_denial_precedes_capture(tmp_path):
    policy = ComputerPolicy(tmp_path, tools=())
    use = DesktopAdapter(policy, lambda: None, tmp_path / "control")
    use._host = FakeDesktop()
    with pytest.raises(ComputerRefused, match="not enabled"):
        use.execute("desktop.observe", {})
    assert use._host.captures == 0


def test_outside_window_refuses_without_recapture(tmp_path):
    use = adapter(tmp_path)
    observation = use.execute("desktop.observe", {})
    with pytest.raises(ComputerRefused, match="outside"):
        use.execute("desktop.click", {"observation_id": observation["observation_id"],
                    "x": 100, "y": 0, "expected": "target"})
    assert use._host.captures == 1 and use._host.inputs == []


def test_desktop_lock_contention_prevents_input(tmp_path):
    from daedalus.atomic import ExclusiveFileLock, FileLockUnavailable
    use = adapter(tmp_path)
    with ExclusiveFileLock(tmp_path / "computer-desktop-session-fixture.lock"):
        with pytest.raises(FileLockUnavailable):
            use.execute("desktop.observe", {})
    assert use._host.captures == 0
