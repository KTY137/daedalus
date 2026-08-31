"""Contracts for G1-MUT-02B gate/promotion mutation runner migration."""
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
SPEC = ROOT / "configs" / "mutations" / "gate-report-v3.json"
WRAPPER = ROOT / "scripts" / "run_gate_report_v3_mutations.py"

FAMILY = {
    "run_gate_report_writer_inventory_mutations.py",
    "run_gate_report_v3_mutations.py",
    "run_gate_baseline_v2_mutations.py",
    "run_gate0_release_writer_inventory_mutations.py",
    "run_promotion_receipt_authority_mutations.py",
    "run_promotion_execution_reader_mutations.py",
    "run_promotion_execution_mutations.py",
    "run_persisted_promotion_authorization_mutations.py",
    "run_live_promotion_seam_mutations.py",
}

UNMIGRATED = {
    "run_gate_report_writer_inventory_mutations.py":
        ("unbounded-timeout", "162aaaadfaf21b5519af211f7001afe56b6c6afa58ede00169b317618c427762"),
    "run_gate_baseline_v2_mutations.py":
        ("unbounded-timeout", "c6b6c6412feb74af769aaed37f499c713b7878c0426f722e06573a08db42c122"),
    "run_gate0_release_writer_inventory_mutations.py":
        ("unbounded-timeout", "4b40b2afd1701f6b47a64f59c2c6071062c3e246e44d4ee0457333cdca5c0a19"),
    "run_promotion_receipt_authority_mutations.py":
        ("unbounded-timeout-and-file-creation", "de0d4ba66f49bb1963343db483f396bb71d959f5b843a73008d506644bccfa64"),
    "run_promotion_execution_reader_mutations.py":
        ("unbounded-timeout", "8e5f9fd7c7ff1b61f7cf954c59c198bb5235ced09dd649e0df3dc60f8901b80a"),
    "run_promotion_execution_mutations.py":
        ("unbounded-timeout", "de446768f611a0cd8d958e035014aaa0c291e334d0cb2708c265948fae0fc8a5"),
    "run_persisted_promotion_authorization_mutations.py":
        ("unbounded-timeout", "7cbb166825d4b635de505df1a4e052b553de3bef56a6960a1df43a34656ebe25"),
    "run_live_promotion_seam_mutations.py":
        ("unbounded-timeout-and-multi-replace", "8e0333f5a45d01c89b456b75d1593b176035110b9d239bc9cccf2cda149f3c37"),
}

EXPECTED_TESTS = (
    "tests/gates/test_gate_report_v3.py",
    "tests/gates/test_gate_report_v3_bounds.py",
    "tests/gates/test_gate_report_v3_drift.py",
    "tests/gates/test_gate_report_v3_review.py",
    "tests/gates/test_gate_report_v3_schema.py",
    "tests/gates/test_gate_report_v3_cli.py",
    "tests/gates/test_gate_report_v3_surface_authentication.py",
    "tests/gates/test_gate_report_v3_raw_input_composition.py",
)
EXPECTED_JOB_DIGEST = (
    "28052aff76754f032241f304354bd6b2a9e520c061869626a2755a3311af88d8"
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


class GatePromotionMutationSpecTests(unittest.TestCase):
    def test_inventory_is_exact_and_unmigrated_runners_are_byte_identical(self):
        self.assertEqual(len(FAMILY), 9)
        self.assertEqual(
            FAMILY,
            set(UNMIGRATED) | {"run_gate_report_v3_mutations.py"},
        )
        for name in FAMILY:
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)
        for name, (reason, expected_digest) in UNMIGRATED.items():
            with self.subTest(runner=name):
                self.assertTrue(reason)
                self.assertEqual(
                    _sha256(ROOT / "scripts" / name),
                    expected_digest,
                )

    def test_spec_strictly_loads_the_frozen_legacy_job(self):
        payload = json.loads(SPEC.read_text(encoding="utf-8"))
        spec = ms.load_explicit_spec(ROOT, SPEC)
        self.assertEqual(spec.packet_id, "G1-MUT-02B")
        self.assertEqual(spec.spec_id, "gate-report-v3")
        self.assertEqual(len(spec.jobs), 1)
        job = spec.jobs[0]
        self.assertEqual(job.module, "daedalus/gates/report_v3.py")
        self.assertEqual(job.tests, EXPECTED_TESTS)
        self.assertEqual(job.timeout_s, 300.0)
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
        self.assertIn("gate-report-v3.json", source)
        self.assertIn(
            'return mutation_main(["--repo", str(ROOT), "--spec", str(SPEC)])',
            source,
        )

    def test_legacy_shape_shadows_through_the_canonical_sandbox(self):
        spec = ms.load_explicit_spec(ROOT, SPEC)
        source = ROOT / spec.jobs[0].module
        before = source.read_bytes()
        runner = _ShadowRunner(spec)
        with tempfile.TemporaryDirectory(prefix="g1-mut-02b-shadow-") as raw:
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
