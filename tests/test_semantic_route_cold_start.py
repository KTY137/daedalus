"""A COLD embedding model is not a dead host -- and the latent route survives it.

THE DEFECT THIS FILE EXISTS TO KEEP FIXED
-----------------------------------------
``daedalus/orchestration/semantic_route.py`` was fully wired into
``provider_router.route_and_select``, covered by two test files, and listed as a
shipped feature. It had also never once run in production.

Every embedding call shared one hardcoded ``timeout=10``, including the call
that pulls the model into memory. MEASURED 2026-07-29 against the backend this
repo ships with (``nomic-embed-text`` on 127.0.0.1:11434):

    cold first call ... 15.48s   -> blew the 10s cap
    the same, warm ...  0.18s

So on every freshly started process the first role embedding timed out,
``_role_vectors_detailed`` aborted the whole batch, and routing degraded to
keywords while the receipt blamed ``host_unreachable`` -- about a host that was
up and 0.18s away. Failures are deliberately never cached, so each later call
paid another 10s and degraded again.

MEASURED through ``route_and_select`` on the real backend, before and after:

    before ... latent ran 0 of 5 probes, changed the outcome on 0
    after .... latent ran 4 of 5 probes, changed the outcome on 3
               (the 5th was the lane guard correctly overruling a cross-lane
               steer, which is the guard working, not the route failing)

WHY THESE TESTS GO THROUGH ``route_and_select``
-----------------------------------------------
Calling ``_embed_detailed`` directly would prove the timeout argument is passed
and nothing else. The bug was never in that function -- it was in which budget
the CALLER handed it, so the caller is what gets exercised. ``route_and_select``
is the seam ``offload`` uses.

NOTHING in ``semantic_route`` is mocked. Each test starts a real HTTP server
speaking the Ollama ``/api/embeddings`` protocol, and makes it SLOW on purpose.
Only the backend is fake.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from daedalus.orchestration import semantic_route as sr
from daedalus.provider_router import LATENT_ENV, route_and_select
from daedalus.router import load_agents

AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}

# Budgets are scaled DOWN so the suite stays fast; the shape is what is pinned,
# not the wall-clock numbers. WARM must be too small for a cold load and COLD
# must be comfortably larger -- that ratio is the whole fix.
WARM_S = 0.25
COLD_S = 10.0
#: Longer than WARM_S, far shorter than COLD_S: the cold call survives only if
#: it is given the cold budget.
COLD_LOAD_S = 1.0
#: Longer than both, so nothing can rescue it.
FOREVER_S = 30.0


def _distinct_vector(text: str, dim: int) -> list[float]:
    """A valid embedding that is DIFFERENT for every distinct prompt.

    Deliberately not ``hash()``: PYTHONHASHSEED is randomised per process, so a
    ``hash()``-derived fixture collides on some runs and not others. Two roles
    landing on the same vector is a tie, which ``semantic_route`` correctly
    refuses as "no discriminating signal" -- a real behaviour, but not the one
    under test here, and it made this file fail intermittently.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(digest[i % len(digest)] / 255.0) + 0.01 for i in range(dim)]


