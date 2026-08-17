"""Fail-closed contract for the Linux container fault driver.

Docker is mocked here: every test drives the driver through a stand-in for
``run_in_docker_sandbox`` so the fail-closed semantics can be exercised on any
host. The one test that needs a real Linux kernel lives in
``test_container_fault_driver_integration.py`` and is marked ``docker``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from daedalus.kernel.sandbox import SandboxExecutionReceipt
from daedalus.runtimes import container_fault_driver as driver_module
from daedalus.runtimes.container_fault_driver import (
    EXECUTOR_SCRIPTS,
    ContainerFaultDriver,
    ContainerFaultDriverError,
    ContainerFaultEvidenceMalformed,
    ContainerFaultEvidenceMissing,
    ContainerFaultScenarioDrift,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG, RuntimeFaultScenario
from daedalus.spine.envelope import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "b" * 40

LINUX_SCENARIOS = tuple(
    row for row in RUNTIME_FAULT_CATALOG.scenarios if row.authority == "linux-host"
)


def _digest(value: bytes | str = b"x") -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _receipt(
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    launch_state: str = "completed",
    error_code: str | None = None,
) -> SandboxExecutionReceipt:
    return SandboxExecutionReceipt(
        argv_sha256=_digest(b"argv"),
        returncode=returncode,
        timed_out=timed_out,
        stdout_sha256=_digest(b"out"),
        stderr_sha256=_digest(b"err"),
        launch_state=launch_state,
        error_code=error_code,
    )


def _container_evidence(
    scenario: RuntimeFaultScenario,
    *,
    status: str,
    observed_outcome: str | None,
    detail_code: str | None,
    raw: bytes,
    source_revision: str = REVISION,
    scenario_id: str | None = None,
    scenario_sha256: str | None = None,
    executor: str | None = None,
) -> dict[str, Any]:
    started = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    return {
        "schema": "daedalus-linux-host-fault-evidence/1",
        "scenario_id": scenario_id or scenario.scenario_id,
        "scenario_sha256": scenario_sha256 or scenario.digest,
        "source_revision": source_revision,
        "executor": executor or scenario.executor,
        "executor_sha256": _digest(b"executor"),
        "started_at": started.isoformat(timespec="microseconds"),
        "finished_at": (started + timedelta(seconds=1)).isoformat(timespec="microseconds"),
        "status": status,
        "observed_outcome": observed_outcome,
        "detail_code": detail_code,
        "raw_evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "facts": [{"name": "container-fact", "value": "present"}],
    }


class FakeSandbox:
    """Stand-in for run_in_docker_sandbox that materializes workspace files."""

    def __init__(self) -> None:
        self.receipt = _receipt()
        self.writer = None
        self.calls: list[tuple[Any, tuple[str, ...]]] = []
        self.policies: list[Any] = []

    def __call__(self, policy, command) -> SandboxExecutionReceipt:
        command = tuple(command)
        self.calls.append((policy, command))
        self.policies.append(policy)
        if self.writer is not None and self.receipt.launch_state == "completed":
            self.writer(Path(policy.candidate_workspace), command)
        return self.receipt


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSandbox]:
    fake = FakeSandbox()
    monkeypatch.setattr(driver_module, "run_in_docker_sandbox", fake)
    yield fake


def _write_all_passing(workspace: Path, command: tuple[str, ...]) -> None:
    """Emit passing evidence for every scenario the invoked script owns."""

    script = command[3].removeprefix("/repo/")
    for scenario in LINUX_SCENARIOS:
        if EXECUTOR_SCRIPTS[scenario.executor] != script:
            continue
        raw = b"raw-" + scenario.scenario_id.encode("utf-8")
        document = _container_evidence(
            scenario,
            status="passed",
            observed_outcome=scenario.expected_outcome,
            detail_code=None,
            raw=raw,
        )
        (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
            canonical_json(document), encoding="utf-8"
        )
        (workspace / f"{scenario.scenario_id}.raw").write_bytes(raw)


def _driver(**kwargs: Any) -> ContainerFaultDriver:
    return ContainerFaultDriver(
        repo_root=REPO_ROOT, source_revision=REVISION, **kwargs
    )


# -- happy path --------------------------------------------------------------


def test_every_linux_scenario_runs_and_keeps_its_passing_outcome(
    sandbox: FakeSandbox,
) -> None:
    sandbox.writer = _write_all_passing
    runs = _driver().run_catalog()

    assert len(runs) == len(LINUX_SCENARIOS) == 9
    assert {run.observation.scenario_id for run in runs} == {
        row.scenario_id for row in LINUX_SCENARIOS
    }
    for run in runs:
        assert run.observation.status == "passed"
        assert run.observation.authority == "linux-host"
        assert run.evidence.schema == "daedalus-linux-host-fault-evidence/1"
        assert run.evidence.source_revision == REVISION


def test_one_container_per_script_is_reused_across_its_scenarios(
    sandbox: FakeSandbox,
) -> None:
    sandbox.writer = _write_all_passing
    _driver().run_catalog()

    # Nine scenarios, eight scripts: the process executor owns two scenarios
    # and must not be started twice.
    assert len(sandbox.calls) == len(set(EXECUTOR_SCRIPTS.values())) == 8


def test_container_runs_read_only_offline_and_non_root(sandbox: FakeSandbox) -> None:
    sandbox.writer = _write_all_passing
    _driver().run_catalog()

    for policy in sandbox.policies:
        argv = policy.argv(("python", "-c", "pass"))
        assert "--read-only" in argv
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--cap-drop" in argv and "ALL" in argv
        assert policy.user == "65532:65532"
        mounts = [argv[i + 1] for i, part in enumerate(argv) if part == "--mount"]
        repo_mounts = [spec for spec in mounts if "dst=/repo" in spec]
        assert repo_mounts and all(spec.endswith(",ro") for spec in repo_mounts)


# -- fail-closed: the sandbox never started ----------------------------------


@pytest.mark.parametrize(
    ("error_code", "detail_code"),
    [
        ("runtime-not-found", "docker-cli-unavailable"),
        ("runtime-not-executable", "docker-cli-not-executable"),
        ("runtime-launch-error", "docker-launch-error"),
        ("docker-cli-refused", "docker-cli-refused"),
    ],
)
def test_a_sandbox_that_refuses_to_start_blocks_every_scenario(
    sandbox: FakeSandbox, error_code: str, detail_code: str
) -> None:
    sandbox.receipt = _receipt(
        returncode=125 if error_code == "docker-cli-refused" else None,
        launch_state="refused-before-start",
        error_code=error_code,
    )
    runs = _driver().run_catalog()

    assert len(runs) == 9
    for run in runs:
        assert run.observation.status == "blocked"
        assert run.observation.observed_outcome is None
        assert run.observation.detail_code == detail_code


def test_a_timed_out_container_blocks_rather_than_passes(sandbox: FakeSandbox) -> None:
    sandbox.receipt = _receipt(
        returncode=None, timed_out=True, launch_state="timed-out", error_code="timeout"
    )
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"blocked"}
    assert {run.observation.detail_code for run in runs} == {"sandbox-timeout"}


def test_missing_docker_cli_is_reported_and_never_treated_as_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver_module.shutil, "which", lambda name: None)
    assert driver_module.docker_cli_available() is False


# -- fail-closed: the container ran but the evidence is unusable -------------


def test_a_completed_container_that_wrote_nothing_fails(sandbox: FakeSandbox) -> None:
    sandbox.writer = lambda workspace, command: None
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        assert run.observation.detail_code == "executor-error"
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["exception-type"] == "ContainerFaultEvidenceMissing"


def test_malformed_evidence_json_fails_closed(sandbox: FakeSandbox) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                "{not json", encoding="utf-8"
            )

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["exception-type"] == "ContainerFaultEvidenceMalformed"


def test_duplicate_json_keys_are_rejected(sandbox: FakeSandbox) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                '{"status": "passed", "status": "passed"}', encoding="utf-8"
            )

    sandbox.writer = writer
    runs = _driver().run_catalog()
    assert {run.observation.status for run in runs} == {"failed"}


@pytest.mark.parametrize(
    "drift",
    ["scenario_id", "scenario_sha256", "source_revision", "executor"],
)
def test_evidence_bound_to_another_identity_cannot_pass(
    sandbox: FakeSandbox, drift: str
) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            raw = b"raw-drift"
            overrides: dict[str, Any] = {}
            if drift == "scenario_id":
                overrides["scenario_id"] = "runtime.some.other"
            elif drift == "scenario_sha256":
                overrides["scenario_sha256"] = _digest(b"foreign")
            elif drift == "source_revision":
                overrides["source_revision"] = "c" * 40
            else:
                overrides["executor"] = "host-fixture:foreign"
            document = _container_evidence(
                scenario,
                status="passed",
                observed_outcome=scenario.expected_outcome,
                detail_code=None,
                raw=raw,
                **overrides,
            )
            # The file keeps the real scenario name so the driver finds it and
            # must reject it on content rather than on absence.
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                canonical_json(document), encoding="utf-8"
            )
            (workspace / f"{scenario.scenario_id}.raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        # The document is found under the expected filename, so it has to be
        # rejected on its contents rather than on its absence.
        assert facts["exception-type"] == "ContainerFaultScenarioDrift"


def test_raw_evidence_that_contradicts_its_digest_fails(sandbox: FakeSandbox) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            document = _container_evidence(
                scenario,
                status="passed",
                observed_outcome=scenario.expected_outcome,
                detail_code=None,
                raw=b"declared",
            )
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                canonical_json(document), encoding="utf-8"
            )
            (workspace / f"{scenario.scenario_id}.raw").write_bytes(b"substituted")

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["exception-type"] == "ContainerFaultScenarioDrift"


# -- fail-closed: never upgrade a result -------------------------------------


def test_a_pass_claiming_the_wrong_outcome_is_downgraded_to_failed(
    sandbox: FakeSandbox,
) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            wrong = next(
                value
                for value in ("failed", "cancelled", "refused-before-start")
                if value != scenario.expected_outcome
            )
            raw = b"raw-wrong-outcome"
            document = _container_evidence(
                scenario,
                status="passed",
                observed_outcome=wrong,
                detail_code=None,
                raw=raw,
            )
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                canonical_json(document), encoding="utf-8"
            )
            (workspace / f"{scenario.scenario_id}.raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        assert run.observation.detail_code == "outcome-mismatch"


def test_container_blocked_and_failed_results_are_passed_through_unchanged(
    sandbox: FakeSandbox,
) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            raw = b"raw-blocked"
            document = _container_evidence(
                scenario,
                status="blocked",
                observed_outcome=None,
                detail_code="linux-required",
                raw=raw,
            )
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                canonical_json(document), encoding="utf-8"
            )
            (workspace / f"{scenario.scenario_id}.raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    for run in runs:
        assert run.observation.status == "blocked"
        assert run.observation.detail_code == "linux-required"
        assert run.observation.observed_outcome is None


# -- provenance and retention ------------------------------------------------


def test_retained_raw_evidence_binds_the_container_record_and_sandbox_receipt(
    sandbox: FakeSandbox,
) -> None:
    sandbox.writer = _write_all_passing
    runs = _driver().run_catalog()

    for run in runs:
        envelope = json.loads(run.raw_evidence.decode("utf-8"))
        assert envelope["schema"] == "daedalus-linux-container-fault-driver/1"
        assert envelope["scenario_id"] == run.observation.scenario_id
        assert envelope["source_revision"] == REVISION
        assert envelope["image"] == driver_module.DEFAULT_IMAGE
        assert envelope["sandbox_receipt"]["launch_state"] == "completed"
        assert envelope["container"]["evidence"]["status"] == "passed"
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["driver-image"] == driver_module.DEFAULT_IMAGE
        assert facts["sandbox-launch-state"] == "completed"


def test_executor_identity_differs_per_locator_and_binds_the_script(
    sandbox: FakeSandbox,
) -> None:
    driver = _driver()
    bindings = driver.bindings()
    assert set(bindings) == {row.executor for row in LINUX_SCENARIOS}
    for locator, binding in bindings.items():
        assert binding.locator == locator
        assert len(binding.implementation_sha256) == 64
    # Two locators share one script but remain distinct executor identities.
    assert (
        bindings["host-fixture:runtime-process-timeout"].implementation_sha256
        != bindings["host-fixture:runtime-process-tree-kill"].implementation_sha256
    )


def test_bare_evidence_filenames_are_discovered(sandbox: FakeSandbox) -> None:
    """Single-scenario executors write ``evidence.json``, not a prefixed name."""

    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        script = command[3].removeprefix("/repo/")
        owned = [
            row for row in LINUX_SCENARIOS if EXECUTOR_SCRIPTS[row.executor] == script
        ]
        if len(owned) != 1:
            # The process executor owns two scenarios and keeps its prefixes.
            _write_all_passing(workspace, command)
            return
        scenario = owned[0]
        raw = b"raw-bare"
        document = _container_evidence(
            scenario,
            status="passed",
            observed_outcome=scenario.expected_outcome,
            detail_code=None,
            raw=raw,
        )
        (workspace / "evidence.json").write_text(
            canonical_json(document), encoding="utf-8"
        )
        (workspace / "raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert len(runs) == 9
    assert {run.observation.status for run in runs} == {"passed"}


def test_a_prefixed_filename_must_agree_with_the_declared_scenario(
    sandbox: FakeSandbox,
) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            raw = b"raw-mislabelled"
            document = _container_evidence(
                scenario,
                status="passed",
                observed_outcome=scenario.expected_outcome,
                detail_code=None,
                raw=raw,
                scenario_id="runtime.some.other",
            )
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                canonical_json(document), encoding="utf-8"
            )
            (workspace / f"{scenario.scenario_id}.raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["exception-type"] == "ContainerFaultScenarioDrift"


def test_two_documents_for_one_scenario_are_refused(sandbox: FakeSandbox) -> None:
    def writer(workspace: Path, command: tuple[str, ...]) -> None:
        for scenario in LINUX_SCENARIOS:
            if EXECUTOR_SCRIPTS[scenario.executor] != command[3].removeprefix("/repo/"):
                continue
            raw = b"raw-duplicate"
            document = _container_evidence(
                scenario,
                status="passed",
                observed_outcome=scenario.expected_outcome,
                detail_code=None,
                raw=raw,
            )
            payload = canonical_json(document)
            # The same scenario declared by both a bare and a prefixed file.
            (workspace / "evidence.json").write_text(payload, encoding="utf-8")
            (workspace / f"{scenario.scenario_id}.evidence.json").write_text(
                payload, encoding="utf-8"
            )
            (workspace / "raw").write_bytes(raw)

    sandbox.writer = writer
    runs = _driver().run_catalog()

    assert {run.observation.status for run in runs} == {"failed"}
    for run in runs:
        facts = {fact.name: fact.value for fact in run.evidence.facts}
        assert facts["exception-type"] == "ContainerFaultScenarioDrift"


def test_driver_refuses_a_root_that_is_not_a_daedalus_checkout(tmp_path: Path) -> None:
    with pytest.raises(ContainerFaultDriverError, match="Daedalus checkout"):
        ContainerFaultDriver(repo_root=tmp_path, source_revision=REVISION)


def test_every_mapped_executor_script_exists_in_the_repository() -> None:
    for locator, relative in EXECUTOR_SCRIPTS.items():
        assert (REPO_ROOT / relative).is_file(), f"{locator} -> {relative}"


def test_the_map_covers_the_canonical_catalog_exactly() -> None:
    locators = {row.executor for row in LINUX_SCENARIOS}
    assert set(EXECUTOR_SCRIPTS) == locators
    assert len(LINUX_SCENARIOS) == 9


def test_the_default_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in driver_module.DEFAULT_IMAGE
    assert "latest" not in driver_module.DEFAULT_IMAGE


def test_publish_writes_bounded_artifacts_and_claims_no_trust(
    sandbox: FakeSandbox, tmp_path: Path
) -> None:
    sandbox.writer = _write_all_passing
    summary = driver_module.publish_container_faults(
        repo_root=REPO_ROOT,
        source_revision=REVISION,
        output_dir=tmp_path / "out",
    )

    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    assert summary["passed"] == 9
    assert len(summary["runs"]) == 9
    for row in summary["runs"]:
        assert (tmp_path / "out" / f"{row['scenario_id']}.evidence.json").is_file()
        assert (tmp_path / "out" / f"{row['scenario_id']}.observation.json").is_file()
        assert (tmp_path / "out" / f"{row['scenario_id']}.raw").is_file()
    assert (tmp_path / "out" / "summary.json").is_file()
