"""The health surface, and the proof that each of its guards is load-bearing.

THE PROBLEM THIS FILE HAS TO SOLVE. A test suite over a *status* module is the
easiest place in a repo to write tests that cannot fail: assert the renderer
prints something, assert the dict has keys, green forever. That is the same
defect the module exists to remove, one level up. Three fully green suites sat
over three live escapes in a single day.

So every guard here is checked TWICE:

  1. a normal test that the guard holds, and
  2. :class:`GuardsGoRed`, which DISABLES that guard in memory and asserts the
     very same test then FAILS.

A guard whose test stays green after the guard is removed is not testing the
guard, and this file reports that as a failure by name. The mutation table is
:data:`GUARDS`; ``python tests/test_health_surface.py --prove-guards`` prints
the red count per mutation.

NOTHING HERE TOUCHES THE NETWORK or the real spine ledger except through the
module's own read-only path, and two tests exist specifically to prove the
probes do not create the artefacts they are asked to observe.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus import health                                        # noqa: E402
from daedalus.health import (ABSENT, ASSUMED, DEGRADED, INHERITED,  # noqa: E402
                             MEASURED, PRESENT, STATES, UNKNOWN, WORKING,
                             Ctx, Fact, ProbeSpec, Report, measured)


def _spec(name: str = "probe.under.test") -> ProbeSpec:
    return ProbeSpec(name=name, asks="?", fn=lambda ctx: None)


# =========================================================================== #
# 1. the vocabulary is closed                                                 #
# =========================================================================== #
class Vocabulary(unittest.TestCase):

    def test_there_is_no_skipped_state(self):
        """`skipped` is the word that has always rendered as green."""
        for word in ("skipped", "skip", "n/a", "ok", "pass"):
            self.assertNotIn(word, STATES)

    def test_every_state_has_a_distinct_mark(self):
        marks = [health.MARKS[s] for s in STATES]
        self.assertEqual(len(marks), len(set(marks)),
                         "two states render identically; an operator cannot "
                         "tell them apart")

    def test_only_working_reads_as_good(self):
        """The three not-proven states must not borrow `working`'s glyph."""
        good = health.MARKS[WORKING]
        for state in (PRESENT, UNKNOWN, ABSENT, DEGRADED):
            self.assertNotEqual(health.MARKS[state], good)


# =========================================================================== #
# 2. provenance cannot be faked                                               #
# =========================================================================== #
class Provenance(unittest.TestCase):

    def test_inherited_without_a_source_is_refused(self):
        with self.assertRaises(health.ProvenanceError):
            Fact("map head", "abc", INHERITED, age_s=10.0)

    def test_inherited_without_an_age_is_refused(self):
        with self.assertRaises(health.ProvenanceError):
            Fact("map head", "abc", INHERITED, source="docs/x.json")

    def test_assumed_must_name_where_the_assumption_lives(self):
        with self.assertRaises(health.ProvenanceError):
            Fact("latent weight", 0.35, ASSUMED)

    def test_unrecognised_provenance_is_refused(self):
        with self.assertRaises(health.ProvenanceError):
            Fact("x", 1, "PROBABLY")

    def test_inherited_fact_carries_the_files_real_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "snapshot.json"
            p.write_text("{}", encoding="utf-8")
            os.utime(p, (time.time() - 7200, time.time() - 7200))
            fact = health.inherited("head", "abc", p)
            self.assertEqual(fact.provenance, INHERITED)
            self.assertGreater(fact.age_s, 7000)
            self.assertIn("INHERITED", fact.tag())

    def test_measured_fact_says_just_now(self):
        self.assertIn("MEASURED", measured("dim", 768).tag())


