"""Browser capability: the refusals that must hold with no Chromium present.

`tests/runtimes/test_computer_browser.py` proves the browser guards against a
real Chromium and a disposable local HTTP fixture. That file opens with
`pytest.importorskip("playwright.sync_api")` and also skips when the Chromium
distribution is missing, so on a host without the optional `computer` extra the
whole browser policy-refusal / stale-target row silently disappears from the
evidence. Plan §11 Gate 1 requires policy refusal and stale-target handling as
*evidence*, so the contract half of it must not depend on an installed browser.

This file is the offline half: no Playwright import, no browser process, no
network. Every case ends in a refusal before the adapter can touch a page.

Which production change turns these red
(all in `daedalus/runtimes/computer_browser.py::BrowserAdapter.execute`):

* Removing `self.policy.admit(tool, args)` from the top of `execute` — a tool
  the owner never enabled, and a navigation to an origin the owner never
  admitted, would both reach `_start()` and launch Chromium. The `_start`
  tripwire below fires in that case.
* Removing the `set(args) != fields` argument fence — extra or missing browser
  arguments would reach the live page.
* Removing the freshness/identity check
  (`not observation or args["observation_id"] != ... or ... > 30`) — a missing,
  replayed or expired observation would reach `self._state()` and drive the
  live page. The exploding-page tripwire below fires in that case.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from daedalus.kernel.policy.computer import BROWSER_TOOLS, ComputerPolicy, ComputerRefused
from daedalus.runtimes.computer_browser import BrowserAdapter

ORIGIN = "http://127.0.0.1:9"
OUTSIDE = "http://127.0.0.1:10"


class BrowserStarted(BaseException):
    """Tripwire: reaching `_start` means a refusal that should have preceded it did not."""


class PageTouched(BaseException):
    """Tripwire: any attribute read on the page means a live interaction leaked."""


class ExplodingPage:
    def __getattr__(self, name: str) -> Any:
        raise PageTouched(f"browser page attribute reached: {name}")


def _adapter(tmp_path, *, origins: tuple[str, ...] = (ORIGIN,)) -> BrowserAdapter:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    policy = ComputerPolicy(workspace, tools=BROWSER_TOOLS, origins=origins)
    return BrowserAdapter(policy, lambda: None, tmp_path / "control")


def _no_start(monkeypatch) -> None:
    def started(self) -> None:
        raise BrowserStarted("browser start reached")

    monkeypatch.setattr(BrowserAdapter, "_start", started)


def _live_page(use: BrowserAdapter) -> None:
    """Make `_start` a no-op early return without importing Playwright.

    `_start` returns immediately when `_page` is already set, so a sentinel page
    lets the post-start guards run offline while proving they touch no page.
    """
    use._page = ExplodingPage()


# --- policy refusal precedes any browser process --------------------------

@pytest.mark.parametrize("tool", ["browser.navigate", "browser.click", "browser.fill"])
def test_a_tool_the_owner_did_not_enable_never_starts_a_browser(tmp_path, monkeypatch, tool):
    _no_start(monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    # Only browser.read is enabled; the other three must refuse before `_start`.
    policy = ComputerPolicy(workspace, tools=("browser.read",), origins=(ORIGIN,))
    use = BrowserAdapter(policy, lambda: None, tmp_path / "control")
    args = {"browser.navigate": {"url": ORIGIN},
            "browser.click": {"observation_id": "x", "selector": "#a"},
            "browser.fill": {"observation_id": "x", "selector": "#a", "text": "t"}}[tool]
    with pytest.raises(ComputerRefused, match="tool is not enabled"):
        use.execute(tool, args)
    # ... while the one enabled tool does reach `_start`.
    with pytest.raises(BrowserStarted):
        use.execute("browser.read", {})


@pytest.mark.parametrize("url", [OUTSIDE, "http://example.invalid/", "https://127.0.0.1:9/",
                                 "http://127.0.0.1:9999/", "http://127.0.0.19:9/"])
def test_navigation_outside_the_admitted_origin_never_starts_a_browser(tmp_path, monkeypatch, url):
    _no_start(monkeypatch)
    use = _adapter(tmp_path)
    with pytest.raises(ComputerRefused, match="browser origin is not enabled"):
        use.execute("browser.navigate", {"url": url})


@pytest.mark.parametrize("url", ["file:///c:/windows/win.ini", "ftp://127.0.0.1/x", "data:text/html,x",
                                 "http://user:pw@127.0.0.1:9/"])
def test_non_http_or_credential_urls_never_start_a_browser(tmp_path, monkeypatch, url):
    _no_start(monkeypatch)
    use = _adapter(tmp_path)
    with pytest.raises(ComputerRefused):
        use.execute("browser.navigate", {"url": url})


def test_the_start_tripwire_is_reachable_for_an_admitted_request(tmp_path, monkeypatch):
    """Positive control: the refusals above really precede `_start`, they are not
    passing because `_start` is unreachable in this fixture."""
    _no_start(monkeypatch)
    use = _adapter(tmp_path)
    with pytest.raises(BrowserStarted):
        use.execute("browser.navigate", {"url": ORIGIN + "/page"})


@pytest.mark.parametrize(
    "tool,args",
    [("browser.navigate", {"url": ORIGIN, "wait": 1}),
     ("browser.read", {"observation_id": "x"}),
     ("browser.click", {"selector": "#a"}),
     ("browser.click", {"observation_id": "x", "selector": "#a", "button": "right"}),
     ("browser.fill", {"observation_id": "x", "selector": "#a"}),
     ("browser.fill", {"observation_id": "x", "selector": "#a", "text": "t", "submit": True})],
)
def test_unknown_or_missing_browser_arguments_never_start_a_browser(tmp_path, monkeypatch, tool, args):
    _no_start(monkeypatch)
    use = _adapter(tmp_path)
    with pytest.raises(ComputerRefused, match="unknown browser arguments"):
        use.execute(tool, args)


def test_navigate_without_a_url_is_refused_by_policy_before_start(tmp_path, monkeypatch):
    """`policy.admit` resolves the origin first, so a missing url dies there."""
    _no_start(monkeypatch)
    use = _adapter(tmp_path)
    with pytest.raises(ComputerRefused, match="invalid URL"):
        use.execute("browser.navigate", {})


def test_cancellation_before_start_leaves_no_browser(tmp_path, monkeypatch):
    _no_start(monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    policy = ComputerPolicy(workspace, tools=BROWSER_TOOLS, origins=(ORIGIN,))

    def cancelled() -> None:
        raise ComputerRefused("computer work was cancelled")

    use = BrowserAdapter(policy, cancelled, tmp_path / "control")
    with pytest.raises(ComputerRefused, match="cancelled"):
        use.execute("browser.navigate", {"url": ORIGIN})


# --- stale target handling, offline ---------------------------------------

@pytest.mark.parametrize("tool", ["browser.click", "browser.fill"])
def test_input_without_any_observation_never_touches_the_page(tmp_path, tool):
    use = _adapter(tmp_path)
    _live_page(use)
    args = {"observation_id": "0" * 32, "selector": "#a"}
    if tool == "browser.fill":
        args["text"] = "typed"
    with pytest.raises(ComputerRefused, match="fresh browser observation required"):
        use.execute(tool, args)


@pytest.mark.parametrize("drift", ["replayed_id", "expired"])
def test_a_replayed_or_expired_observation_never_touches_the_page(tmp_path, drift):
    use = _adapter(tmp_path)
    _live_page(use)
    created = time.monotonic() - (31 if drift == "expired" else 0)
    use._observation = {"observation_id": "a" * 32, "url": ORIGIN + "/page",
                        "document_sha256": "d" * 64, "created": created}
    presented = "a" * 32 if drift == "expired" else "b" * 32
    with pytest.raises(ComputerRefused, match="fresh browser observation required"):
        use.execute("browser.click", {"observation_id": presented, "selector": "#a"})


def test_the_page_tripwire_is_reachable_for_a_fresh_observation(tmp_path):
    """Positive control: a fresh, matching observation does reach the live page,
    so the refusals above are produced by the freshness guard itself."""
    use = _adapter(tmp_path)
    _live_page(use)
    use._observation = {"observation_id": "a" * 32, "url": ORIGIN + "/page",
                        "document_sha256": "d" * 64, "created": time.monotonic()}
    with pytest.raises(PageTouched):
        use.execute("browser.click", {"observation_id": "a" * 32, "selector": "#a"})


def test_the_adapter_module_does_not_import_playwright_at_module_scope():
    """These refusals must hold on a host without the optional computer extra:
    Playwright is imported lazily inside `_start`, never at import time."""
    import sys

    module = sys.modules["daedalus.runtimes.computer_browser"]
    assert not hasattr(module, "sync_playwright")
    assert not hasattr(module, "playwright")
