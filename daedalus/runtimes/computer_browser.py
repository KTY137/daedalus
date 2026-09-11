"""Private, disposable browser adapter behind canonical computer admission.

No ambient profile, cookies or client secrets are loaded. Browser observations
are untrusted page content. Form submission, downloads, websocket traffic and
non-read HTTP methods have no authority in this initial adapter. Page JavaScript
is disabled: dynamic applications remain unavailable. These controls are not a
complete network firewall or proof that an arbitrary server treats GET safely.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, origin


class BrowserAdapter:
    def __init__(self, policy: ComputerPolicy, checkpoint: Callable[[], None], control_root: Path) -> None:
        self.policy, self.checkpoint, self.control_root = policy, checkpoint, Path(control_root)
        self._runtime: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._thread: int | None = None
        self._observation: dict[str, Any] | None = None
        self._refusals: list[str] = []

    def _network(self, route: Any) -> None:
        request = route.request
        response = None
        try:
            self.checkpoint()
            if origin(request.url) not in self.policy.origins or request.method not in {"GET", "HEAD"}:
                raise ComputerRefused("browser request origin or method is not admitted")
            # Fetch with redirect following disabled. route.continue_ alone
            # does not promise interception of each hop in a redirect chain.
            response = route.fetch(max_redirects=0, timeout=10000)
            if 300 <= response.status < 400 and response.status != 304:
                raise ComputerRefused("browser redirect requires a separately admitted navigation")
            headers = dict(response.headers)
            if "attachment" in headers.get("content-disposition", "").lower():
                raise ComputerRefused("browser downloads are unavailable in this adapter")
            # This additional CSP intersects with any policy supplied by the
            # page. Submission/embedded worker channels cannot grant effects.
            sources = " ".join(self.policy.origins)
            restriction = (
                "default-src 'none'; script-src 'none'; connect-src 'none'; "
                "media-src 'none'; form-action 'none'; frame-src 'none'; "
                "worker-src 'none'; object-src 'none'; base-uri 'none'; "
                f"img-src data: {sources}; style-src 'unsafe-inline' {sources}; font-src {sources}"
            )
            current = headers.get("content-security-policy")
            headers["content-security-policy"] = (current + ", " if current else "") + restriction
            self.checkpoint()
            route.fulfill(response=response, headers=headers)
        except Exception as exc:
            self._refusals.append(str(exc)[:200])
            del self._refusals[:-20]
            route.abort("blockedbyclient")
        finally:
            if response is not None:
                response.dispose()

    def _start(self) -> None:
        if self._thread is not None and self._thread != threading.get_ident():
            raise ComputerRefused("browser session must remain on its owning worker thread")
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ComputerRefused("browser unavailable; install the computer extra and Playwright Chromium") from exc
        self.checkpoint()
        self._thread = threading.get_ident()
        try:
            self._runtime = sync_playwright().start()
            self.checkpoint()
            self._browser = self._runtime.chromium.launch(headless=True, args=[
                "--disable-background-networking", "--disable-quic", "--dns-prefetch-disable",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
            self.checkpoint()
            self._context = self._browser.new_context(
                accept_downloads=False, service_workers="block", java_script_enabled=False,
            )
            self._context.set_default_timeout(5000)
            self._context.route("**/*", self._network)
            self._context.route_web_socket("**/*", lambda route: route.close())
            self.checkpoint()
            self._page = self._context.new_page()
            self._page.on("dialog", lambda dialog: dialog.dismiss())
            self._page.on("popup", lambda popup: popup.close())
        except Exception as exc:
            self.close()
            raise ComputerRefused(f"browser initialization unavailable: {type(exc).__name__}") from exc

    def close(self) -> None:
        """Release disposable processes; cleanup remains allowed after cancel."""
        for item, method in ((self._context, "close"), (self._browser, "close"), (self._runtime, "stop")):
            if item is not None:
                try:
                    getattr(item, method)()
                except Exception:
                    pass
        self._runtime = self._browser = self._context = self._page = None
        self._observation, self._thread = None, None

    def _state(self) -> tuple[str, str]:
        self.checkpoint()
        url = self._page.url
        if origin(url) not in self.policy.origins:
            raise ComputerRefused("browser left its admitted origin")
        # Include values in the digest only, never in returned read content.
        state = self._page.evaluate("""() => JSON.stringify({html: document.documentElement.outerHTML,
            values: Array.from(document.querySelectorAll('input,textarea,select')).map(e => [e.value,e.checked])})""")
        return url, hashlib.sha256(state.encode("utf-8")).hexdigest()

    def _observe(self) -> dict[str, Any]:
        url, digest = self._state()
        text = self._page.locator("body").inner_text()[:20000]
        controls = self._page.locator("input,textarea,select,button,a[href]").evaluate_all("""els => els.slice(0,100).map(e => ({
            tag:e.tagName.toLowerCase(),id:e.id,type:e.type||'',name:e.getAttribute('name')||'',
            text:(e.innerText||e.getAttribute('aria-label')||'').slice(0,200)}))""")
        if self._state() != (url, digest):
            raise ComputerRefused("browser document changed during observation")
        self._observation = {"observation_id": uuid.uuid4().hex, "url": url, "document_sha256": digest,
                             "created": time.monotonic()}
        return {"status": "observed", **{k: v for k, v in self._observation.items() if k != "created"},
                "text": text, "controls": controls, "untrusted_page_content": True,
                "network_refusals": list(self._refusals), "postcondition_verified": False,
                "page_javascript": False, "dynamic_applications_available": False}

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.policy.admit(tool, args)
        if tool not in {"browser.navigate", "browser.read", "browser.click", "browser.fill"}:
            raise ComputerRefused("unsupported browser tool")
        fields = {"browser.navigate": {"url"}, "browser.read": set(),
                  "browser.click": {"observation_id", "selector"},
                  "browser.fill": {"observation_id", "selector", "text"}}[tool]
        if set(args) != fields:
            raise ComputerRefused("unknown browser arguments")
        self.checkpoint()
        self._start()
        if tool == "browser.navigate":
            self._observation = None
            self._refusals = []
            self.checkpoint()
            try:
                self._page.goto(args["url"], wait_until="domcontentloaded", timeout=10000)
            except Exception as exc:
                raise ComputerRefused("browser navigation failed or was refused; no success claimed") from exc
            return self._observe()
        if tool == "browser.read":
            return self._observe()
        observation = self._observation
        if not observation or args["observation_id"] != observation["observation_id"] or time.monotonic() - observation["created"] > 30:
            raise ComputerRefused("fresh browser observation required")
        if self._state() != (observation["url"], observation["document_sha256"]):
            self._observation = None
            raise ComputerRefused("browser document changed; observe again")
        selector = args["selector"]
        if not isinstance(selector, str) or not 1 <= len(selector) <= 2000:
            raise ComputerRefused("browser selector must be bounded text")
        target = self._page.locator(selector)
        if target.count() != 1 or not target.is_visible() or not target.is_enabled():
            raise ComputerRefused("browser target is missing, ambiguous or unavailable")
        kind = target.evaluate("""e => ({tag:e.tagName.toLowerCase(),type:e.type||'',href:e.href||'',
            form:!!e.form,editable:e.isContentEditable,download:e.hasAttribute('download')})""")
        if kind["type"] in {"password", "file", "hidden"}:
            raise ComputerRefused("credential/file browser fields require unavailable separate authority")
        if tool == "browser.fill":
            if kind["tag"] not in {"input", "textarea"} or kind["type"] not in {"text", "search", "email", "url", "tel", "number", "textarea", ""}:
                raise ComputerRefused("browser target is not a supported text field")
            if not isinstance(args["text"], str) or len(args["text"]) > 4096:
                raise ComputerRefused("browser fill text exceeds its bound")
        elif (kind["tag"] not in {"a", "button", "input"}
              or kind["type"] in {"submit", "image", "reset"}
              or kind["download"]
              or (kind["tag"] == "a" and (not kind["href"] or origin(kind["href"]) not in self.policy.origins))):
            raise ComputerRefused("browser target would submit or lacks an admitted action")
        # Consume before triggering the page, including failure/unknown outcome.
        self._observation = None
        self.checkpoint()
        if tool == "browser.fill":
            target.fill(args["text"], timeout=5000)
            if target.input_value() != args["text"]:
                raise ComputerRefused("browser field value did not match requested text")
        else:
            target.click(timeout=5000, no_wait_after=True)
        result = self._observe()
        if tool == "browser.fill":
            result["field_value_verified"] = True
        return result
