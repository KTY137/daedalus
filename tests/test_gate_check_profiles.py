from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

import pytest

import tools.run_gate_checks as gate_checks
from tools.run_gate_checks import G0_CHAIN_TESTS, G0_TESTS, G1_TESTS, PROFILES


def test_gate_check_profiles_are_deduplicated_and_cover_the_stack() -> None:
    assert len(G0_TESTS) == len(set(G0_TESTS))
    assert len(G1_TESTS) == len(set(G1_TESTS))
    consolidated = PROFILES["consolidated"]
    assert len(consolidated) == len(set(consolidated))
    assert set(G0_TESTS) | set(G1_TESTS) == set(consolidated)
    assert "tests/kernel/test_artifact_identity.py" in G0_TESTS
    assert "tests/ignition/test_voltage_ignition.py" in G1_TESTS


def test_g0_chain_is_fixed_broad_and_does_not_change_legacy_profiles() -> None:
    required_chain_seams = {
        "tests/chains/test_source_state.py",
        "tests/kernel/test_artifact_identity.py",
        "tests/kernel/test_offload_execution_plan.py",
        "tests/kernel/test_offload_authority.py",
        "tests/kernel/test_effect_leases.py",
        "tests/kernel/test_leased_offload.py",
        "tests/test_spine_attempt.py",
        "tests/test_effect_boundary.py",
        "tests/test_gate0_faults_atalanta.py",
        "tests/twin",
        "tests/kernel/test_fourfold_evidence.py",
        "tests/kernel/test_fourfold_approval_integration.py",
        "tests/kernel/test_owner_approval.py",
        "tests/kernel/test_sealed_promotion.py",
        "tests/kernel/test_runtime_conformance_harness.py",
        "tests/kernel/test_docker_sandbox_policy.py",
        "tests/gates/test_gate_report.py",
        "tests/test_kernel_contracts.py",
    }
    assert len(G0_CHAIN_TESTS) == len(set(G0_CHAIN_TESTS))
    assert required_chain_seams <= set(G0_CHAIN_TESTS)
    assert PROFILES["g0-chain"] == G0_CHAIN_TESTS
    assert PROFILES["g0-chain-receipt"] == G0_CHAIN_TESTS
    assert PROFILES["consolidated"] == tuple(dict.fromkeys((*G0_TESTS, *G1_TESTS)))
    assert gate_checks.HASH_SEEDS == ("0", "123456")


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def chain_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is required for source-fingerprint receipt tests")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Daedalus Test")
    _git(repo, "config", "user.email", "daedalus-test@example.invalid")
    (repo / ".gitignore").write_text("runs/spine/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("canonical\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "fixture")
    monkeypatch.setattr(gate_checks, "ROOT", repo)
    monkeypatch.setattr(
        gate_checks,
        "RECEIPT_ROOT",
        repo / "runs" / "spine" / "g0-chain",
    )
    return repo


def _fake_command_runner(
    repo: Path,
    *,
    nonpass_kind: str | None = None,
    mutate_after_seed: str | None = None,
) -> tuple[
    Callable[
        [Sequence[str], Path, dict[str, str] | None, int], tuple[int, bool]
    ],
    list[tuple[tuple[str, ...], dict[str, str] | None]],
]:
    calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def run(
        argv: Sequence[str],
        output_path: Path,
        env: dict[str, str] | None,
        timeout_s: int,
    ) -> tuple[int, bool]:
        del timeout_s
        calls.append((tuple(argv), env))
        summaries = {
            "xfail": "1 xfailed in 0.01s\n",
            "skip": "1 skipped in 0.01s\n",
            "xpass": "1 xpassed in 0.01s\n",
        }
        output_path.write_text(
            summaries[nonpass_kind]
            if nonpass_kind is not None and env
            else "1 passed in 0.01s\n",
            encoding="utf-8",
        )
        junit_arg = next(
            (argument for argument in argv if argument.startswith("--junitxml=")),
            None,
        )
        if junit_arg is not None:
            junit_path = Path(junit_arg.removeprefix("--junitxml="))
            result = {
                "xfail": '<skipped type="pytest.xfail" message="known gap" />',
                "skip": '<skipped type="pytest.skip" message="missing dependency" />',
                "xpass": "",
                None: "",
            }[nonpass_kind]
            junit_path.write_text(
                "<testsuites><testsuite tests=\"1\"><testcase "
                f'classname="chain" name="test_chain">{result}</testcase>'
                "</testsuite></testsuites>\n",
                encoding="utf-8",
            )
            seed = env["PYTHONHASHSEED"] if env is not None else None
            if seed == mutate_after_seed:
                (repo / "tracked.txt").write_text("mutated\n", encoding="utf-8")
        return 0, False

    return run, calls


