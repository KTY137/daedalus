# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The latent route is WIRED: ``route_and_select`` actually reaches it.

``daedalus/semantic_route.py`` was dead code -- importing every module in the
package never pulled it in, and production routing went straight to
``router.route_task``. These tests pin the wiring itself, at the seam
(:func:`daedalus.provider_router.route_and_select`) that ``offload`` calls.

Two claims have to hold at once, and a suite that only checks one of them is
worthless:

* **ALLOW.** The latent route STEERS the production call -- it routes to a role
  the keyword router does not pick. A wiring that quietly always fell back
  would pass every failure test below while the feature was dead, which is the
  exact state this work exists to end.
* **DENY.** No latent failure can break routing, and none can be silent. The
  keyword router is always the floor, and the receipt always says which path
  ran and why.

NOTHING in ``semantic_route`` is mocked -- not the module, not its helpers, not
``urllib``. Each test starts a REAL HTTP server speaking the Ollama
``/api/embeddings`` protocol and points the production code at it through
``OLLAMA_HOST``, exactly as :mod:`tests.test_semantic_route_live` does. Only the
backend is fake. A guard that "passes" because the test's own stub never made it
to the code under test proves nothing, and this repo has been burned by that
before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from daedalus import semantic_route as sr
from daedalus.provider_router import (
    LATENT_DISABLED,
    LATENT_ENV,
    LATENT_OVERRULED,
    route_and_select,
    select_provider,
)
from daedalus.router import load_agents, route_task

AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}
# Cross-lane fixtures need roles to resolve to measurably different empirical
# lanes. With trusted Ollama available both roles now resolve to ollama/write,
# so use an external advisory fallback for the external-ok role.
CROSS_AVAIL = {
    "claude_cli": True,
    "ollama": False,
    "deepseek": True,
    "codex_cli": False,
}

# Every key LatentRouteResult.to_dict() promises, plus the lane-guard verdict.
# The receipt must have the same shape on every path, so a reader never has to
# interpret a missing key.
RECEIPT_KEYS = {
    "agent", "mechanism", "ran", "attempted", "reason", "error_kind", "detail",
    "host", "model", "scores", "margin", "dimension", "embed_calls", "lane_guard",
}

# An INTRA-LANE steer. The keyword router picks data-analysis-dev; the embedding
# picks ui-ux-dev. Both are external_ok, so both resolve to the same provider
# lane and the latent route is allowed to win. This is where the feature's value
# lives, and it is the pair the ALLOW-side tests use.
INTRA_OBJECTIVE = "make the plot legible"
INTRA_TARGET = "ui-ux-dev"

# A CROSS-LANE steer. No trigger fires, so the keyword router falls to its
# qa-critic catch-all (external_ok=false -> trusted lane), while the embedding
# wants ui-ux-dev (external_ok=true -> external advisory). This is the measured
# case that has to be overruled: on the real backend the top three roles were
# within 0.0069 cosine of each other.
CROSS_OBJECTIVE = "the graph is hard to read"
CROSS_TARGET = "ui-ux-dev"


