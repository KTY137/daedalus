"""Contracts for G1-MUT-02D attempt effect-inventory migration."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from daedalus.spine.effect_boundary import registry_sha256
from tools import mutation_score as ms


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts"
SPEC = ROOT / "configs/mutations/attempt-effect-inventory.json"
WRAPPER = SCRIPT_DIR / "run_attempt_effect_inventory_mutations.py"
TARGET = ROOT / "daedalus/spine/effect_boundary.py"
EXPECTED_BASELINE = (
    "tests/kernel/test_isolated_attempt_effect_inventory_registration.py",
    "tests/kernel/test_isolated_attempt_effect_inventory.py",
)
EXPECTED_MUTATIONS = (
    "hide-attempt-ledger-from-static-discovery",
    "remove-canonical-attempt-begin-owner",
)
EXPECTED_JOB_DIGEST = (
    "7d84b2853fddaeee9fed16ec0f7ce5e3befe6da625a847102255eb8cba9cef48"
)
EXPECTED_REGISTRY_DIGEST = (
    "615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752"
)
REMAINING_UNMIGRATED = {
    "run_attempt_durability_admission_mutations.py": (
        "c63d0b9610031529dbaade8e32426e1170bfc4e0d02e481f02491ef42a7afe9b"
    ),
    "run_attempt_workspace_root_authority_mutations.py": (
        "fbd0e2783f84ac3689b83a8731238e77149841a246b5530b1da1f9ea174dd23e"
    ),
    "run_isolated_attempt_mutations.py": (
        "5028c6d112a4f53bc4cae745f279a50b9163a7e728b26296f5738f0b52707ba8"
    ),
    "run_offload_lease_dominance_mutations.py": (
        "23dcda82a3b23c98fa77bf8d8d51ebebfa8dcf9dfb50a53c2c526b1fca4955ed"
    ),
    "run_write_evidence_production_mutations.py": (
        "2ec05e6f868741c6fdfa63fbc5c9bc51632a14f8e02bd2f755ad20942936e657"
    ),
}
FORBIDDEN_IMPORTS = {"os", "shutil", "subprocess", "tempfile"}
FORBIDDEN_CALLS = {
    "copy",
    "copy2",
    "copytree",
    "open",
    "popen",
    "remove",
    "rename",
    "replace",
    "run",
    "unlink",
    "write_bytes",
    "write_text",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"jobs": payload["jobs"]},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _ShadowRunner:
    def __init__(self, spec: ms.ExplicitMutationSpec):
        job = spec.jobs[0]
        self.expected = [job.tests] * (len(job.mutations) + 1)
        self.timeouts: list[float | None] = []

    def __call__(
        self,
        root: Path,
        test_paths: list[str],
        timeout: float | None,
    ) -> ms.RunResult:
        del root
        expected = self.expected.pop(0)
        if tuple(test_paths) != expected:
            raise AssertionError((tuple(test_paths), expected))
        self.timeouts.append(timeout)
        if len(self.timeouts) == 1:
            return ms.RunResult(returncode=0)
        return ms.RunResult(
            returncode=1,
            failing={"tests/shadow.py::test_detects_mutant"},
        )


class AttemptEffectInventoryMutationSpecTests(unittest.TestCase):
    def test_spec_is_the_exact_two_mutant_unbounded_projection(self):
        payload = json.loads(SPEC.read_text(encoding="utf-8"))
        spec = ms.load_explicit_spec(ROOT, SPEC)
        self.assertEqual(spec.packet_id, "G1-MUT-02D")
        self.assertEqual(spec.spec_id, "attempt-effect-inventory")
        self.assertEqual(len(spec.jobs), 1)
        job = spec.jobs[0]
        self.assertEqual(job.module, "daedalus/spine/effect_boundary.py")
        self.assertEqual(job.tests, EXPECTED_BASELINE)
        self.assertEqual(job.timeout_policy, ms.JOB_TIMEOUT_LEGACY_UNBOUNDED)
        self.assertIsNone(job.timeout_s)
        self.assertEqual(tuple(m.id for m in job.mutations), EXPECTED_MUTATIONS)
        self.assertEqual(_job_digest(payload), EXPECTED_JOB_DIGEST)

    def test_list_mode_is_read_only(self):
        before = {path: path.read_bytes() for path in (SPEC, WRAPPER, TARGET)}
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = ms.main(
                ["--repo", str(ROOT), "--spec", str(SPEC), "--list"]
            )
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("2 explicit mutant(s) in 1 job(s)", output.getvalue())
        self.assertEqual(
            {path: path.read_bytes() for path in (SPEC, WRAPPER, TARGET)},
            before,
        )

    def test_historical_path_has_no_mutation_or_process_authority(self):
        source = WRAPPER.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertTrue(FORBIDDEN_IMPORTS.isdisjoint(imports))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        calls.update(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        )
        self.assertTrue(FORBIDDEN_CALLS.isdisjoint(calls))
        self.assertIn("from tools.mutation_score import main", source)
        self.assertIn("attempt-effect-inventory.json", source)

    def test_canonical_shadow_preserves_selection_outcomes_and_source(self):
        spec = ms.load_explicit_spec(ROOT, SPEC)
        before = TARGET.read_bytes()
        runner = _ShadowRunner(spec)
        with tempfile.TemporaryDirectory(prefix="g1-mut-02d-shadow-") as raw:
            shadow = Path(raw)
            target = shadow / spec.jobs[0].module
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before)
            report = ms.score_explicit_spec(shadow, spec, runner=runner)
        self.assertEqual(report["verdict"], "NO_SURVIVORS", report)
        self.assertEqual(report["n_caught"], 2, report)
        self.assertEqual(report["n_survived"], 0, report)
        self.assertEqual(report["n_inconclusive"], 0, report)
        self.assertEqual(report["n_not_applicable"], 0, report)
        self.assertFalse(runner.expected)
        self.assertEqual(runner.timeouts, [None, None, None])
        self.assertEqual(TARGET.read_bytes(), before)

    def test_five_larger_or_blocked_runners_remain_byte_identical(self):
        self.assertEqual(len(REMAINING_UNMIGRATED), 5)
        for name, expected_digest in REMAINING_UNMIGRATED.items():
            with self.subTest(runner=name):
                self.assertEqual(_sha256(SCRIPT_DIR / name), expected_digest)

    def test_write_evidence_production_blocker_is_not_masked(self):
        legacy = (
            SCRIPT_DIR / "run_write_evidence_production_mutations.py"
        ).read_text(encoding="utf-8")
        stale_anchor = (
            "    if worktree_root is not None:\n"
            "        return str(root), str(Path(worktree_root).resolve())\n"
        )
        current = (ROOT / "daedalus/kernel/offload_lease.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("measure-containment-over-the-default-manager", legacy)
        self.assertEqual(current.count(stale_anchor), 0)

    def test_effect_registry_digest_is_exact(self):
        self.assertEqual(registry_sha256(), EXPECTED_REGISTRY_DIGEST)


if __name__ == "__main__":
    unittest.main()
