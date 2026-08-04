from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_replay.py"
TESTS = (
    "tests/kernel/test_promotion_execution.py",
    "tests/kernel/test_promotion_replay_projection.py",
    "tests/kernel/test_promotion_replay_projection_review.py",
)
MUTATIONS = (
    (
        "skip-authorization-validation",
        "    expected = _authorization_payload(authorization)\n",
        "    expected = authorization.to_dict()  # mutant trusts caller fields\n",
    ),
    (
        "accept-candidate-substitution",
        "        \"candidate_artifact_sha256\": (\n"
        "            start.candidate_artifact_sha256,\n"
        "            expected[\"candidate_artifact_sha256\"],\n"
        "        ),\n",
        "        \"candidate_artifact_sha256\": (\n"
        "            start.candidate_artifact_sha256,\n"
        "            start.candidate_artifact_sha256,\n"
        "        ),\n",
    ),
    (
        "accept-evidence-substitution",
        "        \"evidence_packet_sha256\": (\n"
        "            start.evidence_packet_sha256,\n"
        "            expected[\"evidence_packet_sha256\"],\n"
        "        ),\n",
        "        \"evidence_packet_sha256\": (\n"
        "            start.evidence_packet_sha256,\n"
        "            start.evidence_packet_sha256,\n"
        "        ),\n",
    ),
    (
        "accept-approval-substitution",
        "        \"approval_consumption_sha256\": (\n"
        "            start.approval_consumption_sha256,\n"
        "            expected[\"approval_consumption_sha256\"],\n"
        "        ),\n",
        "        \"approval_consumption_sha256\": (\n"
        "            start.approval_consumption_sha256,\n"
        "            start.approval_consumption_sha256,\n"
        "        ),\n",
    ),
    (
        "decode-completion-before-binding",
        "    if mismatches:\n"
        "        raise PromotionReplayProjectionMismatch(\n"
        "            \"persisted promotion start contradicts authorization: \"\n"
        "            + \", \".join(mismatches)\n"
        "        )\n"
        "\n"
        "    completion = ledger._decode_completion(intent, start)\n",
        "    completion = ledger._decode_completion(intent, start)\n"
        "    if mismatches:\n"
        "        raise PromotionReplayProjectionMismatch(\n"
        "            \"persisted promotion start contradicts authorization: \"\n"
        "            + \", \".join(mismatches)\n"
        "        )\n",
    ),
    (
        "reexecute-on-replay",
        "        execute=False,\n",
        "        execute=True,  # mutant grants a second execution\n",
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
        sys.stderr.write("baseline failed before promotion-replay mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion-replay mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
