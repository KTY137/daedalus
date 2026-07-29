"""The prose lane's gate: fact preservation, the docref denominator, and the
difference between a check that failed and a check that never ran.

Every case here is paired -- a BLOCKED case and an ALLOWED case -- because a
guard that only proves it says no has not been shown to be usable, and a guard
that only proves it says yes has not been shown to be a guard.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus import verifier
from daedalus.spine import docref_gate, docrefs
from daedalus.verifier import VerifyResult, verify


def _report(files_changed=()):
    return {"status": "done", "summary": "ok", "files_changed": list(files_changed),
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


# --------------------------------------------------------------------------- #
# 1. verifier prose branch                                                     #
# --------------------------------------------------------------------------- #
_BEFORE = """# Local models

Ollama can be pointed at an OpenAI-compatible endpoint via three env vars.

Per `docs/IMPROVEMENTS_RESEARCH.md`, the 24B tier needs ~12-16 GB of VRAM.
"""
# The MEASURED qwen2.5-coder:7b damage: a true fact carrying no markdown at all.
_DAMAGED = """# Local models

Ollama can be configured via three environment variables.

Per `docs/IMPROVEMENTS_RESEARCH.md`, the 24B tier needs ~12-16 GB of VRAM.
"""
# Rewrapped and re-marked-up, but every fact intact.
_HONEST = """# Local models

Ollama can be pointed at an
OpenAI-compatible endpoint via three env vars.

