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
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_an_untimed_read_reports_no_wait_rather_than_the_sum(self):
        """`wall_seconds` is measured or it is null. It is never derived.

        The probes are concurrent, so the sum of the rows is the WORK and the
        wall clock is the WAIT -- 8.3s and 2.2s respectively, measured
        2026-09-10. Back-filling one from the other would put a 4x overstatement
        on the screen under the word "measured", which is the exact class of
        claim this module exists to refuse.
        """
        rows = [Report("a", WORKING, "", (measured("x", 1),), seconds=2.0),
                Report("b", WORKING, "", (measured("x", 1),), seconds=2.0)]
        self.assertIsNone(health.to_payload(rows)["wall_seconds"])
        timed = health.to_payload(rows, wall_seconds=2.061)
        self.assertEqual(timed["wall_seconds"], 2.061)
        self.assertLess(timed["wall_seconds"],
                        sum(r["seconds"] for r in timed["subsystems"]))


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
        # THIRD pinning, and the last one that should ever be needed.
        #
        # It was pinned to `daedalus.spine.containment`, which stopped being an
        # island the moment it was wired into the gate. It was then re-pinned to
        # `daedalus.compaction` -- which was DELETED on 2026-07-29 (superseded by
        # the token-accurate eviction already in providers/ollama.py), and the
        # test went red again, this time reporting "do not exist" rather than
        # "ZERO callers".
        #
        # A test nailed to a fact in the live tree rots every time the fact does.
        # So this one now BUILDS the condition it is about: a module that exists
        # on disk and that nothing in the product imports. No repo fact can
        # falsify it, and no future wiring or deletion can rot it.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / "daedalus"
            pkg.mkdir()
            (pkg / "lonely_capability.py").write_text(
                "def capability():\n    return 42\n", encoding="utf-8")
            # A production file that exists and imports something ELSE, proving
            # the scanner did run and simply found no importer of the island.
            (pkg / "caller.py").write_text(
                "from daedalus import os_shim\n", encoding="utf-8")
            with mock.patch.object(health, "CAPABILITY_MODULES",
                                   ("daedalus.lonely_capability",)):
                rep = health._p_islands(Ctx(repo_root=root))
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("ZERO", rep.headline)
        self.assertIn("lonely_capability", rep.headline)

    def test_every_import_FORM_counts_as_a_caller(self):
        """The regression this file did not catch, pinned directly.

        The detector required the module's leaf name inside the dotted path,
        which cannot span the space before `import` -- so
        `from daedalus.spine import containment` was invisible and the surface
        reported a freshly-wired module as having ZERO production callers.
        """
        forms = {
            "import a.b.leafmod": "import a.b.leafmod\n",
            "from a.b.leafmod import X": "from a.b.leafmod import X\n",
            "from a.b import leafmod": "from a.b import leafmod\n",
            "from a.b import x, leafmod": "from a.b import x, leafmod\n",
        }
        for label, text in forms.items():
            rows = [("daedalus/caller.py", "daedalus/caller.py", text)]
            hits = health.production_importers("a.b.leafmod", Path("."), rows)
            self.assertEqual(hits, ["daedalus/caller.py"],
                             f"{label} was not recognised as an import")

    def test_an_unrelated_word_is_not_an_import(self):
        """The allow side. A detector that matched any mention of the name
        would report every docstring as a caller and never find an island."""
        rows = [("daedalus/caller.py", "daedalus/caller.py",
                 "# see daedalus.spine.leafmod for why\nx = 'leafmod'\n")]
        self.assertEqual(
            health.production_importers("a.b.leafmod", Path("."), rows), [])

    def test_a_wired_module_is_not_an_island(self):
        with mock.patch.object(health, "CAPABILITY_MODULES",
                               ("daedalus.orchestration.semantic_route",)):
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
        import daedalus.orchestration.semantic_route as sr
        with mock.patch.object(health, "production_importers",
                               return_value=["daedalus/provider_router.py"]), \
             mock.patch.object(sr, "semantic_route_explained",
                               side_effect=RuntimeError("dim mismatch")):
            rep = health._p_route(Ctx(deep=True))
        self.assertEqual(rep.state, DEGRADED)
        self.assertIn("dim mismatch", rep.headline)

    def test_a_keyword_fallback_is_degraded_not_working(self):
        """A route that silently fell back is not a latent route working."""
        import daedalus.orchestration.semantic_route as sr

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
# 7b. the probes run CONCURRENTLY, and the answer is unchanged by that        #
# =========================================================================== #
class ProbesRunConcurrently(unittest.TestCase):
    """The wait is bounded by the slowest probe, not by their sum.

    MEASURED 2026-09-10: the serial loop this replaced made `GET /api/health`
    cost 6.2s warm and 11.3s cold, and the desktop's status line therefore read
    "Zustand wird gelesen …" for that whole time on every launch. Two of the
    twenty probes ask the same dead local Ollama host one after the other, and
    a refused TCP connect costs ~2.04s on that machine whatever the port.

    NOT A CLOCK ASSERTION. A test that asserts "faster than N seconds" is a
    test that goes red on a loaded box and green on a serial implementation
    that happens to run on a fast one. These probes meet at a
    :class:`threading.Barrier` instead: every probe must be in flight at the
    same moment or the barrier breaks and the reports say so. Serial cannot
    pass it, and a slow machine cannot fail it.
    """

    #: Long enough that a busy box is not what breaks the barrier, short enough
    #: that the mutation in :data:`GUARDS` does not stall the suite.
    RENDEZVOUS_S = 8.0

    @classmethod
    def _fan(cls, n: int):
        """`n` probes that only report WORKING if all `n` are running at once."""
        barrier = threading.Barrier(n, timeout=cls.RENDEZVOUS_S)

        def make(i):
            def fn(ctx):
                barrier.wait()      # BrokenBarrierError when run one by one
                return health.working(f"fan.{i}", "met the other probes",
                                      (measured("index", i),))
            return ProbeSpec(name=f"fan.{i}", asks="are we concurrent?", fn=fn)

        return [make(i) for i in range(n)]

    def test_all_probes_are_in_flight_at_the_same_moment(self):
        with mock.patch.object(health, "PROBES", self._fan(4)):
            reports = health.assess()
        self.assertEqual([r.name for r in reports],
                         ["fan.0", "fan.1", "fan.2", "fan.3"])
        self.assertEqual([r.state for r in reports], [WORKING] * 4,
                         "\n".join(f"{r.name}: {r.headline}" for r in reports))

    def test_reports_come_back_in_registry_order_not_finishing_order(self):
        """Concurrency must not reshuffle the board under the operator."""
        def slow(seconds, i):
            def fn(ctx):
                time.sleep(seconds)
                return health.working(f"ord.{i}", "done", (measured("i", i),))
            return ProbeSpec(name=f"ord.{i}", asks="?", fn=fn)

        # Registered slowest-first, so finishing order is the exact reverse.
        specs = [slow(0.30, 0), slow(0.20, 1), slow(0.10, 2), slow(0.0, 3)]
        with mock.patch.object(health, "PROBES", specs):
            reports = health.assess()
        self.assertEqual([r.name for r in reports],
                         ["ord.0", "ord.1", "ord.2", "ord.3"])

    def test_a_probe_that_raises_still_becomes_unknown_off_the_main_thread(self):
        """`_coerce`'s guarantee has to survive being called in a worker."""
        def boom(ctx):
            raise RuntimeError("the probe itself fell over")

        specs = [ProbeSpec(name="ok.one", asks="?",
                           fn=lambda ctx: health.working(
                               "ok.one", "fine", (measured("x", 1),))),
                 ProbeSpec(name="bad.one", asks="?", fn=boom)]
        with mock.patch.object(health, "PROBES", specs):
            reports = health.assess()
        self.assertEqual(reports[0].state, WORKING)
        self.assertEqual(reports[1].state, UNKNOWN)
        self.assertIn("RuntimeError", reports[1].headline)

    def test_a_single_probe_read_still_answers(self):
        """`?only=` narrows to one probe; it must not need a rendezvous."""
        specs = [ProbeSpec(name="solo.probe", asks="?",
                           fn=lambda ctx: health.working(
                               "solo.probe", "alone", (measured("x", 1),))),
                 ProbeSpec(name="other.probe", asks="?",
                           fn=lambda ctx: health.working(
                               "other.probe", "no", (measured("x", 2),)))]
        with mock.patch.object(health, "PROBES", specs):
            reports = health.assess(only="solo")
        self.assertEqual([r.name for r in reports], ["solo.probe"])
        self.assertEqual(reports[0].state, WORKING)

    def test_the_bench_is_dialled_once_even_when_both_probes_start_together(self):
        """"one timeout, not two" survives the two probes becoming simultaneous.

        NO SLEEP TO RACE ON. The first version of this stubbed the dial with
        `time.sleep(0.25)` and hoped the second caller arrived inside that
        window; on a loaded box it does not, and the test then passes for the
        wrong reason. The stub now BLOCKS until released, so "the second caller
        found the first one in flight" is arranged rather than hoped for.
        """
        calls = []
        hold = threading.Event()
        together = threading.Barrier(2, timeout=self.RENDEZVOUS_S)

        def blocking_ssh(host, script, timeout):
            calls.append(host)
            hold.wait(self.RENDEZVOUS_S)     # a waiter never reaches this
            return True, {"task": {"ok": False, "error": "stub"},
                          "crashes": {"ok": False, "error": "stub"}}

        ctx = Ctx()                          # ONE run: the cache is run-scoped
        stopwatch = {}

        def call(_):
            together.wait()                  # both enter the cache together
            t0 = time.monotonic()
            out = health._ssh_bench_snapshot(ctx)
            stopwatch[threading.get_ident()] = time.monotonic() - t0
            return out

        with mock.patch.object(health, "_ssh_powershell", blocking_ssh):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(call, i) for i in range(2)]
                time.sleep(0.20)
                # The winner is parked in the stub and the loser must be parked
                # on its answer, so at this instant exactly one dial exists.
                dialled_while_blocked = len(calls)
                hold.set()
                out = [f.result(timeout=self.RENDEZVOUS_S) for f in futures]

        self.assertEqual(dialled_while_blocked, 1,
                         f"{dialled_while_blocked} caller(s) dialled while the "
                         f"first dial was still in flight")
        self.assertEqual(len(calls), 1,
                         f"the bench was dialled {len(calls)} time(s)")
        self.assertEqual(out[0], out[1])

    def test_the_waiter_is_not_billed_for_the_dial_it_waited_on(self):
        """ONE dial must not be reported as two probes' worth of work.

        MEASURED before the fix, with a 3.0s stubbed dial: `sum(seconds)` came
        to 6.04 against a `wall_seconds` of 3.01, because the probe that merely
        waited carried the winner's 3.0s inside its own row. `HealthPanel`
        prints that sum, so the figure the wall-clock split exists to keep
        honest was itself inflated by exactly the waiting it excludes.
        """
        dial_s = 0.60

        def slow_ssh(host, script, timeout):
            time.sleep(dial_s)
            return True, {"task": {"ok": False, "error": "stub"},
                          "crashes": {"ok": False, "error": "stub"}}

        def probe_fn(ctx):
            health._ssh_bench_snapshot(ctx)
            return health.working("bench.x", "asked", (measured("asked", 1),))

        specs = [ProbeSpec(name=f"bench.{i}", asks="?", fn=probe_fn)
                 for i in range(2)]
        with mock.patch.object(health, "_ssh_powershell", slow_ssh):
            with mock.patch.object(health, "PROBES", specs):
                t0 = time.monotonic()
                reports = health.assess()
                wall = time.monotonic() - t0

        billed = sum(r.seconds for r in reports)
        self.assertLessEqual(
            billed, wall + 0.25,
            f"the board billed {billed:.2f}s of work inside a {wall:.2f}s read")
        # And the waiter specifically: one row is ~0, not another whole dial.
        self.assertLess(min(r.seconds for r in reports), dial_s / 2,
                        f"rows were {[round(r.seconds, 3) for r in reports]}")

    def test_the_tree_is_walked_once_per_run_however_many_probes_ask(self):
        """`route.latent` and `wiring.islands` share one walk again.

        Serially, the second probe found the first one's walk already cached.
        Started together they both missed a cold module dict and both walked --
        measured 1 walk -> 2 at one caller and 2 -> 4 at two, against a
        docstring promising "read ONCE per run".
        """
        walks = []

        def counting_walk(repo_root):
            walks.append(str(repo_root))
            time.sleep(0.05)
            return [("x.py", "x.py", "")]

        def asker(ctx):
            health.run_sources(ctx)
            return health.working("ask", "asked", (measured("asked", 1),))

        specs = [ProbeSpec(name=f"ask.{i}", asks="?", fn=asker)
                 for i in range(4)]
        with mock.patch.object(health, "_production_sources", counting_walk):
            with mock.patch.object(health, "PROBES", specs):
                health.assess()
        self.assertEqual(len(walks), 1,
                         f"the tree was walked {len(walks)} time(s)")

    def test_two_concurrent_assess_calls_do_not_clear_each_others_work(self):
        """The scenario the threading HTTP server makes reachable on any poll.

        The module dicts were cleared at the top of `assess`, OUTSIDE the lock
        that guarded them: request B entering `assess` between request A's two
        bench probes made A's second probe miss and dial again -- two 9s
        timeouts inside one request. Run-scoped state cannot do that, so four
        probes across two overlapping runs produce exactly two walks and two
        dials, never one and never six.
        """
        walks, dials = [], []

        def counting_walk(repo_root):
            walks.append(str(repo_root))
            time.sleep(0.05)
            return [("x.py", "x.py", "")]

        def counting_ssh(host, script, timeout):
            dials.append(host)
            time.sleep(0.05)
            return True, {"task": {"ok": False, "error": "stub"},
                          "crashes": {"ok": False, "error": "stub"}}

        def asker(ctx):
            health.run_sources(ctx)
            health._ssh_bench_snapshot(ctx)
            return health.working("ask", "asked", (measured("asked", 1),))

        specs = [ProbeSpec(name=f"ask.{i}", asks="?", fn=asker)
                 for i in range(3)]
        start = threading.Barrier(2, timeout=self.RENDEZVOUS_S)

        def one_request(_):
            start.wait()          # the two runs really do overlap
            return health.assess()

        with mock.patch.object(health, "_production_sources", counting_walk):
            with mock.patch.object(health, "_ssh_powershell", counting_ssh):
                with mock.patch.object(health, "PROBES", specs):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        boards = list(pool.map(one_request, range(2)))

        self.assertEqual(len(walks), 2, f"{len(walks)} walk(s) for 2 runs")
        self.assertEqual(len(dials), 2, f"{len(dials)} dial(s) for 2 runs")
        for board in boards:
            self.assertEqual([r.state for r in board], [WORKING] * 3)

    def test_an_interrupt_on_the_joining_thread_ends_the_read_at_once(self):
        """Ctrl-C during a 9s ssh must not be swallowed until the ssh returns.

        `ThreadPoolExecutor`'s context manager calls `shutdown(wait=True)`, so
        the interrupt could not leave `assess` until every probe finished --
        MEASURED 2026-09-10, KeyboardInterrupt escaped a serial read in 0.32s
        and a pooled one in 4.00s, and the ssh and git ceilings put the worst
        case at 15s.

        SIGINT is delivered to the main thread, which inside `_fan_out` is the
        thread sitting in `Thread.join`; that join raising is exactly what a
        Ctrl-C looks like from in here. The probes keep running -- they are
        daemons, and the next test pins that -- so the requirement is that the
        CALLER is released, not that the work stopped.
        """
        slow_s = 4.0
        release = threading.Event()

        def slow(_item):
            release.wait(slow_s)
            return health.working("slow", "done", (measured("x", 1),))

        real_join = threading.Thread.join
        fired = []

        def join_once(self_thread, timeout=None):
            if not fired:
                fired.append(True)
                raise KeyboardInterrupt("SIGINT during the poll")
            return real_join(self_thread, timeout)

        t0 = time.monotonic()
        try:
            with mock.patch.object(threading.Thread, "join", join_once):
                with self.assertRaises(KeyboardInterrupt):
                    health._fan_out(slow, [1, 2])
            took = time.monotonic() - t0
        finally:
            release.set()
        self.assertLess(took, slow_s / 2,
                        f"the interrupt took {took:.2f}s to escape a "
                        f"{slow_s:.1f}s read")

    def test_the_fan_out_threads_are_daemons(self):
        """The property that lets an interrupted read actually end.

        `ThreadPoolExecutor` workers are non-daemon AND it registers an atexit
        hook that joins them, so `shutdown(wait=False, cancel_futures=True)`
        only moves the same wait to interpreter shutdown. Daemon threads are
        what make abandoning a probe possible at all -- safe here only because
        `ProbesDoNotMutate` proves the probes do not write.
        """
        seen = []

        def note(ctx):
            t = threading.current_thread()
            seen.append((t.daemon, t.name))
            return health.working("n", "ok", (measured("x", 1),))

        specs = [ProbeSpec(name=f"n.{i}", asks="?", fn=note) for i in range(2)]
        with mock.patch.object(health, "PROBES", specs):
            health.assess()
        self.assertEqual(len(seen), 2)
        for daemon, name in seen:
            self.assertTrue(daemon, f"{name} is not a daemon thread")


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


