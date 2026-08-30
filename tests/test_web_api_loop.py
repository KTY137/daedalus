# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The self-improvement loop over the local API -- driven through a REAL server.

Every test here goes through ``ThreadingHTTPServer`` + ``DaedalusHandler`` on a
free loopback port and reads the bytes that actually cross the socket. Nothing
under test is mocked: the picker builds a real queue from this checkout, the
ledger is a real SQLite file this module writes with the real ``SpineLedger``,
and the assertions are made against the raw response body.

THREE PROPERTIES, EACH WITH A TEST THAT WAS VERIFIED TO GO RED
--------------------------------------------------------------
1. READ-ONLY -- ``LedgerIsNotMutatedByAReadTest``. The plain ``SpineLedger``
   constructor creates the parent directory, sets ``journal_mode=WAL`` and runs
   migrations inside BEGIN IMMEDIATE, so merely OPENING a ledger writes to it.
   The test hashes the database file across a request.
2. A FAILED SOURCE IS NOT AN EMPTY QUEUE -- ``DegradedSourceIsVisibleTest``. A
   real, unreadable ledger (a file that is not a database) is used to degrade a
   source for real, and the control case proves the endpoint discriminates.
3. BOUNDED, AND NO BLOB PASS-THROUGH -- ``BoundedResponseTest`` and
   ``NoSecretsInTheAttemptHistoryTest``.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from daedalus import web_api
from daedalus.sensitivity import ENV_TRUSTED_HOSTS, is_loopback_host, lane_for_host
from daedalus.spine.ledger import SpineLedger

ATTEMPT_KIND = "attempt.candidate"


# --------------------------------------------------------------------------- #
# a real server on a free loopback port                                        #
# --------------------------------------------------------------------------- #
class LoopApiTestCase(unittest.TestCase):
    """Drives the real handler over a real socket.

    One server for the whole class: starting it is the only expensive part, and
    every endpoint under test is read-only, so requests cannot interfere.
    """

    server: ThreadingHTTPServer
    thread: threading.Thread

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)

    def get(self, path: str) -> tuple[int, bytes, dict]:
        """(status, raw body, parsed body). Raw bytes matter: the size and
        secret-leak assertions are about what crossed the socket, not about a
        dict this process happens to hold."""
        try:
            with urllib.request.urlopen(self.base + path, timeout=120) as resp:
                raw = resp.read()
                status = resp.status
                self.headers = dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            self.headers = dict(exc.headers)
        return status, raw, json.loads(raw.decode("utf-8"))

    def get_in(self, path: str, repo: Path) -> tuple[int, bytes, dict]:
        """``get``, but the endpoint resolves ``?project=`` to ``repo``.

        The request completes inside the patch: urlopen blocks until the
        response is fully written, so the server thread cannot outlive it.
        """
        with mock.patch.object(web_api, "resolve_repo_root",
                               lambda _root, project: str(repo)):
            return self.get(path)


def _picker_ledger_path(repo: Path) -> Path:
    """The ledger path the PICKER will actually open for ``repo``.

    The queue's attempt-memory source resolves its ledger REPO-LOCALLY
    (``<repo>/runs/spine/spine.sqlite3`` or ``spine.ledger_path`` in project
    config) and deliberately does NOT read ``DAEDALUS_SPINE_DB`` -- that env
    var belongs to the process-global LEDGER surface (``/api/loop/attempts``),
    not to the repo-confined picker (ruling by the resolver's author,
    2026-07-29, in the room; the picker's confinement is itself pinned by
    ``tests/test_picker_work_queue.py``). Three tests here used to set the env
    var and silently fall through to the REAL ledger -- red in the full suite,
    green alone, measuring this developer's machine instead of the fixture.
    Queue tests write the fixture database HERE; ledger-surface tests keep
    using the env var, correctly.
    """
    p = Path(repo) / "runs" / "spine" / "spine.sqlite3"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _seed_ledger(path: Path, n: int = 2,
                 instruction: str = "wire the island in") -> None:
    """Write a real ledger with real intents, then close it cleanly."""
    ledger = SpineLedger(path)
    try:
        for i in range(n):
            payload = {
                "task_id": f"map-island-seeded-{i}",
                "instruction": instruction,
                "base_revision": "0" * 40,
                "gate_paths": [],
                "metadata": {"picker_source": "map_island",
                             "picker_score": 830.0,
                             "picker_reason": "unreachable from every entry point",
                             "picker_evidence": {"module": f"daedalus/seed_{i}.py"}},
                "resolved_base_revision": "0" * 40,
                "branch": f"daedalus-attempt-seeded-{i}",
                "repo_root": "/seeded/repo/root",
                "worktree_root": "/seeded/worktree/root",
            }
            intent = ledger.record_intent(ATTEMPT_KIND, payload,
                                          effect_key=f"daedalus-attempt-seeded-{i}")
            if i == 0:
                ledger.mark_completed(intent.id, effect_id="sha256:seeded",
                                      result={"state": "no_change",
                                              "branch": payload["branch"],
                                              "gates": None, "artifact": None,
                                              "error": None})
    finally:
        ledger.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trusted_map_repo(tmp: str, islands: int = 8, shims: int = 3) -> Path:
    """A repo whose GENERATED map snapshot the picker will trust.

    The queue tests must not depend on whether THIS checkout currently has
    work. Measured mid-session: another agent added a freshness gate to
    ``map_state_trustworthy`` and moved HEAD, and the live queue went from ten
    candidates to zero with both sources degraded -- correct behaviour, and it
    would have turned every queue test into a test of the tree's mood.

    Freshness fails OPEN when git cannot answer, and this fixture has no
    ``.git``, so a recorded ``repo_state.head`` plus a correct digest is enough
    to be trusted. The digest is computed with the mapping module's own
    function, so the fixture cannot drift from what the checker accepts.
    """
    from daedalus.mapping.drift import _digest

    doc = {
        "schema": 3,
        "counts": {"modules": islands + shims + 4, "islands": islands,
                   "shims": shims, "test_only": 2, "unknown": 0,
                   "unparsable": 0, "index_extra_edges": 0,
                   "dark_switches": 0, "doc_drift": 0},
        "ignore": {},
        "modules": [f"pkg/mod_{i}.py" for i in range(islands + shims + 4)],
        "islands": [f"pkg/island_{i}.py" for i in range(islands)],
        "shims": [f"pkg/shim_{i}.py" for i in range(shims)],
        "test_only": ["pkg/island_0.py", "pkg/island_1.py"],
        "unknown": [], "dark_switches": [], "doc_drift": [],
        "unparsable": [], "index_extra_edges": [], "acceptances": [],
        "note": "fixture",
        "repo_state": {"head": "abcdef1234567", "dirty": False},
    }
    doc["digest"] = _digest(doc)
    repo = Path(tmp) / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "architecture-state.json").write_text(
        json.dumps(doc), encoding="utf-8")
    return repo


