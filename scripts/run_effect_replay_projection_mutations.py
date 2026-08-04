from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "effect_replay.py"
TESTS = (
    "tests/kernel/test_effect_replay_projection.py",
    "tests/kernel/test_effect_replay_projection_review.py",
)
MUTATIONS = (
    (
        "accept-request-json-substitution",
        "            \"request_json\": (\n"
        "                str(row[\"request_json\"]),\n"
        "                canonical_json(execution.to_dict()),\n"
        "            ),\n",
        "            \"request_json\": (\n"
        "                str(row[\"request_json\"]),\n"
        "                str(row[\"request_json\"]),\n"
        "            ),\n",
    ),
    (
        "accept-start-digest-substitution",
        "        if str(row[\"start_receipt_sha256\"]) != start.receipt_sha256:\n"
        "            raise EffectReplayProjectionError(\n"
        "                \"effect row start digest does not bind persisted start receipt\"\n"
        "            )\n",
        "        if False:  # mutant accepts detached start digest\n"
        "            raise EffectReplayProjectionError(\n"
        "                \"effect row start digest does not bind persisted start receipt\"\n"
        "            )\n",
    ),
    (
        "skip-historical-lease-authentication",
        "        verify_effect_lease(\n"
        "            authorization.lease,\n"
        "            request=authorization.request,\n"
        "            policy_decision=authorization.policy_decision,\n"
        "            keyring=authorization.lease_keyring,\n"
        "            current_kill_switch_generation=authorization.lease.kill_switch_generation,\n"
        "            now=_parse_utc(start.started_at, \"started_at\"),\n"
        "            registry=authorization.registry,\n"
        "        )\n",
        "        if False:  # mutant skips historical lease authentication\n"
        "            verify_effect_lease(\n"
        "                authorization.lease,\n"
        "                request=authorization.request,\n"
        "                policy_decision=authorization.policy_decision,\n"
        "                keyring=authorization.lease_keyring,\n"
        "                current_kill_switch_generation=authorization.lease.kill_switch_generation,\n"
        "                now=_parse_utc(start.started_at, \"started_at\"),\n"
        "                registry=authorization.registry,\n"
        "            )\n",
    ),
    (
        "accept-started-terminal-material",
        "            if any(\n"
        "                row[name] is not None\n"
        "                for name in (\n"
        "                    \"finished_at\",\n"
        "                    \"terminal_receipt_sha256\",\n"
        "                    \"terminal_receipt_json\",\n"
        "                )\n"
        "            ):\n"
        "                raise EffectReplayProjectionError(\n"
        "                    \"started effect row contains terminal material\"\n"
        "                )\n",
        "            if False:  # mutant accepts terminal material on STARTED\n"
        "                raise EffectReplayProjectionError(\n"
        "                    \"started effect row contains terminal material\"\n"
        "                )\n",
    ),
    (
        "accept-terminal-outcome-substitution",
        "        \"outcome\": (receipt.outcome, row_state),\n",
        "        \"outcome\": (receipt.outcome, receipt.outcome),\n",
    ),
    (
        "accept-terminal-digest-substitution",
        "        if str(row[\"terminal_receipt_sha256\"]) != terminal.receipt_sha256:\n"
        "            raise EffectReplayProjectionError(\n"
        "                \"effect row terminal digest does not bind persisted terminal receipt\"\n"
        "            )\n",
        "        if False:  # mutant accepts detached terminal digest\n"
        "            raise EffectReplayProjectionError(\n"
        "                \"effect row terminal digest does not bind persisted terminal receipt\"\n"
        "            )\n",
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before effect-replay mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            TARGET.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} effect-replay mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