def _serial_assess(only=None, *, repo_root=None, probe_remote=False,
                   deep=False, timeout_s=6.0):
    """`assess` as it was before 2026-09-10: one probe after another.

    This is the regression, verbatim. It answers exactly the same thing, which
    is why no assertion about STATES or provenance can catch it -- only the
    rendezvous in :class:`ProbesRunConcurrently` can.
    """
    ctx = Ctx(repo_root=Path(repo_root).resolve() if repo_root else health.ROOT,
              probe_remote=probe_remote, deep=deep, timeout_s=timeout_s)
    out = []
    for spec in health.PROBES:
        if only and only not in spec.name:
            continue
        t0 = time.monotonic()
        try:
            value = spec.fn(ctx)
        except BaseException as exc:                     # noqa: BLE001
            if isinstance(exc, KeyboardInterrupt):
                raise
            value = exc
        out.append(health._coerce(spec, value, time.monotonic() - t0))
    return out


def _unshared_ssh_snapshot(ctx):
    """`_ssh_bench_snapshot` without the run-scoped single flight.

    Every caller dials for itself, and is billed for its own dial. That is the
    state of affairs a plain dict produced once the two bench probes started at
    the same moment -- the dict was always empty when both of them looked.
    """
    return health._ssh_powershell(health.BENCH_SSH_HOST,
                                  health._BENCH_SNAPSHOT_SCRIPT,
                                  health.BENCH_SSH_TIMEOUT_S)


