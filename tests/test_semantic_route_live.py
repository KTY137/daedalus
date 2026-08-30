# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Drive the REAL latent route against a REAL (fake-backed) embedding server.

Nothing here mocks ``semantic_route`` or its helpers. Every test starts an
actual HTTP server on localhost that speaks the Ollama ``/api/embeddings``
protocol, and the module under test reaches it over real urllib with real JSON
parsing. Only the BACKEND is fake. That matters: a probe that "catches" a
defect because its own stub failed to parse proves nothing about the property,
and this repo has already been burned by exactly that.

The suite pins two separate claims:

1. When the backend answers, the latent route RUNS and steers the outcome --
   demonstrated by routing a prose objective to a role the keyword router does
   NOT pick (:meth:`LatentRouteRunsTests.test_latent_route_overrides_keyword_choice`).
2. When the backend does not answer, the route says so, naming the cause --
   host unreachable vs model missing vs server-cannot-embed are different
   operator problems and must not collapse into one silent "no match".
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from daedalus import semantic_route as sr
from daedalus.router import load_agents, route_task


class FakeOllama:
    """A real HTTP server that answers /api/embeddings however you tell it to.

    ``handler(payload) -> (status, body_dict)``. Records every prompt it was
    asked to embed, so a test can prove the backend was NOT contacted.
    """

    def __init__(self, handler):
        self.prompts: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # silence stderr noise
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                outer.prompts.append(payload.get("prompt", ""))
                status, body = handler(payload)
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def host(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _free_port() -> int:
    """A port with nothing listening on it -- a genuinely unreachable host."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _distinct_vector(text: str, dim: int = 12) -> list[float]:
    """Deterministic, non-degenerate, stable per text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = [(digest[i % len(digest)] / 255.0) + 0.01 for i in range(dim)]
    return vec


class _ServerCase(unittest.TestCase):
    """Base: guarantees cache isolation and server teardown."""

    def setUp(self):
        sr.cache_clear()
        self.addCleanup(sr.cache_clear)

    def serve(self, handler) -> FakeOllama:
        server = FakeOllama(handler)
        self.addCleanup(server.stop)
        return server


# --------------------------------------------------------------------------
# 1. The route RUNS when the backend answers.
# --------------------------------------------------------------------------

class LatentRouteRunsTests(_ServerCase):

    @staticmethod
    def _healthy(payload):
        return 200, {"embedding": _distinct_vector(payload["prompt"])}

    def test_latent_route_runs_and_reports_that_it_ran(self):
        server = self.serve(self._healthy)
        result = sr.semantic_route_explained(
            "make the plot legible", paths=[], host=server.host, model="fake-embed")

        self.assertTrue(result.ran, msg=result.explain())
        self.assertEqual(result.mechanism, sr.LATENT)
        self.assertTrue(result.attempted)
        self.assertIsNone(result.error_kind)
        self.assertIn(result.name, [a["name"] for a in load_agents()])
        # roster embeddings + the objective
        self.assertEqual(result.embed_calls, len(load_agents()) + 1)
        self.assertEqual(server.call_count, len(load_agents()) + 1)
        self.assertIn("latent route RAN", result.explain())

    def test_latent_route_overrides_keyword_choice(self):
        """The route must actually STEER, not just decorate the keyword answer.

        A prose objective with no keyword hit falls to the keyword router's
        catch-all. Here the backend places `ui-ux-dev` nearest, and the latent
        route must return that instead.
        """
        objective = "the graph is hard to read"
        target = "ui-ux-dev"
        keyword_choice = route_task(objective, [])["name"]
        self.assertNotEqual(keyword_choice, target,
                            "fixture assumes the keyword router does NOT pick the target")

        names = [a["name"] for a in load_agents()]

        def handler(payload):
            prompt = payload["prompt"]
            # Role prompts start with the role name (see _role_text).
            for idx, name in enumerate(names):
                if prompt.startswith(name):
                    vec = [0.0] * (len(names) + 1)
                    vec[0 if name == target else idx + 1] = 1.0
                    return 200, {"embedding": vec}
            # the objective: identical to the target role's vector
            vec = [0.0] * (len(names) + 1)
            vec[0] = 1.0
            return 200, {"embedding": vec}

        server = self.serve(handler)
        result = sr.semantic_route_explained(
            objective, paths=[], host=server.host, model="fake-embed")

        self.assertTrue(result.ran, msg=result.explain())
        self.assertEqual(result.name, target)
        self.assertNotEqual(result.name, keyword_choice)
        self.assertAlmostEqual(result.scores[0][1], 1.0, places=6)
        self.assertGreater(result.margin, 0.5)

    def test_legacy_wrapper_still_returns_a_bare_agent_dict(self):
        server = self.serve(self._healthy)
        agent = sr.semantic_route("make the plot legible", paths=[],
                                  host=server.host, model="fake-embed")
        self.assertIsInstance(agent, dict)
        self.assertIn("name", agent)

    def test_role_vectors_are_cached_across_calls(self):
        server = self.serve(self._healthy)
        n = len(load_agents())
        sr.semantic_route_explained("first", paths=[], host=server.host, model="fake-embed")
        after_first = server.call_count
        sr.semantic_route_explained("second", paths=[], host=server.host, model="fake-embed")
        self.assertEqual(after_first, n + 1)
        # only the objective is re-embedded the second time
        self.assertEqual(server.call_count, n + 2)


# --------------------------------------------------------------------------
# 2. The route REPORTS HONESTLY when the backend does not answer.
# --------------------------------------------------------------------------

class HonestFailureTests(_ServerCase):

    def _assert_fell_back(self, result, expected_kind):
        self.assertFalse(result.ran, msg=result.explain())
        self.assertEqual(result.mechanism, sr.FALLBACK)
        self.assertEqual(result.error_kind, expected_kind)
        self.assertIn("NEVER RAN", result.explain())
        # routing still succeeds -- failing honest must not mean failing hard
        self.assertIn("name", result.agent)

    def test_host_unreachable_is_named_as_such(self):
        host = f"http://127.0.0.1:{_free_port()}"
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=host, model="fake-embed")
        self._assert_fell_back(result, "host_unreachable")
        self.assertTrue(result.attempted)

    def test_model_not_found_is_distinct_from_host_down(self):
        """404 'model not found' needs `ollama pull`, not `ollama serve`."""
        server = self.serve(lambda p: (404, {"error": 'model "x" not found, try pulling it first'}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="missing-model")
        self._assert_fell_back(result, "model_not_found")
        self.assertNotEqual(result.error_kind, "host_unreachable")

    def test_server_without_embedding_support_is_named(self):
        server = self.serve(lambda p: (
            500, {"error": "This server does not support embeddings. Start it with `--embeddings`"}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="chat-only")
        self._assert_fell_back(result, "embeddings_unsupported")

    def test_non_json_response_is_named(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                raw = b"<html>proxy error</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        result = sr.semantic_route_explained(
            "make the plot legible", paths=[],
            host=f"http://127.0.0.1:{httpd.server_address[1]}", model="fake-embed")
        self._assert_fell_back(result, "bad_response")

    # -- guarded degenerate answers -------------------------------------

    def test_empty_embedding_is_a_failure_not_a_route(self):
        """`{"embedding": []}` scored 0.0 for every role, and max() returned
        whichever sorted first -- an arbitrary pick wearing a decision's
        costume. It must be reported as a failure."""
        server = self.serve(lambda p: (200, {"embedding": []}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")
        self._assert_fell_back(result, "empty_embedding")
        self.assertNotEqual(result.mechanism, sr.LATENT)

    def test_all_zero_embedding_is_a_failure_not_a_route(self):
        server = self.serve(lambda p: (200, {"embedding": [0.0] * 12}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")
        self._assert_fell_back(result, "degenerate_vector")

    def test_missing_embedding_field_is_a_failure(self):
        server = self.serve(lambda p: (200, {"nope": 1}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")
        self._assert_fell_back(result, "bad_response")

    def test_dimension_mismatch_is_a_failure_not_a_truncated_score(self):
        """zip() silently scores a prefix; two models of different width would
        otherwise produce a confident-looking nonsense route."""
        names = {a["name"] for a in load_agents()}

        def handler(payload):
            prompt = payload["prompt"]
            wide = any(prompt.startswith(n) for n in names)
            return 200, {"embedding": _distinct_vector(prompt, 16 if wide else 8)}

        server = self.serve(handler)
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")
        self._assert_fell_back(result, "dimension_mismatch")
        self.assertIn("dim", (result.detail or ""))

    def test_identical_scores_are_ambiguous_not_a_route(self):
        """A backend returning one constant vector gives every role the same
        cosine. That is no signal, not a winner."""
        server = self.serve(lambda p: (200, {"embedding": [0.3] * 12}))
        result = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")
        self._assert_fell_back(result, "ambiguous")


# --------------------------------------------------------------------------
# 3. Cache poisoning: one blip must not disable the route forever.
# --------------------------------------------------------------------------

class CacheRecoveryTests(_ServerCase):

    def test_transient_failure_does_not_poison_the_route(self):
        """The original `@lru_cache` cached the None returned on failure, so a
        single failure at process start silently disabled the latent route for
        the entire process -- and no recovery of the backend could revive it."""
        state = {"up": False}

        def handler(payload):
            if not state["up"]:
                return 500, {"error": "warming up"}
            return 200, {"embedding": _distinct_vector(payload["prompt"])}

        server = self.serve(handler)

        first = sr.semantic_route_explained("make the plot legible", paths=[],
                                            host=server.host, model="fake-embed")
        self.assertFalse(first.ran)
        calls_after_failure = server.call_count

        state["up"] = True
        second = sr.semantic_route_explained("make the plot legible", paths=[],
                                             host=server.host, model="fake-embed")

        self.assertTrue(second.ran,
                        msg=f"route stayed dead after the backend recovered: {second.explain()}")
        self.assertGreater(server.call_count, calls_after_failure,
                           msg="no new embed calls after recovery -> the failure was cached")

    def test_roster_change_invalidates_cached_vectors(self):
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))
        agents = load_agents()
        sr._role_vectors_detailed(server.host, "fake-embed", agents)
        baseline = server.call_count
        mutated = [dict(a) for a in agents]
        mutated[0] = {**mutated[0], "triggers": list(mutated[0].get("triggers", [])) + ["brand-new"]}
        sr._role_vectors_detailed(server.host, "fake-embed", mutated)
        self.assertGreater(server.call_count, baseline,
                           msg="a changed roster reused stale vectors")


# --------------------------------------------------------------------------
# 4. Path ownership short-circuit is a DESIGN skip, not a failure.
# --------------------------------------------------------------------------

class PathOwnershipTests(_ServerCase):

    def test_owned_path_skips_the_backend_entirely(self):
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))
        result = sr.semantic_route_explained(
            "review scan state machine races",
            paths=["TCT_app/controller/state_machine.py"],
            host=server.host, model="fake-embed")

        self.assertEqual(result.mechanism, sr.PATH_OWNED)
        self.assertFalse(result.ran)
        self.assertFalse(result.attempted)
        self.assertIsNone(result.error_kind)
        self.assertEqual(server.call_count, 0, "backend was contacted despite an owned path")
        self.assertIn("SKIPPED BY DESIGN", result.explain())

    def test_design_skip_is_distinguishable_from_failure(self):
        """The whole defect class: 'chose not to run' must not read the same as
        'tried and failed'."""
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))
        skipped = sr.semantic_route_explained(
            "review scan state machine races",
            paths=["TCT_app/controller/state_machine.py"],
            host=server.host, model="fake-embed")
        failed = sr.semantic_route_explained(
            "review scan state machine races", paths=[],
            host=f"http://127.0.0.1:{_free_port()}", model="fake-embed")

        self.assertNotEqual(skipped.mechanism, failed.mechanism)
        self.assertNotEqual(skipped.explain(), failed.explain())
        self.assertIsNone(skipped.error_kind)
        self.assertIsNotNone(failed.error_kind)


# --------------------------------------------------------------------------
# 5. Visibility: a skipped route cannot be silent.
# --------------------------------------------------------------------------

class VisibilityTests(_ServerCase):

    def test_legacy_wrapper_warns_when_the_latent_route_never_ran(self):
        """`semantic_route()` returns a bare dict and cannot express provenance
        in its return type, so it must SAY so."""
        host = f"http://127.0.0.1:{_free_port()}"
        with self.assertLogs("daedalus.semantic_route", level=logging.WARNING) as caught:
            sr.semantic_route("make the plot legible", paths=[], host=host, model="fake-embed")
        blob = "\n".join(caught.output)
        self.assertIn("NEVER RAN", blob)
        self.assertIn("host_unreachable", blob)

    def test_legacy_wrapper_does_not_warn_when_the_route_ran(self):
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))
        with self.assertLogs("daedalus.semantic_route", level=logging.DEBUG) as caught:
            sr.semantic_route("make the plot legible", paths=[],
                              host=server.host, model="fake-embed")
        self.assertFalse([r for r in caught.records if r.levelno >= logging.WARNING],
                         msg="a successful latent route must not warn")
        self.assertIn("latent route RAN", "\n".join(caught.output))

    def test_result_serialises_for_a_receipt(self):
        host = f"http://127.0.0.1:{_free_port()}"
        payload = sr.semantic_route_explained("make the plot legible", paths=[],
                                              host=host, model="fake-embed").to_dict()
        json.dumps(payload)  # must be receipt-safe
        self.assertFalse(payload["ran"])
        self.assertEqual(payload["mechanism"], sr.FALLBACK)
        self.assertEqual(payload["error_kind"], "host_unreachable")
        self.assertEqual(payload["model"], "fake-embed")


