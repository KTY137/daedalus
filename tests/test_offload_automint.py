"""The flywheel seam: a LANDED offload write mints its own eval task.

``daedalus.eval.mint.mint_task_from_landed_edit`` has existed for several
sessions with no caller -- minted tasks only ever entered the corpus by hand.
``offload`` now calls it after a write that actually landed, and stamps the
outcome on ``result["auto_mint"]`` for EVERY write-mode run so a seam that
declined to fire is visible rather than invisible.

Invariants pinned here:
  * fires only on a genuinely landed edit (verified disk change, gate passed,
    nothing rolled back) -- never on an escalated, rolled-back, advisory or
    dry run;
  * exactly one mint + one store write per landed run;
  * the minted task is QUARANTINE tier, and a non-quarantine task is REFUSED
    rather than persisted (minting at write time must never inject a
    primary-tier label into the corpus a promotion decision reads);
  * a minter that raises is fail-soft AND loud -- the offload stays
    ``offloaded``, the write is not rolled back, and the failure is reported as
    ``auto_mint.status == "error"``;
  * the env flag toggles it, and it is OFF by default (minting shells out to
    git and rebuilds the index -- see ``_auto_mint_enabled``).

The real minter is never invoked here: both ``mint_task_from_landed_edit`` and
``add_minted_task`` are patched, so no test can write the repo's real mint
store.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.offload import _AUTO_MINT_ENV

from test_offload_lease_harness import live_offload as offload


# Benign wording (risk stays low -> mode "write"); non-sensitive docs path.
_OBJECTIVE = "improve the helper defaults"
# A review-only objective on a trusted-only agent routes to the ollama ADVISORY
# lane (provider_router._REVIEW_ONLY_TERMS / the not-external_ok branch).
_ADVISORY_OBJECTIVE = "review the helper defaults"
_TARGET = "docs/notes_helper.py"

# Bench up, codex off -> a low-risk write lands on ollama/write.
_AVAIL_OLLAMA = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}

_REPORT = {"status": "done", "summary": "s", "files_changed": [],
           "tests_run": [], "risks": [], "todos": [], "handoff": {}}
# Schema-invalid status -> the verifier's cheap schema check fails with no
# subprocess, so the write is rolled back and the run escalates.
_BAD_REPORT = {**_REPORT, "status": "not-a-real-status"}

_TASK = {
    "id": "mint-landed_edit-deadbeef1234",
    "repo": "/fake/repo",
    "target": _TARGET,
    "must_include": ["blurb", "helper"],
    "tier": "quarantine",
    "label_provenance": "independent_diff",
    "confirmations": 0,
}


@contextlib.contextmanager
def _auto_mint_env(value: str | None):
    """Set/unset the flag for one block; ``None`` = unset (the default)."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop(_AUTO_MINT_ENV, None)
        if value is not None:
            os.environ[_AUTO_MINT_ENV] = value
        yield


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp: str, *, external_ok: bool = True) -> str:
    """One benign docs module + a policy (writes are refused without one) + a
    repo-local agent so routing is hermetic."""
    root = Path(tmp)
    _write(root, _TARGET, "def blurb():\n    return 'hi'\n")
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["docs/"]}}', encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": ' + ("true" if external_ok else "false") + ','
        ' "owns": ["docs"], "triggers": ["helper", "improve", "review"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class _Worker:
    """Rollback-capable worker that writes the declared target."""

    def __init__(self, repo_root: str, rel: str, report: dict):
        self._root, self._rel, self._report = repo_root, rel, report
        self._backup: bytes | None = None
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        p = Path(self._root) / self._rel
        self._backup = p.read_bytes() if p.exists() else None
        p.write_text("def blurb():\n    return 'bye'\n", encoding="utf-8")
        return {"report": dict(self._report)}

    def rollback(self):
        p = Path(self._root) / self._rel
        if self._backup is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(self._backup)
        return [self._rel]


class _NoWriteWorker:
    """Advisory worker: produces a report, touches nothing."""

    def run(self, **kwargs):
        return {"report": dict(_REPORT)}

    def rollback(self):
        return []


class _FakeMinter:
    """Stands in for daedalus.eval.mint -- records calls, never touches git or
    the real mint store."""

    STORE = "C:/fake/minted_tasks.json"

    def __init__(self, task: dict | None = _TASK, raises: Exception | None = None):
        self.task, self.raises = task, raises
        self.mint_calls: list[tuple[dict, str]] = []
        self.saved: list[dict] = []

    def mint(self, report: dict, repo_root: str):
        self.mint_calls.append((dict(report), repo_root))
        if self.raises is not None:
            raise self.raises
        return dict(self.task) if self.task else None

    def add(self, task: dict, path: str | None = None) -> str:
        self.saved.append(task)
        return self.STORE


class AutoMintSeamTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _repo(self._tmp.name)

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def _offload(self, worker, minter, *, flag: str | None = "1",
                 objective: str = _OBJECTIVE, live: bool = True):
        with _auto_mint_env(flag), \
                mock.patch("daedalus.providers.get_provider", return_value=worker), \
                mock.patch("daedalus.eval.mint.mint_task_from_landed_edit", minter.mint), \
                mock.patch("daedalus.eval.mint.add_minted_task", minter.add):
            return offload(objective, self.repo, paths=[_TARGET], live=live,
                           availability=_AVAIL_OLLAMA)

    # --- fires on a landed write ------------------------------------------
    def test_landed_write_mints_once_into_quarantine(self):
        minter = _FakeMinter()
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter)

        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(r["wrote"], [_TARGET])
        # Exactly one mint, one store write.
        self.assertEqual(len(minter.mint_calls), 1)
        self.assertEqual(len(minter.saved), 1)
        # The minter is handed the OFFLOAD RESULT -- its "wrote" is the verified
        # disk diff, not the model's self-report.
        report_seen, root_seen = minter.mint_calls[0]
        self.assertEqual(report_seen["wrote"], [_TARGET])
        self.assertEqual(root_seen, self.repo)
        self.assertEqual(r["auto_mint"]["status"], "minted")
        self.assertEqual(r["auto_mint"]["task_id"], _TASK["id"])
        self.assertEqual(r["auto_mint"]["tier"], "quarantine")
        self.assertEqual(r["auto_mint"]["store"], _FakeMinter.STORE)
        self.assertEqual(minter.saved[0]["tier"], "quarantine")

    def test_minter_finding_nothing_is_a_reported_skip(self):
        minter = _FakeMinter(task=None)
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter)
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(len(minter.mint_calls), 1)
        self.assertEqual(minter.saved, [])
        self.assertEqual(r["auto_mint"]["status"], "skipped")
        self.assertIn("no independent label", r["auto_mint"]["reason"])

    # --- never fires on a run that did not land ---------------------------
    def test_rolled_back_write_does_not_mint(self):
        minter = _FakeMinter()
        worker = _Worker(self.repo, _TARGET, _BAD_REPORT)
        original = (Path(self.repo) / _TARGET).read_text(encoding="utf-8")
        r = self._offload(worker, minter)

        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertEqual(r["rolled_back"], [_TARGET])
        self.assertEqual((Path(self.repo) / _TARGET).read_text(encoding="utf-8"),
                         original)
        self.assertEqual(minter.mint_calls, [])
        self.assertEqual(minter.saved, [])
        # Reported, not silent.
        self.assertEqual(r["auto_mint"]["status"], "skipped")
        self.assertIn("escalated_after_verify_fail", r["auto_mint"]["reason"])

    def test_write_lane_that_changed_nothing_does_not_mint(self):
        minter = _FakeMinter()
        r = self._offload(_NoWriteWorker(), minter)
        # No disk change -> the write-mode gate escalates; nothing landed.
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["wrote"], [])
        self.assertNotEqual(r["action"], "offloaded")
        self.assertEqual(minter.mint_calls, [])
        self.assertEqual(r["auto_mint"]["status"], "skipped")

    def test_advisory_run_never_reaches_the_minter(self):
        # A trusted-only agent + a review-only objective is the advisory lane.
        self.repo = _repo(tempfile.mkdtemp(dir=self._tmp.name), external_ok=False)
        minter = _FakeMinter()
        r = self._offload(_NoWriteWorker(), minter, objective=_ADVISORY_OBJECTIVE)
        self.assertEqual(r["mode"], "advisory")
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(minter.mint_calls, [])
        # Advisory results stay byte-identical to before the seam existed.
        self.assertNotIn("auto_mint", r)

    def test_dry_run_never_reaches_the_minter(self):
        minter = _FakeMinter()
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter, live=False)
        self.assertEqual(r["action"], "would_offload")
        self.assertEqual(minter.mint_calls, [])
        self.assertNotIn("auto_mint", r)

    # --- fail-soft and loud -----------------------------------------------
    def test_minter_that_raises_leaves_the_offload_successful(self):
        minter = _FakeMinter(raises=RuntimeError("git exploded"))
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter)

        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(r["wrote"], [_TARGET])
        self.assertNotIn("rolled_back", r)
        # The landed edit is still on disk -- minting failure rolls back nothing.
        self.assertEqual((Path(self.repo) / _TARGET).read_text(encoding="utf-8"),
                         "def blurb():\n    return 'bye'\n")
        self.assertEqual(r["auto_mint"]["status"], "error")
        self.assertIn("RuntimeError", r["auto_mint"]["reason"])
        self.assertIn("git exploded", r["auto_mint"]["reason"])
        self.assertEqual(minter.saved, [])

    def test_store_write_failure_is_also_fail_soft(self):
        minter = _FakeMinter()
        minter.add = mock.Mock(side_effect=OSError("mint store is read-only"))
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter)
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(r["auto_mint"]["status"], "error")
        self.assertIn("read-only", r["auto_mint"]["reason"])

    def test_non_quarantine_task_is_refused_not_persisted(self):
        minter = _FakeMinter(task={**_TASK, "tier": "primary"})
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter)
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(r["auto_mint"]["status"], "error")
        self.assertIn("quarantine", r["auto_mint"]["reason"])
        self.assertEqual(minter.saved, [])

    # --- the switch --------------------------------------------------------
    def test_flag_defaults_off_and_says_so(self):
        minter = _FakeMinter()
        r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter, flag=None)
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(minter.mint_calls, [])
        self.assertEqual(r["auto_mint"]["status"], "disabled")
        self.assertIn(_AUTO_MINT_ENV, r["auto_mint"]["reason"])

    def test_flag_toggles_the_seam(self):
        for value, expected, mints in (("0", "disabled", 0), ("", "disabled", 0),
                                       ("1", "minted", 1), ("true", "minted", 1),
                                       ("ON", "minted", 1)):
            with self.subTest(flag=value):
                # Reset the target: the previous iteration already wrote "bye",
                # and an identical rewrite is not an on-disk change.
                _write(Path(self.repo), _TARGET, "def blurb():\n    return 'hi'\n")
                minter = _FakeMinter()
                r = self._offload(_Worker(self.repo, _TARGET, _REPORT), minter,
                                  flag=value)
                self.assertEqual(r["auto_mint"]["status"], expected)
                self.assertEqual(len(minter.mint_calls), mints)


if __name__ == "__main__":
    unittest.main()