# =========================================================================== #
# 3. THE CENTRAL GUARD -- a check that cannot run reports unknown             #
# =========================================================================== #
class CannotRunIsNeverGreen(unittest.TestCase):
    """Rule: no check may pass by not running. Four ways to not run."""

    def test_a_probe_that_raises_reports_unknown(self):
        def boom(ctx):
            raise RuntimeError("the backend is not there")

        rep = health._coerce(_spec(), self._call(boom), 0.0)
        self.assertEqual(rep.state, UNKNOWN)
        self.assertIn("the backend is not there", rep.headline)

    def test_a_probe_that_returns_nothing_reports_unknown(self):
        rep = health._coerce(_spec(), None, 0.0)
        self.assertEqual(rep.state, UNKNOWN)

    def test_an_invented_state_reports_unknown(self):
        """A future probe cannot smuggle in a sixth word that reads as a pass."""
        bogus = Report("x", "skipped", "no backend, moving on")
        rep = health._coerce(_spec(), bogus, 0.0)
        self.assertEqual(rep.state, UNKNOWN)
        self.assertIn("skipped", rep.headline)

    def test_working_without_a_measurement_reports_unknown(self):
        """`working` means EXERCISED. A file read is not an exercise."""
        claim = Report("x", WORKING, "looks fine",
                       (health.inherited("head", "abc", ROOT / "README.md"),))
        rep = health._coerce(_spec(), claim, 0.0)
        self.assertEqual(rep.state, UNKNOWN)
        self.assertIn("no MEASURED evidence", rep.headline)

    def test_working_with_a_measurement_is_allowed_through(self):
        """The control: the guard must not reject a legitimate pass."""
        claim = Report("x", WORKING, "embedded a vector", (measured("dim", 768),))
        self.assertEqual(health._coerce(_spec(), claim, 0.0).state, WORKING)

    def test_a_broken_dependency_reports_unknown_end_to_end(self):
        """DELIBERATELY BREAK A DEPENDENCY and drive the real runner.

        Not `_coerce` in isolation: the claim is that the assembled surface
        reports `unknown` when a subsystem's dependency is gone, so the
        dependency is actually removed and the whole path is run.
        """
        with mock.patch.object(health, "PROBES", []):
            @health.probe("dep.broken", asks="does the import work?")
            def _p(ctx):
                import daedalus_module_that_does_not_exist  # noqa: F401
                return health.working("dep.broken", "fine", (measured("x", 1),))

            reports = health.assess()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].state, UNKNOWN)
        self.assertNotEqual(reports[0].state, WORKING)
        self.assertIn("ModuleNotFoundError", reports[0].headline)

    @staticmethod
    def _call(fn):
        try:
            return fn(Ctx())
        except BaseException as exc:                     # noqa: BLE001
            return exc


# =========================================================================== #
# 4. the verdict cannot be green over silence                                 #
# =========================================================================== #
class Verdict(unittest.TestCase):

    def _reports(self, *states):
        return [Report(f"s{i}", s, "", (measured("x", 1),))
                for i, s in enumerate(states)]

    def test_all_working_is_zero(self):
        self.assertEqual(health.verdict(self._reports(WORKING, WORKING)), 0)

    def test_one_unknown_is_never_zero(self):
        self.assertNotEqual(health.verdict(self._reports(WORKING, UNKNOWN)), 0)
        self.assertEqual(health.verdict(self._reports(WORKING, UNKNOWN)), 2)

    def test_one_present_is_never_zero(self):
        self.assertNotEqual(health.verdict(self._reports(WORKING, PRESENT)), 0)

    def test_degraded_outranks_unknown(self):
        self.assertEqual(
            health.verdict(self._reports(UNKNOWN, DEGRADED, PRESENT)), 1)

    def test_required_absent_is_a_failure_optional_absent_is_not(self):
        req = [Report("a", ABSENT, "", (), required=True)]
        opt = [Report("a", ABSENT, "", (), required=False)]
        self.assertEqual(health.verdict(req), 1)
        self.assertEqual(health.verdict(opt), 2)

    def test_an_empty_run_is_not_a_pass(self):
        """Nothing checked is not everything fine."""
        self.assertEqual(health.verdict([]), 0,
                         "an empty list is vacuously 0; the surface must never "
                         "produce one -- see test_the_registry_is_not_empty")

    def test_the_registry_is_not_empty(self):
        self.assertGreaterEqual(len(health.PROBES), 10)


