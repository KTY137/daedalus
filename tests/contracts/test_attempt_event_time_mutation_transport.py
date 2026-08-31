"""Contracts for the G1-MUT-02E/02F event-time mutation migration."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from scripts import run_attempt_event_time_window_mutations as runner
from tools import mutation_score as ms


ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "configs/mutations/attempt-event-time-window.json"
WRAPPER = ROOT / "scripts/run_attempt_event_time_window_mutations.py"
TARGET = ROOT / "daedalus/kernel/attempt_spine_reader.py"
EXPECTED_TESTS = (
    "tests/kernel/test_isolated_attempt_time_tampering.py",
    "tests/kernel/test_isolated_attempt_time_and_preflight.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_spine_wire_review.py",
)
EXPECTED_MUTATION_IDS = (
    "accept-arbitrary-historical-record-time",
    "accept-record-time-after-event",
    "skip-terminal-time-binding",
)
EXPECTED_MUTATION_DIGEST = (
    "9f45fb294da71fd707f08de8b559a9c64f75908e08b584d6cddef4cfa2d93211"
)
EXPECTED_TARGET_BLOB = "ac7c379b41963b731e3536f4ac42db332639f109"
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


def _git_blob_sha1(payload: bytes) -> str:
    canonical = payload.replace(b"\r\n", b"\n")
    header = f"blob {len(canonical)}\0".encode("ascii")
    return hashlib.sha1(header + canonical).hexdigest()


def _semantic_projection(
    spec: ms.ExplicitMutationSpec,
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (mutation.id, mutation.before, mutation.after)
        for mutation in spec.jobs[0].mutations
    )


def _semantic_digest(spec: ms.ExplicitMutationSpec) -> str:
    encoded = json.dumps(
        _semantic_projection(spec),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _ShadowRunner:
    def __init__(self, spec: ms.ExplicitMutationSpec, original: bytes):
        self.job = spec.jobs[0]
        source = original.decode("utf-8").replace("\r\n", "\n")
        self.expected_sources = [source]
        self.expected_sources.extend(
            source.replace(mutation.before, mutation.after, 1)
            for mutation in self.job.mutations
        )
        self.timeouts: list[float | None] = []
        self.roots: list[Path] = []

    def __call__(
        self,
        root: Path,
        test_paths: list[str],
        timeout: float | None,
    ) -> ms.RunResult:
        expected_source = self.expected_sources.pop(0)
        assert tuple(test_paths) == self.job.tests
        assert (
            root / self.job.module
        ).read_text(encoding="utf-8") == expected_source
        self.timeouts.append(timeout)
        self.roots.append(root)
        if len(self.timeouts) == 1:
            return ms.RunResult(returncode=0)
        return ms.RunResult(
            returncode=1,
            failing={"tests/shadow.py::test_detects_mutant"},
        )


def test_spec_is_the_exact_three_mutant_unbounded_projection() -> None:
    payload = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = ms.load_explicit_spec(ROOT, SPEC)
    assert spec.packet_id == "G1-MUT-02F"
    assert spec.spec_id == "attempt-event-time-window"
    assert len(spec.jobs) == 1
    job = spec.jobs[0]
    assert job.module == "daedalus/kernel/attempt_spine_reader.py"
    assert job.tests == EXPECTED_TESTS
    assert job.timeout_policy == ms.JOB_TIMEOUT_LEGACY_UNBOUNDED
    assert job.timeout_s is None
    assert "timeout_s" not in payload["jobs"][0]
    assert tuple(mutation.id for mutation in job.mutations) == EXPECTED_MUTATION_IDS
    assert _semantic_digest(spec) == EXPECTED_MUTATION_DIGEST

    normalized_source = TARGET.read_text(encoding="utf-8")
    assert all(
        normalized_source.count(mutation.before) == 1
        for mutation in job.mutations
    )
    original = TARGET.read_bytes()
    lf_count = original.count(b"\n")
    assert lf_count > 0
    assert original.count(b"\r\n") in {0, lf_count}
    assert _git_blob_sha1(original) == EXPECTED_TARGET_BLOB


def test_list_mode_is_read_only() -> None:
    observed = (SPEC, WRAPPER, TARGET)
    before = {path: path.read_bytes() for path in observed}
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = ms.main(
            ["--repo", str(ROOT), "--spec", str(SPEC), "--list"]
        )
    assert result == 0, output.getvalue()
    assert "3 explicit mutant(s) in 1 job(s)" in output.getvalue()
    assert {path: path.read_bytes() for path in observed} == before


def test_wrapper_has_no_mutation_or_process_authority() -> None:
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
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    calls.update(
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    )
    assert FORBIDDEN_IMPORTS.isdisjoint(imports)
    assert FORBIDDEN_CALLS.isdisjoint(calls)
    assert "from tools.mutation_score import main" in source
    assert "attempt-event-time-window.json" in source


def test_wrapper_preserves_the_common_exit_classes_and_exact_argv() -> None:
    expected_argv = ["--repo", str(ROOT), "--spec", str(SPEC)]
    for exit_code in (0, 1, 2):
        with mock.patch.object(
            runner,
            "mutation_main",
            return_value=exit_code,
        ) as call:
            assert runner.main() == exit_code
        call.assert_called_once_with(expected_argv)


def test_canonical_shadow_is_unbounded_and_never_writes_the_source_tree() -> None:
    spec = ms.load_explicit_spec(ROOT, SPEC)
    original = TARGET.read_bytes()
    with tempfile.TemporaryDirectory(prefix="g1-mut-02f-shadow-") as raw:
        shadow = Path(raw)
        target = shadow / spec.jobs[0].module
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
        fake = _ShadowRunner(spec, original)
        report = ms.score_explicit_spec(shadow, spec, runner=fake)
        assert target.read_bytes() == original

    assert report["verdict"] == "NO_SURVIVORS"
    assert report["n_caught"] == 3
    assert report["n_survived"] == 0
    assert report["n_not_applicable"] == 0
    assert report["n_inconclusive"] == 0
    assert fake.timeouts == [None, None, None, None]
    assert not fake.expected_sources
    assert all(root != ROOT for root in fake.roots)
    assert TARGET.read_bytes() == original
    assert _git_blob_sha1(TARGET.read_bytes()) == EXPECTED_TARGET_BLOB


def test_common_result_classes_keep_legacy_process_exit_classes() -> None:
    spec = ms.load_explicit_spec(ROOT, SPEC)
    assert (
        ms._explicit_spec_exit_code(
            spec,
            {"verdict": "NO_SURVIVORS", "n_survived": 0},
        )
        == 0
    )
    assert (
        ms._explicit_spec_exit_code(
            spec,
            {"verdict": "SURVIVORS", "n_survived": 1},
        )
        == 1
    )
    assert (
        ms._explicit_spec_exit_code(
            spec,
            {
                "verdict": ms.INCONCLUSIVE,
                "n_survived": 0,
                "baseline_green": False,
                "n_not_applicable": 0,
                "n_inconclusive": 0,
                "timed_out_mutations": [],
            },
        )
        == 2
    )
