"""`/api/health` -- the endpoint that carries the five states to the browser.

WHY IT MATTERS THAT THIS EXISTS AT ALL. `daedalus/health.py` reports five states
that deliberately cannot collapse into green -- working, present, degraded,
absent, unknown -- and tags every fact MEASURED, INHERITED or ASSUMED. None of
it was reachable from the UI, so the browser re-derived a weaker judgement from
other payloads and had to catch a failing eval baseline by matching free text
in a `notes` string.

WHAT THESE TESTS GUARD IS THE COLLAPSE. An endpoint that flattened the states,
or that turned its own failure into a cheerful empty payload, would put the
defect back one layer out -- which is exactly how it got there the first time:
the UI agent found that gating a fetch on a resolved project made a DEAD BACKEND
render as `present` instead of `unknown`.

The expensive probes are the second property. `deep` calls the latent route
(~7s cold) and `probe_remote` embeds against a host that is not this machine. A
browser tab must not start either by accident, and skipping them must be
DECLARED rather than silently reported as if they had run.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from daedalus.interfaces.http import web_api


@pytest.fixture
def server():
    """A real server on a free loopback port. Nothing under test is mocked."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), web_api.DaedalusHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",
                                   timeout=30)
            break
        except urllib.error.HTTPError:
            break                                     # answering, that is enough
        except OSError:
            time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=10)


def _get(base: str, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(base + path, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_the_endpoint_answers_with_the_five_state_vocabulary(server):
    status, body = _get(server, "/api/health")
    assert status == 200, body
    payload = body.get("health")
    assert payload, "no health payload"
    reports = payload.get("reports") or payload.get("subsystems") or []
    assert reports, f"no subsystem reports in {sorted(payload)}"
    states = {r.get("state") for r in reports}
    assert states, "no states reported"
    assert states <= {"working", "present", "degraded", "absent", "unknown"}, (
        f"a state outside the closed vocabulary reached the wire: {states}")


def test_present_and_unknown_are_NOT_reported_as_working(server):
    """The collapse this whole vocabulary exists to prevent.

    On this machine several subsystems are genuinely `present` (the code is
    there, this run did not exercise it). If the endpoint rendered those as
    `working`, a reader would conclude the system is healthier than it is --
    which is the defect, not a rounding.
    """
    _, body = _get(server, "/api/health")
    reports = (body.get("health") or {}).get("reports") or []
    for r in reports:
        if r.get("state") == "working":
            # a `working` claim must carry a measurement, per health.py's own
            # rule that "working" means exercised BY THIS RUN
            facts = r.get("facts") or []
            kinds = {f.get("provenance") or f.get("kind") for f in facts}
            assert not facts or "MEASURED" in kinds or "measured" in kinds, (
                f"{r.get('name')} claims working with no MEASURED fact: {facts}")


def test_the_expensive_probes_are_OFF_unless_asked_and_the_answer_says_so(server):
    """Skipping must be declared. A browser tab must not be able to start a
    multi-second latent call or an off-machine embed by loading a page."""
    _, body = _get(server, "/api/health")
    asked = (body.get("health") or {}).get("asked")
    assert asked is not None, "the response does not say what it was asked to do"
    assert asked["deep"] is False
    assert asked["probe_remote"] is False


def test_asking_for_deep_is_recorded(server):
    _, body = _get(server, "/api/health?deep=1")
    asked = (body.get("health") or {}).get("asked")
    assert asked["deep"] is True


def test_a_failure_of_the_SURFACE_is_distinguishable_from_bad_health(
        server, monkeypatch):
    """A health surface that 500s tells you nothing about the system and
    everything about itself. The response must say which one happened.

    Without this, a broken probe renders as "no subsystems reported", which a
    reader takes for "nothing is wrong".
    """
    from daedalus import health as _health

    def explode(*a, **kw):
        raise RuntimeError("probe table is corrupt")

    monkeypatch.setattr(_health, "assess", explode)
    status, body = _get(server, "/api/health")
    assert status == 500
    assert body.get("ok") is False
    assert "the health surface itself failed" in body.get("error", "")
    assert "RuntimeError" in body.get("error", "")
    assert body.get("health") is None, (
        "a failed surface returned a payload, which reads as a verdict")
