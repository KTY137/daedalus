"""KITCHEN-02: empty checks and repair-induced evaluator drift cannot go green."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.kitchen import toolchain


def _observation(name: str, *, required: bool = True, passed: bool = True) -> toolchain.Observation:
    return toolchain.Observation(name, [sys.executable, "check.py"], 0 if passed else 1, 0.0, passed, required=required)


@pytest.mark.parametrize("observations", [
    [],
    [_observation("install")],
    [_observation("lint", required=False)],
    [_observation("lint", required=False, passed=False)],
    [_observation("test", required=False)],
    [_observation("install"), _observation("lint", required=False, passed=False)],
])
def test_verdict_requires_a_required_build_or_test(observations: list[toolchain.Observation]) -> None:
    green, failures = toolchain.verdict(observations)
    assert not green
    assert "required_verification_missing" in failures


def test_required_install_failure_does_not_impersonate_verification(tmp_path: Path) -> None:
    plan = toolchain.Plan([
        toolchain.Step("install", [sys.executable, "-c", "raise SystemExit(7)"]),
        toolchain.Step("test", [sys.executable, "check.py"]),
    ], None, None, "fixture", "python")
    observations = toolchain.run_plan(plan, tmp_path, timeout_s=10)
    assert [item.name for item in observations] == ["install"]
    assert toolchain.verdict(observations) == (False, ["install", "required_verification_missing"])


def test_optional_failure_preserves_successful_required_verification() -> None:
    assert toolchain.verdict([_observation("build"), _observation("lint", required=False, passed=False)]) == (True, [])


def test_passed_flag_cannot_hide_a_nonzero_required_exit() -> None:
    observation = _observation("test")
    observation.exit_code = 2
    assert toolchain.verdict([observation]) == (False, ["test"])


def _candidate(workspace: Path) -> toolchain.Plan:
    (workspace / "main.py").write_text("value = 1\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_main.py").write_text("from main import value\n\ndef test_value():\n    assert value == 2\n", encoding="utf-8")
    (workspace / toolchain.MANIFEST).write_text(json.dumps({
        "build": ["python", "-m", "compileall", "-q", "."],
        "test": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
    }), encoding="utf-8")
    return toolchain.detect(workspace)


def test_source_repair_can_pass_the_same_frozen_verifier(tmp_path: Path) -> None:
    plan = _candidate(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    assert frozen.error is None
    before = toolchain.run_plan(plan, tmp_path, timeout_s=30)
    assert toolchain.verdict(before) == (False, ["test"])
    assert toolchain.verification_integrity(frozen, plan, tmp_path) is None
    # Avoid timestamp-and-size bytecode reuse when the source repair is rapid.
    (tmp_path / "main.py").write_text("value = 2  # repaired\n", encoding="utf-8")
    assert toolchain.verification_integrity(frozen, plan, tmp_path) is None
    after = toolchain.run_plan(plan, tmp_path, timeout_s=30)
    assert toolchain.verdict(after) == (True, [])
    assert toolchain.verification_integrity(frozen, plan, tmp_path) is None


@pytest.mark.parametrize("mutation", ["manifest", "test_changed", "test_deleted", "test_added", "config_added"])
def test_repair_cannot_change_frozen_verification(tmp_path: Path, mutation: str) -> None:
    plan = _candidate(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    test_path = tmp_path / "tests" / "test_main.py"
    if mutation == "manifest":
        (tmp_path / toolchain.MANIFEST).write_text(json.dumps({"test": ["python", "-c", "pass"]}), encoding="utf-8")
    elif mutation == "test_changed":
        test_path.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    elif mutation == "test_deleted":
        test_path.unlink()
    elif mutation == "test_added":
        (tmp_path / "tests" / "conftest.py").write_text("def pytest_collection_modifyitems(items):\n    items.clear()\n", encoding="utf-8")
    else:
        (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --ignore=tests/test_main.py\n", encoding="utf-8")
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and failure.required and not failure.passed
    assert "changed" in failure.output_tail
    assert not toolchain.verdict([_observation("build"), failure])[0]


def test_mutating_plan_in_place_does_not_mutate_the_frozen_contract(tmp_path: Path) -> None:
    plan = _candidate(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    plan.steps[-1].required = False
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and "plan changed" in failure.output_tail


def test_package_script_change_is_detected_even_when_argv_stays_equal(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"scripts": {"test": "node check.js"}}), encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    package.write_text(json.dumps({"scripts": {"test": "node -e 'process.exit(0)'"}}), encoding="utf-8")
    assert toolchain.detect(tmp_path).to_dict() == plan.to_dict()
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and "package.json" in failure.output_tail


@pytest.mark.parametrize("command,script", [
    (["python", "checks.py"], "checks.py"),
    (["python", "build/checks.py"], "build/checks.py"),
    (["python", "-m", "verify.checks"], "verify/checks.py"),
    (["python", "checks.py", "--config=rules.json"], "rules.json"),
])
def test_custom_command_inputs_are_frozen(tmp_path: Path, command: list[str], script: str) -> None:
    script_path = tmp_path / script
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("original evaluator\n", encoding="utf-8")
    (tmp_path / toolchain.MANIFEST).write_text(json.dumps({"test": command}), encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    script_path.write_text("weakened evaluator\n", encoding="utf-8")
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and script in failure.output_tail


def test_local_npm_script_entrypoint_is_frozen(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node checks.js"}}), encoding="utf-8")
    script = tmp_path / "checks.js"
    script.write_text("process.exit(1);\n", encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    script.write_text("process.exit(0);\n", encoding="utf-8")
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and "checks.js" in failure.output_tail


def test_npm_check_freezes_nested_script_without_freezing_application_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": "npm run verify", "verify": "node checks.js", "start": "node main.js",
    }}), encoding="utf-8")
    (tmp_path / "checks.js").write_text("process.exit(1);\n", encoding="utf-8")
    (tmp_path / "main.js").write_text("broken();\n", encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    (tmp_path / "main.js").write_text("console.log('repaired');\n", encoding="utf-8")
    assert toolchain.verification_integrity(frozen, plan, tmp_path) is None
    (tmp_path / "checks.js").write_text("process.exit(0);\n", encoding="utf-8")
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and "checks.js" in failure.output_tail


def test_integrity_read_errors_refuse_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _candidate(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)

    def fail_read(*args):
        raise OSError("unreadable evaluator")

    monkeypatch.setattr(toolchain, "_verification_files", fail_read)
    failure = toolchain.verification_integrity(frozen, plan, tmp_path)
    assert failure is not None and "unreadable evaluator" in failure.output_tail
    unavailable = toolchain.freeze_verification(plan, tmp_path)
    assert unavailable.error and toolchain.verification_integrity(unavailable, plan, tmp_path) is not None


def test_static_web_build_remains_a_supported_scoped_check(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    frozen = toolchain.freeze_verification(plan, tmp_path)
    observations = toolchain.run_plan(plan, tmp_path, timeout_s=10)
    assert toolchain.verdict(observations) == (True, [])
    assert toolchain.verification_integrity(frozen, plan, tmp_path) is None
