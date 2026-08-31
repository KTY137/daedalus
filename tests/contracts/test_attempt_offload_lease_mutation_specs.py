"""Contracts for G1-MUT-02C attempt/offload/lease runner migration."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools import mutation_score as ms


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts"
SPEC = ROOT / "configs/mutations/repository-write-effect-lease.json"
WRAPPER = SCRIPT_DIR / "run_repository_write_effect_lease_mutations.py"

FAMILY = {
    "run_attempt_durability_admission_mutations.py",
    "run_attempt_effect_inventory_mutations.py",
    "run_attempt_event_time_window_mutations.py",
    "run_attempt_workspace_root_authority_mutations.py",
    "run_isolated_attempt_mutations.py",
    "run_offload_lease_dominance_mutations.py",
    "run_repository_write_effect_lease_mutations.py",
    "run_write_evidence_production_mutations.py",
}

UNMIGRATED = {
    "run_attempt_durability_admission_mutations.py": (
        "unbounded-timeout",
        "c63d0b9610031529dbaade8e32426e1170bfc4e0d02e481f02491ef42a7afe9b",
    ),
    "run_attempt_effect_inventory_mutations.py": (
        "unbounded-timeout",
        "f9a8d82984e18507ec7eff8df36ac5f866344269b5e4631fb564edea3c854b35",
    ),
    "run_attempt_event_time_window_mutations.py": (
        "unbounded-timeout",
        "e2b723f2541f32338026e3e0aa779213d0f0d5c6680dbfc2545cb4690d70168a",
    ),
    "run_attempt_workspace_root_authority_mutations.py": (
        "unbounded-timeout",
        "fbd0e2783f84ac3689b83a8731238e77149841a246b5530b1da1f9ea174dd23e",
    ),
    "run_isolated_attempt_mutations.py": (
        "unbounded-timeout-and-multi-target",
        "5028c6d112a4f53bc4cae745f279a50b9163a7e728b26296f5738f0b52707ba8",
    ),
    "run_offload_lease_dominance_mutations.py": (
        "unbounded-timeout-and-multi-target-crlf-writer",
        "23dcda82a3b23c98fa77bf8d8d51ebebfa8dcf9dfb50a53c2c526b1fca4955ed",
    ),
    "run_write_evidence_production_mutations.py": (
        "stale-hier-04b-anchor-and-non-byte-restoring-writer",
        "2ec05e6f868741c6fdfa63fbc5c9bc51632a14f8e02bd2f755ad20942936e657",
    ),
}

EXPECTED_BASELINE = (
    "tests/gates/test_repository_write_effect_lease.py",
    "tests/gates/test_repository_write_effect_lease_review.py",
)
EXPECTED_MUTANT_TEST_FILES = (
    "tests/gates/test_repository_write_non_runtime_conformity_admission.py",
    "tests/gates/test_repository_write_effect_lease_non_runtime.py",
)
EXPECTED_JOB_DIGEST = (
    "64aff892dc073fe77165ddddeaf8ac1cc084c18218b76761abf1eebded47badf"
)
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
        self.expected: list[tuple[tuple[str, ...], float, bool]] = []
        for job in spec.jobs:
            self.expected.append((job.tests, job.timeout_s, True))
            for mutation in job.mutations:
                self.expected.append(
                    (mutation.test_paths or job.tests, job.timeout_s, False)
                )

    def __call__(
        self,
        root: Path,
        test_paths: list[str],
        timeout: float,
    ) -> ms.RunResult:
        del root
        expected_paths, expected_timeout, baseline = self.expected.pop(0)
        if tuple(test_paths) != expected_paths:
            raise AssertionError((tuple(test_paths), expected_paths))
        if timeout != expected_timeout:
            raise AssertionError((timeout, expected_timeout))
        if baseline:
            return ms.RunResult(returncode=0)
        return ms.RunResult(
            returncode=1,
            failing={"tests/shadow.py::test_detects_mutant"},
        )


class AttemptOffloadLeaseMutationSpecTests(unittest.TestCase):
    def test_inventory_is_exact_and_unmigrated_runners_are_byte_identical(self):
        self.assertEqual(len(FAMILY), 8)
        self.assertEqual(
            FAMILY,
            set(UNMIGRATED) | {"run_repository_write_effect_lease_mutations.py"},
        )
        for name in FAMILY:
            self.assertTrue((SCRIPT_DIR / name).is_file(), name)
        for name, (reason, expected_digest) in UNMIGRATED.items():
            with self.subTest(runner=name):
                self.assertTrue(reason)
                self.assertEqual(_sha256(SCRIPT_DIR / name), expected_digest)

    def test_target_only_runner_and_hier_04b_blocker_are_explicit(self):
        legacy = (
            SCRIPT_DIR / "run_write_evidence_production_mutations.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'KERNEL = ROOT / "daedalus/kernel/offload_lease.py"',
            legacy,
        )
        stale_anchor = (
            "    if worktree_root is not None:\n"
            "        return str(root), str(Path(worktree_root).resolve())\n"
        )
        current = (ROOT / "daedalus/kernel/offload_lease.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(current.count(stale_anchor), 0)
        self.assertIn("measure-containment-over-the-default-manager", legacy)

    def test_spec_strictly_loads_the_frozen_legacy_projection(self):
        payload = json.loads(SPEC.read_text(encoding="utf-8"))
        spec = ms.load_explicit_spec(ROOT, SPEC)
        self.assertEqual(spec.packet_id, "G1-MUT-02C")
        self.assertEqual(spec.spec_id, "repository-write-effect-lease")
        self.assertEqual(spec.mutant_timeout_policy, "legacy-timeout-exit-1")
        self.assertEqual(len(spec.jobs), 1)
        job = spec.jobs[0]
        self.assertEqual(
            job.module,
            "daedalus/gates/repository_write_effect_lease.py",
        )
        self.assertEqual(job.tests, EXPECTED_BASELINE)
        self.assertEqual(job.mutant_test_files, EXPECTED_MUTANT_TEST_FILES)
        self.assertEqual(job.timeout_s, 180.0)
        self.assertEqual(len(job.mutations), 13)
        self.assertEqual(_job_digest(payload), EXPECTED_JOB_DIGEST)

    def test_list_mode_is_read_only(self):
        spec = ms.load_explicit_spec(ROOT, SPEC)
        observed = {SPEC, WRAPPER}
        observed.update(ROOT / job.module for job in spec.jobs)
        before = {path: path.read_bytes() for path in observed}
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = ms.main(
                ["--repo", str(ROOT), "--spec", str(SPEC), "--list"]
            )
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("13 explicit mutant(s) in 1 job(s)", output.getvalue())
        self.assertEqual(
            {path: path.read_bytes() for path in observed},
            before,
        )

    def test_wrapper_has_no_mutation_or_process_authority(self):
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
        self.assertIn("repository-write-effect-lease.json", source)

    def test_legacy_shape_shadows_through_the_canonical_sandbox(self):
        spec = ms.load_explicit_spec(ROOT, SPEC)
        source = ROOT / spec.jobs[0].module
        before = source.read_bytes()
        runner = _ShadowRunner(spec)
        with tempfile.TemporaryDirectory(prefix="g1-mut-02c-shadow-") as raw:
            shadow = Path(raw)
            target = shadow / spec.jobs[0].module
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before)
            report = ms.score_explicit_spec(shadow, spec, runner=runner)
        self.assertEqual(report["verdict"], "NO_SURVIVORS", report)
        self.assertEqual(report["n_caught"], 13, report)
        self.assertEqual(report["n_survived"], 0, report)
        self.assertEqual(report["n_inconclusive"], 0, report)
        self.assertEqual(report["n_not_applicable"], 0, report)
        self.assertFalse(runner.expected)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