class FakeOllama:
    """A real HTTP server answering /api/embeddings however you tell it to.

    Records every prompt, so a test can prove the backend was NOT contacted.
    """

    def __init__(self, handler):
        self.prompts: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
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
    """A port with nothing listening -- a genuinely unreachable host."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _distinct_vector(text: str, dim: int = 12) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(digest[i % len(digest)] / 255.0) + 0.01 for i in range(dim)]


def _steer_to(target: str, names: list[str]):
    """A backend that places ``target`` nearest to whatever it is asked.

    Role prompts start with the role name (see ``semantic_route._role_text``);
    the objective gets the target's own vector, so the target wins outright.
    """
    def handler(payload):
        prompt = payload["prompt"]
        for idx, name in enumerate(names):
            if prompt.startswith(name):
                vec = [0.0] * (len(names) + 1)
                vec[0 if name == target else idx + 1] = 1.0
                return 200, {"embedding": vec}
        vec = [0.0] * (len(names) + 1)
        vec[0] = 1.0
        return 200, {"embedding": vec}
    return handler


class _WiredCase(unittest.TestCase):
    """Base: cache isolation, server teardown, and a pinned environment.

    The environment is pinned on EVERY test because both the host and the kill
    switch are read from it at call time; inheriting an operator's real
    ``OLLAMA_HOST`` would make these tests pass or fail based on the box.
    """

    def setUp(self):
        sr.cache_clear()
        self.addCleanup(sr.cache_clear)
        env = patch.dict(os.environ, {"OLLAMA_EMBED_MODEL": "fake-embed"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LATENT_ENV, None)

    def serve(self, handler) -> FakeOllama:
        server = FakeOllama(handler)
        self.addCleanup(server.stop)
        self.point_at(server.host)
        return server

    def point_at(self, host: str) -> None:
        env = patch.dict(os.environ, {"OLLAMA_HOST": host})
        env.start()
        self.addCleanup(env.stop)


# --------------------------------------------------------------------------
# 1. ALLOW: the latent route actually STEERS production routing.
# --------------------------------------------------------------------------

class LatentRouteSteersTests(_WiredCase):
    """The anti-dead-feature half. Without these, a wiring that always fell
    back to keywords would pass the entire failure suite below.

    Every steer here is WITHIN a lane, because that is the only steer the lane
    guard permits -- and it is the whole of the feature's remaining value, so it
    had better be demonstrably alive.
    """

    OBJECTIVE = INTRA_OBJECTIVE
    TARGET = INTRA_TARGET

    def test_route_and_select_returns_a_role_the_keyword_router_does_not_pick(self):
        keyword_choice = route_task(self.OBJECTIVE, [])["name"]
        self.assertNotEqual(keyword_choice, self.TARGET,
                            "fixture assumes keywords do NOT pick the target")
        names = [a["name"] for a in load_agents()]
        server = self.serve(_steer_to(self.TARGET, names))

        agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(agent["name"], self.TARGET,
                         msg=f"latent route did not steer: {decision.latent_route}")
        self.assertNotEqual(agent["name"], keyword_choice)
        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)
        self.assertTrue(decision.latent_route["ran"])
        self.assertGreater(server.call_count, 0, "the backend was never contacted")

    def test_same_call_differs_with_the_latent_route_on_and_off(self):
        """The sharpest form of the allow-side claim: one code path, one
        backend, one objective -- and the switch alone changes the answer."""
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(self.TARGET, names))

        latent_agent, latent_dec = route_and_select(self.OBJECTIVE, [], AVAIL, latent=True)
        kw_agent, kw_dec = route_and_select(self.OBJECTIVE, [], AVAIL, latent=False)

        self.assertNotEqual(latent_agent["name"], kw_agent["name"])
        self.assertEqual(latent_dec.latent_route["mechanism"], sr.LATENT)
        self.assertEqual(kw_dec.latent_route["mechanism"], LATENT_DISABLED)

    def test_an_intra_lane_steer_is_allowed_and_the_lane_does_not_move(self):
        """The permitted case, pinned from both ends: the role changes, the
        lane does not, and the guard records that it did not fire."""
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(self.TARGET, names))

        _, kw = route_and_select(self.OBJECTIVE, [], AVAIL, latent=False)
        agent, latent = route_and_select(self.OBJECTIVE, [], AVAIL, latent=True)

        self.assertEqual(agent["name"], self.TARGET)
        self.assertNotEqual(kw.persona, latent.persona)      # the role did move
        self.assertEqual((kw.provider, kw.mode), (latent.provider, latent.mode))
        self.assertEqual(latent.latent_route["mechanism"], sr.LATENT)
        self.assertIsNone(latent.latent_route["lane_guard"])


# --------------------------------------------------------------------------
# 1b. THE LANE GUARD: a latent decision may never change the lane.
# --------------------------------------------------------------------------

class LaneGuardTests(_WiredCase):
    """A 0.0069-margin embedding must not decide an egress lane.

    Measured on the real backend: ``the graph is hard to read`` scored
    data-analysis-dev 0.4735 / docs-dev 0.4666 / ui-ux-dev 0.4638, and that
    near-tie moved the task from the trusted write lane onto an external
    advisory lane.
    """

    def _cross_lane(self):
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(CROSS_TARGET, names))
        return route_and_select(CROSS_OBJECTIVE, [], CROSS_AVAIL)

    def test_a_cross_lane_latent_choice_is_overruled(self):
        keyword_choice = route_task(CROSS_OBJECTIVE, [])["name"]
        self.assertNotEqual(keyword_choice, CROSS_TARGET)

        agent, decision = self._cross_lane()

        self.assertEqual(agent["name"], keyword_choice,
                         msg=f"the latent route moved the lane: {decision.latent_route}")
        self.assertEqual(decision.latent_route["mechanism"], LATENT_OVERRULED)
        self.assertFalse(decision.latent_route["ran"])

    def test_the_overruled_task_keeps_the_keyword_lane_exactly(self):
        """Not merely 'a' lane -- the SAME decision the keyword router alone
        would have produced, persona and reason included."""
        _, kw = route_and_select(CROSS_OBJECTIVE, [], CROSS_AVAIL, latent=False)
        _, guarded = self._cross_lane()

        self.assertEqual(kw.provider, guarded.provider)
        self.assertEqual(kw.mode, guarded.mode)
        self.assertEqual(kw.persona, guarded.persona)
        # the measured case: trusted write lane held, external advisory refused
        self.assertEqual(guarded.provider, "claude_cli")

    def test_the_overrule_records_both_roles_both_lanes_and_the_margin(self):
        """A filtered sample that does not announce itself would corrupt the
        margin measurement this guard is waiting on."""
        _, decision = self._cross_lane()
        guard = decision.latent_route["lane_guard"]

        self.assertIsNotNone(guard)
        self.assertTrue(guard["overruled"])
        self.assertEqual(guard["latent_agent"], CROSS_TARGET)
        self.assertEqual(guard["keyword_agent"], route_task(CROSS_OBJECTIVE, [])["name"])
        self.assertTrue(guard["latent_lane"]["external_ok"])
        self.assertFalse(guard["keyword_lane"]["external_ok"])
        self.assertNotEqual(guard["latent_lane"]["provider"],
                            guard["keyword_lane"]["provider"])
        self.assertIsNotNone(guard["margin"])
        json.dumps(guard)

    def test_the_overruled_receipt_keeps_the_latent_scores(self):
        """The embedding's own numbers survive the overrule, or nobody can
        measure how good the route that was thrown away actually was."""
        _, decision = self._cross_lane()
        receipt = decision.latent_route

        self.assertTrue(receipt["scores"], "scores were discarded")
        self.assertEqual(receipt["scores"][0][0], CROSS_TARGET)
        self.assertIsNotNone(receipt["dimension"])
        self.assertGreater(receipt["embed_calls"], 0)

    def test_the_overrule_is_never_silent(self):
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(CROSS_TARGET, names))

        with self.assertLogs("daedalus.provider_router", level=logging.WARNING) as caught:
            route_and_select(CROSS_OBJECTIVE, [], CROSS_AVAIL)

        blob = "\n".join(caught.output)
        self.assertIn("LANE GUARD", blob)
        self.assertIn(CROSS_TARGET, blob)

    def test_the_guard_is_measured_against_the_real_select_provider(self):
        """Availability changes the lane, so the guard must re-derive it rather
        than assume external_ok maps to a fixed provider. With the bench down,
        ui-ux-dev degrades to Claude -- the same lane as qa-critic -- and the
        steer becomes legal. A guard hard-coded to external_ok would still
        block it, and would be wrong."""
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(CROSS_TARGET, names))
        bench_down = {"claude_cli": True, "ollama": False, "deepseek": False,
                      "codex_cli": False}

        agent, decision = route_and_select(CROSS_OBJECTIVE, [], bench_down)

        self.assertEqual(decision.provider, "claude_cli")
        self.assertEqual(agent["name"], CROSS_TARGET,
                         msg=f"same-lane steer was blocked: {decision.latent_route}")
        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)


# --------------------------------------------------------------------------
# 2. DENY: no latent failure breaks routing, and none is silent.
# --------------------------------------------------------------------------

class FailSoftTests(_WiredCase):

    OBJECTIVE = "the graph is hard to read"

    def test_unreachable_backend_still_routes_via_keywords(self):
        self.point_at(f"http://127.0.0.1:{_free_port()}")
        expected = route_task(self.OBJECTIVE, [])["name"]

        agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(agent["name"], expected)
        self.assertEqual(decision.latent_route["mechanism"], sr.FALLBACK)
        self.assertEqual(decision.latent_route["error_kind"], "host_unreachable")
        self.assertFalse(decision.latent_route["ran"])

    def test_model_not_found_is_named_in_the_receipt_not_collapsed(self):
        """`ollama pull` and `ollama serve` are different fixes; a receipt that
        says only 'it failed' sends the operator to the wrong one."""
        self.serve(lambda p: (404, {"error": 'model "x" not found, try pulling it first'}))

        _, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(decision.latent_route["error_kind"], "model_not_found")
        self.assertNotEqual(decision.latent_route["error_kind"], "host_unreachable")

    def test_degenerate_backend_does_not_produce_a_confident_route(self):
        """All-zero vectors scored every role 0.0 and max() picked whichever
        sorted first. Through the wiring that must surface as a FALLBACK."""
        self.serve(lambda p: (200, {"embedding": [0.0] * 12}))

        _, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(decision.latent_route["mechanism"], sr.FALLBACK)
        self.assertEqual(decision.latent_route["error_kind"], "degenerate_vector")

    def test_a_crashing_latent_route_does_not_take_routing_down(self):
        """A malformed OLLAMA_HOST is a real operator mistake, and it raises a
        ValueError that ``semantic_route`` does not catch (its handler covers
        HTTPError/URLError/OSError only). Routing must survive it.

        Nothing is mocked here: the exception is genuinely raised from inside
        urllib, inside the real latent route.
        """
        self.point_at("not-a-url-scheme")
        expected = route_task(self.OBJECTIVE, [])["name"]

        agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(agent["name"], expected)
        self.assertEqual(decision.latent_route["mechanism"], sr.FALLBACK)
        self.assertEqual(decision.latent_route["error_kind"], "latent_route_crashed")
        self.assertTrue(decision.latent_route["attempted"])
        self.assertIn("ValueError", decision.latent_route["detail"])

    def test_a_failed_latent_route_is_never_silent(self):
        """Fail soft is only half the contract. A capability that degrades
        quietly reads as a working capability forever."""
        self.point_at(f"http://127.0.0.1:{_free_port()}")

        with self.assertLogs("daedalus.provider_router", level=logging.WARNING) as caught:
            route_and_select(self.OBJECTIVE, [], AVAIL)

        blob = "\n".join(caught.output)
        self.assertIn("NEVER RAN", blob)
        self.assertIn("host_unreachable", blob)

    def test_a_crash_is_never_silent_either(self):
        self.point_at("not-a-url-scheme")

        with self.assertLogs("daedalus.provider_router", level=logging.WARNING) as caught:
            route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertIn("RAISED", "\n".join(caught.output))

    def test_a_successful_latent_route_does_not_warn(self):
        """Warning on the healthy path would train the operator to ignore the
        warning that matters."""
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(INTRA_TARGET, names))

        with self.assertLogs("daedalus.provider_router", level=logging.DEBUG) as caught:
            route_and_select(INTRA_OBJECTIVE, [], AVAIL)

        self.assertFalse([r for r in caught.records if r.levelno >= logging.WARNING],
                         msg="a working latent route warned")

    def test_an_unroutable_task_raises_exactly_as_it_did_before_the_wiring(self):
        """The fail-soft catch must not swallow a real routing failure and
        invent an agent. An empty roster still raises RuntimeError."""
        self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))

        with self.assertRaises(RuntimeError):
            route_and_select(self.OBJECTIVE, [], AVAIL,
                             active_agents=["no-such-role"])


# --------------------------------------------------------------------------
# 3. The operator kill switch.
# --------------------------------------------------------------------------

class KillSwitchTests(_WiredCase):

    # intra-lane, so the kill switch is the only thing under test here and the
    # lane guard never confounds the result
    OBJECTIVE = INTRA_OBJECTIVE

    def test_env_off_skips_the_backend_entirely(self):
        names = [a["name"] for a in load_agents()]
        server = self.serve(_steer_to("ui-ux-dev", names))
        expected = route_task(self.OBJECTIVE, [])["name"]

        with patch.dict(os.environ, {LATENT_ENV: "0"}):
            agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(agent["name"], expected)
        self.assertEqual(server.call_count, 0,
                         "the kill switch did not stop the embedding calls")
        self.assertEqual(decision.latent_route["mechanism"], LATENT_DISABLED)
        self.assertFalse(decision.latent_route["attempted"])

    def test_disabled_is_not_reported_as_a_failure(self):
        """'Told not to run' and 'tried and could not run' are different
        operator situations; collapsing them is the defect being removed."""
        self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))

        with patch.dict(os.environ, {LATENT_ENV: "0"}):
            _, off = route_and_select(self.OBJECTIVE, [], AVAIL)
        self.point_at(f"http://127.0.0.1:{_free_port()}")
        _, broken = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertNotEqual(off.latent_route["mechanism"], broken.latent_route["mechanism"])
        self.assertIsNone(off.latent_route["error_kind"])
        self.assertIsNotNone(broken.latent_route["error_kind"])

    def test_explicit_argument_beats_the_environment(self):
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to("ui-ux-dev", names))

        with patch.dict(os.environ, {LATENT_ENV: "0"}):
            agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL, latent=True)

        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)
        self.assertEqual(agent["name"], "ui-ux-dev")

    def test_default_is_on(self):
        """An opt-in flag that nothing sets is the dead module all over again."""
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to("ui-ux-dev", names))
        self.assertNotIn(LATENT_ENV, os.environ)

        _, decision = route_and_select(self.OBJECTIVE, [], AVAIL)

        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)


# --------------------------------------------------------------------------
# 4. Roster threading: the latent route must score the CALLER's roster.
# --------------------------------------------------------------------------

class RosterThreadingTests(_WiredCase):

    OBJECTIVE = "the graph is hard to read"

    def test_active_agents_bound_the_latent_choice(self):
        """Without threading, the latent route embeds the global crew and can
        return a role the caller explicitly excluded -- routing work to an agent
        the project switched off.

        The backend is rigged so the EXCLUDED role ``ui-ux-dev`` is the nearest
        match overall and the allowed ``docs-dev`` is a clear second. If the
        filter reaches the embeddings, the route runs and returns docs-dev; if
        it does not, ui-ux-dev wins outright and the leak is unmissable. Note
        that both must be graded, not just "did it fall back" -- a route that
        merely failed here would also avoid the leak while proving nothing.
        """
        names = [a["name"] for a in load_agents()]
        # Both allowed roles are external_ok, so the steer stays inside one lane
        # and the lane guard cannot mask a roster leak by overruling it.
        excluded, allowed = "ui-ux-dev", ["docs-dev", "researcher"]
        self.assertIn(excluded, names)
        self.assertNotIn(excluded, allowed)

        def handler(payload):
            prompt = payload["prompt"]
            for idx, name in enumerate(names):
                if prompt.startswith(name):
                    vec = [0.0] * len(names)
                    vec[idx] = 1.0
                    return 200, {"embedding": vec}
            vec = [0.0] * len(names)
            vec[names.index(excluded)] = 1.0     # nearest, but not on the roster
            vec[names.index("researcher")] = 0.5  # nearest among the allowed
            return 200, {"embedding": vec}

        server = self.serve(handler)
        agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL,
                                           active_agents=allowed)

        self.assertIn(agent["name"], allowed,
                      msg=f"excluded role leaked through: {decision.latent_route}")
        self.assertEqual(agent["name"], "researcher")
        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)
        self.assertNotIn(excluded, [s[0] for s in decision.latent_route["scores"]],
                         "an excluded role was scored at all")
        # roster embeddings are bounded by the filter, not the global crew
        self.assertEqual(server.call_count, len(allowed) + 1)

    def test_repo_root_reaches_the_latent_route(self):
        """A repo whose crew lives in its own .agentenv must be embedded against
        THAT crew; scoring the global roster would route to a role the repo
        does not have."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agents_dir = Path(tmp.name) / ".agentenv" / "agents"
        agents_dir.mkdir(parents=True)
        local = [
            {"name": "repo-only-alpha", "triggers": ["alpha"], "owns": ["alpha/"],
             "external_ok": True},
            {"name": "repo-only-beta", "triggers": ["beta"], "owns": ["beta/"],
             "external_ok": True},
        ]
        for a in local:
            (agents_dir / f"{a['name']}.json").write_text(json.dumps(a), encoding="utf-8")
        local_names = [a["name"] for a in local]
        server = self.serve(_steer_to("repo-only-beta", local_names))

        agent, decision = route_and_select(self.OBJECTIVE, [], AVAIL,
                                           repo_root=tmp.name)

        self.assertEqual(agent["name"], "repo-only-beta",
                         msg=f"repo roster not used: {decision.latent_route}")
        self.assertEqual(decision.latent_route["mechanism"], sr.LATENT)
        self.assertEqual(server.call_count, len(local_names) + 1)
        self.assertNotIn(agent["name"], [a["name"] for a in load_agents()])


