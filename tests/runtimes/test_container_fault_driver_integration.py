# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""One real container run of a canonical Linux-host fault scenario.

Everything else about the driver is covered with a mocked sandbox in
``test_container_fault_driver.py``. This module is the single place where a
container is genuinely started, so it is marked ``docker`` and skips with an
explicit reason whenever a Linux-engine daemon is not reachable. A skip is
never a pass: the canonical matrix still counts an unobserved scenario as a
blocker.

The scenario chosen here is the effect-ledger lock contention, which needs only
SQLite and a Linux kernel -- no nested container runtime -- so it is the
cheapest honest proof that the repository really executes inside the container.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from daedalus.runtimes.container_fault_driver import ContainerFaultDriver
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import run_linux_host_fault

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_ID = "runtime.effect-ledger.lock-contention"
REVISION = "0" * 40


def _docker_unavailable_reason() -> str | None:
    """Return an honest reason to skip, or None when a Linux engine is ready."""

    if shutil.which("docker") is None:
        return "docker CLI is not on PATH"
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"docker daemon is not reachable: {type(exc).__name__}"
    if proc.returncode != 0:
        return f"docker daemon is not reachable (exit {proc.returncode})"
    ostype = proc.stdout.strip()
    if ostype != "linux":
        return f"docker engine is {ostype!r}, the fault catalog needs a Linux engine"
    return None


SKIP_REASON = _docker_unavailable_reason()

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(SKIP_REASON is not None, reason=str(SKIP_REASON)),
]


def test_a_real_container_produces_canonical_linux_host_evidence() -> None:
    scenario = next(
        row for row in RUNTIME_FAULT_CATALOG.scenarios if row.scenario_id == SCENARIO_ID
    )
    driver = ContainerFaultDriver(
        repo_root=REPO_ROOT, source_revision=REVISION, timeout_s=600
    )
    run = run_linux_host_fault(
        scenario,
        source_revision=REVISION,
        executor=driver.binding(scenario.executor),
    )

    # The collector artifact must be complete and self-consistent regardless of
    # whether the fault itself reproduced on this host.
    assert run.evidence.schema == "daedalus-linux-host-fault-evidence/1"
    assert run.evidence.scenario_id == SCENARIO_ID
    assert run.evidence.scenario_sha256 == scenario.digest
    assert run.evidence.source_revision == REVISION
    assert run.evidence.executor == scenario.executor
    assert run.observation.authority == "linux-host"
    assert run.observation.evidence_sha256 == run.evidence.digest
    assert run.evidence.status in {"passed", "failed", "blocked"}

    # A pass is only ever a pass when the observed outcome is the declared one;
    # the collector downgrades anything else, so this must hold by construction.
    if run.evidence.status == "passed":
        assert run.observation.observed_outcome == scenario.expected_outcome
        assert run.evidence.detail_code is None
    else:
        assert run.evidence.detail_code, "a non-pass must carry a detail code"

    facts = {fact.name: fact.value for fact in run.evidence.facts}
    assert facts["sandbox-launch-state"] in {
        "completed",
        "timed-out",
        "refused-before-start",
    }
    assert facts["driver-executor-script"].endswith(
        "effect_ledger_contention_fault_executor.py"
    )


def test_the_container_actually_reaches_a_linux_kernel() -> None:
    """The repository must be importable and the platform must be Linux inside."""

    scenario = next(
        row for row in RUNTIME_FAULT_CATALOG.scenarios if row.scenario_id == SCENARIO_ID
    )
    driver = ContainerFaultDriver(
        repo_root=REPO_ROOT, source_revision=REVISION, timeout_s=600
    )
    run = run_linux_host_fault(
        scenario,
        source_revision=REVISION,
        executor=driver.binding(scenario.executor),
    )
    facts = {fact.name: fact.value for fact in run.evidence.facts}

    # If the executor had refused because it was not on Linux, the container
    # never reached a Linux kernel and this driver would be pointless.
    assert facts.get("container-detail-code") != "linux-required"