# --------------------------------------------------------------------------- #
# routing                                                                      #
# --------------------------------------------------------------------------- #
class LoopRoutesAnswerTest(LoopApiTestCase):
    def test_the_live_checkout_answers_and_stays_self_consistent(self) -> None:
        """No claim about what THIS tree contains -- only that the endpoint
        answers about it coherently. Right now this checkout's queue is empty
        with two degraded sources, which is a fact about the tree."""
        status, _, body = self.get("/api/loop/queue?limit=5")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        queue = body["queue"]
        self.assertLessEqual(queue["returned"], 5)
        self.assertEqual(queue["incomplete"], bool(queue["degraded_sources"]))
        self.assertEqual(queue["returned"], len(queue["candidates"]))
        # If it IS incomplete, it must say so where a human will see it.
        if queue["degraded_sources"]:
            self.assertTrue(any("INCOMPLETE" in w for w in body["warnings"]))

    def test_queue_endpoint_returns_candidates_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, _, body = self.get_in("/api/loop/queue?limit=5&project=fake",
                                          _trusted_map_repo(tmp))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        queue = body["queue"]
        self.assertEqual(queue["returned"], 5)
        self.assertEqual(queue["degraded_sources"], [])
        self.assertIn("sources", queue)
        for cand in queue["candidates"]:
            # NO TASK WITHOUT EVIDENCE, all the way to the socket. A queue whose
            # entries cannot be argued with is a queue of opinion.
            self.assertTrue(cand["reason"].strip(), cand["task_id"])
            self.assertTrue(cand["evidence"], cand["task_id"])
            self.assertIn("measurement", cand["evidence"])
            self.assertEqual(cand["score"],
                             cand["band"] + cand["measured_offset"])

    def test_architecture_endpoint_returns_the_generated_counts(self) -> None:
        status, _, body = self.get("/api/loop/architecture")
        self.assertEqual(status, 200)
        arch = body["architecture"]
        self.assertTrue(arch["read"])
        self.assertIn("modules", arch["counts"])
        self.assertIn("islands", arch["counts"])
        self.assertTrue(arch["digest"].startswith("sha256:"))
        # The snapshot's own counts must agree with the lists in the same file.
        self.assertEqual(arch["count_disagreements"], {})
        # DELIBERATELY NOT an assertion that this tree's snapshot is trusted.
        # Trust is a fact about the checkout (the predicate grew a freshness
        # question mid-session and the live snapshot stopped qualifying), and a
        # test that pinned it would be testing the repo, not this endpoint.
        # What must hold is that the endpoint stays self-consistent about it.
        self.assertEqual(arch["incomplete"], not arch["trusted"])
        self.assertEqual(arch["degraded_sources"],
                         [] if arch["trusted"] else ["map"])
        self.assertEqual(arch["trust"]["trusted"], arch["trusted"])

    def test_a_trustworthy_snapshot_is_reported_as_trusted(self) -> None:
        """The positive control, built rather than borrowed from the tree.

        Without it the endpoint could report EVERY snapshot as degraded and the
        untrusted test above would still pass.
        """
        from daedalus.mapping.drift import _digest

        doc = {"schema": 3, "counts": {"modules": 2, "islands": 1, "shims": 0},
               "ignore": {}, "modules": ["a.py", "b.py"], "islands": ["a.py"],
               "unknown": [], "shims": [], "test_only": [], "dark_switches": [],
               "doc_drift": [], "unparsable": [], "index_extra_edges": [],
               "acceptances": [], "note": "fixture",
               # A real abbreviated sha. The temp repo has no .git, so the
               # freshness check cannot read HEAD and fails OPEN -- which is
               # the documented behaviour for a checkout without git.
               "repo_state": {"head": "abcdef1234567", "dirty": False}}
        doc["digest"] = _digest(doc)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "docs").mkdir(parents=True)
            (repo / "docs" / "architecture-state.json").write_text(
                json.dumps(doc), encoding="utf-8")
            with mock.patch.object(web_api, "resolve_repo_root",
                                   lambda _r, project: str(repo)):
                _, _, body = self.get("/api/loop/architecture?project=fake")

        arch = body["architecture"]
        self.assertTrue(arch["trusted"], arch["trust_reason"])
        self.assertEqual(arch["degraded_sources"], [])
        self.assertFalse(arch["incomplete"])
        self.assertEqual(arch["counts"]["modules"], 2)
        self.assertEqual(arch["count_disagreements"], {})

    def test_attempts_endpoint_answers_from_a_real_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            _seed_ledger(db, n=2)
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                status, _, body = self.get("/api/loop/attempts?limit=10")
        self.assertEqual(status, 200)
        attempts = body["attempts"]
        self.assertEqual(attempts["returned"], 2)
        self.assertTrue(attempts["ledger"]["read_only"])
        ids = {row["task_id"] for row in attempts["intents"]}
        self.assertEqual(ids, {"map-island-seeded-0", "map-island-seeded-1"})
        resolved = [r for r in attempts["intents"] if r["state"] == "COMPLETED"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["outcome"], "no_change")

    def test_attempts_can_be_filtered_to_one_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            _seed_ledger(db, n=3)
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                _, _, body = self.get(
                    "/api/loop/attempts?task_id=map-island-seeded-1")
        rows = body["attempts"]["intents"]
        self.assertEqual([r["task_id"] for r in rows], ["map-island-seeded-1"])

    def test_unknown_loop_endpoint_is_a_404_not_the_webapp(self) -> None:
        status, _, body = self.get("/api/loop/nope")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_an_unknown_project_is_a_400_not_a_500(self) -> None:
        """A caller's bad input is a client error. A 500 here would put a
        stack-trace string where a message belongs and read as a server bug."""
        for endpoint in ("/api/loop/queue", "/api/loop/architecture"):
            with self.subTest(endpoint=endpoint):
                status, _, body = self.get(
                    f"{endpoint}?project=no-such-project-exists")
                self.assertEqual(status, 400)
                self.assertFalse(body["ok"])
                self.assertTrue(body["error"])