def _read_receipt(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="ascii"))


def test_g0_chain_writes_a_complete_two_seed_receipt(chain_repo: Path) -> None:
    receipt_path = gate_checks.RECEIPT_ROOT / "pass.json"
    runner, calls = _fake_command_runner(chain_repo)

    exit_status = gate_checks.run_g0_chain(
        profile="g0-chain",
        requested_argv=["g0-chain", "--receipt", os.fspath(receipt_path)],
        receipt_path=receipt_path,
        command_runner=runner,
    )

    receipt = _read_receipt(receipt_path)
    assert exit_status == gate_checks.EXIT_OK
    assert receipt["outcome"] == "PASS"
    assert receipt["exit_status"] == gate_checks.EXIT_OK
    assert receipt["gate0_closure_claimed"] is False
    assert receipt["git_head"] == _git(chain_repo, "rev-parse", "HEAD")
    python_environment = dict(receipt["python"]["environment"])
    python_environment_sha = python_environment.pop("sha256")
    assert python_environment_sha == gate_checks.canonical_sha(python_environment)
    assert receipt["python"]["executable_identity"]["sha256"]
    assert receipt["python"]["prefix"]
    assert receipt["dirty_manifest"]["entries"] == []
    manifest_without_sha = dict(receipt["dirty_manifest"])
    manifest_sha = manifest_without_sha.pop("sha256")
    assert manifest_sha == gate_checks.canonical_sha(manifest_without_sha)
    assert receipt["source_before"]["fingerprint_sha256"] == receipt[
        "source_after"
    ]["fingerprint_sha256"]
    assert receipt["worktree_unchanged"] is True
    assert receipt["mutation_detected"] is False
    assert [run["seed"] for run in receipt["runs"]] == ["0", "123456"]
    assert [call[1] for call in calls] == [
        None,
        {"PYTHONHASHSEED": "0"},
        {"PYTHONHASHSEED": "123456"},
    ]
    for run in receipt["runs"]:
        assert run["counts"] == {
            "tests": 1,
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
        }
        for artifact_name in ("pytest_output", "junit"):
            artifact = run[artifact_name]
            artifact_path = chain_repo / artifact["path"]
            assert artifact["sha256"] == hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()


@pytest.mark.parametrize(
    ("nonpass_kind", "count_name"),
    (("xfail", "xfailed"), ("skip", "skipped"), ("xpass", "xpassed")),
)
def test_g0_chain_treats_nonpass_as_incomplete_evidence(
    chain_repo: Path,
    nonpass_kind: str,
    count_name: str,
) -> None:
    receipt_path = gate_checks.RECEIPT_ROOT / f"{nonpass_kind}.json"
    runner, _ = _fake_command_runner(chain_repo, nonpass_kind=nonpass_kind)

    exit_status = gate_checks.run_g0_chain(
        profile="g0-chain-receipt",
        requested_argv=["g0-chain-receipt"],
        receipt_path=receipt_path,
        command_runner=runner,
    )

    receipt = _read_receipt(receipt_path)
    assert exit_status == gate_checks.EXIT_INCOMPLETE
    assert receipt["outcome"] == "INCOMPLETE"
    assert [run["counts"][count_name] for run in receipt["runs"]] == [1, 1]
    assert [run["outcome"] for run in receipt["runs"]] == [
        "INCOMPLETE",
        "INCOMPLETE",
    ]


def test_g0_chain_fails_red_on_primary_worktree_mutation(chain_repo: Path) -> None:
    receipt_path = gate_checks.RECEIPT_ROOT / "mutation.json"
    runner, calls = _fake_command_runner(chain_repo, mutate_after_seed="0")

    exit_status = gate_checks.run_g0_chain(
        profile="g0-chain",
        requested_argv=["g0-chain"],
        receipt_path=receipt_path,
        command_runner=runner,
    )

    receipt = _read_receipt(receipt_path)
    assert exit_status == gate_checks.EXIT_FAILED
    assert receipt["outcome"] == "FAIL"
    assert receipt["mutation_detected"] is True
    assert receipt["mutation_observation"]["stage"] == "pytest-seed-0"
    assert receipt["worktree_unchanged"] is False
    assert len(receipt["runs"]) == 1
    assert len(calls) == 2
    assert receipt["source_before"]["fingerprint_sha256"] != receipt[
        "source_after"
    ]["fingerprint_sha256"]


def test_g0_chain_receipt_path_is_bounded(chain_repo: Path) -> None:
    with pytest.raises(ValueError, match="must stay under"):
        gate_checks._bounded_receipt_path(chain_repo / "outside.json", "unused")