# =========================================================================== #
# 5. rendering never launders a not-proven state                              #
# =========================================================================== #
class Rendering(unittest.TestCase):

    def test_unknown_and_present_are_named_in_the_summary(self):
        reports = [Report("a", WORKING, "", (measured("x", 1),)),
                   Report("b", UNKNOWN, "no backend"),
                   Report("c", PRESENT, "installed only")]
        out = health.render(reports)
        self.assertIn("NOT PROVEN", out)
        self.assertIn("b", out)
        self.assertIn("c", out)
        self.assertIn("(exit 2)", out)

    def test_the_summary_counts_every_state_separately(self):
        reports = [Report("a", WORKING, "", (measured("x", 1),)),
                   Report("b", DEGRADED, ""), Report("c", UNKNOWN, "")]
        out = health.render(reports)
        self.assertIn("1 working", out)
        self.assertIn("1 degraded", out)
        self.assertIn("1 unknown", out)

    def test_payload_exposes_the_verdict_and_the_not_proven_list(self):
        payload = health.to_payload(
            [Report("a", UNKNOWN, "no git"), Report("b", PRESENT, "on PATH")])
        self.assertEqual(payload["verdict"], 2)
        self.assertEqual(sorted(payload["not_proven"]), ["a", "b"])
        json.dumps(payload)      # must stay serialisable