# --------------------------------------------------------------------------- #
# PROPERTY 1 -- reading the ledger must not write it                           #
# --------------------------------------------------------------------------- #
class LedgerIsNotMutatedByAReadTest(LoopApiTestCase):
    """A GET is not allowed to write the ledger it reports on.

    This is not pedantry. ``SpineLedger.__init__`` without ``read_only=True``
    mkdirs the parent, sets ``journal_mode=WAL`` and runs migrations inside a
    BEGIN IMMEDIATE transaction. An endpoint the cockpit polls would therefore
    be MIGRATING the durable record of what the loop intended, every few
    seconds, forever -- and taking the write lock while doing it.

    THE DIGEST OF A HEALTHY LEDGER IS NOT, BY ITSELF, A CONTROL. Measured: a
    ledger that is already in WAL and was closed cleanly has byte-identical
    contents after a plain writing open, because the migrations are all ``IF NOT
    EXISTS`` / ``OR IGNORE`` and commit no pages. A test that only hashed a
    healthy ledger would stay green with ``read_only`` removed -- a guard
    everybody believes and nothing enforces.

    So the discriminating case is a SQLite file that is not a spine ledger yet.
    A writing open migrates whatever you point it at: measured 8 KB -> 40 KB,
    four tables created, bytes changed. A read-only open cannot, and the
    endpoint reports that it could not read instead of quietly manufacturing an
    empty history. Both cases are asserted below.

    VERIFIED RED: flipping ``read_only=True`` to ``False`` in
    ``web_api._loop_attempts`` fails the foreign-database test.
    """

    @staticmethod
    def _foreign_sqlite(path: Path) -> None:
        """A real SQLite database that is not a spine ledger."""
        import sqlite3

        con = sqlite3.connect(str(path))
        try:
            con.execute("CREATE TABLE unrelated (x TEXT)")
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _tables(path: Path) -> set:
        import sqlite3

        con = sqlite3.connect(str(path))
        try:
            return {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()

    def test_attempts_request_leaves_a_healthy_ledger_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            _seed_ledger(db, n=3)
            before, size_before = _sha256(db), db.stat().st_size

            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                status, _, body = self.get("/api/loop/attempts?limit=10")

            self.assertEqual(status, 200)
            # The read has to have actually happened; an endpoint that returned
            # nothing would pass a "did not mutate" test trivially.
            self.assertEqual(body["attempts"]["returned"], 3)
            self.assertIsNone(body["attempts"]["ledger"]["error"])
            self.assertEqual(_sha256(db), before,
                             "the spine ledger's bytes changed during a GET")
            self.assertEqual(db.stat().st_size, size_before)

    def test_attempts_request_does_not_migrate_a_foreign_database(self) -> None:
        """The control. A writing open would create the spine schema here."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            self._foreign_sqlite(db)
            before, tables_before = _sha256(db), self._tables(db)

            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                status, _, body = self.get("/api/loop/attempts?limit=10")

            self.assertEqual(status, 200)
            self.assertEqual(_sha256(db), before,
                             "the GET wrote to the database it was reading")
            self.assertEqual(self._tables(db), tables_before,
                             "the GET created the spine schema by opening it")
            self.assertNotIn("intents", self._tables(db))
            # And it said so, rather than reporting an empty history it had
            # just invented by creating the tables.
            self.assertTrue(body["attempts"]["incomplete"])
            self.assertEqual(body["attempts"]["degraded_sources"],
                             ["spine_ledger"])
            self.assertIn("intents", body["attempts"]["ledger"]["error"])

    def test_queue_request_does_not_write_the_ledger_either(self) -> None:
        """The queue reads the ledger too -- through the picker's attempt
        memory -- so it carries the same obligation. Both cases, same reasons."""
        with tempfile.TemporaryDirectory() as tmp:
            # A repo with real candidates, so attempt memory is actually
            # consulted. With an empty queue the picker never opens the ledger
            # at all and this test would prove nothing.
            repo = _trusted_map_repo(tmp)
            healthy = _picker_ledger_path(repo)
            _seed_ledger(healthy, n=2)
            before = _sha256(healthy)
            status, _, body = self.get_in(
                "/api/loop/queue?limit=10&project=fake", repo)
            self.assertEqual(status, 200)
            self.assertGreater(body["queue"]["returned"], 0)
            self.assertTrue(body["queue"]["sources"]["attempt_memory"]["read"])
            self.assertEqual(_sha256(healthy), before,
                             "the spine ledger's bytes changed during a GET")

            healthy.unlink()
            foreign = _picker_ledger_path(repo)
            self._foreign_sqlite(foreign)
            before, tables_before = _sha256(foreign), self._tables(foreign)
            _, _, body = self.get_in(
                "/api/loop/queue?limit=10&project=fake", repo)
            self.assertEqual(_sha256(foreign), before,
                             "the GET wrote to the database it was reading")
            self.assertEqual(self._tables(foreign), tables_before)
            self.assertIn("attempt_memory", body["queue"]["degraded_sources"])

    def test_no_write_verb_reaches_the_loop_surface(self) -> None:
        """The loop is read-only as a SURFACE, not just per call site: there is
        no POST or PUT that can reach any of these three paths."""
        for path in ("/api/loop/queue", "/api/loop/attempts",
                     "/api/loop/architecture"):
            for verb in ("POST", "PUT"):
                req = urllib.request.Request(self.base + path, data=b"{}",
                                             method=verb,
                                             headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        code, raw = resp.status, resp.read()
                except urllib.error.HTTPError as exc:
                    code, raw = exc.code, exc.read()
                self.assertEqual(code, 404, f"{verb} {path} was answered")
                self.assertFalse(json.loads(raw.decode("utf-8"))["ok"])


# --------------------------------------------------------------------------- #
# PROPERTY 2 -- "a source failed" must not read as "there is no work"          #
# --------------------------------------------------------------------------- #
class DegradedSourceIsVisibleTest(LoopApiTestCase):
    """Degrades a source FOR REAL and checks the API says so.

    The degradation is a file that exists and is not a SQLite database, which is
    what a truncated write or a half-copied runs/ directory actually looks like.
    ``attempt_history`` catches it, the picker records it in
    ``sources.attempt_memory.error``, and ``degraded_sources`` names it.

    Both halves are asserted, because only the pair is a control: an endpoint
    that always reported "degraded" would pass the first test, and one that
    never did would pass the second.

    VERIFIED RED: dropping ``degraded_sources``/``incomplete`` from the queue
    payload in ``web_api._loop_queue`` fails this test on a KeyError.
    """

    def test_an_unreadable_ledger_is_reported_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _trusted_map_repo(tmp)
            bad = _picker_ledger_path(repo)
            bad.write_bytes(b"this is not a sqlite database" * 32)
            _, raw, body = self.get_in(
                "/api/loop/queue?limit=5&project=fake", repo)

        queue = body["queue"]
        self.assertIn("attempt_memory", queue["degraded_sources"])
        self.assertTrue(queue["incomplete"])
        # The failure names itself in the response, not only in a server log.
        self.assertIn("error", queue["sources"]["attempt_memory"])
        self.assertTrue(any("INCOMPLETE" in w for w in body["warnings"]),
                        body["warnings"])
        # And the queue did NOT quietly empty: a broken source degrades the
        # answer, it does not delete the work that other sources found.
        self.assertGreater(queue["returned"], 0)

    def test_a_healthy_ledger_is_not_reported_as_degraded(self) -> None:
        # Repo-local like the failing cases above -- with the env var this
        # passed VACUOUSLY (the picker never opened the fixture at all).
        with tempfile.TemporaryDirectory() as tmp:
            repo = _trusted_map_repo(tmp)
            _seed_ledger(_picker_ledger_path(repo), n=1)
            _, _, body = self.get_in(
                "/api/loop/queue?limit=5&project=fake", repo)
        self.assertGreater(body["queue"]["returned"], 0)
        self.assertEqual(body["queue"]["degraded_sources"], [])

    def test_attempts_distinguishes_no_ledger_from_a_broken_ledger(self) -> None:
        """An absent ledger is a fresh checkout with nothing attempted. An
        unreadable one is a source that failed. Both return zero rows, and
        collapsing them is exactly how a broken loop looks idle."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "never-written.sqlite3"
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(missing)}):
                _, _, absent = self.get("/api/loop/attempts")

            broken = Path(tmp) / "broken.sqlite3"
            broken.write_bytes(b"not a database at all" * 16)
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(broken)}):
                _, _, failed = self.get("/api/loop/attempts")

        self.assertEqual(absent["attempts"]["returned"], 0)
        self.assertEqual(failed["attempts"]["returned"], 0)
        # Same row count, different answer.
        self.assertFalse(absent["attempts"]["incomplete"])
        self.assertEqual(absent["attempts"]["degraded_sources"], [])
        self.assertIsNotNone(absent["attempts"]["ledger"]["note"])

        self.assertTrue(failed["attempts"]["incomplete"])
        self.assertEqual(failed["attempts"]["degraded_sources"], ["spine_ledger"])
        self.assertIn("not a database", failed["attempts"]["ledger"]["error"])

    def test_architecture_reports_an_untrusted_snapshot_as_degraded(self) -> None:
        """A hand-edited generated file is worse than a missing one: it looks
        authoritative. The digest verdict has to reach the client."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "docs").mkdir(parents=True)
            (repo / "docs" / "architecture-state.json").write_text(
                json.dumps({"schema": 3, "digest": "sha256:" + "0" * 64,
                            "counts": {"modules": 1, "islands": 1},
                            "modules": ["a.py"], "islands": ["a.py"],
                            "shims": [], "test_only": [], "unknown": []}),
                encoding="utf-8")
            with mock.patch.object(web_api, "resolve_repo_root",
                                   lambda _r, project: str(repo)):
                _, _, body = self.get("/api/loop/architecture?project=fake")

        arch = body["architecture"]
        self.assertTrue(arch["read"])
        self.assertFalse(arch["trusted"])
        self.assertEqual(arch["degraded_sources"], ["map"])
        self.assertTrue(arch["incomplete"])
        self.assertTrue(any("INCOMPLETE" in w for w in body["warnings"]))


# --------------------------------------------------------------------------- #
# PROPERTY 3a -- bounded payloads                                              #
# --------------------------------------------------------------------------- #
class BoundedResponseTest(LoopApiTestCase):
    """Nothing here may return an unbounded number of unbounded rows.

    VERIFIED RED: removing the range check in ``web_api._loop_limit`` makes the
    limit test fail; removing the ``_clip`` calls in ``_loop_attempt_row`` makes
    the oversize test fail; making ``_loop_fit`` return its payload unchanged
    makes the size-cap test fail.
    """

    def test_limit_is_range_checked(self) -> None:
        for bad, message in (("0", "between"), ("51", "between"),
                             ("-1", "between"), ("9999", "between"),
                             ("abc", "integer")):
            for endpoint in ("/api/loop/queue", "/api/loop/attempts"):
                status, _, body = self.get(f"{endpoint}?limit={bad}")
                self.assertEqual(status, 400, f"{endpoint}?limit={bad}")
                self.assertFalse(body["ok"])
                self.assertIn(message, body["error"])

    def test_limit_at_the_ceiling_is_accepted(self) -> None:
        status, _, body = self.get(
            f"/api/loop/queue?limit={web_api.LOOP_MAX_LIMIT}")
        self.assertEqual(status, 200)
        self.assertLessEqual(body["queue"]["returned"], web_api.LOOP_MAX_LIMIT)

    def test_an_enormous_instruction_is_clipped_visibly(self) -> None:
        """A runner is free to record a 400 KB instruction. The API is not free
        to hand it to a browser, and it is not free to truncate it silently
        either -- a shortened instruction reads as a complete one."""
        huge = "W" * 400_000
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            _seed_ledger(db, n=3, instruction=huge)
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                status, raw, body = self.get("/api/loop/attempts?limit=50")

        self.assertEqual(status, 200)
        self.assertLessEqual(len(raw), web_api.LOOP_RESPONSE_MAX_BYTES,
                             f"response was {len(raw)} bytes")
        self.assertEqual(body["attempts"]["returned"], 3)
        for row in body["attempts"]["intents"]:
            self.assertLess(len(row["instruction"]), 2000)
            self.assertIn("chars truncated", row["instruction"])

    def test_evidence_and_sources_are_bounded_in_width_and_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(web_api, "LOOP_VALUE_CHARS", 24), \
             mock.patch.object(web_api, "LOOP_TEXT_CHARS", 60):
            _, _, body = self.get_in("/api/loop/queue?limit=10&project=fake",
                                     _trusted_map_repo(tmp))
        queue = body["queue"]
        self.assertGreater(queue["returned"], 0)
        for cand in queue["candidates"]:
            self.assertIn("chars truncated", cand["instruction"])
            for key, value in cand["evidence"].items():
                # Nested scalars obey the NESTED bound, and say where they were
                # cut -- an evidence value that ends mid-number is a
                # measurement a reviewer would misread.
                if isinstance(value, str) and len(value) > 24:
                    self.assertIn("chars truncated", value, f"{key}={value!r}")

    def test_the_size_cap_drops_rows_but_never_the_degraded_report(self) -> None:
        """When the cap bites it trims WORK, never the reason the answer is
        incomplete. A cap that can delete "a source failed" while keeping "here
        is more work" makes property 2 a coincidence."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _trusted_map_repo(tmp)
            bad = _picker_ledger_path(repo)
            bad.write_bytes(b"not a database" * 64)
            with mock.patch.object(web_api, "LOOP_RESPONSE_MAX_BYTES", 4000):
                _, raw, body = self.get_in(
                    "/api/loop/queue?limit=25&project=fake", repo)

        queue = body["queue"]
        self.assertLessEqual(len(raw), 4000, f"response was {len(raw)} bytes")
        self.assertGreater(queue["dropped_for_size"], 0)
        self.assertLess(queue["returned"], queue["n_candidates"])
        # The header survived the trim.
        self.assertIn("attempt_memory", queue["degraded_sources"])
        self.assertTrue(queue["incomplete"])