# --------------------------------------------------------------------------
# 6. Roster threading: the latent route must see the caller's agents.
# --------------------------------------------------------------------------

class RosterTests(_ServerCase):

    def test_active_agents_filter_is_honoured_by_the_latent_route(self):
        """Without roster threading the latent route embeds the global crew and
        can return a role the caller explicitly excluded."""
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))
        allowed = ["docs-dev", "qa-critic"]
        result = sr.semantic_route_explained(
            "make the plot legible", paths=[], host=server.host,
            model="fake-embed", active_agents=allowed)

        self.assertTrue(result.ran, msg=result.explain())
        self.assertIn(result.name, allowed)
        self.assertEqual(server.call_count, len(allowed) + 1)


# --------------------------------------------------------------------------
# 7. What the REAL local backend does right now (measured, not assumed).
# --------------------------------------------------------------------------

class RealBackendTests(unittest.TestCase):
    """Runs against whatever embedding host this machine actually has.

    Skips -- with the measured cause -- when no usable embedding backend is
    present, which is the normal state of a dev box. It never fails the suite
    for the absence of a host; it fails only if a usable host produces a route
    that claims not to have run.
    """

    def setUp(self):
        sr.cache_clear()
        self.addCleanup(sr.cache_clear)

    def test_real_backend_either_routes_or_explains_itself(self):
        result = sr.semantic_route_explained("make the plot legible", paths=[])
        self.assertIn("name", result.agent, "routing must succeed either way")
        if not result.ran:
            self.skipTest(
                f"no usable embedding backend here: {result.error_kind} -- "
                f"{result.detail} (host={result.host}, model={result.model})")
        self.assertEqual(result.mechanism, sr.LATENT)
        self.assertIsNotNone(result.dimension)
        self.assertGreater(result.dimension, 0)


if __name__ == "__main__":
    unittest.main()