# --------------------------------------------------------------------------
# 5. The receipt: one shape, always present, always serialisable.
# --------------------------------------------------------------------------

class ReceiptTests(_WiredCase):

    OBJECTIVE = INTRA_OBJECTIVE

    def _receipt(self, objective: str | None = None,
                 availability: dict | None = None) -> dict:
        _, decision = route_and_select(
            objective or self.OBJECTIVE, [], availability or AVAIL)
        return decision.as_dict()["latent_route"]

    def test_receipt_reaches_as_dict_on_the_latent_path(self):
        names = [a["name"] for a in load_agents()]
        self.serve(_steer_to(INTRA_TARGET, names))

        receipt = self._receipt()

        self.assertEqual(set(receipt) & RECEIPT_KEYS, RECEIPT_KEYS)
        self.assertEqual(receipt["mechanism"], sr.LATENT)
        self.assertTrue(receipt["ran"])
        self.assertEqual(receipt["agent"], INTRA_TARGET)
        self.assertEqual(receipt["model"], "fake-embed")
        self.assertGreater(receipt["embed_calls"], 0)
        self.assertIsNotNone(receipt["dimension"])
        json.dumps(receipt)

    def test_receipt_reaches_as_dict_on_the_fallback_path(self):
        self.point_at(f"http://127.0.0.1:{_free_port()}")

        receipt = self._receipt()

        self.assertEqual(set(receipt) & RECEIPT_KEYS, RECEIPT_KEYS)
        self.assertFalse(receipt["ran"])
        self.assertEqual(receipt["mechanism"], sr.FALLBACK)
        self.assertEqual(receipt["error_kind"], "host_unreachable")
        json.dumps(receipt)

    def test_every_path_reports_the_same_receipt_shape(self):
        """Latent, overruled, disabled, path-owned, crash and fallback must all
        be readable by one parser; a missing key must never be a seventh
        answer."""
        shapes = []
        names = [a["name"] for a in load_agents()]

        self.serve(_steer_to(INTRA_TARGET, names))
        shapes.append(self._receipt())                                   # latent
        shapes.append(self._receipt(
            CROSS_OBJECTIVE, availability=CROSS_AVAIL))                 # overruled
        with patch.dict(os.environ, {LATENT_ENV: "0"}):
            shapes.append(self._receipt())                               # disabled
        _, owned = route_and_select("review scan state machine races",
                                    ["TCT_app/controller/state_machine.py"], AVAIL)
        shapes.append(owned.as_dict()["latent_route"])                   # path-owned
        self.point_at("not-a-url-scheme")
        shapes.append(self._receipt())                                   # crashed
        self.point_at(f"http://127.0.0.1:{_free_port()}")
        shapes.append(self._receipt())                                   # fallback

        for receipt in shapes:
            self.assertEqual(set(receipt), RECEIPT_KEYS)
            json.dumps(receipt)
        mechanisms = [r["mechanism"] for r in shapes]
        self.assertEqual(mechanisms,
                         [sr.LATENT, LATENT_OVERRULED, LATENT_DISABLED,
                          sr.PATH_OWNED, sr.FALLBACK, sr.FALLBACK])
        # the two FALLBACKs are distinguishable by cause, not merged
        self.assertNotEqual(shapes[4]["error_kind"], shapes[5]["error_kind"])
        # only the overruled receipt carries a fired lane guard
        self.assertEqual([bool(r["lane_guard"]) for r in shapes],
                         [False, True, False, False, False, False])

    def test_path_owned_is_a_design_skip_not_a_failure(self):
        server = self.serve(lambda p: (200, {"embedding": _distinct_vector(p["prompt"])}))

        _, decision = route_and_select("review scan state machine races",
                                       ["TCT_app/controller/state_machine.py"], AVAIL)

        self.assertEqual(decision.latent_route["mechanism"], sr.PATH_OWNED)
        self.assertIsNone(decision.latent_route["error_kind"])
        self.assertEqual(server.call_count, 0, "backend contacted despite an owned path")