# --------------------------------------------------------------------------- #
# PROPERTY 3b -- no blob pass-through, so no secrets                           #
# --------------------------------------------------------------------------- #
class NoSecretsInTheAttemptHistoryTest(LoopApiTestCase):
    """The ledger payload is PROJECTED through a fixed allowlist, not dumped.

    The recorded payload carries the primary checkout's absolute path, the
    worktree root and whatever a caller put in ``metadata``; the recorded result
    carries a gate's command line and 4000 characters of its output. An endpoint
    that returns the blob has an exposure that changes silently whenever someone
    edits a runner -- which is not a property anybody can review.

    VERIFIED RED: replacing the projection in ``web_api._loop_attempt_row`` with
    ``dict(payload)`` leaks every needle below.
    """

    NEEDLES = ("sk-ant-LEAK-ME-NOW", "gh_pat_LEAK", "/seeded/worktree/root",
               "/seeded/repo/root", "OPENAI_API_KEY")

    def test_payload_and_result_blobs_do_not_cross_the_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            ledger = SpineLedger(db)
            try:
                intent = ledger.record_intent(ATTEMPT_KIND, {
                    "task_id": "map-island-secretive",
                    "instruction": "wire the island into a real caller",
                    "repo_root": "/seeded/repo/root",
                    "worktree_root": "/seeded/worktree/root",
                    "api_key": "sk-ant-LEAK-ME-NOW",
                    "metadata": {
                        "picker_source": "map_island",
                        "picker_reason": "unreachable from every entry point",
                        "env": {"OPENAI_API_KEY": "gh_pat_LEAK"},
                    },
                }, effect_key="daedalus-attempt-secretive")
                ledger.mark_failed(intent.id, json.dumps({
                    "state": "gates_failed",
                    "error": "the gate refused the diff",
                    "gates": {"command": ["pytest", "--token", "gh_pat_LEAK"],
                              "output_tail": "sk-ant-LEAK-ME-NOW" * 100},
                }))
            finally:
                ledger.close()

            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                status, raw, body = self.get("/api/loop/attempts?limit=10")

        self.assertEqual(status, 200)
        text = raw.decode("utf-8")
        for needle in self.NEEDLES:
            self.assertNotIn(needle, text, f"{needle!r} reached the client")

        # ... while the endpoint still answers the question it exists for.
        row = body["attempts"]["intents"][0]
        self.assertEqual(row["task_id"], "map-island-secretive")
        self.assertEqual(row["state"], "FAILED")
        self.assertEqual(row["outcome"], "gates_failed")
        self.assertEqual(row["error"], "the gate refused the diff")
        self.assertEqual(row["source"], "map_island")
        self.assertIn("wire the island", row["instruction"])

    def test_the_projection_is_a_closed_set_of_fields(self) -> None:
        """A field list a reviewer can read in one place. If a new field is
        added it has to be added here too, on purpose."""
        expected = {"intent_id", "kind", "state", "created_ts", "resolved_ts",
                    "effect_key", "task_id", "instruction", "source", "score",
                    "reason", "outcome", "gates_passed", "changed_paths",
                    "error"}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            _seed_ledger(db, n=1)
            with mock.patch.dict(os.environ, {"DAEDALUS_SPINE_DB": str(db)}):
                _, _, body = self.get("/api/loop/attempts")
        self.assertEqual(set(body["attempts"]["intents"][0]), expected)

    def test_the_ledger_path_cannot_be_chosen_by_the_caller(self) -> None:
        """``?db=`` would be a filesystem read primitive for anything that can
        reach the port. The ledger location comes from the environment only."""
        source = inspect.getsource(web_api)
        self.assertNotIn('qs.get("db")', source)
        self.assertNotIn('qs.get("repo_root")', source)
        self.assertNotIn('qs.get("path")', source)


