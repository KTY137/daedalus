#!/usr/bin/env python3
"""Run bounded local verification profiles for the active G0-to-G1 stack.

``g0`` and ``g1`` remain quick compatibility profiles.  ``g0-chain`` (also
available as ``g0-chain-receipt``) is the broader, receipt-producing local
profile.  Its receipt is regression evidence for one observed working tree; it
does not claim that Gate 0 is closed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from daedalus.spine.envelope import canonical_sha
from daedalus.spine.source_state import SourceFingerprint, fingerprint_source


RECEIPT_ROOT = ROOT / "runs" / "spine" / "g0-chain"
RECEIPT_SCHEMA = "daedalus.g0-chain-receipt/v1"
DIRTY_MANIFEST_SCHEMA = "daedalus.dirty-manifest/v1"
HASH_SEEDS = ("0", "123456")
PLAN_TIMEOUT_S = 180
PYTEST_TIMEOUT_S = 3600

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INCOMPLETE = 2

G0_TESTS = (
    "tests/kernel/test_artifact_identity.py",
    "tests/kernel/test_owner_approval.py",
    "tests/kernel/test_sealed_promotion.py",
    "tests/kernel/test_runtime_conformance_harness.py",
    "tests/kernel/test_docker_sandbox_policy.py",
    "tests/kernel/test_fourfold_evidence.py",
    "tests/kernel/test_fourfold_approval_integration.py",
    "tests/gates/test_gate_report.py",
    "tests/test_effect_boundary.py",
)

G1_TESTS = (
    "tests/ignition/test_voltage_ignition.py",
    "tests/kernel/test_fourfold_evidence.py",
    "tests/kernel/test_fourfold_approval_integration.py",
    "tests/kernel/test_owner_approval.py",
    "tests/twin/test_wiki_reference.py",
    "tests/twin/test_reference_hardening.py",
)

# One fixed, broad selection.  These modules exercise the currently available
# source -> plan -> routing -> lease -> attempt -> Fourfold evidence -> sealed
# authorization seams.  They do not yet constitute one production end-to-end
# chain, which is why the receipt explicitly refuses a Gate-closure claim.
G0_CHAIN_TESTS = (
    "tests/chains/test_source_state.py",
    "tests/kernel/test_artifact_identity.py",
    "tests/kernel/test_offload_execution_plan.py",
    "tests/kernel/test_offload_authority.py",
    "tests/test_effect_free_routing.py",
    "tests/test_frozen_provider_routing.py",
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
)

PROFILES = {
    "g0": G0_TESTS,
    "g1": G1_TESTS,
    "consolidated": tuple(dict.fromkeys((*G0_TESTS, *G1_TESTS))),
    "g0-chain": G0_CHAIN_TESTS,
    "g0-chain-receipt": G0_CHAIN_TESTS,
}

CHAIN_PROFILES = frozenset({"g0-chain", "g0-chain-receipt"})


def _run(argv: list[str]) -> None:
    """Compatibility runner used by the pre-existing smoke profiles."""

    completed = subprocess.run(argv, cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_output_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return os.fspath(path.resolve())


def _file_record(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return {
        "path": _display_output_path(path),
        "size": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _python_environment_record() -> dict[str, object]:
    """Freeze the interpreter bytes and installed distribution set.

    Gate receipts must distinguish an isolated bench from an ambient user
    interpreter even when both report the same Python version.  Package
    metadata is read in-process; this observation performs no provider or
    network probe and starts no additional process.
    """

    packages = sorted(
        (
            {
                "name": str(distribution.metadata.get("Name") or "").strip(),
                "version": str(distribution.version),
            }
            for distribution in importlib.metadata.distributions()
        ),
        key=lambda item: (item["name"].casefold(), item["version"]),
    )
    package_body: dict[str, object] = {
        "schema": "daedalus.python-environment/v1",
        "packages": packages,
    }
    package_body["sha256"] = canonical_sha(package_body)
    executable = Path(sys.executable).resolve()
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": os.fspath(executable),
        "executable_identity": _file_record(executable),
        "prefix": os.fspath(Path(sys.prefix).resolve()),
        "environment": package_body,
    }


def _open_new_binary(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    return os.fdopen(fd, "wb")


def _write_new_json(path: Path, payload: dict[str, object]) -> str:
    raw = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    with _open_new_binary(path) as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest()


def _status_records(raw: bytes) -> tuple[tuple[str, bytes], ...]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("source status is not a complete porcelain-v1-z record")
    records: list[tuple[str, bytes]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("source status contains an invalid porcelain-v1-z record")
        records.append((record[:2].decode("ascii", "replace"), record[3:]))
    return tuple(records)


def dirty_manifest(source: SourceFingerprint) -> dict[str, object]:
    """Project the canonical source observation into a reviewable dirty list."""

    untracked = {item.path_bytes: item.to_dict() for item in source.untracked_files}
    entries: list[dict[str, object]] = []
    for status_code, raw_path in _status_records(source.status_porcelain_v1_z):
        entries.append(
            {
                "status": status_code,
                "path_b64": base64.b64encode(raw_path).decode("ascii"),
                "path_display": raw_path.decode("utf-8", "backslashreplace"),
                "untracked_identity": untracked.get(raw_path),
            }
        )
    body: dict[str, object] = {
        "schema": DIRTY_MANIFEST_SCHEMA,
        "source_fingerprint_sha256": source.fingerprint_sha256,
        "status_sha256": source.status_sha256,
        "tracked_index_sha256": source.tracked_index_sha256,
        "tracked_tree_sha256": source.tracked_tree_sha256,
        "untracked_tree_sha256": source.untracked_tree_sha256,
        "entries": entries,
    }
    body["sha256"] = canonical_sha(body)
    return body


def _run_logged(
    argv: Sequence[str],
    output_path: Path,
    env: dict[str, str] | None,
    timeout_s: int,
) -> tuple[int, bool]:
    """Run one fixed argv directly, with no shell and no argument interpolation."""

    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    timed_out = False
    returncode = 127
    with _open_new_binary(output_path) as output:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=full_env,
                timeout=timeout_s,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = 124
            output.write(f"\nTIMEOUT after {timeout_s}s\n".encode("ascii"))
        except OSError as exc:
            output.write(
                f"\nEXECUTION ERROR: {type(exc).__name__}: {exc}\n".encode(
                    "utf-8", "backslashreplace"
                )
            )
        output.flush()
        os.fsync(output.fileno())
    return returncode, timed_out


def _pytest_counts(junit_path: Path, output_path: Path) -> dict[str, object] | None:
    if not junit_path.is_file():
        return None
    try:
        tree = ET.parse(junit_path)
    except (ET.ParseError, OSError):
        return None
    cases = list(tree.getroot().iter("testcase"))
    failures = errors = skipped_total = xfailed = 0
    for case in cases:
        failures += int(case.find("failure") is not None)
        errors += int(case.find("error") is not None)
        skipped = case.find("skipped")
        if skipped is not None:
            skipped_total += 1
            kind = (skipped.get("type") or "").casefold()
            message = (skipped.get("message") or "").casefold()
            if "xfail" in kind or "xfail" in message:
                xfailed += 1
    try:
        terminal = output_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        terminal = ""
    matches = re.findall(r"(?<!\d)(\d+)\s+xpassed\b", terminal, flags=re.IGNORECASE)
    xpassed = int(matches[-1]) if matches else 0
    passed_including_xpass = len(cases) - failures - errors - skipped_total
    return {
        "tests": len(cases),
        "passed": max(0, passed_including_xpass - xpassed),
        "failed": failures,
        "errors": errors,
        "skipped": max(0, skipped_total - xfailed),
        "xfailed": xfailed,
        "xpassed": xpassed,
    }


def _bounded_receipt_path(requested: Path | None, run_id: str) -> Path:
    root = RECEIPT_ROOT.resolve()
    candidate = requested if requested is not None else root / f"{run_id}.json"
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"receipt must stay under {root}") from exc
    if resolved.suffix.casefold() != ".json":
        raise ValueError("receipt path must end in .json")
    if resolved.exists():
        raise ValueError(f"receipt already exists: {resolved}")
    return resolved


def _source_capture(
    capture: Callable[[], SourceFingerprint],
) -> tuple[SourceFingerprint | None, dict[str, object] | None, str | None]:
    try:
        source = capture()
        return source, source.to_dict(), None
    except Exception as exc:  # receipt the unavailable observation, then fail closed
        return None, None, f"{type(exc).__name__}: {exc}"


def _run_record(
    *,
    seed: str,
    artifacts: Path,
    command_runner: Callable[
        [Sequence[str], Path, dict[str, str] | None, int], tuple[int, bool]
    ],
) -> dict[str, object]:
    output_path = artifacts / f"pytest-seed-{seed}.log"
    junit_path = artifacts / f"pytest-seed-{seed}.xml"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rA",
        f"--junitxml={junit_path}",
        *G0_CHAIN_TESTS,
    ]
    started = _utc_now()
    clock = time.perf_counter()
    returncode, timed_out = command_runner(
        argv, output_path, {"PYTHONHASHSEED": seed}, PYTEST_TIMEOUT_S
    )
    finished = _utc_now()
    counts = _pytest_counts(junit_path, output_path)
    nonpass = None
    if counts is not None:
        nonpass = sum(int(counts[name]) for name in ("skipped", "xfailed", "xpassed"))
    if returncode != 0:
        outcome = "FAIL"
    elif counts is None or not counts["tests"] or nonpass:
        outcome = "INCOMPLETE"
    else:
        outcome = "PASS"
    return {
        "seed": seed,
        "argv": argv,
        "environment": {"PYTHONHASHSEED": seed},
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_seconds": round(time.perf_counter() - clock, 6),
        "exit_status": returncode,
        "timed_out": timed_out,
        "outcome": outcome,
        "counts": counts,
        "pytest_output": _file_record(output_path),
        "junit": _file_record(junit_path),
    }


def run_g0_chain(
    *,
    profile: str,
    requested_argv: Sequence[str],
    receipt_path: Path | None = None,
    source_capture: Callable[[], SourceFingerprint] | None = None,
    command_runner: Callable[
        [Sequence[str], Path, dict[str, str] | None, int], tuple[int, bool]
    ]
    | None = None,
) -> int:
    """Run both fixed hash seeds and write one bounded, fail-closed receipt."""

    if profile not in CHAIN_PROFILES:
        raise ValueError(f"not a chain profile: {profile}")
    capture = source_capture or (lambda: fingerprint_source(ROOT))
    runner = command_runner or _run_logged
    started = _utc_now()
    clock = time.perf_counter()

    before, before_dict, before_error = _source_capture(capture)
    head_hint = before.head[:12] if before is not None else "unknown"
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}-{head_hint}-{os.getpid()}"
    target = _bounded_receipt_path(receipt_path, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    artifacts = target.parent / f"{target.stem}.artifacts"
    artifacts.mkdir(exist_ok=False)

    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "profile": profile,
        "evidence_scope": "local regression evidence only",
        "gate0_closure_claimed": False,
        "invocation_argv": [os.fspath(Path(__file__).resolve()), *requested_argv],
        "hash_seeds": list(HASH_SEEDS),
        "started_at": _iso(started),
        "python": _python_environment_record(),
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "git_head": before.head if before is not None else None,
        "source_before": before_dict,
        "source_before_error": before_error,
        "dirty_manifest": dirty_manifest(before) if before is not None else None,
        "plan_check": None,
        "runs": [],
        "source_after": None,
        "source_after_error": None,
        "worktree_unchanged": False,
        "mutation_detected": False,
        "mutation_observation": None,
    }

    plan_output = artifacts / "iron-plan.log"
    plan_argv = [sys.executable, "tools/iron_plan_guard.py", "verify"]
    plan_started = _utc_now()
    plan_clock = time.perf_counter()
    plan_rc, plan_timed_out = runner(plan_argv, plan_output, None, PLAN_TIMEOUT_S)
    receipt["plan_check"] = {
        "argv": plan_argv,
        "started_at": _iso(plan_started),
        "finished_at": _iso(_utc_now()),
        "duration_seconds": round(time.perf_counter() - plan_clock, 6),
        "exit_status": plan_rc,
        "timed_out": plan_timed_out,
        "output": _file_record(plan_output),
    }

    mutation_detected = False

    def observe_again(stage: str) -> SourceFingerprint | None:
        nonlocal mutation_detected
        observed, _, error = _source_capture(capture)
        if error is not None:
            receipt["source_after_error"] = error
            return None
        if observed is None:
            receipt["source_after_error"] = "source observation returned no result"
            return None
        if not observed.exact:
            receipt["source_after_error"] = f"inexact source observation after {stage}"
            return None
        if before is not None and observed.fingerprint_sha256 != before.fingerprint_sha256:
            mutation_detected = True
            if receipt["mutation_observation"] is None:
                receipt["mutation_observation"] = {
                    "stage": stage,
                    "source": observed.to_dict(),
                }
        return observed

    if before is not None and before.exact and plan_rc == 0:
        after_plan = observe_again("plan-check")
        if after_plan is not None and not mutation_detected:
            for seed in HASH_SEEDS:
                run = _run_record(seed=seed, artifacts=artifacts, command_runner=runner)
                receipt["runs"].append(run)
                current = observe_again(f"pytest-seed-{seed}")
                if current is None or mutation_detected:
                    break

    after, after_dict, after_error = _source_capture(capture)
    if (
        after is not None
        and after.exact
        and before is not None
        and after.fingerprint_sha256 != before.fingerprint_sha256
    ):
        mutation_detected = True
        if receipt["mutation_observation"] is None:
            receipt["mutation_observation"] = {
                "stage": "final",
                "source": after.to_dict(),
            }
    receipt["source_after"] = after_dict
    receipt["source_after_error"] = receipt["source_after_error"] or after_error
    if after is not None and not after.exact and receipt["source_after_error"] is None:
        receipt["source_after_error"] = "final source observation is inexact"
    receipt["mutation_detected"] = mutation_detected
    receipt["worktree_unchanged"] = bool(
        before is not None
        and before.exact
        and after is not None
        and after.exact
        and before.fingerprint_sha256 == after.fingerprint_sha256
        and not mutation_detected
    )

    runs = receipt["runs"]
    run_outcomes = [str(run["outcome"]) for run in runs]
    if mutation_detected or plan_rc != 0:
        exit_status, outcome = EXIT_FAILED, "FAIL"
    elif "FAIL" in run_outcomes:
        exit_status, outcome = EXIT_FAILED, "FAIL"
    elif (
        before is None
        or not before.exact
        or after is None
        or not after.exact
        or receipt["source_after_error"] is not None
        or not receipt["worktree_unchanged"]
        or len(runs) != len(HASH_SEEDS)
        or "INCOMPLETE" in run_outcomes
    ):
        exit_status, outcome = EXIT_INCOMPLETE, "INCOMPLETE"
    else:
        exit_status, outcome = EXIT_OK, "PASS"

    finished = _utc_now()
    receipt.update(
        {
            "finished_at": _iso(finished),
            "duration_seconds": round(time.perf_counter() - clock, 6),
            "outcome": outcome,
            "exit_status": exit_status,
        }
    )
    receipt_sha = _write_new_json(target, receipt)
    print(f"g0-chain receipt: {target}")
    print(f"g0-chain receipt sha256: {receipt_sha}")
    print(
        f"g0-chain outcome: {outcome}; seeds={len(runs)}/{len(HASH_SEEDS)}; "
        f"worktree_unchanged={receipt['worktree_unchanged']}"
    )
    return exit_status


def main(argv: list[str] | None = None) -> int:
    requested_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=tuple(PROFILES))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--skip-plan", action="store_true")
    parser.add_argument(
        "--receipt",
        type=Path,
        help="g0-chain only; must stay below runs/spine/g0-chain",
    )
    args = parser.parse_args(requested_argv)
    tests = PROFILES[args.profile]
    if args.list:
        print("\n".join(tests))
        return 0
    if args.profile in CHAIN_PROFILES:
        if args.skip_plan:
            parser.error("g0-chain receipts may not skip Iron Plan verification")
        try:
            return run_g0_chain(
                profile=args.profile,
                requested_argv=requested_argv,
                receipt_path=args.receipt,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.receipt is not None:
        parser.error("--receipt is available only for g0-chain profiles")
    if not args.skip_plan:
        _run([sys.executable, "tools/iron_plan_guard.py", "verify"])
    _run([sys.executable, "-m", "pytest", "-q", *tests])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