class SlowOllama:
    """An /api/embeddings server whose Nth response can be made slow.

    ``delays`` maps a 1-based call index to seconds to sleep BEFORE answering,
    which is how a model load looks from the client: the connection is
    accepted, then nothing arrives for a while.
    """

    def __init__(self, delays: dict[int, float] | None = None, dim: int = 8):
        self.delays = delays or {}
        self.dim = dim
        self.prompts: list[str] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                with outer._lock:
                    outer.prompts.append(payload.get("prompt", ""))
                    n = len(outer.prompts)
                delay = outer.delays.get(n, 0.0)
                if delay:
                    time.sleep(delay)
                vec = _distinct_vector(payload.get("prompt", ""), outer.dim)
                raw = json.dumps({"embedding": vec}).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    # The client already gave up and closed the socket. That is
                    # the scenario under test, not an error.
                    pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def host(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.prompts)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _free_port() -> int:
    """A port with nothing listening -- a genuinely absent host, which fails
    with a refused connection rather than a deadline."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _ColdCase(unittest.TestCase):
    """Cache isolation plus a fully pinned environment.

    Both budgets are pinned on every test: inheriting an operator's exported
    ``DAEDALUS_EMBED_*`` would make these pass or fail based on the box, which
    is the machine-dependence ``tests/conftest.py`` exists to remove.
    """

    ENV = {
        "OLLAMA_EMBED_MODEL": "fake-embed",
        sr.EMBED_TIMEOUT_ENV: str(WARM_S),
        sr.EMBED_COLD_TIMEOUT_ENV: str(COLD_S),
    }

    def setUp(self):
        sr.cache_clear()
        self.addCleanup(sr.cache_clear)
        env = patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        # conftest pins the latent route OFF for the whole suite; it is the
        # SUBJECT here, so re-enable it inside the patch that restores it.
        os.environ.pop(LATENT_ENV, None)
        self.role_count = len(load_agents())
        self.assertGreater(self.role_count, 1, "fixture needs a real roster")

    def serve(self, delays=None) -> SlowOllama:
        server = SlowOllama(delays)
        self.addCleanup(server.stop)
        env = patch.dict(os.environ, {"OLLAMA_HOST": server.host})
        env.start()
        self.addCleanup(env.stop)
        return server

    def receipt(self, objective="make the plot legible", paths=None):
        _, decision = route_and_select(objective, paths or [], AVAIL)
        return decision.latent_route


class ColdStartSurvivesTests(_ColdCase):
    """The ALLOW half: a slow first call must not kill the feature."""

    def test_a_cold_first_call_does_not_kill_the_latent_route(self):
        """THE REGRESSION TEST. Reinstate one shared timeout and this goes red.

        The first embedding takes longer than the warm budget and far less than
        the cold one -- exactly the shape of a model load. If the cold call is
        handed the warm budget (the old behaviour), the batch aborts and the
        mechanism is ``keyword_fallback``.
        """
        server = self.serve({1: COLD_LOAD_S})

        receipt = self.receipt()

        self.assertEqual(
            receipt["mechanism"], sr.LATENT,
            msg=f"the cold first call killed the route again: {receipt}")
        self.assertTrue(receipt["ran"])
        self.assertIsNone(receipt["error_kind"])
        # Every role plus the objective: the batch ran to completion.
        self.assertEqual(server.call_count, self.role_count + 1)

    def test_only_the_first_call_of_a_batch_gets_the_cold_budget(self):
        """The other side of the bound, and the reason this is not just a
        bigger constant.

        A backend that stalls on its SECOND call is not loading a model -- it is
        wedged. Handing every call the cold budget would let it hold routing for
        roles x COLD seconds, so the second slow call must still fall back.
        """
        server = self.serve({2: COLD_LOAD_S})

        receipt = self.receipt()

        self.assertEqual(receipt["mechanism"], sr.FALLBACK,
                         msg=f"the cold budget leaked past call 1: {receipt}")
        self.assertEqual(receipt["error_kind"], "embed_timeout")
        # It gave up ON the second call rather than working through the roster.
        self.assertEqual(server.call_count, 2)

    def test_the_route_still_falls_back_when_nothing_can_rescue_it(self):
        """Fail-soft is unchanged: a backend slower than both budgets still
        yields a keyword answer rather than an exception."""
        self.serve({1: FOREVER_S})
        with patch.dict(os.environ, {sr.EMBED_COLD_TIMEOUT_ENV: "0.4"}):
            receipt = self.receipt()

        self.assertEqual(receipt["mechanism"], sr.FALLBACK)
        self.assertTrue(receipt["agent"], "routing produced no role at all")


class DeadlineIsNotADeadHostTests(_ColdCase):
    """The receipt has to name the right remedy.

    ``host_unreachable`` sends an operator to restart a daemon. When the daemon
    is up and merely slow that is a wrong answer with a real cost, and it is the
    answer this module gave for the entire life of the defect.
    """

    def test_a_blown_deadline_is_reported_as_a_timeout(self):
        self.serve({1: FOREVER_S})
        with patch.dict(os.environ, {sr.EMBED_COLD_TIMEOUT_ENV: "0.4"}):
            receipt = self.receipt()

        self.assertEqual(receipt["error_kind"], "embed_timeout",
                         msg=f"a slow host was blamed as a dead one: {receipt}")
        self.assertIn("accepted the connection", receipt["detail"])
        # The remedy has to be in the receipt, not in someone's memory.
        self.assertIn(sr.EMBED_COLD_TIMEOUT_ENV, receipt["detail"])

    def test_a_genuinely_absent_host_is_still_host_unreachable(self):
        """Guards the other direction: widening the timeout branch until it
        swallowed a refused connection would relabel a real outage."""
        env = patch.dict(os.environ,
                         {"OLLAMA_HOST": f"http://127.0.0.1:{_free_port()}"})
        env.start()
        self.addCleanup(env.stop)

        receipt = self.receipt()

        self.assertEqual(receipt["error_kind"], "host_unreachable",
                         msg=f"a dead host was relabelled: {receipt}")


class BudgetEnvironmentTests(_ColdCase):
    """An operator's typo must not take routing down."""

    def test_a_non_numeric_budget_falls_back_to_the_default(self):
        server = self.serve({1: COLD_LOAD_S})
        with patch.dict(os.environ, {sr.EMBED_COLD_TIMEOUT_ENV: "banana"}):
            receipt = self.receipt()

        # The default cold budget is generous, so the slow first call survives.
        self.assertEqual(receipt["mechanism"], sr.LATENT,
                         msg=f"a bad env var broke routing: {receipt}")
        self.assertEqual(server.call_count, self.role_count + 1)

    def test_a_non_positive_budget_falls_back_to_the_default(self):
        self.serve({1: COLD_LOAD_S})
        with patch.dict(os.environ, {sr.EMBED_COLD_TIMEOUT_ENV: "0"}):
            receipt = self.receipt()

        self.assertEqual(receipt["mechanism"], sr.LATENT,
                         msg=f"a zero budget was taken literally: {receipt}")

    def test_a_cache_hit_still_pays_the_cold_budget_for_the_objective(self):
        """The subtle re-entry of the same bug.

        When role vectors come from the cache the objective embed becomes the
        first call of the batch, and the model may have been evicted since. If
        it were handed the warm budget, one cache hit would restore the exact
        silent degradation this file removes.
        """
        server = self.serve({self.role_count + 2: COLD_LOAD_S})

        first = self.receipt()
        self.assertEqual(first["mechanism"], sr.LATENT)
        self.assertEqual(first["embed_calls"], self.role_count + 1)

        second = self.receipt()

        self.assertEqual(second["embed_calls"], 1, "role vectors were not cached")
        self.assertEqual(
            second["mechanism"], sr.LATENT,
            msg=f"the objective embed was given the warm budget: {second}")
        self.assertEqual(server.call_count, self.role_count + 2)


if __name__ == "__main__":
    unittest.main()