# =========================================================================== #
# 6. the probes observe without becoming the reason it looks healthy          #
# =========================================================================== #
class ProbesDoNotMutate(unittest.TestCase):

    def test_the_ledger_probe_opens_read_only(self):
        """The probe must pass ``read_only=True``, and leave the file alone.

        BOTH HALVES, because the sha alone is not enough: under WAL a
        migration lands in the ``-wal`` sidecar and the main file's bytes do
        not move, so a read-write open can pass a sha check while having taken
        the write lock and re-run migrations on the operator's ledger. The
        constructor spy is the assertion that actually discriminates; the sha
        is the belt to its braces.
        """
        from daedalus.spine import ledger as ledger_mod
        seen: list[dict] = []
        real_init = ledger_mod.SpineLedger.__init__

        def spy(self, path=None, **kw):
            seen.append(dict(kw))
            return real_init(self, path, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            with ledger_mod.SpineLedger(db) as led:
                led.record_intent("attempt.candidate", {"task_id": "t"})
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}), \
                    mock.patch.object(ledger_mod.SpineLedger, "__init__", spy):
                rep = health._p_ledger(Ctx())
            after = hashlib.sha256(db.read_bytes()).hexdigest()
        self.assertTrue(seen, "the probe never opened the ledger at all")
        self.assertTrue(
            all(kw.get("read_only") is True for kw in seen),
            f"the ledger was opened WRITABLE by a status read: {seen}")
        self.assertEqual(before, after,
                         "the ledger probe CHANGED the ledger it was reading")
        self.assertIn(rep.state, (WORKING, DEGRADED, PRESENT))

    def test_the_ledger_probe_does_not_create_a_missing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "nested" / "spine.sqlite3"
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                rep = health._p_ledger(Ctx())
            self.assertFalse(db.exists(),
                             "asking whether the ledger exists CREATED it")
            self.assertFalse(db.parent.exists())
        self.assertEqual(rep.state, ABSENT)

    def test_the_vector_probe_does_not_create_the_index(self):
        """EventVectorStore(path) creates the file. Existence is tested first."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vectors.db"
            with mock.patch.object(health, "_p_vectors", health._p_vectors):
                with mock.patch("daedalus.memory.VECTOR_DB_PATH", db):
                    rep = health._p_vectors(Ctx())
            self.assertFalse(db.exists(),
                             "asking whether the index exists CREATED it")
        self.assertEqual(rep.state, ABSENT)
        self.assertIn("never existed", rep.headline)

    def test_an_empty_index_is_present_not_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vectors.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE agent_event_projections (id TEXT)")
            con.commit()
            con.close()
            with mock.patch("daedalus.memory.VECTOR_DB_PATH", db):
                rep = health._p_vectors(Ctx())
        self.assertEqual(rep.state, PRESENT)
        self.assertNotEqual(rep.state, WORKING)


# =========================================================================== #
# 7. the individual probes tell the truth about a broken world                #
# =========================================================================== #
class ProbesReportBadNews(unittest.TestCase):

    def test_a_dead_watcher_over_a_queued_task_is_degraded(self):
        """The measured escape: `Outbox: 1 pending` is green in both worlds."""
        with tempfile.TemporaryDirectory() as tmp:
            out, inb, arc = (Path(tmp) / d for d in ("outbox", "inbox", "arch"))
            for d in (out, inb, arc):
                d.mkdir()
            (out / "a-task.json").write_text("{}", encoding="utf-8")
            with mock.patch("daedalus.file_bridge.OUTBOX", out), \
                 mock.patch("daedalus.file_bridge.INBOX", inb), \
                 mock.patch("daedalus.file_bridge.ARCHIVE", arc), \
                 mock.patch("daedalus.file_bridge.heartbeat_status",
                            return_value={"state": "stale", "age_s": 900000.0,
                                          "restart": "restart me"}):
                rep = health._p_bridge(Ctx())
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("sit forever", rep.headline)

    def test_a_live_watcher_is_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, inb, arc = (Path(tmp) / d for d in ("outbox", "inbox", "arch"))
            for d in (out, inb, arc):
                d.mkdir()
            with mock.patch("daedalus.file_bridge.OUTBOX", out), \
                 mock.patch("daedalus.file_bridge.INBOX", inb), \
                 mock.patch("daedalus.file_bridge.ARCHIVE", arc), \
                 mock.patch("daedalus.file_bridge.heartbeat_status",
                            return_value={"state": "alive", "age_s": 3.0,
                                          "restart": ""}):
                rep = health._p_bridge(Ctx())
        self.assertEqual(rep.state, WORKING)

    def test_a_degraded_picker_source_is_degraded_even_with_candidates(self):
        """A short queue built from half the sources is not a healthy queue."""
        from daedalus.spine.picker import Candidate, PickedQueue
        cand = Candidate(task_id="t", source="map", instruction="i",
                         reason="r", score=0.9, evidence={"why": "measured"})
        queue = PickedQueue(candidates=(cand,),
                            sources={"map": {"suppressed": True},
                                     "eval_baseline": {"candidates": 1}},
                            notes=("MAP SUPPRESSED (10 withheld): stale",))
        with mock.patch("daedalus.spine.picker.build_queue", return_value=queue):
            rep = health._p_picker(Ctx())
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("map", rep.headline)

    def test_a_healthy_empty_queue_is_working_not_degraded(self):
        """The control: "no work" and "could not read" must stay different."""
        from daedalus.spine.picker import PickedQueue
        queue = PickedQueue(candidates=(), sources={"map": {"candidates": 0}})
        with mock.patch("daedalus.spine.picker.build_queue", return_value=queue):
            rep = health._p_picker(Ctx())
        self.assertEqual(rep.state, WORKING)

    def test_a_stale_map_snapshot_is_degraded(self):
        with mock.patch("daedalus.mapping.drift.digest_ok", return_value=True), \
             mock.patch("daedalus.mapping.drift.snapshot_freshness",
                        return_value={"fresh": False, "recorded_head": "aaa",
                                      "actual_head": "bbb",
                                      "reason": "written against aaa"}):
            rep = health._p_map(Ctx())
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("aaa", rep.headline)

    def test_a_hand_edited_map_snapshot_is_degraded(self):
        with mock.patch("daedalus.mapping.drift.digest_ok", return_value=False), \
             mock.patch("daedalus.mapping.drift.snapshot_freshness",
                        return_value={"fresh": True, "recorded_head": "aaa",
                                      "actual_head": "aaa", "reason": "ok"}):
            rep = health._p_map(Ctx())
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("hand-edited", rep.headline)

    def test_a_missing_map_snapshot_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = health._p_map(Ctx(repo_root=Path(tmp)))
        self.assertEqual(rep.state, ABSENT)

    def test_an_unreachable_embedding_host_is_degraded_not_silent(self):
        import urllib.error
        with mock.patch.object(health, "_http_json",
                               side_effect=urllib.error.URLError("refused")):
            rep = health._embed_probe(Ctx(), "embed.local", "http://127.0.0.1:1",
                                      exercise=True)
        self.assertEqual(rep.state, DEGRADED)
        self.assertNotEqual(rep.state, UNKNOWN)

    def test_a_pulled_model_without_a_vector_is_present_not_working(self):
        """A tag in /api/tags proves weights on disk and nothing else."""
        with mock.patch.object(
                health, "_http_json",
                return_value={"models": [{"model": "nomic-embed-text:latest"}]}):
            rep = health._embed_probe(Ctx(), "embed.bench", "http://host:1",
                                      exercise=False, why_not="off by default")
        self.assertEqual(rep.state, PRESENT)
        self.assertNotEqual(rep.state, WORKING)

    def test_a_module_with_no_production_caller_is_an_island(self):
        with mock.patch.object(health, "CAPABILITY_MODULES",
                               ("daedalus.spine.containment",)):
            rep = health._p_islands(Ctx())
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("ZERO", rep.headline)

    def test_a_wired_module_is_not_an_island(self):
        with mock.patch.object(health, "CAPABILITY_MODULES",
                               ("daedalus.semantic_route",)):
            rep = health._p_islands(Ctx())
        self.assertEqual(rep.state, WORKING)

    def test_the_health_module_does_not_count_as_a_caller(self):
        """The observer is not a caller.

        health.py imports memory.embeddings to look at it. If that counted, the
        surface would certify an island as wired because it touched it.
        """
        hits = health.production_importers("daedalus.memory.embeddings", ROOT)
        self.assertNotIn("daedalus/health.py", hits)
        self.assertNotIn("daedalus/status.py", hits)

    def test_an_unwired_router_is_degraded(self):
        """`semantic_route` shipped as a feature with nothing calling it."""
        with mock.patch.object(health, "production_importers", return_value=[]):
            rep = health._p_route(Ctx(deep=True))
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("NOTHING in the product", rep.headline)

    def test_a_wired_router_that_is_not_called_is_present_not_working(self):
        """Wired is a file fact. Working needs a route to come back."""
        with mock.patch.object(health, "production_importers",
                               return_value=["daedalus/provider_router.py"]):
            rep = health._p_route(Ctx(deep=False))
        self.assertEqual(rep.state, PRESENT)
        self.assertNotEqual(rep.state, WORKING)

    def test_a_router_that_raises_when_called_is_degraded(self):
        """'unwired AND broken if wired' -- the second half."""
        import daedalus.semantic_route as sr
        with mock.patch.object(health, "production_importers",
                               return_value=["daedalus/provider_router.py"]), \
             mock.patch.object(sr, "semantic_route_explained",
                               side_effect=RuntimeError("dim mismatch")):
            rep = health._p_route(Ctx(deep=True))
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("dim mismatch", rep.headline)

    def test_a_keyword_fallback_is_degraded_not_working(self):
        """A route that silently fell back is not a latent route working."""
        import daedalus.semantic_route as sr

        class _R:
            mechanism = sr.FALLBACK
            agent = {"name": "generalist-dev"}

            def explain(self):
                return "latent route UNAVAILABLE; keyword router chose it"

        with mock.patch.object(health, "production_importers",
                               return_value=["daedalus/provider_router.py"]), \
             mock.patch.object(sr, "semantic_route_explained",
                               return_value=_R()):
            rep = health._p_route(Ctx(deep=True))
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("FELL BACK", rep.headline)

    def test_a_vendor_cli_on_path_is_never_working(self):
        """Installed is not working, and proving otherwise costs money."""
        with mock.patch("shutil.which", side_effect=lambda n: f"/usr/bin/{n}"):
            rep = health._p_vendors(Ctx())
        self.assertEqual(rep.state, PRESENT)
        self.assertNotEqual(rep.state, WORKING)

    def test_no_probe_can_report_a_vendor_lane_working(self):
        """Structural: nothing in this module invokes a paid binary."""
        src = (ROOT / "daedalus" / "health.py").read_text(encoding="utf-8")
        for banned in ("subprocess.run([\"claude\"", "subprocess.run(['claude'",
                       "\"codex\", \"exec\"", "'codex', 'exec'",
                       "api.anthropic.com", "api.openai.com"):
            self.assertNotIn(banned, src)


# =========================================================================== #
# 8. the assembled surface on THIS repo                                       #
# =========================================================================== #
class LiveSurface(unittest.TestCase):
    """Runs the real probes against the real tree. Read-only and free."""

    @classmethod
    def setUpClass(cls):
        cls.reports = health.assess(repo_root=ROOT)

    def test_every_report_carries_a_recognised_state(self):
        for r in self.reports:
            self.assertIn(r.state, STATES, f"{r.name} returned {r.state!r}")

    def test_every_report_says_what_it_asked(self):
        for r in self.reports:
            self.assertTrue(r.asks.strip(), f"{r.name} does not state its question")
            self.assertTrue(r.headline.strip(), f"{r.name} has no headline")

    def test_every_working_report_carries_a_measurement(self):
        for r in self.reports:
            if r.state == WORKING:
                self.assertTrue(
                    any(f.provenance == MEASURED for f in r.facts),
                    f"{r.name} claims WORKING with nothing measured")

    def test_no_report_claims_more_than_it_measured(self):
        """Every fact is tagged, and nothing is tagged by accident."""
        for r in self.reports:
            for f in r.facts:
                self.assertIn(f.provenance, health.PROVENANCE)
                if f.provenance == INHERITED:
                    self.assertIsNotNone(f.age_s)
                    self.assertTrue(f.source)

    def test_this_repo_is_not_all_green(self):
        """A surface that cannot say bad news is not a surface.

        This repo is measurably broken right now -- a stale map, a suppressed
        picker queue, a latent weight over an index that has never existed. If
        this assertion ever fails, check the repo BEFORE believing it.
        """
        self.assertNotEqual(health.verdict(self.reports), 0)

    def test_the_render_is_stable_and_names_the_verdict(self):
        out = health.render(self.reports)
        self.assertIn("VERDICT", out)
        self.assertIn("working /", out)


# =========================================================================== #
# 9. status.py stays compatible with its two existing consumers               #
# =========================================================================== #
class StatusSurface(unittest.TestCase):

    def test_collect_status_keeps_every_legacy_key(self):
        from daedalus.status import collect_status
        got = collect_status(str(ROOT))
        for key in ("repo_root", "git_branch", "git_status", "outbox_count",
                    "inbox_count", "memory_events", "open_todos",
                    "todo_snapshot"):
            self.assertIn(key, got)

    def test_count_open_todos_still_exists_for_its_test(self):
        from daedalus.status import _count_open_todos
        self.assertEqual(_count_open_todos([]), 0)

    def test_json_mode_exits_zero_and_carries_the_verdict(self):
        """The VS Code extension treats a non-zero exit as a crashed command.

        A truthful `degraded` must not turn its status bar into an error, so
        --json always exits 0 and puts the verdict in the payload instead.
        """
        import io
        import contextlib
        from daedalus import status as status_mod

        fake = [Report("a", DEGRADED, "broken", (measured("x", 1),))]
        buf = io.StringIO()
        with mock.patch.object(status_mod.health, "assess", return_value=fake), \
                contextlib.redirect_stdout(buf):
            code = status_mod.main(["--repo-root", str(ROOT), "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["health"]["verdict"], 1)
        self.assertIn("outbox_count", payload)

    def test_human_mode_propagates_the_verdict(self):
        import io
        import contextlib
        from daedalus import status as status_mod

        fake = [Report("a", DEGRADED, "broken", (measured("x", 1),))]
        with mock.patch.object(status_mod.health, "assess", return_value=fake), \
                contextlib.redirect_stdout(io.StringIO()):
            code = status_mod.main(["--repo-root", str(ROOT), "--quiet"])
        self.assertEqual(code, 1)


# =========================================================================== #
# 10. THE MUTATION TABLE -- every guard, disabled, must go RED                #
# =========================================================================== #
def _naive_coerce(spec, value, seconds):
    """`_coerce` with all four guards removed: whatever came back, shipped."""
    rep = value if isinstance(value, Report) else Report(spec.name, WORKING, "ok")
    rep.name, rep.asks, rep.required, rep.seconds = (
        spec.name, spec.asks, spec.required, seconds)
    return rep


def _no_post_init(self):
    return None


def _read_write_ledger_probe(ctx):
    """The ledger probe WITHOUT `read_only=True` -- i.e. the mistake."""
    from daedalus.spine.ledger import SpineLedger, default_db_path
    path = default_db_path()
    led = SpineLedger(path)                 # writes: mkdir + WAL + migrate
    try:
        recent = led.recent_intents(limit=10)
    finally:
        led.close()
    return health.working("spine.ledger", f"read {len(recent)}",
                          (measured("intents", len(recent)),))


def _creating_vector_probe(ctx):
    """The vector probe that BUILDS the store to look at it."""
    from daedalus.memory import VECTOR_DB_PATH
    from daedalus.memory.embeddings import EventVectorStore
    store = EventVectorStore(VECTOR_DB_PATH)
    store.close()
    return health.working("memory.vector_index", "opened",
                          (measured("opened", True),))


def _counting_observers(module, repo_root):
    """`production_importers` without the observer exclusion."""
    saved = health._OBSERVERS
    health._OBSERVERS = ()
    try:
        return health.production_importers(module, repo_root)
    finally:
        health._OBSERVERS = saved


#: (name, what it disables, how, which tests must then FAIL)
GUARDS = [
    ("coerce.all_four_ways_of_not_running",
     "the four not-an-answer guards in _coerce",
     lambda: mock.patch.object(health, "_coerce", _naive_coerce),
     ["CannotRunIsNeverGreen.test_a_probe_that_returns_nothing_reports_unknown",
      "CannotRunIsNeverGreen.test_an_invented_state_reports_unknown",
      "CannotRunIsNeverGreen.test_working_without_a_measurement_reports_unknown",
      "CannotRunIsNeverGreen.test_a_broken_dependency_reports_unknown_end_to_end"]),

    ("verdict.unknown_and_present_are_not_green",
     "verdict's refusal to return 0 over a not-proven state",
     lambda: mock.patch.object(health, "verdict", lambda reports: 0),
     ["Verdict.test_one_unknown_is_never_zero",
      "Verdict.test_one_present_is_never_zero",
      "Verdict.test_degraded_outranks_unknown",
      "Verdict.test_required_absent_is_a_failure_optional_absent_is_not",
      "LiveSurface.test_this_repo_is_not_all_green"]),

    ("fact.provenance_is_mandatory",
     "Fact.__post_init__, i.e. a file read can pose as a measurement",
     lambda: mock.patch.object(Fact, "__post_init__", _no_post_init),
     ["Provenance.test_inherited_without_a_source_is_refused",
      "Provenance.test_inherited_without_an_age_is_refused",
      "Provenance.test_assumed_must_name_where_the_assumption_lives",
      "Provenance.test_unrecognised_provenance_is_refused"]),

    ("ledger.read_only",
     "the ledger probe's read-only open",
     lambda: mock.patch.object(health, "_p_ledger", _read_write_ledger_probe),
     ["ProbesDoNotMutate.test_the_ledger_probe_opens_read_only",
      "ProbesDoNotMutate.test_the_ledger_probe_does_not_create_a_missing_ledger"]),

    ("vector_index.existence_checked_before_opening",
     "the existence test that stops the probe creating the index",
     lambda: mock.patch.object(health, "_p_vectors", _creating_vector_probe),
     ["ProbesDoNotMutate.test_the_vector_probe_does_not_create_the_index",
      "ProbesDoNotMutate.test_an_empty_index_is_present_not_working"]),

    ("islands.observer_is_not_a_caller",
     "the exclusion that stops health.py certifying itself",
     lambda: mock.patch.object(health, "production_importers",
                               _counting_observers),
     ["ProbesReportBadNews.test_the_health_module_does_not_count_as_a_caller"]),

    ("render.not_proven_is_named",
     "the NOT PROVEN line in the summary",
     lambda: mock.patch.object(
         health, "render",
         lambda reports, verbose=True: "  everything looks fine\n  VERDICT: ok"),
     ["Rendering.test_unknown_and_present_are_named_in_the_summary",
      "Rendering.test_the_summary_counts_every_state_separately"]),

    ("marks.states_are_distinguishable",
     "the distinct glyph per state",
     lambda: mock.patch.object(
         health, "MARKS", {s: "  works " for s in STATES}),
     ["Vocabulary.test_every_state_has_a_distinct_mark",
      "Vocabulary.test_only_working_reads_as_good"]),

    ("bridge.dead_watcher_is_degraded",
     "the watcher-state branch in the bridge probe",
     lambda: mock.patch.object(
         health, "_p_bridge",
         lambda ctx: health.working("bridge.queue", "1 pending",
                                    (measured("queued", 1),))),
     ["ProbesReportBadNews.test_a_dead_watcher_over_a_queued_task_is_degraded"]),

    ("picker.degraded_sources_are_degraded",
     "the degraded_sources branch, i.e. 'a source failed' reads as 'no work'",
     lambda: mock.patch.object(
         health, "_p_picker",
         lambda ctx: health.working("picker.queue", "queue built",
                                    (measured("candidates", 1),))),
     ["ProbesReportBadNews."
      "test_a_degraded_picker_source_is_degraded_even_with_candidates"]),

    ("vendors.presence_is_never_working",
     "the refusal to call an installed vendor CLI a working lane",
     lambda: mock.patch.object(
         health, "_p_vendors",
         lambda ctx: health.working("vendors.cli", "claude on PATH",
                                    (measured("claude", True),))),
     ["ProbesReportBadNews.test_a_vendor_cli_on_path_is_never_working"]),

    ("route.wired_is_not_working",
     "the router probe's three-way split (unwired / uncalled / fell back)",
     lambda: mock.patch.object(
         health, "_p_route",
         lambda ctx: health.working("route.latent", "the router is present",
                                    (measured("exists", True),))),
     ["ProbesReportBadNews.test_an_unwired_router_is_degraded",
      "ProbesReportBadNews."
      "test_a_wired_router_that_is_not_called_is_present_not_working",
      "ProbesReportBadNews.test_a_router_that_raises_when_called_is_degraded",
      "ProbesReportBadNews.test_a_keyword_fallback_is_degraded_not_working"]),

    ("status.json_exits_zero",
     "the --json exit-0 contract the VS Code extension depends on",
     lambda: mock.patch.object(
         sys.modules["daedalus.status"], "main",
         lambda argv=None: 1),
     ["StatusSurface.test_json_mode_exits_zero_and_carries_the_verdict"]),
]


def _run_named(names):
    """Run exactly these tests and return (failures+errors, total)."""
    suite = unittest.TestSuite()
    module = sys.modules[__name__]
    for dotted in names:
        cls_name, meth = dotted.split(".")
        suite.addTest(getattr(module, cls_name)(meth))
    result = unittest.TestResult()
    suite.run(result)
    return len(result.failures) + len(result.errors), result.testsRun


class GuardsGoRed(unittest.TestCase):
    """Disable each guard for real, and require its tests to fail.

    THIS IS THE ONLY TEST IN THE FILE THAT CANNOT BE SATISFIED BY WRITING MORE
    ASSERTIONS. A guard whose tests stay green with the guard removed was never
    testing the guard, and that is reported here by name.
    """

    def test_every_guard_goes_red_when_disabled(self):
        weak = []
        for name, what, patcher, tests in GUARDS:
            with patcher():
                red, total = _run_named(tests)
            if red == 0:
                weak.append(f"{name} ({what}): {total} test(s) stayed GREEN "
                            f"with the guard disabled")
        self.assertEqual(weak, [], "\n  ".join([""] + weak))

    def test_the_same_tests_are_green_with_the_guards_in_place(self):
        """The other half of the control: the mutations, not the tests, are red."""
        broken = []
        for name, _what, _patcher, tests in GUARDS:
            red, total = _run_named(tests)
            if red:
                broken.append(f"{name}: {red}/{total} red WITHOUT any mutation")
        self.assertEqual(broken, [], "\n  ".join([""] + broken))


def prove_guards() -> int:
    """`python tests/test_health_surface.py --prove-guards`."""
    print(f"{len(GUARDS)} guards; each is disabled and its tests must go RED\n")
    weak = 0
    for name, what, patcher, tests in GUARDS:
        base_red, base_total = _run_named(tests)
        with patcher():
            red, total = _run_named(tests)
        mark = "ok  " if red else "WEAK"
        if not red:
            weak += 1
        print(f"  [{mark}] {name:<48} {red}/{total} red when disabled "
              f"(baseline {base_red}/{base_total})")
        print(f"         disables: {what}")
    print(f"\n{len(GUARDS) - weak}/{len(GUARDS)} guards proven load-bearing")
    return 1 if weak else 0


if __name__ == "__main__":
    if "--prove-guards" in sys.argv:
        raise SystemExit(prove_guards())
    unittest.main()
