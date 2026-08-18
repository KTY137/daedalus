"""Amendment 006 kit -- owner-run, one command, full rollback.

Two protected-artifact changes, both proposed with exact diffs in
docs/GATE0_OWNER_DECISIONS_20260817.md (items 1, 5, 6) and accepted by the
owner in conversation on 2026-08-17 (~21:18, "ich akzeptiere alles mach ma"):

1. tests/test_iron_plan_guard.py -- the adoption fixture also copies the
   pinned retained source, so the sealed-promotion checks introduced by
   amendment 005 have their subject in the synthetic repo (option A of the
   owner paper; the assertion set is unchanged, nothing is weakened).
2. .gitattributes -- the two byte-pinned modules are marked ``-text`` so a
   fresh Windows checkout can no longer smudge them to CRLF and break their
   blob pins (the day's CRLF demon, measured four times on 2026-08-17).

Usage:
    python docs/recovery/amendment_006_kit.py selftest
    python docs/recovery/amendment_006_kit.py apply

Apply patches the two files, bumps the plan revision/version, appends the
ledger record, re-verifies with the guard, runs the previously red guard
test, and rolls everything back if any step is not clean.
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
TEST_REL = Path("tests/test_iron_plan_guard.py")
ATTR_REL = Path(".gitattributes")
PLAN_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.md")
LEDGER_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
GUARD_REL = Path("tools/iron_plan_guard.py")
RETAINED_REL = Path("daedalus/kairos/_gated_writes_legacy.py.src")
LEDGER_MODULE_REL = Path("daedalus/runtimes/provider_target_receipt_ledger.py")

OLD_TEST_BLOCK = '''            for rel in guard.PROTECTED_PATHS:
                destination = repo / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                if rel in {guard.PLAN_REL, guard.LEDGER_REL}:
                    historical = run_git(ROOT, "show", f"{adoption_commit}:{rel}")
                    destination.write_text(historical + "\\n", encoding="utf-8")
                else:
                    shutil.copy2(ROOT / rel, destination)
            run_git(repo, "add", "-A")'''

NEW_TEST_BLOCK = '''            for rel in guard.PROTECTED_PATHS:
                destination = repo / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                if rel in {guard.PLAN_REL, guard.LEDGER_REL}:
                    historical = run_git(ROOT, "show", f"{adoption_commit}:{rel}")
                    destination.write_text(historical + "\\n", encoding="utf-8")
                else:
                    shutil.copy2(ROOT / rel, destination)
            # Amendment 006: the sealed-promotion checks read the retained
            # source the strangler pins; a real adopting repo carries it with
            # the tree, so the synthetic adoption repo must carry it too.
            retained = Path("daedalus/kairos/_gated_writes_legacy.py.src")
            shutil.copy2(ROOT / retained, repo / retained)
            run_git(repo, "add", "-A")'''

OLD_ATTR = ".githooks/* text eol=lf\n"
NEW_ATTR = (
    ".githooks/* text eol=lf\n"
    "daedalus/kairos/_gated_writes_legacy.py.src -text\n"
    "daedalus/runtimes/provider_target_receipt_ledger.py -text\n"
)

TEST_NODE = (
    "tests/test_iron_plan_guard.py::IronPlanContractTests::"
    "test_ci_history_check_accepts_adoption_and_rejects_rewrite"
)


def _load_guard(root: Path):
    spec = importlib.util.spec_from_file_location("iron_plan_guard_006", root / GUARD_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selftest(root: Path) -> bool:
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))
        ok = ok and passed

    test_src = (root / TEST_REL).read_bytes().decode("utf-8")
    check("fixture anchor present exactly once",
          test_src.count(OLD_TEST_BLOCK) == 1,
          f"count={test_src.count(OLD_TEST_BLOCK)}")
    check("new fixture block not already applied",
          NEW_TEST_BLOCK not in test_src)

    import ast
    try:
        ast.parse(test_src.replace(OLD_TEST_BLOCK, NEW_TEST_BLOCK))
        check("patched test parses", True)
    except SyntaxError as exc:
        check("patched test parses", False, str(exc))

    attr_src = (root / ATTR_REL).read_bytes().decode("utf-8")
    check("attributes anchor matches", attr_src == OLD_ATTR,
          repr(attr_src[:60]))

    check("retained source exists", (root / RETAINED_REL).is_file())
    check("pinned ledger module exists", (root / LEDGER_MODULE_REL).is_file())

    plan_src = (root / PLAN_REL).read_bytes().decode("utf-8")
    rev = re.search(r"^Revision: (\d+)\s*$", plan_src, re.MULTILINE)
    ver = re.search(r"^Version: (\d+)\.(\d+)\.(\d+)\s*$", plan_src, re.MULTILINE)
    check("plan header parses", bool(rev and ver),
          f"rev={rev and rev.group(1)} ver={ver and ver.group(0).strip()}")

    guard = _load_guard(root)
    check("guard verify clean before apply", not guard.verify(root))
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return ok


def apply(root: Path) -> int:
    paths = [root / TEST_REL, root / ATTR_REL, root / PLAN_REL, root / LEDGER_REL]
    originals = {p: p.read_bytes() for p in paths}

    def rollback() -> None:
        for path, payload in originals.items():
            path.write_bytes(payload)
        print("rolled back all changes")

    if not selftest(root):
        print("ABORT: selftest failed before any change")
        return 1

    guard = _load_guard(root)
    plan_src = originals[root / PLAN_REL].decode("utf-8")
    revision = int(re.search(r"^Revision: (\d+)\s*$", plan_src, re.MULTILINE).group(1))
    major, minor, patch = (int(g) for g in re.search(
        r"^Version: (\d+)\.(\d+)\.(\d+)\s*$", plan_src, re.MULTILINE).groups())
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"

    records = [json.loads(line) for line in
               originals[root / LEDGER_REL].decode("utf-8").splitlines() if line.strip()]
    last = records[-1]
    if last.get("result_revision") != revision:
        print(f"ABORT: plan Revision {revision} != ledger result_revision "
              f"{last.get('result_revision')}")
        return 1

    try:
        test_src = originals[root / TEST_REL].decode("utf-8")
        (root / TEST_REL).write_bytes(
            test_src.replace(OLD_TEST_BLOCK, NEW_TEST_BLOCK).encode("utf-8"))
        (root / ATTR_REL).write_bytes(NEW_ATTR.encode("utf-8"))
        new_plan = plan_src.replace(
            f"Revision: {revision}", f"Revision: {revision + 1}", 1
        ).replace(f"Version: {old_version}", f"Version: {new_version}", 1)
        (root / PLAN_REL).write_bytes(new_plan.encode("utf-8"))

        digest_candidates = [guard.file_sha256(root / PLAN_REL)]
        if hasattr(guard, "normalized_text"):
            digest_candidates.append(hashlib.sha256(
                guard.normalized_text(new_plan).encode("utf-8")).hexdigest())
        verified = False
        for digest in dict.fromkeys(digest_candidates):
            record = {
                "accepted_at": datetime.datetime.now(datetime.timezone.utc)
                    .astimezone().isoformat(timespec="seconds"),
                "approval_ref": "conversation-2026-08-17-owner-accepted-gate0-closure-package",
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
                "summary": ("Adoption fixture carries the pinned retained source so "
                            "the amendment-005 checks have their subject; the two "
                            "byte-pinned modules are attribute-pinned -text so fresh "
                            "Windows checkouts cannot smudge their blob pins."),
                "version": new_version,
            }
            record["record_sha256"] = guard.canonical_record_sha256(record)
            payload = originals[root / LEDGER_REL].decode("utf-8").rstrip("\n")
            (root / LEDGER_REL).write_bytes(
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

        # Find an interpreter that actually has pytest -- the owner may run
        # this kit from a venv without it (measured 2026-08-17 23:01: the
        # .venv-dspy python has no pytest, the empty-tail abort came from
        # that, not from a red test).
        runner = None
        for candidate in ([sys.executable], ["py", "-3"], ["python"]):
            probe = subprocess.run(
                candidate + ["-m", "pytest", "--version"],
                capture_output=True, text=True, timeout=60,
            )
            if probe.returncode == 0:
                runner = candidate
                break
        if runner is None:
            rollback()
            print("ABORT: no interpreter with pytest found (tried the current "
                  "python, 'py -3' and 'python'); install pytest or run the "
                  "kit outside the venv. Rolled back.")
            return 1

        print(f"running the previously red guard test via {' '.join(runner)} "
              "(this takes ~10-30 s)...")
        proc = subprocess.run(
            runner + ["-m", "pytest", TEST_NODE, "-q"],
            cwd=root, capture_output=True, text=True, timeout=600,
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-4:])
        print(tail)
        if proc.returncode != 0:
            rollback()
            print("ABORT: guard test still red after apply; rolled back")
            return 1
    except Exception as exc:  # noqa: BLE001 -- roll back on anything
        rollback()
        print(f"ABORT: {exc}; rolled back")
        return 1

    token = last["result_plan_sha256"]
    print("\nAMENDMENT 006 APPLIED AND VERIFIED. To commit:")
    print(f"  cd {root}")
    print(f"  $env:DAEDALUS_IRON_PLAN_AMENDMENT='{token}'")
    print("  git add tests/test_iron_plan_guard.py .gitattributes "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.md "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
    print('  git commit -m "amend(guard-test): the adoption fixture carries the '
          'pinned retained source; byte-pinned modules gain -text" '
          '-m "Iron-Plan: amendment" -m "Iron-Gate: 0"')
    print("  Remove-Item Env:DAEDALUS_IRON_PLAN_AMENDMENT")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["selftest", "apply"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "selftest":
        sys.exit(0 if selftest(root) else 1)
    sys.exit(apply(root))