# --------------------------------------------------------------------------- #
# the surface itself: local-only, and cheap to start                           #
# --------------------------------------------------------------------------- #
class LocalOnlySurfaceTest(LoopApiTestCase):
    """VERIFIED RED: changing either default fails this test."""

    def test_the_bind_defaults_are_loopback(self) -> None:
        self.assertEqual(
            inspect.signature(web_api.run).parameters["host"].default,
            "127.0.0.1")
        self.assertIn('default="127.0.0.1"', inspect.getsource(web_api.main))
        # No default ANYWHERE in the module hands out a non-loopback bind. The
        # literal may appear in prose (the refusal message explains itself);
        # what may not appear is a default that ships one.
        for default in re.findall(r'default\s*=\s*"([^"]*)"',
                                  inspect.getsource(web_api)):
            if re.fullmatch(r"[0-9a-fA-F:.\[\]]+", default):
                self.assertEqual(lane_for_host(default), "trusted",
                                 f"default={default!r} is not this machine")

    def test_cors_is_not_widened_by_the_loop_endpoints(self) -> None:
        self.get("/api/loop/architecture")
        self.assertEqual(self.headers.get("Access-Control-Allow-Origin"),
                         "http://127.0.0.1:5173")

    def test_importing_web_api_does_not_open_or_create_the_ledger(self) -> None:
        """The acceptance harness starts this server against a readiness
        deadline. Nothing added here may open a database at import time -- and
        creating the ledger merely by importing would break property 1 before a
        single request arrived."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "spine.sqlite3"
            env = {**os.environ, "DAEDALUS_SPINE_DB": str(db),
                   "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys, daedalus.web_api as w;"
                 " print(w.DaedalusHandler.server_version)"],
                cwd=str(Path(web_api.__file__).resolve().parents[1]),
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=180, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            self.assertFalse(db.exists(),
                             "importing web_api created the spine ledger")


class NonLoopbackBindIsRefusedTest(unittest.TestCase):
    """`daedalus web --host <not this machine>` must not start a server.

    THE HOLE THIS CLOSES, measured: ``daedalus/cli.py`` passes its remaining
    argv straight into ``web_api.main``, ``--host`` was an ordinary argparse
    string, and this module contains no authentication of any kind. So
    ``daedalus web --host 0.0.0.0`` served every endpoint to every interface
    with nothing in front of it -- and the endpoints added in this same change
    put the spine ledger and the picker queue behind that same open door. POST
    ``/api/ikarus/ask`` makes it remote SPEND, not merely remote read.
    ``docs/adrs/002-hermes-upstream.md`` rejected an entire subsystem for having
    exactly this shape.

    Nothing binds a socket in this class: ``_resolve_bind`` is the decision, and
    it is reached before ``ThreadingHTTPServer`` is constructed, so a refusal
    provably means no listener existed.

    VERIFIED RED for each guard -- see the module docstring and the report.
    """

    def setUp(self) -> None:
        # No inherited opt-in from the developer's shell.
        self.env = mock.patch.dict(os.environ, {
            web_api.ALLOW_REMOTE_ENV: "", web_api.AUTH_TOKEN_ENV: ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    # -- the refusal --------------------------------------------------------- #
    def test_wildcard_and_lan_addresses_are_refused_by_name(self) -> None:
        for host in ("0.0.0.0", "192.168.1.24", "100.119.126.9", "::", ""):
            with self.subTest(host=host):
                with self.assertRaises(web_api.NonLoopbackBindRefused) as caught:
                    web_api._resolve_bind(host, False)
                message = str(caught.exception)
                # The operator has to be able to see WHICH address was refused.
                if host:
                    self.assertIn(host, message)
                self.assertIn("REFUSED", message)
                self.assertIn("NOT started", message)

    def test_localhost_the_name_is_refused_although_it_resolves_local(self) -> None:
        """Deliberate, and inherited from the predicate rather than decided
        here: a name that resolves to loopback when it is CHECKED can resolve
        elsewhere when it is CONNECTED."""
        self.assertEqual(lane_for_host("localhost"), "untrusted")
        with self.assertRaises(web_api.NonLoopbackBindRefused) as caught:
            web_api._resolve_bind("localhost", False)
        self.assertIn("127.0.0.1", str(caught.exception))

    def test_run_refuses_before_any_socket_is_bound(self) -> None:
        """The refusal is not a message printed next to a live listener.

        Runs in a thread with a deadline rather than under ``assertRaises``.
        Measured the hard way: when this guard is disabled, ``run`` does not
        raise -- it reaches ``serve_forever`` and never returns, so a bare
        ``assertRaises`` hangs the whole suite instead of going red. A guard
        test that deadlocks when the guard is removed reports nothing.
        """
        port = _free_port()
        outcome: dict = {}

        def call() -> None:
            try:
                web_api.run("0.0.0.0", port)
                outcome["result"] = "returned without refusing"
            except web_api.NonLoopbackBindRefused:
                outcome["result"] = "refused"
            except Exception as exc:
                outcome["result"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout=30)
        self.assertFalse(worker.is_alive(),
                         "run() never returned: it is SERVING a non-loopback "
                         "address right now")
        self.assertEqual(outcome.get("result"), "refused")
        # Nothing is listening on that port: we can still take it ourselves.
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()

    def test_the_cli_path_exits_nonzero_and_starts_nothing(self) -> None:
        """`daedalus web --host 0.0.0.0` end to end, through the real CLI."""
        port = _free_port()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "daedalus.cli", "web",
                 "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(Path(web_api.__file__).resolve().parents[1]),
                capture_output=True, encoding="utf-8", errors="replace",
                # A refusal returns immediately. The only way this deadline is
                # reached is a server that started and is now serving, so the
                # timeout is short ON PURPOSE -- a guard test that takes three
                # minutes to go red is a guard test nobody re-runs.
                timeout=60,
                env={**os.environ, "PYTHONIOENCODING": "utf-8",
                     web_api.ALLOW_REMOTE_ENV: "", web_api.AUTH_TOKEN_ENV: ""})
        except subprocess.TimeoutExpired:
            self.fail("`daedalus web --host 0.0.0.0` did not exit: it was NOT "
                      "refused, it is serving every interface right now")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REFUSED", proc.stdout + proc.stderr)
        self.assertNotIn("listening on", proc.stdout)

    # -- the control: the guard must not refuse everything ------------------- #
    def test_loopback_still_works_and_needs_no_token(self) -> None:
        for host in ("127.0.0.1", "127.0.0.53", "[::1]"):
            with self.subTest(host=host):
                self.assertEqual(web_api._resolve_bind(host, False), "")

    def test_an_unbracketed_ipv6_loopback_is_refused_and_that_is_deliberate(
            self) -> None:
        """Measured asymmetry in the shared predicate, inherited on purpose.

        ``lane_for_host`` trusts ``[::1]`` and NOT the bare ``::1`` -- urlsplit
        cannot read an unbracketed IPv6 literal as a hostname. That makes this
        guard slightly STRICTER than the predicate, which is the safe direction,
        and it costs nothing real: ``ThreadingHTTPServer`` is AF_INET, so a bare
        ``::1`` could never have been bound by this server anyway. Normalising
        it here would mean deriving host semantics at the call site, which is
        exactly the habit that put five disagreeing copies of this question in
        the repo.
        """
        self.assertEqual(lane_for_host("::1"), "untrusted")
        with self.assertRaises(web_api.NonLoopbackBindRefused):
            web_api._resolve_bind("::1", False)

    def test_a_loopback_server_really_serves_without_credentials(self) -> None:
        """The end of the control: the default path is untouched by all of
        this. The acceptance harness starts exactly this way."""
        port = _free_port()
        thread = threading.Thread(target=web_api.run, args=("127.0.0.1", port),
                                  daemon=True)
        thread.start()
        body = _await_server(self, port, "/api/loop/architecture")
        self.assertTrue(json.loads(body)["ok"])

    # -- the escape hatch: real, and closed without authentication ----------- #
    def test_the_opt_in_is_refused_without_a_token(self) -> None:
        with self.assertRaises(web_api.NonLoopbackBindRefused) as caught:
            web_api._resolve_bind("0.0.0.0", True)
        self.assertIn(web_api.AUTH_TOKEN_ENV, str(caught.exception))

        with mock.patch.dict(os.environ, {web_api.AUTH_TOKEN_ENV: "short"}):
            with self.assertRaises(web_api.NonLoopbackBindRefused) as caught:
                web_api._resolve_bind("0.0.0.0", True)
        self.assertIn("5 characters long", str(caught.exception))

    def test_the_opt_in_with_a_token_is_granted(self) -> None:
        token = "t" * web_api.MIN_AUTH_TOKEN_CHARS
        with mock.patch.dict(os.environ, {web_api.AUTH_TOKEN_ENV: token}):
            self.assertEqual(web_api._resolve_bind("192.168.1.24", True), token)
            # ... and the env var is a second, equal door to the same opt-in.
            with mock.patch.dict(os.environ, {web_api.ALLOW_REMOTE_ENV: "1"}):
                self.assertEqual(web_api._resolve_bind("192.168.1.24", False),
                                 token)

    # -- the split: a declared-trusted host is a consent, not a location ----- #
    def test_a_declared_trusted_host_is_still_refused_without_the_remote_opt_in(
            self) -> None:
        """THE CRITICAL THIS PREVENTS. An operator can declare a private-
        tunnel bench trusted for INFERENCE EGRESS (DAEDALUS_TRUSTED_HOSTS)
        without that declaration also granting an unauthenticated
        control-plane bind. lane_for_host says "trusted" for this host --
        _resolve_bind must ask is_loopback_host instead and refuse exactly as
        it would for any other non-loopback address.

        MEASURED: before is_loopback_host existed, _resolve_bind read
        lane_for_host directly, so this same declaration returned an empty
        auth token and _authorized() treated every request as authorized --
        publishing the spine ledger, the role-rewriting PUTs and the
        model-invoking POSTs, unauthenticated, to the tailnet.
        """
        with mock.patch.dict(os.environ, {ENV_TRUSTED_HOSTS: "100.119.126.9"}):
            self.assertEqual(lane_for_host("100.119.126.9"), "trusted")
            self.assertFalse(is_loopback_host("100.119.126.9"))
            with self.assertRaises(web_api.NonLoopbackBindRefused) as caught:
                web_api._resolve_bind("100.119.126.9", False)
            message = str(caught.exception)
            self.assertIn("100.119.126.9", message)
            self.assertIn("REFUSED", message)

    def test_a_declared_trusted_host_still_needs_the_SAME_opt_in_as_any_other(
            self) -> None:
        """The control: the declaration does not lock the host out either --
        it reaches the ordinary opt-in+token door, the same one every other
        non-loopback address must use. Consent about egress is not consent
        about the bind; it also is not a *veto* on the bind."""
        token = "d" * web_api.MIN_AUTH_TOKEN_CHARS
        with mock.patch.dict(os.environ, {ENV_TRUSTED_HOSTS: "100.119.126.9",
                                          web_api.AUTH_TOKEN_ENV: token}):
            self.assertEqual(web_api._resolve_bind("100.119.126.9", True), token)

    def test_the_loop_endpoints_are_401_on_an_authenticated_bind(self) -> None:
        """The escape hatch does not reopen the hole. Bound to loopback (so the
        test binds nothing exotic) but carrying the token a non-loopback bind
        would carry -- which is the only thing that changes about the server."""
        token = "z" * web_api.MIN_AUTH_TOKEN_CHARS
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
        server.daedalus_auth_token = token
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for path in ("/api/loop/queue", "/api/loop/attempts",
                         "/api/loop/architecture", "/api/dashboard"):
                with self.subTest(path=path):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + path, timeout=60)
                    self.assertEqual(caught.exception.code, 401)
            # A wrong token is not close enough.
            req = urllib.request.Request(
                base + "/api/loop/queue",
                headers={"Authorization": "Bearer " + "z" * 31 + "y"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=60)
            self.assertEqual(caught.exception.code, 401)
            # The right one is.
            req = urllib.request.Request(
                base + "/api/loop/queue",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read())["ok"])
            # Writes are behind the same door.
            req = urllib.request.Request(base + "/api/queue", data=b"{}",
                                         method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=60)
            self.assertEqual(caught.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _await_server(case: unittest.TestCase, port: int, path: str,
                  deadline_s: float = 30.0) -> bytes:
    """Poll until the server answers. Mirrors the acceptance harness's
    readiness deadline rather than sleeping a guessed interval."""
    import time

    end, last = time.time() + deadline_s, ""
    while time.time() < end:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
            time.sleep(0.2)
    case.fail(f"server did not answer within {deadline_s}s: {last}")


if __name__ == "__main__":
    unittest.main()
