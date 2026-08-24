"""Amendment kit: the Gesamtplan becomes program authority under the plan.

Owner-run, one command, full rollback. Owner approval: conversation
2026-08-18 ("ja lass den gesamtplan als Autoritaet verfassen").

What it does, atomically:
1. Copies docs/DAEDALUS_GESAMTPLAN.md byte-exact from the checkpoint tree
   into the trunk (an authority must live in the tree its constitution
   governs).
2. Adds one row to the section-0 authority table: program authority,
   ranked below evidence (evidence refutes even the program) and above
   history/backlog.
3. Qualifies the one sentence that made the plan the only semantic
   authority, so the Gesamtplan details the program WITHIN the plan's
   bounds, conflicts resolve to the plan, and measured drift becomes work.
4. Bumps the plan revision and appends the hash-chained ledger record.

Usage:
    python docs/recovery/amendment_gesamtplan_kit.py selftest
    python docs/recovery/amendment_gesamtplan_kit.py apply
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path("C:/Users/nukei/Desktop/agent_env_g0")
CHECKPOINT_GESAMTPLAN = Path(
    "C:/Users/nukei/Desktop/agent_env/docs/DAEDALUS_GESAMTPLAN.md"
)
GESAMTPLAN_REL = Path("docs/DAEDALUS_GESAMTPLAN.md")
PLAN_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.md")
LEDGER_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
GUARD_REL = Path("tools/iron_plan_guard.py")

TABLE_ANCHOR = "| ADRs, TODOs, handoffs, inventories | history/backlog | supply evidence and proposals |"
TABLE_NEW = (
    "| `docs/DAEDALUS_GESAMTPLAN.md` | program authority | detail the build "
    "program within this plan's bounds |\n"
    + TABLE_ANCHOR
)

SENTENCE_ANCHOR = (
    "A capability policy cannot broaden the plan, and the plan cannot grant a\n"
    "capability. For effects, the stricter mechanical policy wins. For product\n"
    "meaning and sequencing, only this plan is authoritative."
)
SENTENCE_NEW = (
    "A capability policy cannot broaden the plan, and the plan cannot grant a\n"
    "capability. For effects, the stricter mechanical policy wins. For product\n"
    "meaning and sequencing, this plan is the final authority; the Gesamtplan\n"
    "details the build program within these bounds, and where they conflict,\n"
    "this plan wins. Measured drift between the Gesamtplan and the tree is\n"
    "recorded as work, never papered over."
)


def _load_guard(root: Path):
    spec = importlib.util.spec_from_file_location("iron_plan_guard_gp", root / GUARD_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selftest(root: Path) -> bool:
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
        ok = ok and passed

    plan_src = (root / PLAN_REL).read_bytes().decode("utf-8")
    check("table anchor present exactly once", plan_src.count(TABLE_ANCHOR) == 1,
          f"count={plan_src.count(TABLE_ANCHOR)}")
    check("gesamtplan row not already present",
          "DAEDALUS_GESAMTPLAN" not in plan_src)
    check("authority sentence present exactly once",
          plan_src.count(SENTENCE_ANCHOR) == 1,
          f"count={plan_src.count(SENTENCE_ANCHOR)}")
    check("gesamtplan source exists (checkpoint)", CHECKPOINT_GESAMTPLAN.is_file(),
          str(CHECKPOINT_GESAMTPLAN))
    target = root / GESAMTPLAN_REL
    if target.exists():
        same = target.read_bytes() == CHECKPOINT_GESAMTPLAN.read_bytes()
        check("trunk copy absent or identical", same, "differing copy exists")
    else:
        check("trunk copy absent or identical", True, "absent")
    rev = re.search(r"^Revision: (\d+)\s*$", plan_src, re.MULTILINE)
    ver = re.search(r"^Version: (\d+)\.(\d+)\.(\d+)\s*$", plan_src, re.MULTILINE)
    check("plan header parses", bool(rev and ver),
          f"rev={rev and rev.group(1)} ver={ver and ver.group(0).strip()}")
    guard = _load_guard(root)
    check("guard verify clean before apply", not guard.verify(root))
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return ok


def apply(root: Path) -> int:
    plan_path = root / PLAN_REL
    ledger_path = root / LEDGER_REL
    gp_path = root / GESAMTPLAN_REL
    originals = {p: p.read_bytes() for p in (plan_path, ledger_path)}
    gp_existed = gp_path.exists()
    gp_original = gp_path.read_bytes() if gp_existed else None

    def rollback() -> None:
        for path, payload in originals.items():
            path.write_bytes(payload)
        if gp_existed and gp_original is not None:
            gp_path.write_bytes(gp_original)
        elif gp_path.exists():
            gp_path.unlink()
        print("rolled back all changes")

    if not selftest(root):
        print("ABORT: selftest failed before any change")
        return 1

    guard = _load_guard(root)
    plan_src = originals[plan_path].decode("utf-8")
    revision = int(re.search(r"^Revision: (\d+)\s*$", plan_src, re.MULTILINE).group(1))
    major, minor, patch = (int(g) for g in re.search(
        r"^Version: (\d+)\.(\d+)\.(\d+)\s*$", plan_src, re.MULTILINE).groups())
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"

    records = [json.loads(line) for line in
               originals[ledger_path].decode("utf-8").splitlines() if line.strip()]
    last = records[-1]
    if last.get("result_revision") != revision:
        print(f"ABORT: plan Revision {revision} != ledger result_revision "
              f"{last.get('result_revision')}")
        return 1

    try:
        gp_path.write_bytes(CHECKPOINT_GESAMTPLAN.read_bytes())
        new_plan = (plan_src
                    .replace(TABLE_ANCHOR, TABLE_NEW, 1)
                    .replace(SENTENCE_ANCHOR, SENTENCE_NEW, 1)
                    .replace(f"Revision: {revision}", f"Revision: {revision + 1}", 1)
                    .replace(f"Version: {old_version}", f"Version: {new_version}", 1))
        plan_path.write_bytes(new_plan.encode("utf-8"))

        digest_candidates = [guard.file_sha256(plan_path)]
        if hasattr(guard, "normalized_text"):
            digest_candidates.append(hashlib.sha256(
                guard.normalized_text(new_plan).encode("utf-8")).hexdigest())
        verified = False
        for digest in dict.fromkeys(digest_candidates):
            record = {
                "accepted_at": datetime.datetime.now(datetime.timezone.utc)
                    .astimezone().isoformat(timespec="seconds"),
                "approval_ref": "conversation-2026-08-18-owner-elevates-gesamtplan",
                "base_plan_sha256": last["result_plan_sha256"],
                "base_revision": revision,
                "owner": "repository-owner",
                "plan_id": "daedalus-master-plan",
                "previous_record_sha256": last["record_sha256"],
                "result_plan_sha256": digest,
                "result_revision": revision + 1,
                "schema": "daedalus-master-plan-amendment/1",
                "scope": ["governance"],
                "sequence": last["sequence"] + 1,
                "status": "accepted",
                "summary": ("The Gesamtplan enters the tree and the authority "
                            "table as program authority: it details the build "
                            "program within the plan's bounds, conflicts resolve "
                            "to the plan, and measured drift between Gesamtplan "
                            "and tree is recorded as work."),
                "version": new_version,
            }
            record["record_sha256"] = guard.canonical_record_sha256(record)
            payload = originals[ledger_path].decode("utf-8").rstrip("\n")
            ledger_path.write_bytes(
                (payload + "\n" + json.dumps(record, sort_keys=True,
                 separators=(",", ":")) + "\n").encode("utf-8"))
            guard = _load_guard(root)
            errors = guard.verify(root)
            if not errors:
                verified = True
                break
            print(f"digest candidate rejected, verify said: {errors[:3]}")
        if not verified:
            rollback()
            print("ABORT: no digest variant satisfied verify; nothing changed")
            return 1
    except Exception as exc:  # noqa: BLE001 -- roll back on anything
        rollback()
        print(f"ABORT: {exc}; rolled back")
        return 1

    token = last["result_plan_sha256"]
    print("\nAMENDMENT APPLIED AND VERIFIED. To commit:")
    print(f"  cd {root}")
    print(f"  $env:DAEDALUS_IRON_PLAN_AMENDMENT='{token}'")
    print("  git add docs/DAEDALUS_GESAMTPLAN.md docs/IKARUS_ARIADNE_MASTER_PLAN.md "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
    print('  git commit -m "amend(authority): the Gesamtplan enters the table as '
          'program authority within the plan' + "'" + 's bounds" '
          '-m "Iron-Plan: amendment" -m "Iron-Gate: 0"')
    print("  Remove-Item Env:DAEDALUS_IRON_PLAN_AMENDMENT")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["selftest", "apply"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    sys.exit(0 if (selftest(args.root.resolve()) if args.command == "selftest"
                   else apply(args.root.resolve()) == 0) else 1)