Per docs/IMPROVEMENTS_RESEARCH.md, the 24B tier
needs 12-16GB of VRAM.
"""


class ProseBranchTests(unittest.TestCase):
    def _run(self, after_text, prose_before, rel="docs/LOCAL_MODELS.md"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if after_text is not None:
                p.write_text(after_text, encoding="utf-8")
            return verify(_report([rel]), d, require_changes=True,
                          disk_changed=[rel], prose_before=prose_before)

    def test_deleted_fact_blocks(self):
        vr = self._run(_DAMAGED, {"docs/LOCAL_MODELS.md": _BEFORE})
        self.assertFalse(vr.ok)
        self.assertIn("prose:docs/LOCAL_MODELS.md", vr.failed)
        self.assertEqual(vr.verdict, "fail")          # a real finding, not a shrug

    def test_faithful_rewrite_passes(self):
        vr = self._run(_HONEST, {"docs/LOCAL_MODELS.md": _BEFORE})
        self.assertTrue(vr.ok, vr.as_dict())

    def test_missing_before_image_fails_closed_and_is_inconclusive(self):
        # The check COULD NOT RUN. It must block, and it must not be recorded as
        # "the model broke the prose".
        vr = self._run(_HONEST, None)
        self.assertFalse(vr.ok)
        check = [c for c in vr.checks if c["name"].startswith("prose:")][0]
        self.assertEqual(check["status"], "unknown")
        self.assertEqual(vr.verdict, "inconclusive")
        self.assertIn("prose:docs/LOCAL_MODELS.md", vr.inconclusive)

    def test_before_image_supplied_but_not_for_this_file_still_fails_closed(self):
        vr = self._run(_HONEST, {"docs/OTHER.md": "x"})
        self.assertFalse(vr.ok)
        self.assertEqual(vr.verdict, "inconclusive")

    def test_created_file_passes(self):
        vr = self._run(_HONEST, {"docs/LOCAL_MODELS.md": None})
        self.assertTrue(vr.ok, vr.as_dict())

    def test_deleted_prose_file_blocks(self):
        vr = self._run(None, {"docs/LOCAL_MODELS.md": _BEFORE})
        self.assertFalse(vr.ok)
        self.assertEqual(vr.verdict, "fail")

    def test_advisory_mode_does_not_demand_a_before_image(self):
        # Nothing was written; files_changed is a draft's claim, not an edit.
        with tempfile.TemporaryDirectory() as d:
            vr = verify(_report(["docs/x.md"]), d)
            self.assertTrue(vr.ok, vr.as_dict())


class DispatchUsesDiskTruthTests(unittest.TestCase):
    """A writer must not dodge the per-file checks by reporting nothing."""

    def test_unreported_but_written_py_is_still_checked(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "broken.py").write_text("def (:\n", encoding="utf-8")
            vr = verify(_report([]), d, require_changes=True,
                        disk_changed=["broken.py"])
            self.assertFalse(vr.ok)
            self.assertIn("syntax:broken.py", vr.failed)

    def test_self_report_still_used_when_no_disk_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "broken.py").write_text("def (:\n", encoding="utf-8")
            vr = verify(_report(["broken.py"]), d)
            self.assertFalse(vr.ok)
            self.assertIn("syntax:broken.py", vr.failed)


class VerdictTests(unittest.TestCase):
    """A budget shortfall and a red suite must not collapse into one signal."""

    def test_timeout_is_inconclusive_not_a_failure(self):
        vr = VerifyResult(ok=False, checks=[
            {"name": "schema", "ok": True, "detail": "valid"},
            {"name": "tests", "ok": False, "status": "timeout", "detail": "killed"}])
        self.assertEqual(vr.verdict, "inconclusive")
        self.assertEqual(vr.inconclusive, ["tests"])
        self.assertEqual(vr.reason_note(), "tests:timeout")

    def test_red_suite_is_a_failure(self):
        vr = VerifyResult(ok=False, checks=[
            {"name": "tests", "ok": False, "status": "fail", "detail": "3 failed"}])
        self.assertEqual(vr.verdict, "fail")
        self.assertEqual(vr.inconclusive, [])
        self.assertEqual(vr.reason_note(), "tests")

    def test_a_real_failure_outranks_a_concurrent_timeout(self):
        vr = VerifyResult(ok=False, checks=[
            {"name": "syntax:a.py", "ok": False, "detail": "bad"},
            {"name": "tests", "ok": False, "status": "timeout", "detail": "killed"}])
        self.assertEqual(vr.verdict, "fail")

    def test_pass(self):
        self.assertEqual(VerifyResult(ok=True, checks=[]).verdict, "pass")


class BeforeImageTests(unittest.TestCase):
    def test_backups_become_repo_relative_before_images(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            images = verifier.prose_before_images(
                {str(root / "docs" / "a.md"): b"hello",
                 str(root / "docs" / "b.md"): None}, str(root))
            self.assertEqual(images, {"docs/a.md": "hello", "docs/b.md": None})

    def test_no_backups_is_no_evidence_not_empty_evidence(self):
        self.assertEqual(verifier.prose_before_images(None, "."), {})


# --------------------------------------------------------------------------- #
# 2. docrefs: the denominator, and scanning a remembered snapshot              #
# --------------------------------------------------------------------------- #
class DocrefsOverrideTests(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "daedalus").mkdir()
        (root / "daedalus" / "sensitivity.py").write_text(
            "def classify_data():\n    pass\n", encoding="utf-8")
        (root / "docs").mkdir()
        return root

    def test_before_report_is_built_from_remembered_text(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            (root / "docs" / "a.md").write_text(
                "See `daedalus.sensitivity.classify_data`.\n", encoding="utf-8")
            after = docrefs.scan(root)
            before = docrefs.scan(root, overrides={
                "docs/a.md": "See `daedalus.sensitivity.classify_data` and "
                             "`daedalus.sensitivity.gone`.\n"})
            self.assertEqual(before.n_broken, 1)
            self.assertEqual(after.n_broken, 0)
            self.assertEqual(before.n_resolving, after.n_resolving)

    def test_override_none_models_a_file_that_did_not_exist(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            (root / "docs" / "a.md").write_text(
                "See `daedalus.sensitivity.classify_data`.\n", encoding="utf-8")
            before = docrefs.scan(root, overrides={"docs/a.md": None})
            self.assertEqual(before.files_scanned, 0)
            self.assertEqual(before.n_resolving, 0)

    def test_override_can_add_a_document_the_disk_no_longer_has(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            before = docrefs.scan(root, overrides={
                "docs/gone.md": "See `daedalus.sensitivity.classify_data`.\n"})
            self.assertEqual(before.n_resolving, 1)
            self.assertEqual(docrefs.scan(root).n_resolving, 0)


class DenominatorTests(unittest.TestCase):
    def _reports(self, before_resolving, after_resolving, after_broken=()):
        mk = lambda n: tuple(
            docrefs.Reference(doc_path="d.md", line=i, raw=f"r{i}",
                              state="resolving") for i in range(n))
        return (docrefs.DocRefReport(resolving=mk(before_resolving)),
                docrefs.DocRefReport(resolving=mk(after_resolving),
                                     broken=tuple(after_broken)))

    def test_deleting_the_corpus_is_refused_even_though_the_claim_is_gone(self):
        before, after = self._reports(5, 0)
        v = docrefs.verify_fix(before, after, {"doc_path": "d.md", "raw": "`x.y`"})
        self.assertFalse(v.ok)
        self.assertEqual(v.verdict, "evidence_destroyed")

    def test_correcting_the_reference_passes(self):
        before, after = self._reports(5, 5)
        v = docrefs.verify_fix(before, after, {"doc_path": "d.md", "raw": "`x.y`"})
        self.assertTrue(v.ok)

    def test_still_broken_fails(self):
        broken = (docrefs.Reference(doc_path="d.md", line=1, raw="`x.y`",
                                    state="broken"),)
        before, after = self._reports(5, 5, broken)
        v = docrefs.verify_fix(before, after, {"doc_path": "d.md", "raw": "`x.y`"})
        self.assertFalse(v.ok)
        self.assertEqual(v.verdict, "still_broken")

    def test_verify_fixes_asks_the_denominator_before_any_finding(self):
        broken = (docrefs.Reference(doc_path="d.md", line=1, raw="`x.y`",
                                    state="broken"),)
        before, after = self._reports(5, 1, broken)
        ok, verdicts = docrefs.verify_fixes(
            before.n_resolving, after, [{"doc_path": "d.md", "raw": "`x.y`"}])
        self.assertFalse(ok)
        self.assertEqual([v.verdict for v in verdicts], ["evidence_destroyed"])

    def test_verify_fixes_refuses_an_empty_target_list(self):
        before, after = self._reports(5, 5)
        ok, verdicts = docrefs.verify_fixes(before.n_resolving, after, [])
        self.assertFalse(ok)
        self.assertEqual(verdicts, ())


# --------------------------------------------------------------------------- #
# 3. the docref gate                                                           #
# --------------------------------------------------------------------------- #
class DocrefGateTests(unittest.TestCase):
    def _repo(self, d, doc_text):
        root = Path(d)
        (root / "daedalus").mkdir()
        (root / "daedalus" / "sensitivity.py").write_text(
            "def classify_data():\n    pass\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "a.md").write_text(doc_text, encoding="utf-8")
        return root

    def _run(self, root, refs=("`daedalus.sensitivity.gone`",), expect=1, **kw):
        return docref_gate.run_gate(str(root), "docs/a.md", expect, list(refs), **kw)

    def test_a_real_correction_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data`.\n")
            code, lines = self._run(root)
            self.assertEqual(code, docref_gate.EXIT_PASS, "\n".join(lines))
            self.assertIn("VERDICT: pass", lines)

    def test_an_unfixed_reference_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data` and "
                                 "`daedalus.sensitivity.gone`.\n")
            code, lines = self._run(root)
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))
            self.assertTrue(any("still_broken" in ln for ln in lines))

    def test_deleting_the_document_fails_on_the_denominator(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data`.\n")
            (root / "docs" / "a.md").unlink()
            code, lines = self._run(root)
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))
            self.assertTrue(any("evidence_destroyed" in ln for ln in lines))

    def test_deleting_a_document_that_held_no_resolving_reference_still_fails(self):
        # The corpus denominator cannot see this one: the document contributed
        # nothing to it, so removing the file lowers no count.
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.gone`.\n")
            (root / "docs" / "a.md").unlink()
            code, lines = self._run(root, expect=0)
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))
            self.assertTrue(any("is GONE" in ln for ln in lines))

    def test_emptying_the_document_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.gone`.\n")
            (root / "docs" / "a.md").write_text("\n", encoding="utf-8")
            code, lines = self._run(root, expect=0)
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))
            self.assertTrue(any("is EMPTY" in ln for ln in lines))

    def test_a_target_that_never_matched_is_inconclusive_not_withdrawn(self):
        # The reference is still sitting in the document, but the key we were
        # handed matches nothing (here: truncated, as the queue's evidence is).
        # "I found it nowhere" must not be read as "it was honestly withdrawn".
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.gone`.\n")
            code, lines = self._run(root, refs=("daedalus.sensitivity.go",),
                                    expect=0)
            self.assertEqual(code, docref_gate.EXIT_INCONCLUSIVE, "\n".join(lines))
            self.assertTrue(any("STILL in the document" in ln for ln in lines))

    def test_backticks_on_a_target_do_not_turn_a_finding_into_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data` and "
                                 "`daedalus.sensitivity.gone`.\n")
            code, lines = self._run(root, refs=("`daedalus.sensitivity.gone`",))
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))
            self.assertTrue(any("still_broken" in ln for ln in lines))

    def test_no_targets_is_inconclusive_never_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data`.\n")
            code, lines = self._run(root, refs=())
            self.assertEqual(code, docref_gate.EXIT_INCONCLUSIVE, "\n".join(lines))
            self.assertIn("VERDICT: inconclusive", lines)

    def test_missing_repo_root_is_inconclusive_not_a_failure(self):
        code, lines = docref_gate.run_gate(
            str(Path(tempfile.gettempdir()) / "definitely-not-here-9f3a"),
            "docs/a.md", 1, ["`x.y`"])
        self.assertEqual(code, docref_gate.EXIT_INCONCLUSIVE, "\n".join(lines))

    def test_per_document_denominator_catches_a_gutted_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.gone`.\n")
            code, lines = self._run(root, expect=0, expect_doc_resolving=2)
            self.assertEqual(code, docref_gate.EXIT_FAIL, "\n".join(lines))

    def test_gate_always_produces_output(self):
        # command_gate refuses an exit-0 gate that printed nothing.
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data`.\n")
            _, lines = self._run(root)
            self.assertTrue("\n".join(lines).strip())

    def test_argv_surface_is_wired(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, "See `daedalus.sensitivity.classify_data`.\n")
            code = docref_gate.main([
                "--repo-root", str(root), "--doc", "docs/a.md",
                "--expect-resolving", "1", "--ref", "`daedalus.sensitivity.gone`"])
            self.assertEqual(code, docref_gate.EXIT_PASS)

    def test_unparseable_argv_is_inconclusive(self):
        self.assertEqual(docref_gate.main(["--nonsense"]),
                         docref_gate.EXIT_INCONCLUSIVE)


if __name__ == "__main__":
    unittest.main()
