"""Contracts for G1-MUT-02A provider/runtime mutation runner migration."""
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
SPEC_DIR = ROOT / "configs" / "mutations"
SCRIPT_DIR = ROOT / "scripts"

MIGRATED = {
    "run_provider_invocation_identity_mutations.py":
        "provider-invocation-identity.json",
    "run_provider_observation_authority_mutations.py":
        "provider-observation-authority.json",
    "run_provider_observation_persistence_inventory_mutations.py":
        "provider-observation-persistence-inventory.json",
    "run_provider_target_verification_mutations.py":
        "provider-target-verification.json",
    "run_runtime_effect_replay_projection_mutations.py":
        "runtime-effect-replay-projection.json",
}

UNMIGRATED_REASONS = {
    "run_provider_broker_exact_authority_mutations.py": "ambiguous-anchor",
    "run_provider_executable_structure_mutations.py": "unbounded-timeout",
    "run_provider_executable_target_mutations.py": "missing-anchor",
    "run_provider_invocation_authority_mutations.py": "unbounded-timeout",
    "run_provider_invocation_registry_mutations.py": "unbounded-timeout",
    "run_provider_invocation_resolution_mutations.py": "unbounded-timeout",
    "run_provider_observation_store_contract_mutations.py": "unbounded-timeout",
    "run_provider_observation_store_mutations.py": "unbounded-timeout",
    "run_provider_target_receipt_retention_admission_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_completed_evidence_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_contract_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_effect_terminal_evidence_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_inventory_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_mutations.py": "unbounded-timeout",
    "run_provider_target_receipt_retention_preflight_mutations.py":
        "unbounded-timeout",
    "run_provider_target_receipt_retention_recovery_mutations.py":
        "unbounded-timeout",
    "run_runtime_authorization_clock_mutations.py":
        "unbounded-timeout-and-multi-anchor",
    "run_runtime_post_provider_unknown_mutations.py": "missing-anchor",
    "run_runtime_terminal_binding_mutations.py": "unbounded-timeout",
}

# Three digests moved in G1-PKG-01 and only because the ``module`` field of
# each job now reads daedalus/runtimes/provider/<name>.py. The projection is
# over the jobs payload, so a path is part of it; the mutations, their find/
# replace text, the job and mutation counts and the tests each job runs are
# byte-identical. Re-derived from the spec files, not re-typed.
EXPECTED_JOB_PROJECTIONS = {
    "provider-invocation-identity.json":
        ("18ff2bf0fcef5fdb3d0c0ea4415accc8a7f08085a206e3fd4fdfa29a0e2023a3", 1, 9),
    "provider-observation-authority.json":
        ("9ecefee330763b3c5d961235efc3a377314fa3a968baf039d3f4de891d2be627", 3, 8),
    "provider-observation-persistence-inventory.json":
        ("58d380f8a3c1592447f263e85fc4cc8887bf299c4ece1c4d1963bba754e426bc", 1, 6),
    "provider-target-verification.json":
        ("7b3b7c9b8de16921da03d20f179f7dac462e1afb6abe890067783957da98e60c", 2, 11),
    "runtime-effect-replay-projection.json":
        ("5280552f98df8ee7559f5f9be0989ab1b24ff7295426de8a01ce9e5e672e0f95", 1, 6),
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


def _targeted_runner_names() -> set[str]:
    return {
        path.name
        for pattern in ("run_provider_*_mutations.py", "run_runtime_*_mutations.py")
        for path in SCRIPT_DIR.glob(pattern)
    }


def _job_projection_digest(payload: dict[str, object]) -> str:
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
                selected = mutation.test_paths or job.tests
                self.expected.append((selected, job.timeout_s, False))

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


class ProviderRuntimeMutationSpecTests(unittest.TestCase):
    def test_inventory_is_exhaustive_and_every_migrated_runner_has_one_spec(self):
        self.assertEqual(
            _targeted_runner_names(),
            set(MIGRATED) | set(UNMIGRATED_REASONS),
        )
        self.assertEqual(len(MIGRATED), 5)
        self.assertEqual(len(UNMIGRATED_REASONS), 19)
        self.assertEqual(
            {
                path.name
                for path in SPEC_DIR.glob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("packet_id")
                == "G1-MUT-02A"
            },
            set(MIGRATED.values()),
        )

    def test_specs_strictly_load_with_frozen_legacy_jobs(self):
        for spec_name, (digest, job_count, mutation_count) in (
            EXPECTED_JOB_PROJECTIONS.items()
        ):
            with self.subTest(spec=spec_name):
                path = SPEC_DIR / spec_name
                payload = json.loads(path.read_text(encoding="utf-8"))
                spec = ms.load_explicit_spec(ROOT, path)
                self.assertEqual(spec.packet_id, "G1-MUT-02A")
                self.assertEqual(len(spec.jobs), job_count)
                self.assertEqual(
                    sum(len(job.mutations) for job in spec.jobs),
                    mutation_count,
                )
                self.assertEqual(_job_projection_digest(payload), digest)

    def test_list_mode_is_read_only_for_every_migrated_spec(self):
        observed_paths = {
            SPEC_DIR / spec_name for spec_name in MIGRATED.values()
        }
        observed_paths.update(SCRIPT_DIR / script for script in MIGRATED)
        for spec_name in MIGRATED.values():
            spec = ms.load_explicit_spec(ROOT, SPEC_DIR / spec_name)
            observed_paths.update(ROOT / job.module for job in spec.jobs)
        before = {path: path.read_bytes() for path in observed_paths}

        for spec_name in MIGRATED.values():
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = ms.main(
                    [
                        "--repo",
                        str(ROOT),
                        "--spec",
                        str(SPEC_DIR / spec_name),
                        "--list",
                    ]
                )
            self.assertEqual(result, 0, output.getvalue())
            self.assertIn("explicit mutant(s)", output.getvalue())

        self.assertEqual(
            {path: path.read_bytes() for path in observed_paths},
            before,
        )

    def test_compatibility_wrappers_have_no_mutation_or_process_authority(self):
        expected_return = (
            'return mutation_main(["--repo", str(ROOT), "--spec", str(SPEC)])'
        )
        for script_name, spec_name in MIGRATED.items():
            with self.subTest(script=script_name):
                source = (SCRIPT_DIR / script_name).read_text(encoding="utf-8")
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
                self.assertIn(spec_name, source)
                self.assertIn(expected_return, source)

    def test_each_legacy_form_shadows_through_the_canonical_sandbox(self):
        source_before: dict[Path, bytes] = {}
        for spec_name in MIGRATED.values():
            spec = ms.load_explicit_spec(ROOT, SPEC_DIR / spec_name)
            for job in spec.jobs:
                path = ROOT / job.module
                source_before.setdefault(path, path.read_bytes())
            runner = _ShadowRunner(spec)
            with tempfile.TemporaryDirectory(prefix="g1-mut-02a-shadow-") as raw:
                shadow = Path(raw)
                for job in spec.jobs:
                    target = shadow / job.module
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / job.module).read_bytes())
                report = ms.score_explicit_spec(shadow, spec, runner=runner)
            self.assertEqual(report["verdict"], "NO_SURVIVORS", report)
            self.assertEqual(report["n_survived"], 0, report)
            self.assertEqual(report["n_inconclusive"], 0, report)
            self.assertEqual(report["n_not_applicable"], 0, report)
            self.assertFalse(runner.expected)

        self.assertEqual(
            {path: path.read_bytes() for path in source_before},
            source_before,
        )


if __name__ == "__main__":
    unittest.main()
