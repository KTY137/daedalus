"""Owner tool: append the sequence-8 amendment record sealing Gate 0.

Run FROM THE REPO ROOT, in YOUR terminal (the harness classifier deliberately
refuses to let an agent touch the amendment chain -- three denials on
2026-08-26, which is the protection working, not a bug):

    python docs/recovery/gate0_seal_append_record.py

What it does, all of it visible below: recomputes the plan digest, verifies it
matches the value the record claims, chains previous_record_sha256 from the
current tail, computes record_sha256 over the canonical compact sorted JSON of
the body (the same recipe as json.dumps(sort_keys=True, separators=(",",":"),
ensure_ascii=False)), appends EXACTLY ONE line to
docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl, and prints what it wrote.
It refuses to run twice (sequence 8 already present) and refuses if the plan
bytes are not the sealed Revision-8 bytes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "IKARUS_ARIADNE_MASTER_PLAN.md"
CHAIN = ROOT / "docs" / "IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl"

EXPECTED_RESULT_PLAN_SHA = (
    "7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704"
)


def main() -> int:
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    if plan_sha != EXPECTED_RESULT_PLAN_SHA:
        print(
            "REFUSED: the plan on disk is not the sealed Revision-8 bytes.\n"
            f"  on disk : {plan_sha}\n"
            f"  expected: {EXPECTED_RESULT_PLAN_SHA}\n"
            "Someone edited the plan after the seal was prepared. Re-verify "
            "before appending anything.",
            file=sys.stderr,
        )
        return 2

    lines = [l for l in CHAIN.read_text(encoding="utf-8").splitlines() if l.strip()]
    tail = json.loads(lines[-1])
    if tail.get("sequence") == 8:
        print("REFUSED: sequence 8 is already appended; nothing to do.",
              file=sys.stderr)
        return 2
    if tail.get("sequence") != 7:
        print(f"REFUSED: chain tail is sequence {tail.get('sequence')}, not 7.",
              file=sys.stderr)
        return 2

    record = {
        "accepted_at": "2026-08-26T13:45:00+02:00",
        "approval_ref": "conversation-2026-08-26-owner-seals-gate0-scoped",
        "base_plan_sha256": (
            "cfc0f27e5387b942e0daf0a6752952e5748ce2e09526346b2cc6b96c8abe398d"
        ),
        "base_revision": 7,
        "note": (
            "base_plan_sha256 is the MEASURED pre-edit digest, not revision "
            "7's recorded result (306115e6...): two owner-era docs commits "
            "(79825b57 retirement note via 5a7e0c1d, 062780df citation "
            "annotations) moved the bytes after the final machine-validated "
            "record, as that record itself anticipated ('later records are "
            "owner-appended'). Stated rather than smoothed."
        ),
        "owner": "repository-owner",
        "plan_id": "daedalus-master-plan",
        "previous_record_sha256": tail["record_sha256"],
        "result_plan_sha256": EXPECTED_RESULT_PLAN_SHA,
        "result_revision": 8,
        "schema": "daedalus-master-plan-amendment/1",
        "scope": ["governance", "gate-closure"],
        "sequence": 8,
        "status": "accepted",
        "summary": (
            "Scoped Gate-0 closure by explicit owner instruction of "
            "2026-08-26; active delivery gate moves to Gate 1. Full blocker "
            "disposition, the four carried obligations, and the rollback "
            "path are in docs/GATE0_CLOSURE_DECISION_20260826.md. The "
            "machine report keeps saying closed:false over the scoped rows "
            "by design; security_boundary_claimed stays false on purpose."
        ),
        "version": "1.3.0",
    }
    record["record_sha256"] = hashlib.sha256(
        json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    with CHAIN.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    print("appended sequence 8:")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
