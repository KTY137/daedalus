"""Run the canonical Linux-host fault scenarios inside a Docker Linux container.

The catalog in :mod:`daedalus.runtimes.fault_matrix` declares nine ``linux-host``
scenarios and names the exact fixture executor for each. The collector seam in
:mod:`daedalus.runtimes.host_fault_runner` turns one executor result into
canonical ``daedalus-linux-host-fault-evidence/1``. What has been missing is the
driver in between: something that can actually reach a Linux kernel from a
non-Linux workstation.

This module is that driver and nothing more. It does not invoke Docker itself;
it goes through :func:`daedalus.kernel.sandbox.run_in_docker_sandbox`, so the
container inherits the canonical bounded-effect policy -- read-only root
filesystem, no network, dropped capabilities, non-root user, pinned image, and
one writable workspace. The repository is mounted read-only; the only writable
surface is the workspace the executor reports into.

Fail-closed is preserved end to end and this module never upgrades a result:

* an unreachable Docker CLI, a pre-start refusal, or a timeout becomes an
  explicit ``blocked`` observation carrying the refusal reason;
* an executor that returns nothing, malformed evidence, or evidence bound to a
  different scenario, revision, or executor raises, and the collector records a
  ``failed`` observation;
* a ``passed`` container result is passed through verbatim, leaving the
  collector's own expected-outcome comparison as the deciding check.

A produced observation is still only a retained record. The attestation
boundary in :mod:`daedalus.runtimes.fault_attestations` must independently
authenticate it before it may enter a trusted digest set, and this driver
deliberately holds no signing key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.kernel.sandbox import (
    DockerSandboxPolicy,
    SandboxExecutionReceipt,
    SandboxMount,
    run_in_docker_sandbox,
)
from daedalus.runtimes.fault_matrix import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultCatalog,
    RuntimeFaultScenario,
)
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault_catalog,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-linux-container-fault-driver/1"

# python:3.10-slim pinned by digest. DockerSandboxPolicy refuses any image that
# is unpinned or tagged "latest", so this constant is the only supported image.
DEFAULT_IMAGE = (
    "python:3.10-slim@sha256:"
    "a78e4529630cfe8c5199cafd6e0c28ee1579a13f86274396d8b6b2d80367aa3a"
)

_REPO_MOUNT = "/repo"
_WORKSPACE = "/workspace"
_DEFAULT_TIMEOUT_S = 900
_MAX_RAW_EVIDENCE_BYTES = 1024 * 1024
_MAX_EVIDENCE_FILE_BYTES = 256 * 1024

# Each canonical linux-host locator and the fixture executor that owns it.
# linux_process_fault_executor.py owns two locators and emits both in one run.
EXECUTOR_SCRIPTS: Mapping[str, str] = {
    "host-fixture:runtime-trust-lock-contention": (
        "tests/fixtures/runtime_trust_contention_fault_executor.py"
    ),
    "host-fixture:runtime-effect-lock-contention": (
        "tests/fixtures/effect_ledger_contention_fault_executor.py"
    ),
    "host-fixture:runtime-process-timeout": (
        "tests/fixtures/linux_process_fault_executor.py"
    ),
    "host-fixture:runtime-process-tree-kill": (
        "tests/fixtures/linux_process_fault_executor.py"
    ),
    "host-fixture:runtime-container-oom": (
        "tests/fixtures/container_oom_fault_executor.py"
    ),
    "host-fixture:runtime-sandbox-unavailable": (
        "tests/fixtures/sandbox_unavailable_fault_executor.py"
    ),
    "host-fixture:runtime-unauthorized-egress": (
        "tests/fixtures/unauthorized_egress_fault_executor.py"
    ),
    "host-fixture:runtime-secret-isolation": (
        "tests/fixtures/undeclared_secret_fault_executor.py"
    ),
    "host-fixture:runtime-unknown-outcome-reconciliation": (
        "tests/fixtures/unknown_outcome_reconciliation_fault_executor.py"
    ),
}

# Runs one repository fixture executor inside the container. The repository is
# mounted read-only at /repo and is not the working directory, so the package
# root is placed on sys.path explicitly. PYTHONPATH is exported as well because
# some executors re-exec themselves as a child process.
_LAUNCH_SOURCE = (
    "import os, runpy, sys\n"
    "script, revision, out = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "os.environ['PYTHONPATH'] = '/repo'\n"
    "sys.path.insert(0, '/repo')\n"
    "sys.argv = [script, '--source-revision', revision, '--output-dir', out]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)

# Docker CLI and sandbox refusal reasons, mapped to stable blocked detail codes.
_REFUSAL_DETAIL_CODES: Mapping[str, str] = {
    "runtime-not-found": "docker-cli-unavailable",
    "runtime-not-executable": "docker-cli-not-executable",
    "runtime-launch-error": "docker-launch-error",
    "docker-cli-refused": "docker-cli-refused",
    "timeout": "sandbox-timeout",
}


class ContainerFaultDriverError(RuntimeError):
    """Base class for container-driver failures."""


class ContainerFaultEvidenceMissing(ContainerFaultDriverError):
    """The container produced no evidence document for a declared scenario."""


class ContainerFaultEvidenceMalformed(ContainerFaultDriverError):
    """The container evidence document is unreadable or oversized."""


class ContainerFaultScenarioDrift(ContainerFaultDriverError):
    """Container evidence is bound to a different scenario, revision, or executor."""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContainerFaultEvidenceMalformed(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ContainerFaultEvidenceMalformed(f"non-finite JSON constant: {value}")


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ContainerFaultEvidenceMissing(f"{label} was not produced")
    raw = path.read_bytes()
    if len(raw) > _MAX_EVIDENCE_FILE_BYTES:
        raise ContainerFaultEvidenceMalformed(f"{label} exceeds the bounded size")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ContainerFaultEvidenceMalformed(f"{label} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ContainerFaultEvidenceMalformed(f"{label} is malformed JSON") from exc
    if not isinstance(payload, dict):
        raise ContainerFaultEvidenceMalformed(f"{label} root must be an object")
    return payload


def _collect_workspace_evidence(
    workspace: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, bytes]]:
    """Read whichever artifact layout the invoked fixture executor produced.

    An executor that owns a single scenario writes bare ``evidence.json`` and
    ``raw``; the process executor owns two scenarios and prefixes both with the
    scenario id. Documents are keyed by the scenario id they declare, and a
    prefixed filename must agree with that declaration -- a file that claims to
    be one scenario while containing another is drift, not a naming detail.
    """

    evidence: dict[str, Mapping[str, Any]] = {}
    raw_evidence: dict[str, bytes] = {}
    for path in sorted(workspace.glob("*evidence.json")):
        if path.name == "evidence.json":
            prefix, raw_name = None, "raw"
        elif path.name.endswith(".evidence.json"):
            prefix = path.name[: -len(".evidence.json")]
            raw_name = f"{prefix}.raw"
        else:
            continue
        document = _read_json_object(path, f"{path.name} evidence")
        declared = document.get("scenario_id")
        if not isinstance(declared, str) or not declared:
            raise ContainerFaultEvidenceMalformed(
                f"{path.name} declares no scenario_id"
            )
        if prefix is not None and prefix != declared:
            raise ContainerFaultScenarioDrift(
                f"{path.name} is named for {prefix} but declares {declared}"
            )
        if declared in evidence:
            raise ContainerFaultScenarioDrift(
                f"container produced two evidence documents for {declared}"
            )
        evidence[declared] = document
        raw_path = workspace / raw_name
        if raw_path.is_file():
            raw_evidence[declared] = raw_path.read_bytes()
    return evidence, raw_evidence


@dataclass(frozen=True)
class ContainerScriptRun:
    """One container invocation of one fixture executor."""

    script: str
    script_sha256: str
    receipt: SandboxExecutionReceipt
    evidence: Mapping[str, Mapping[str, Any]]
    raw_evidence: Mapping[str, bytes]


def _blocked_result(
    *,
    detail_code: str,
    envelope: Mapping[str, Any],
    facts: Sequence[HostFaultFact],
) -> HostFaultResult:
    return HostFaultResult(
        status="blocked",
        observed_outcome=None,
        detail_code=detail_code,
        raw_evidence=canonical_json(dict(envelope)).encode("utf-8"),
        facts=tuple(facts),
    )


class ContainerFaultDriver:
    """Execute linux-host catalog scenarios through the canonical sandbox path."""

    def __init__(
        self,
        *,
        repo_root: Path,
        source_revision: str,
        image: str = DEFAULT_IMAGE,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG,
    ) -> None:
        root = Path(repo_root).resolve()
        if not (root / "daedalus").is_dir() or not (root / "tests").is_dir():
            raise ContainerFaultDriverError(
                "repo_root must be a Daedalus checkout containing daedalus/ and tests/"
            )
        self.repo_root = root
        self.source_revision = source_revision
        self.image = image
        self.timeout_s = timeout_s
        self.catalog = catalog
        self._runs: dict[str, ContainerScriptRun] = {}

    # -- container execution -------------------------------------------------

    def _script_path(self, locator: str) -> Path:
        relative = EXECUTOR_SCRIPTS.get(locator)
        if relative is None:
            raise ContainerFaultDriverError(f"no executor script for locator {locator}")
        path = self.repo_root / relative
        if not path.is_file():
            raise ContainerFaultDriverError(f"executor script is missing: {relative}")
        return path

    def _run_script(self, relative: str) -> ContainerScriptRun:
        cached = self._runs.get(relative)
        if cached is not None:
            return cached

        script = self.repo_root / relative
        workspace = Path(tempfile.mkdtemp(prefix="daedalus-container-fault-"))
        policy = DockerSandboxPolicy(
            image=self.image,
            candidate_workspace=workspace,
            reference_mounts=(SandboxMount(self.repo_root, _REPO_MOUNT, True),),
            network="none",
            timeout_s=self.timeout_s,
        )
        receipt = run_in_docker_sandbox(
            policy,
            (
                "python",
                "-c",
                _LAUNCH_SOURCE,
                f"{_REPO_MOUNT}/{relative}",
                self.source_revision,
                _WORKSPACE,
            ),
        )
        evidence: dict[str, Mapping[str, Any]] = {}
        raw_evidence: dict[str, bytes] = {}
        if receipt.launch_state == "completed":
            evidence, raw_evidence = _collect_workspace_evidence(workspace)
        run = ContainerScriptRun(
            script=relative,
            script_sha256=_file_sha256(script),
            receipt=receipt,
            evidence=evidence,
            raw_evidence=raw_evidence,
        )
        self._runs[relative] = run
        shutil.rmtree(workspace, ignore_errors=True)
        return run

    # -- collector-facing executor ------------------------------------------

    def _execute(self, scenario: RuntimeFaultScenario) -> HostFaultResult:
        relative = EXECUTOR_SCRIPTS[scenario.executor]
        run = self._run_script(relative)
        base_facts = [
            HostFaultFact("driver-image", self.image),
            HostFaultFact("driver-executor-script", relative),
            HostFaultFact("driver-executor-script-sha256", run.script_sha256),
            HostFaultFact("sandbox-launch-state", run.receipt.launch_state),
            HostFaultFact("sandbox-argv-sha256", run.receipt.argv_sha256),
        ]
        envelope: dict[str, Any] = {
            "schema": _SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "source_revision": self.source_revision,
            "image": self.image,
            "executor_script": relative,
            "executor_script_sha256": run.script_sha256,
            "sandbox_receipt": run.receipt.to_dict(),
        }

        if run.receipt.launch_state != "completed":
            detail = _REFUSAL_DETAIL_CODES.get(
                run.receipt.error_code or "", "sandbox-refused-before-start"
            )
            envelope["container"] = None
            envelope["refusal"] = {
                "launch_state": run.receipt.launch_state,
                "error_code": run.receipt.error_code,
            }
            return _blocked_result(
                detail_code=detail,
                envelope=envelope,
                facts=[
                    *base_facts,
                    HostFaultFact(
                        "sandbox-error-code", run.receipt.error_code or "unspecified"
                    ),
                ],
            )

        document = run.evidence.get(scenario.scenario_id)
        if document is None:
            raise ContainerFaultEvidenceMissing(
                f"container produced no evidence for {scenario.scenario_id}"
            )

        self._assert_binding(scenario, document)

        raw = run.raw_evidence.get(scenario.scenario_id)
        if raw is None:
            raise ContainerFaultEvidenceMissing(
                f"container retained no raw evidence for {scenario.scenario_id}"
            )
        declared = document.get("raw_evidence_sha256")
        if hashlib.sha256(raw).hexdigest() != declared:
            raise ContainerFaultScenarioDrift(
                f"container raw evidence does not match its own digest for "
                f"{scenario.scenario_id}"
            )

        status = document.get("status")
        observed_outcome = document.get("observed_outcome")
        detail_code = document.get("detail_code")
        envelope["container"] = {
            "evidence": dict(document),
            "raw_sha256": declared,
        }
        payload = canonical_json(envelope).encode("utf-8")
        if len(payload) > _MAX_RAW_EVIDENCE_BYTES:
            envelope["container"] = {"evidence_sha256": canonical_sha(dict(document))}
            envelope["truncated"] = True
            payload = canonical_json(envelope).encode("utf-8")

        facts = [
            *base_facts,
            HostFaultFact("container-status", str(status)),
            HostFaultFact("container-evidence-sha256", canonical_sha(dict(document))),
            HostFaultFact("container-raw-sha256", str(declared)),
        ]
        if detail_code:
            facts.append(HostFaultFact("container-detail-code", str(detail_code)))

        return HostFaultResult(
            status=str(status),
            observed_outcome=observed_outcome,
            detail_code=detail_code,
            raw_evidence=payload,
            facts=tuple(facts),
        )

    def _assert_binding(
        self, scenario: RuntimeFaultScenario, document: Mapping[str, Any]
    ) -> None:
        expected = {
            "scenario_id": (document.get("scenario_id"), scenario.scenario_id),
            "scenario_sha256": (document.get("scenario_sha256"), scenario.digest),
            "source_revision": (
                document.get("source_revision"),
                self.source_revision,
            ),
            "executor": (document.get("executor"), scenario.executor),
        }
        mismatches = sorted(
            name for name, (actual, wanted) in expected.items() if actual != wanted
        )
        if mismatches:
            raise ContainerFaultScenarioDrift(
                "container evidence binding mismatch: " + ", ".join(mismatches)
            )

    # -- public surface ------------------------------------------------------

    def binding(self, locator: str) -> LinuxHostExecutorBinding:
        script = self._script_path(locator)
        return LinuxHostExecutorBinding(
            locator=locator,
            implementation_sha256=canonical_sha(
                {
                    "schema": _SCHEMA,
                    "locator": locator,
                    "image": self.image,
                    "executor_script": EXECUTOR_SCRIPTS[locator],
                    "executor_script_sha256": _file_sha256(script),
                    "launch_source_sha256": hashlib.sha256(
                        _LAUNCH_SOURCE.encode("utf-8")
                    ).hexdigest(),
                }
            ),
            execute=self._execute,
        )

    def bindings(self) -> dict[str, LinuxHostExecutorBinding]:
        locators = {
            row.executor
            for row in self.catalog.scenarios
            if row.authority == "linux-host"
        }
        return {locator: self.binding(locator) for locator in sorted(locators)}

    def run_catalog(self) -> tuple[LinuxHostFaultRun, ...]:
        return run_linux_host_fault_catalog(
            catalog=self.catalog,
            source_revision=self.source_revision,
            executors=self.bindings(),
        )


def docker_cli_available() -> bool:
    """Report whether a Docker CLI is on PATH. Absence is never a pass."""

    return shutil.which("docker") is not None


def _atomic_write(path: Path, payload: bytes) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def publish_container_faults(
    *,
    repo_root: Path,
    source_revision: str,
    output_dir: Path,
    image: str = DEFAULT_IMAGE,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run every linux-host scenario in a container and retain the artifacts."""

    if output_dir.is_symlink():
        raise ContainerFaultDriverError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    driver = ContainerFaultDriver(
        repo_root=repo_root,
        source_revision=source_revision,
        image=image,
        timeout_s=timeout_s,
    )
    runs = driver.run_catalog()
    rows = []
    for run in runs:
        prefix = run.observation.scenario_id
        _atomic_write(
            output_dir / f"{prefix}.evidence.json",
            (canonical_json(run.evidence.to_dict()) + "\n").encode("utf-8"),
        )
        _atomic_write(
            output_dir / f"{prefix}.observation.json",
            (canonical_json(run.observation.to_dict()) + "\n").encode("utf-8"),
        )
        _atomic_write(output_dir / f"{prefix}.raw", run.raw_evidence)
        rows.append(
            {
                "scenario_id": run.observation.scenario_id,
                "status": run.observation.status,
                "observed_outcome": run.observation.observed_outcome,
                "detail_code": run.observation.detail_code,
                "evidence_sha256": run.evidence.digest,
                "observation_sha256": run.observation.digest,
                "run_sha256": run.digest,
            }
        )
    summary = {
        "schema": _SCHEMA,
        "source_revision": source_revision,
        "image": image,
        "catalog_sha256": driver.catalog.digest,
        "runs": rows,
        "passed": sum(1 for row in rows if row["status"] == "passed"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "blocked": sum(1 for row in rows if row["status"] == "blocked"),
        # This driver holds no signing key: observations are retained records
        # until the separate attestation boundary authenticates them.
        "trusted": False,
        "attested": False,
        "gate_closure_claimed": False,
    }
    _atomic_write(
        output_dir / "summary.json",
        (canonical_json(summary) + "\n").encode("utf-8"),
    )
    return summary


def containment_boundary_decision():
    """Run the ``containment.attempt`` contract for this driver's spawn path.

    The driver never invokes docker itself: every scenario spawn goes through
    :func:`daedalus.kernel.sandbox.run_in_docker_sandbox`, which is where the
    bounded-effect policy (read-only root, ``network=none``, dropped caps,
    ``timeout_s``) actually lives.  That indirection is the whole containment
    story for this row, and the static scanner cannot see across the module
    edge to check it.

    So this decision resolves the binding at the boundary instead of asserting
    it: if the containment symbol this module will call no longer comes from
    ``daedalus.kernel.sandbox``, the decision is negative and the start is
    refused rather than proceeding as a raw docker spawn.
    """
    from daedalus.spine.effect_boundary import GuardDecision

    module = getattr(run_in_docker_sandbox, "__module__", "") or "<unknown>"
    qualname = getattr(run_in_docker_sandbox, "__qualname__", "<unknown>")
    bound = module == "daedalus.kernel.sandbox"
    if bound:
        evidence = (
            f"scenario spawns bound to {module}.{qualname}: read-only root, "
            "network=none, dropped caps and timeout_s are enforced there"
        )
    else:
        evidence = (
            f"containment call resolved to {module}.{qualname}, not "
            "daedalus.kernel.sandbox: refusing to start an unbounded spawn"
        )
    return GuardDecision("containment.attempt", bound, evidence)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run canonical linux-host fault scenarios in a Docker container.",
    )
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--timeout-s", type=int, default=_DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    # Canonical Gate-0 effect start. Two real contracts run here: the spend net
    # is installed before the first container spawn, and the containment
    # decision resolves that the spawn path is still the bounded sandbox.
    # Docker *availability* is deliberately not part of the decision -- a host
    # without docker must still record every scenario as blocked and retain
    # that evidence, so refusing the start there would destroy the honest
    # blocked column rather than protect anything.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "runtimes.container_fault_driver",
        REGISTRY_BY_ID["runtimes.container_fault_driver"].effects,
        (process_guard_boundary_decision(), containment_boundary_decision()),
    )

    if not docker_cli_available():
        print(
            "docker CLI is unavailable; every scenario will be recorded as blocked",
            file=sys.stderr,
        )
    summary = publish_container_faults(
        repo_root=args.repo_root,
        source_revision=args.source_revision,
        output_dir=args.output_dir,
        image=args.image,
        timeout_s=args.timeout_s,
    )
    print(canonical_json(summary))
    return 0 if summary["failed"] == 0 and summary["blocked"] == 0 else 1


__all__ = [
    "DEFAULT_IMAGE",
    "EXECUTOR_SCRIPTS",
    "ContainerFaultDriver",
    "ContainerFaultDriverError",
    "ContainerFaultEvidenceMalformed",
    "ContainerFaultEvidenceMissing",
    "ContainerFaultScenarioDrift",
    "ContainerScriptRun",
    "containment_boundary_decision",
    "docker_cli_available",
    "publish_container_faults",
]


if __name__ == "__main__":
    raise SystemExit(main())