# --------------------------------------------------------------------------
# 6. Back-compat: callers that never asked for any of this are unchanged.
# --------------------------------------------------------------------------

class OffloadReceiptTests(_WiredCase):
    """The provenance must survive the layer ABOVE provider_router.

    ``offload`` builds its result dict field by field rather than copying
    ``as_dict()``, so a receipt that stops at :class:`ProviderDecision` is
    invisible to every operator who reads an offload result -- which is exactly
    how this capability went quiet the first time.

    The repo gets its OWN roster. ``offload`` passes ``repo_root``, which sends
    ``load_agents`` to that repo's ``.agentenv/agents`` (or the template dir),
    NOT the global crew -- an earlier draft of these tests steered against
    global role names, matched nothing, and passed on a receipt that said
    ``ambiguous``. A controlled roster is what makes the assertions mean
    something.
    """

    #: alpha/beta share a lane (both external_ok); gamma is trusted-only.
    ROLES = [
        {"name": "alpha", "triggers": ["alpha"], "owns": ["alpha/"], "external_ok": True},
        {"name": "beta", "triggers": ["beta"], "owns": ["beta/"], "external_ok": True},
        {"name": "gamma", "triggers": ["gamma"], "owns": ["gamma/"], "external_ok": False},
    ]
    # keyword -> alpha (trigger match). Deliberately does NOT start with a role
    # name: the fake backend identifies role prompts by prefix, so an objective
    # beginning with "alpha" would be served alpha's own role vector and the
    # steer would silently become a no-op.
    OBJECTIVE = "please look at the alpha module"

    def setUp(self):
        super().setUp()
        from daedalus import metrics
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        agents_dir = Path(self._tmp.name) / ".agentenv" / "agents"
        agents_dir.mkdir(parents=True)
        for role in self.ROLES:
            (agents_dir / f"{role['name']}.json").write_text(json.dumps(role),
                                                             encoding="utf-8")
        self.names = [r["name"] for r in self.ROLES]
        self._orig_log = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "metrics.jsonl"
        self.addCleanup(lambda: setattr(metrics, "LOG", self._orig_log))
        self.assertEqual(
            route_task(self.OBJECTIVE, [], repo_root=self._tmp.name)["name"], "alpha",
            "fixture assumes the keyword router picks alpha")

    def _offload(self, availability=None):
        from daedalus.offload import offload
        return offload(
            self.OBJECTIVE,
            self._tmp.name,
            paths=[],
            availability=availability or AVAIL,
        )

    def test_offload_result_carries_the_stage_1_receipt(self):
        """Intra-lane: alpha -> beta, same lane, so the embedding wins and the
        offload result says an embedding did it."""
        self.serve(_steer_to("beta", self.names))

        result = self._offload()

        self.assertIn("latent_route", result)
        self.assertEqual(set(result["latent_route"]), RECEIPT_KEYS)
        self.assertEqual(result["latent_route"]["mechanism"], sr.LATENT)
        self.assertEqual(result["owner"], "beta")
        self.assertEqual(result["latent_route"]["agent"], result["owner"])
        json.dumps(result["latent_route"])

    def test_offload_result_shows_an_overruled_lane_change(self):
        """Cross-lane: alpha (external_ok) -> gamma (trusted-only). The guard
        holds the lane, and the offload result shows what was refused."""
        self.serve(_steer_to("gamma", self.names))

        result = self._offload(availability=CROSS_AVAIL)

        receipt = result["latent_route"]
        self.assertEqual(receipt["mechanism"], LATENT_OVERRULED)
        self.assertEqual(receipt["lane_guard"]["latent_agent"], "gamma")
        self.assertEqual(result["owner"], "alpha")
        self.assertEqual(result["owner"], receipt["lane_guard"]["keyword_agent"])


