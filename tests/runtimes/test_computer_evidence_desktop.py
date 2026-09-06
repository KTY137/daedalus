"""Desktop/application capability: input-vocabulary and postcondition guards.

Packet G1-IKARUS-18 pins target grounding, cancellation and launch args in
`tests/runtimes/test_computer_desktop.py`. Four guards inside
`DesktopAdapter.execute` had no test at all: the `desktop.key` allowlist, the
`desktop.type` character/length bound, the mandatory explicit `expected`
postcondition, and the refusal of caller-supplied `desktop.observe` capture
scope. Plan §7.2 makes the expected postcondition constitutional ("Every action
binds a current observation, target and expected postcondition"), so it needs a
guard test, not only prose.

Offline, deterministic: a fake host stands in for the Windows desktop, and its
`input()` raises, so every refusal case proves *zero* keyboard/mouse effect.
No real capture, no real window, no real key.

Which production change turns these red
(all in `daedalus/runtimes/computer_desktop.py::DesktopAdapter.execute`):

* Deleting the `desktop.key` allowlist ("desktop key is not enabled") — a
  removed allowlist lets `CTRL+ALT+DELETE` / `F4` reach `host.input`.
* Deleting the `desktop.type` bound ("typing requires bounded printable
  Unicode text") — control characters and surrogates would reach `host.input`.
* Deleting the `expected` check ("desktop input requires an explicit expected
  postcondition") — an empty or non-string `expected` would be accepted. The
  cases below keep the argument *key set* exact, so the neighbouring
  `set(args) != ...` check cannot mask the removal.
* Deleting `if args: raise ComputerRefused("desktop.observe takes no caller
  capture scope")` — the adapter would capture under a caller-chosen scope.
"""
from __future__ import annotations

from typing import Any

import pytest

from daedalus.kernel.policy.computer import DESKTOP_TOOLS, ComputerPolicy, ComputerRefused
from daedalus.runtimes.computer_desktop import DesktopAdapter


class RefusingHost:
    """Fake desktop whose input() is a tripwire: any call means an effect leaked."""

    session_id = "evidence-fixture"

    def __init__(self) -> None:
        self.frame = {"window_id": "evidence", "origin_x": 10, "origin_y": 20,
                      "width": 120, "height": 80, "dpi": 96}
        self.png = b"evidence pixels"
        self.captures = 0
        self.inputs: list[tuple[str, Any]] = []

    def snapshot(self, applications: tuple) -> dict[str, Any]:
        return dict(self.frame)

    def capture(self, frame: dict[str, Any]) -> bytes:
        self.captures += 1
        return self.png

    def input(self, kind: str, value: Any) -> None:  # pragma: no cover - tripwire
        self.inputs.append((kind, value))
        raise AssertionError(f"desktop input reached the host: {kind!r}={value!r}")


class RecordingHost(RefusingHost):
    """Same fake, but input() is allowed: used only for the positive controls."""

    def input(self, kind: str, value: Any) -> None:
        self.inputs.append((kind, value))


def _adapter(tmp_path, host: RefusingHost) -> DesktopAdapter:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    policy = ComputerPolicy(workspace, tools=DESKTOP_TOOLS)
    use = DesktopAdapter(policy, lambda: None, tmp_path / "control")
    use._host = host
    return use


def _observed(tmp_path, host: RefusingHost) -> tuple[DesktopAdapter, str, int]:
    use = _adapter(tmp_path, host)
    observation = use.execute("desktop.observe", {})
    return use, observation["observation_id"], host.captures


# --- desktop.key allowlist -------------------------------------------------

@pytest.mark.parametrize("key", ["F4", "CTRL+ALT+DELETE", "ENTER", "WIN", "tab", "CTRL+C", "ALT+F4", ""])
def test_key_outside_the_allowlist_reaches_neither_capture_nor_input(tmp_path, key):
    host = RefusingHost()
    use, observation_id, captures = _observed(tmp_path, host)
    with pytest.raises(ComputerRefused, match="desktop key is not enabled"):
        use.execute("desktop.key", {"observation_id": observation_id,
                                    "key": key, "expected": "some postcondition"})
    assert host.inputs == [] and host.captures == captures


def test_an_enabled_key_still_reaches_the_host(tmp_path):
    """Positive control: the allowlist, not an unrelated check, causes the refusals."""
    host = RecordingHost()
    use, observation_id, _ = _observed(tmp_path, host)
    result = use.execute("desktop.key", {"observation_id": observation_id,
                                         "key": "TAB", "expected": "next control"})
    assert host.inputs == [("key", "TAB")]
    assert result["postcondition_verified"] is False


# --- desktop.type bound ----------------------------------------------------

@pytest.mark.parametrize("text", ["\n", "line\tbreak", "\x00", "bell\x07", "", "x" * 4097, "\ud800"])
def test_unbounded_or_control_text_reaches_neither_capture_nor_input(tmp_path, text):
    host = RefusingHost()
    use, observation_id, captures = _observed(tmp_path, host)
    with pytest.raises(ComputerRefused, match="bounded printable Unicode text"):
        use.execute("desktop.type", {"observation_id": observation_id,
                                     "text": text, "expected": "typed text"})
    assert host.inputs == [] and host.captures == captures


# --- mandatory explicit postcondition -------------------------------------

@pytest.mark.parametrize(
    "tool,extra",
    [("desktop.click", {"x": 3, "y": 4}), ("desktop.type", {"text": "ok"}), ("desktop.key", {"key": "TAB"})],
)
@pytest.mark.parametrize("expected", ["", 1, None, True, "x" * 1001])
def test_input_without_a_usable_expected_postcondition_performs_nothing(tmp_path, tool, extra, expected):
    host = RefusingHost()
    use, observation_id, captures = _observed(tmp_path, host)
    # The key set stays exactly {observation_id, expected, *extra}, so only the
    # postcondition guard itself can produce this refusal.
    args = {"observation_id": observation_id, "expected": expected, **extra}
    with pytest.raises(ComputerRefused, match="explicit expected postcondition"):
        use.execute(tool, args)
    assert host.inputs == [] and host.captures == captures


def test_an_omitted_expected_key_is_refused_as_well(tmp_path):
    host = RefusingHost()
    use, observation_id, captures = _observed(tmp_path, host)
    with pytest.raises(ComputerRefused, match="explicit expected postcondition"):
        use.execute("desktop.click", {"observation_id": observation_id, "x": 1, "y": 2})
    assert host.inputs == [] and host.captures == captures


# --- observe takes no caller scope ----------------------------------------

@pytest.mark.parametrize("args", [{"region": [0, 0, 10, 10]}, {"window_id": "evidence"}, {"full_screen": True}])
def test_caller_supplied_capture_scope_is_refused_before_any_capture(tmp_path, args):
    host = RefusingHost()
    use = _adapter(tmp_path, host)
    with pytest.raises(ComputerRefused, match="takes no caller capture scope"):
        use.execute("desktop.observe", args)
    assert host.captures == 0


def test_scopeless_observe_is_the_admitted_shape(tmp_path):
    """Positive control: the refusals above come from the argument scope check."""
    host = RefusingHost()
    use = _adapter(tmp_path, host)
    observation = use.execute("desktop.observe", {})
    assert host.captures == 1  # one image; the post-capture focus re-check re-reads the frame only
    assert observation["postcondition_verified"] is False
    assert "png" not in observation and "image" not in observation