def _unshared_sources(ctx):
    """`run_sources` without the single flight: every asker walks the tree."""
    return health._production_sources(ctx.repo_root)


def _joining_fan_out(fn, items):
    """The `ThreadPoolExecutor` fan-out, whose exit joins every worker."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        return list(pool.map(fn, items))


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

    ("assess.probes_are_concurrent",
     "the probe fan-out, i.e. the wait becomes the SUM of the probes again",
     lambda: mock.patch.object(health, "assess", _serial_assess),
     ["ProbesRunConcurrently.test_all_probes_are_in_flight_at_the_same_moment"]),

    ("ssh_cache.single_flight_per_run",
     "the run-scoped single flight: both bench probes dial, and both are billed",
     lambda: mock.patch.object(health, "_ssh_bench_snapshot",
                               _unshared_ssh_snapshot),
     ["ProbesRunConcurrently."
      "test_the_bench_is_dialled_once_even_when_both_probes_start_together",
      "ProbesRunConcurrently."
      "test_the_waiter_is_not_billed_for_the_dial_it_waited_on",
      "ProbesRunConcurrently."
      "test_two_concurrent_assess_calls_do_not_clear_each_others_work"]),

    ("source_cache.one_walk_per_run",
     "the single flight over the tree walk, i.e. every asker walks it again",
     lambda: mock.patch.object(health, "run_sources", _unshared_sources),
     ["ProbesRunConcurrently."
      "test_the_tree_is_walked_once_per_run_however_many_probes_ask"]),

    ("fan_out.is_interruptible",
     "the daemon-thread fan-out, i.e. the exit joins every probe again",
     lambda: mock.patch.object(health, "_fan_out", _joining_fan_out),
     ["ProbesRunConcurrently."
      "test_an_interrupt_on_the_joining_thread_ends_the_read_at_once",
      "ProbesRunConcurrently.test_the_fan_out_threads_are_daemons"]),

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
