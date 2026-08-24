"""The promotion refusal, and the entry point that reaches it.

WHAT THESE TESTS ARE FOR. ``daedalus.spine.bootstrap.gate_discrimination`` is
the only thing standing between "pytest ran" and "this candidate may be
promoted". Its docstring says it "fails closed, four ways". Each of those four
ways gets a test here, and each was verified to go RED with the guard actually
disabled -- not reasoned about, disabled and measured.

Three of these tests cover ways it does NOT fail closed. They are written as
the guard SHOULD behave, so they are red until the hole is closed, and the
docstring of each one names the exact source line.

THE ENTRY-POINT TESTS exist because of a measured incident. The first real
bootstrap of this repository was driven by a script with no
``if __name__ == "__main__":`` guard; ``structcore.index`` uses a spawn-based
``ProcessPoolExecutor``, every worker re-imported the driver, and ten attempts
ran in parallel. A test that reads the module's source for the guard would have
caught it in a second, so there is now one.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from daedalus.spine.bootstrap import (
    CRITICAL_DEFECT_CLASSES,
    DISCRIMINATION_REL_PATH,
    KILL_RATE_FLOOR,
    ShadowResult,
    gate_discrimination,
)

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tools" / "bootstrap_receipt.py"

MEASURED_HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def _load_driver(name: str):
    spec = importlib.util.spec_from_file_location(name, DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True)
    return proc.stdout.strip()


def _external_repo(root: Path) -> Path:
    """A real target repo whose runtime evidence is ignored but inspectable."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "bootstrap-test@example.invalid")
    _git(root, "config", "user.name", "Bootstrap Test")
    (root / ".gitignore").write_text(
        "runs/\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (root / "README.md").write_text("external target\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _frozen_gate(head: str, gate_paths: tuple = ()) -> dict:
    """The gate binding a receipt must carry, in the shape bootstrap validates."""
    from daedalus.spine.attempt import pytest_gate_argv
    return {
        "argv": [str(v) for v in pytest_gate_argv(gate_paths)],
        "gate_paths": list(gate_paths),
        "gate_scope": "whole-suite" if not gate_paths else "scoped",
        "head": head,
    }


def _receipt(tmp: Path, **overrides) -> Path:
    """A receipt that PASSES every check, so a test that flips one field is
    measuring that field and nothing else."""
    doc = {
        "state": "measured",
        "head": MEASURED_HEAD,
        "measured_at": "2026-07-29T06:34:28+00:00",
        "planted": 12,
        "killed": 12,
        "surviving_classes": [],
        "kill_rate_floor": KILL_RATE_FLOOR,
        "critical_defect_classes": list(CRITICAL_DEFECT_CLASSES),
        # Built from the PRODUCTION argv builder, never hand-copied: bootstrap
        # cross-checks the receipt argv against pytest_gate_argv(paths), so a
        # hand-written copy here would drift the day the real command changes
        # and this fixture would start certifying a gate nobody runs.
        "frozen_gate": _frozen_gate(MEASURED_HEAD),
    }
    doc.update(overrides)
    if "frozen_gate" not in overrides:
        # Follow the (possibly overridden) measurement head: a receipt whose
        # binding names a different revision than its own measurement is the
        # forgery bootstrap refuses, so the fixture must not create one by
        # accident while a test is measuring something else entirely.
        doc["frozen_gate"] = dict(doc["frozen_gate"], head=doc["head"])
    path = tmp / DISCRIMINATION_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _allows(tmp: Path, head) -> bool:
    """What the PRODUCT asks: may a gated candidate be promoted?

    Deliberately routed through :class:`ShadowResult` rather than reading
    ``.proven`` directly -- ``promotion_allowed`` is the property the caller
    acts on, and a test that checked ``proven`` would keep passing if the two
    were ever wired apart.
    """
    disc = gate_discrimination(tmp, head=head)
    return ShadowResult(state="gated", discrimination=disc).promotion_allowed


class ThePositiveControl(unittest.TestCase):
    """If this fails, every refusal test below is passing for the wrong reason."""

    def test_a_clean_receipt_at_the_matching_revision_allows_promotion(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp)
            self.assertTrue(_allows(tmp, MEASURED_HEAD))

    def test_an_abbreviated_head_still_matches_its_full_sha(self):
        """``head.startswith(measured_head)`` is the real comparison; a receipt
        recording a short sha must still match the full one it prefixes."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, head=MEASURED_HEAD[:12])
            self.assertTrue(_allows(tmp, MEASURED_HEAD))


class TheFourDocumentedRefusals(unittest.TestCase):
    """Present, parseable, measured at THIS revision, clean on every critical
    class. Each test disables exactly one of those preconditions."""

    def test_no_receipt_at_all_refuses(self):
        with TemporaryDirectory() as d:
            self.assertFalse(_allows(Path(d), MEASURED_HEAD))

    def test_an_unparseable_receipt_refuses(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            path = tmp / DISCRIMINATION_REL_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertFalse(_allows(tmp, MEASURED_HEAD))

    def test_a_receipt_measured_at_another_revision_refuses(self):
        """THE STALE-RECEIPT REFUSAL -- the single most important number in the
        bootstrap. Everything else in this receipt passes; only the revision
        differs."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp)
            self.assertFalse(_allows(tmp, OTHER_HEAD))

    def test_a_receipt_with_no_recorded_head_refuses(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, head="")
            self.assertFalse(_allows(tmp, MEASURED_HEAD))

    def test_a_surviving_critical_class_refuses_even_at_a_high_kill_rate(self):
        """The averaging failure this list exists to prevent: 92% overall with a
        fatal blind spot must not read as better than 80%."""
        for cls in CRITICAL_DEFECT_CLASSES:
            with self.subTest(cls=cls), TemporaryDirectory() as d:
                tmp = Path(d)
                _receipt(tmp, planted=12, killed=11, surviving_classes=[cls])
                self.assertFalse(_allows(tmp, MEASURED_HEAD))

    def test_a_kill_rate_below_the_floor_refuses(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, planted=12, killed=9, surviving_classes=["logic"])
            self.assertFalse(_allows(tmp, MEASURED_HEAD))

    def test_a_non_critical_survivor_above_the_floor_still_allows(self):
        """The floor is deliberately not 1.0. This pins that it is not, so a
        later tightening is a visible decision rather than a drift."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, planted=12, killed=10, surviving_classes=["logic"])
            self.assertTrue(_allows(tmp, MEASURED_HEAD))


class TheRevisionClauseMustNotFailOpen(unittest.TestCase):
    """``bootstrap.py``: ``if head and measured_head and not head.startswith(...)``.

    When the caller cannot name the current revision, ``head`` is falsy and the
    ENTIRE staleness clause is skipped -- a receipt from any revision is then
    accepted. That path is reachable in production: ``shadow_run`` sets
    ``head = None`` inside a bare ``except Exception`` around ``_head_sha``, and
    an empty string arrives from any ``git rev-parse`` that prints nothing.

    "I cannot tell which revision this is" is the case where a promotion gate
    must be MOST reluctant, not least. Fail closed.
    """

    def test_an_unreadable_head_refuses_a_stale_receipt(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp)
            self.assertFalse(
                _allows(tmp, None),
                "a receipt from an unknown revision authorised promotion")

    def test_an_empty_head_refuses_a_stale_receipt(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp)
            self.assertFalse(
                _allows(tmp, ""),
                "an empty rev-parse result authorised promotion")


class TheKillRateMustBeBounded(unittest.TestCase):
    """``rate = float(killed) / float(planted)`` with no relation asserted
    between the two. A receipt claiming more kills than plants scores above
    100% and sails over the floor. The receipt is a file on disk that a
    promotion decision reads; a nonsensical one must be refused, not divided."""

    def test_more_kills_than_plants_refuses(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, planted=12, killed=99)
            self.assertFalse(_allows(tmp, MEASURED_HEAD),
                             "a kill rate of 825% authorised promotion")

    def test_a_negative_kill_count_refuses(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            _receipt(tmp, planted=12, killed=-1)
            self.assertFalse(_allows(tmp, MEASURED_HEAD))


class TheDriverIsSafeToImport(unittest.TestCase):
    """THE TEN-ATTEMPT BUG, as an executable check.

    A spawn-based ``ProcessPoolExecutor`` re-imports the main module in every
    worker. Any top-level statement that starts work therefore runs once per
    core. This asserts the entry point's module body does nothing but define
    things -- and that the one call to ``main()`` sits under the guard.
    """

    def setUp(self):
        self.tree = ast.parse(DRIVER.read_text(encoding="utf-8"))

    def test_the_module_body_only_defines_things(self):
        allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef,
                   ast.AsyncFunctionDef, ast.ClassDef, ast.Assign,
                   ast.AnnAssign, ast.Expr, ast.If)
        for node in self.tree.body:
            self.assertIsInstance(node, allowed,
                                  f"top-level {type(node).__name__} runs on import")
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant,
                                      "a top-level expression that is not a "
                                      "docstring runs on import")

    def test_every_call_to_main_is_under_a_dunder_main_guard(self):
        guarded, unguarded = 0, []
        for node in self.tree.body:
            is_guard = (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in node.test.comparators))
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "main"):
                    if isinstance(node, ast.If) and is_guard:
                        guarded += 1
                    elif not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        unguarded.append(ast.dump(sub)[:80])
        self.assertEqual(unguarded, [], "main() is called outside the guard")
        self.assertGreaterEqual(guarded, 1, "the driver has no __main__ guard "
                                            "-- every spawned worker will re-run it")


class TheWorktreeConfigStampIsReversible(unittest.TestCase):
    """The harness rewrites ``test_command`` inside the WORKTREE's project
    config so verify can finish. If that edit survived into
    ``TaskAttempt._capture_patch`` it would contaminate the candidate patch
    with the harness's own change -- so the restore is byte-exact and checked.
    """

    def setUp(self):
        self.mod = _load_driver("_bootstrap_receipt")

    def _config(self, tmp: Path) -> Path:
        path = tmp / ".agentenv" / "agentenv.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"name": "x", "test_command": "python -m pytest tests -q -x",
             "test_cwd": "."}, indent=2) + "\n", encoding="utf-8")
        return path

    def test_the_original_bytes_come_back_exactly(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            path = self._config(tmp)
            before = path.read_bytes()
            with self.mod._WorktreeConfigStamp(tmp, "pytest -q fast") as stamp:
                during = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(during["test_command"], "pytest -q fast")
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(stamp.record["restored"])
            self.assertEqual(stamp.record["original_test_command"],
                             "python -m pytest tests -q -x")

    def test_the_original_bytes_come_back_even_when_the_body_raises(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            path = self._config(tmp)
            before = path.read_bytes()
            with self.assertRaises(ZeroDivisionError):
                with self.mod._WorktreeConfigStamp(tmp, "pytest -q fast"):
                    1 / 0
            self.assertEqual(path.read_bytes(), before)

    def test_no_override_requested_touches_nothing(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            path = self._config(tmp)
            before = path.read_bytes()
            with self.mod._WorktreeConfigStamp(tmp, None) as stamp:
                self.assertEqual(path.read_bytes(), before)
            self.assertFalse(stamp.record["applied"])

    def test_receipt_binds_the_effective_verify_command_and_restoration(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            path = self._config(tmp)
            before = path.read_bytes()
            sink = {}
            runner = self.mod.stamped_offload_runner(
                live=True, paths=["README.md"], local_only=True,
                test_command="python -m pytest smoke.py -q",
                test_timeout_s=30, stamp_sink=sink)
            ctx = SimpleNamespace(
                worktree=tmp, task=SimpleNamespace(instruction="probe"))
            answer = {
                "verify": {"checks": [{
                    "name": "tests", "ok": True, "status": "pass",
                    "timeout_s": 30, "detail": "1 passed"}]}}
            with mock.patch("daedalus.offload.offload", return_value=answer):
                self.assertIs(runner(ctx), answer)
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(sink["restored"])
            binding = sink["verify_binding"]
            self.assertEqual(
                binding["command"], "python -m pytest smoke.py -q")
            self.assertEqual(binding["timeout_s"], 30)
            self.assertEqual(len(binding["available_check_sha256"]), 64)
            self.assertFalse(binding["raw_output_digest_available"])


class TheLeakCheckIsAttributable(unittest.TestCase):
    """A boolean "the tree is unchanged" is useless in a repository six other
    agents are editing -- measured, three unrelated files went dirty during one
    attempt. The claim that survives that noise is narrower: of the paths THIS
    candidate wrote, none changed state in the primary checkout."""

    def setUp(self):
        self.mod = _load_driver("_bootstrap_receipt2")

    @staticmethod
    def _fp(head: str, lines: list[str]) -> dict:
        return {"head": head, "tracked_status": lines,
                "tracked_status_sha256": "x", "diff_stat_sha256": "y",
                "attempt_branches": []}

    def test_an_unrelated_agents_edit_is_not_reported_as_a_leak(self):
        out = self.mod._leak_check(
            self._fp("h", [" M daedalus/offload.py"]),
            self._fp("h", [" M daedalus/offload.py", " M tests/test_hardening.py"]),
            ["docs/LOCAL_MODELS.md"])
        self.assertFalse(out["primary_quiet"])
        self.assertEqual(out["candidate_paths_leaked"], [])
        self.assertTrue(out["no_candidate_path_reached_the_primary_checkout"])

    def test_a_candidate_path_that_reaches_the_primary_checkout_is_a_leak(self):
        out = self.mod._leak_check(
            self._fp("h", []),
            self._fp("h", [" M docs/LOCAL_MODELS.md"]),
            ["docs/LOCAL_MODELS.md"])
        self.assertEqual(out["candidate_paths_leaked"], ["docs/LOCAL_MODELS.md"])
        self.assertFalse(out["no_candidate_path_reached_the_primary_checkout"])

    def test_a_moved_head_is_reported(self):
        out = self.mod._leak_check(self._fp("h1", []), self._fp("h2", []), [])
        self.assertFalse(out["head_unchanged"])

    def test_an_untracked_candidate_under_a_collapsed_directory_is_a_leak(self):
        before = self._fp("h", [])
        after = self._fp("h", ["?? app/"])
        after["status_entries"] = [{"code": "??", "path": "app/"}]
        after["status_path_sha256"] = {"app/": "new-tree-digest"}
        out = self.mod._leak_check(before, after, ["app/probe.ts"])
        self.assertEqual(out["candidate_paths_leaked"], ["app/probe.ts"])
        self.assertEqual(
            out["candidate_path_evidence"]["app/probe.ts"], ["app/"])

    def test_a_hash_change_catches_a_leak_when_status_code_does_not_move(self):
        before = self._fp("h", ["?? app/"])
        before["status_entries"] = [{"code": "??", "path": "app/"}]
        before["status_path_sha256"] = {"app/": "old"}
        after = self._fp("h", ["?? app/"])
        after["status_entries"] = [{"code": "??", "path": "app/"}]
        after["status_path_sha256"] = {"app/": "new"}
        out = self.mod._leak_check(before, after, ["app/new.ts"])
        self.assertEqual(out["content_changed"], ["app/"])
        self.assertEqual(out["candidate_paths_leaked"], ["app/new.ts"])

    def test_a_real_untracked_candidate_in_the_primary_repo_is_detected(self):
        with TemporaryDirectory() as d:
            target = _external_repo(Path(d) / "target")
            before = self.mod.primary_fingerprint(target)
            leaked = target / "app" / "probe.ts"
            leaked.parent.mkdir()
            leaked.write_text("export const leaked = true;\n", encoding="utf-8")
            after = self.mod.primary_fingerprint(target)
            out = self.mod._leak_check(before, after, ["app/probe.ts"])
            self.assertEqual(out["candidate_paths_leaked"], ["app/probe.ts"])
            self.assertEqual(
                out["candidate_path_evidence"]["app/probe.ts"], ["app/"])


class TheExternalTargetReceipt(unittest.TestCase):
    """Every effect belongs to TARGET while candidate bytes stay in its worktree."""

    def setUp(self):
        self.mod = _load_driver("_bootstrap_receipt_external")

    def test_parser_accepts_argv_json_and_rejects_shell_text(self):
        args = self.mod.build_parser().parse_args([
            "--single", "--instruction", "x",
            "--gate-command", '["npm.cmd","run","build"]'])
        self.assertEqual(args.gate_command, ("npm.cmd", "run", "build"))
        with self.assertRaises(SystemExit):
            self.mod.build_parser().parse_args([
                "--single", "--instruction", "x",
                "--gate-command", "npm run build"])

    def test_external_attempt_binds_repo_storage_gate_and_ledger(self):
        with TemporaryDirectory() as d:
            target = _external_repo(Path(d) / "target")
            before_head = _git(target, "rev-parse", "HEAD")
            before_status = _git(
                target, "status", "--porcelain=v1", "--untracked-files=all")

            def candidate_runner(ctx):
                (ctx.worktree / "candidate.txt").write_text(
                    "candidate\n", encoding="utf-8")
                return {"test_runner": "wrote only inside external worktree"}

            gate_argv = [
                sys.executable, "-c",
                ("from pathlib import Path; "
                 "assert Path('candidate.txt').read_text() == 'candidate\\n'; "
                 "print('candidate gate passed')")]
            task_id = "external-target-attribution"
            receipt = target / "runs" / "spine" / "bootstrap" / f"{task_id}.json"

            with mock.patch.object(
                    self.mod, "stamped_offload_runner",
                    return_value=candidate_runner):
                code = self.mod.main([
                    "--single",
                    "--repo-root", str(target),
                    "--task-id", task_id,
                    "--instruction", "create an isolated candidate probe",
                    "--paths", "candidate.txt",   # the declared scope (68b8d856)
                    "--gate-command", json.dumps(gate_argv),
                ])

            self.assertEqual(code, self.mod.EXIT_OK)
            doc = json.loads(receipt.read_text(encoding="utf-8"))
            target_resolved = str(target.resolve())
            self.assertEqual(doc["code_root"], str(ROOT))
            self.assertEqual(doc["target_repo"], target_resolved)
            self.assertEqual(doc["attempt"]["state"], "clean")
            self.assertEqual(doc["gate_kind"], "custom-command")
            self.assertEqual(doc["gate_scope"], "custom-command")
            self.assertTrue(doc["attempt"]["worktree_removed"])
            self.assertEqual(
                doc["attempt"]["artifact"]["changed_paths"], ["candidate.txt"])
            self.assertFalse((target / "candidate.txt").exists())
            self.assertTrue(doc["primary_unchanged"])
            self.assertEqual(doc["primary_leak"]["candidate_paths_leaked"], [])

            storage = doc["storage"]
            for key in ("ledger_path", "artifact_dir", "receipt_path"):
                self.assertTrue(
                    Path(storage[key]).resolve().is_relative_to(target.resolve()),
                    f"{key} escaped target: {storage[key]}")
            self.assertEqual(Path(storage["receipt_path"]).resolve(),
                             receipt.resolve())
            self.assertTrue(Path(storage["ledger_path"]).is_file())
            # The deposit moved from the ATTEMPT to the TOOL: TaskAttempt's
            # _persist now refuses caller-chosen paths inside the attempt's own
            # checkout (the primary-tree fence), so the attempt reports no
            # artifact_path -- and the tool, which already writes the receipt
            # into the target unfenced by design, deposits the patch bytes
            # itself and records them under storage. Same bytes, same place,
            # honest attribution of who wrote them.
            self.assertIsNone(doc["attempt"]["artifact_path"])
            artifact_path = Path(storage["artifact_path"])
            self.assertTrue(artifact_path.is_file())
            self.assertTrue(artifact_path.resolve().is_relative_to(target.resolve()))

            gate = doc["execution_binding"]["gate"]
            self.assertEqual(gate["command"], gate_argv)
            self.assertEqual(len(gate["output_sha256"]), 64)
            self.assertIsNotNone(gate["containment"])

            conn = sqlite3.connect(storage["ledger_path"])
            try:
                row = conn.execute(
                    "SELECT payload FROM intents WHERE id = ?",
                    (doc["attempt"]["intent_id"],)).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            payload = json.loads(row[0])
            self.assertEqual(payload["repo_root"], target_resolved)

            self.assertEqual(_git(target, "rev-parse", "HEAD"), before_head)
            self.assertEqual(
                _git(target, "status", "--porcelain=v1",
                     "--untracked-files=all"),
                before_status)


if __name__ == "__main__":
    unittest.main()
