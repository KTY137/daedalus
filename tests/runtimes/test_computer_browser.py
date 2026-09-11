from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from daedalus.kernel.policy.computer import BROWSER_TOOLS, ComputerPolicy, ComputerRefused
from daedalus.runtimes.computer_browser import BrowserAdapter


@pytest.fixture
def browser(tmp_path):
    pytest.importorskip("playwright.sync_api")
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append(("GET", self.path))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/denied")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'''<html><body><h1>Local fixture</h1>
            <input id="name"><input id="password" type="password">
            <button type="button" id="local" onclick="document.querySelector('h1').textContent='Clicked'">Local button</button>
            <button class="duplicate" type="button">One</button><button class="duplicate" type="button">Two</button>
            <form method="post"><button id="submit">Submit</button></form>
            <a id="outside" href="http://127.0.0.1:1/denied">Outside</a>
            <a id="download" href="/export" download>Download</a>
            <a id="redirect" href="/redirect">Redirect</a>
            <button type="button" id="fetch" onclick="fetch('/mutate',{method:'POST'})">Mutation</button>
            </body></html>''')
        def do_POST(self):
            requests.append(("POST", self.path))
            self.send_response(200)
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    policy = ComputerPolicy(tmp_path, tools=BROWSER_TOOLS, origins=(url,))
    use = BrowserAdapter(policy, lambda: None, tmp_path / "control")
    try:
        try:
            initial = use.execute("browser.navigate", {"url": url})
        except ComputerRefused as exc:
            if "initialization unavailable" in str(exc):
                pytest.skip("Playwright Chromium distribution unavailable")
            raise
        yield use, initial, requests, url
    finally:
        use.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_live_fill_works_but_dynamic_script_actions_remain_unavailable(browser):
    use, initial, requests, url = browser
    result = use.execute("browser.fill", {"observation_id": initial["observation_id"], "selector": "#name", "text": "Ikarus"})
    assert result["field_value_verified"] is True
    assert result["postcondition_verified"] is False
    result = use.execute("browser.click", {"observation_id": result["observation_id"], "selector": "#local"})
    assert "Clicked" not in result["text"]
    assert result["page_javascript"] is False
    assert result["dynamic_applications_available"] is False
    assert result["untrusted_page_content"] is True


@pytest.mark.parametrize("selector", [".duplicate", "#submit", "#outside", "#download"])
def test_ambiguous_submission_and_external_target_refused(browser, selector):
    use, observation, requests, _ = browser
    with pytest.raises(ComputerRefused):
        use.execute("browser.click", {"observation_id": observation["observation_id"], "selector": selector})
    assert all(method == "GET" for method, _ in requests)


def test_password_fields_and_replayed_observations_refused(browser):
    use, observation, _, _ = browser
    with pytest.raises(ComputerRefused, match="credential"):
        use.execute("browser.fill", {"observation_id": observation["observation_id"], "selector": "#password", "text": "secret"})
    use.execute("browser.fill", {"observation_id": observation["observation_id"], "selector": "#name", "text": "first"})
    with pytest.raises(ComputerRefused, match="fresh"):
        use.execute("browser.fill", {"observation_id": observation["observation_id"], "selector": "#name", "text": "duplicate"})


def test_document_mutation_refuses_before_input(browser):
    use, observation, _, _ = browser
    use._page.evaluate("document.querySelector('#name').value='changed by app'")
    with pytest.raises(ComputerRefused, match="changed"):
        use.execute("browser.fill", {"observation_id": observation["observation_id"], "selector": "#name", "text": "must not write"})
    assert use._page.locator("#name").input_value() == "changed by app"


def test_redirect_is_not_followed(browser):
    use, _, requests, url = browser
    with pytest.raises(ComputerRefused, match="navigation"):
        use.execute("browser.navigate", {"url": url + "/redirect"})
    assert "redirect" in " ".join(use._refusals)


def test_page_script_cannot_submit_non_read_request(browser):
    use, observation, requests, _ = browser
    use.execute("browser.click", {"observation_id": observation["observation_id"], "selector": "#fetch"})
    use.execute("browser.read", {})
    assert not any(method == "POST" for method, _ in requests)
    assert not any(path == "/mutate" for _, path in requests)


def test_script_execution_and_connect_channels_are_disabled(browser):
    use, _, _, _ = browser
    # Trusted DevTools evaluation remains available for DOM measurements;
    # page-injected scripts and event handlers do not execute.
    use._page.evaluate("""() => { window.scriptRan = false;
        const script = document.createElement('script');
        script.textContent = 'window.scriptRan=true'; document.body.appendChild(script); }""")
    assert use._page.evaluate("window.scriptRan") is False


def test_cancellation_stops_before_browser_start(tmp_path):
    def checkpoint():
        raise RuntimeError("cancelled")
    policy = ComputerPolicy(tmp_path, tools=BROWSER_TOOLS, origins=("http://127.0.0.1:1",))
    use = BrowserAdapter(policy, checkpoint, tmp_path / "control")
    with pytest.raises(RuntimeError, match="cancelled"):
        use.execute("browser.navigate", {"url": "http://127.0.0.1:1"})
    assert use._runtime is None