class BackCompatTests(_WiredCase):

    def test_select_provider_alone_carries_no_latent_key(self):
        """``select_provider`` is HANDED a role; it did not route and has no
        provenance to report, so its dict stays byte-identical."""
        agent = {"name": "docs-dev", "external_ok": True}
        decision = select_provider(agent, "Draft docstrings", ["docs/notes.md"], AVAIL)

        self.assertIsNone(decision.latent_route)
        self.assertNotIn("latent_route", decision.as_dict())

    def test_positional_call_signature_is_unchanged(self):
        """``offload`` calls this with five positional arguments."""
        self.point_at(f"http://127.0.0.1:{_free_port()}")
        agent, decision = route_and_select("Draft docstrings for the docs helper",
                                           ["docs/notes.md"], AVAIL, None, None)
        self.assertIn("name", agent)
        self.assertIn("latent_route", decision.as_dict())


class SuiteDeterminismTests(unittest.TestCase):
    """``tests/conftest.py`` pins the latent route OFF for the whole suite.

    Deliberately NOT a :class:`_WiredCase` -- that base class clears the pin,
    because the latent route is its subject. This class checks what every OTHER
    test in the repo sees: stage-1 routing that does not depend on whether the
    box happens to have an embedding backend installed.
    """

    def test_the_suite_pins_the_latent_route_off(self):
        self.assertEqual(os.environ.get(LATENT_ENV), "0",
                         "tests/conftest.py is not pinning stage-1 routing")

    def test_a_test_that_does_not_opt_in_gets_keyword_routing(self):
        """No fake backend, no environment fiddling -- exactly the conditions
        every unrelated routing test runs under. If this ever reports a latent
        mechanism, those tests have become machine-dependent again."""
        _, decision = route_and_select(CROSS_OBJECTIVE, [], AVAIL)

        self.assertEqual(decision.latent_route["mechanism"], LATENT_DISABLED)
        self.assertEqual(decision.latent_route["embed_calls"], 0)


if __name__ == "__main__":
    unittest.main()
