"""Amendment 007 kit -- owner-run, one command, full rollback.

WHY THIS EXISTS
---------------
The sealed owner approval verifies a signed tag against
``configs/owner-allowed-signers``. Until now that file WAS the trust root and
nothing bound it: ``ALLOWED_SIGNERS_REVISION`` is ``"HEAD"``, so a single
commit writing a new signer set simply became the new root, and the commit and
blob OIDs the receipt reports would faithfully describe the attacker's own
file. Moving the file "somewhere protected" does not fix that -- whoever can
commit can commit there too.

The amendment chain is different in kind: hash-linked, each record committing
to the previous one, and section 15 requires owner approval to append. This
amendment writes the expected signer-set digest INTO that chain, so
``resolve_trust_root`` refuses any signer set the owner has not approved.
Rotating the owner's keys becomes an amendment rather than a commit.

TWO PROTECTED CHANGES
---------------------
1. ``docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`` -- one new accepted
   record carrying ``owner_allowed_signers_sha256``, the digest of the signer
   set being approved. The field is covered by ``record_sha256`` and therefore
   by the chain.
2. ``tools/iron_plan_guard.py`` -- ``configs/owner-allowed-signers`` joins
   PROTECTED_PATHS. NECESSARY BUT NOT SUFFICIENT, and it must not be mistaken
   for the fix: it makes an ordinary edit explicit, while the digest binding in
   change 1 is what actually refuses an unapproved signer set.

BEFORE YOU RUN IT
-----------------
This kit approves whatever ``configs/owner-allowed-signers`` currently holds.
READ THAT FILE FIRST. ``selftest`` prints the principals and the digest; if a
key in there is not yours, do not apply.

    python docs/recovery/amendment_007_kit.py selftest --root <repo>
    python docs/recovery/amendment_007_kit.py apply    --root <repo>

Apply patches the guard, bumps the plan revision/version, appends the ledger
record, re-verifies with the guard, runs the trust-root suite, and rolls
everything back if any step is not clean.
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
PLAN_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.md")
LEDGER_REL = Path("docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
GUARD_REL = Path("tools/iron_plan_guard.py")
CODEOWNERS_REL = Path(".github/CODEOWNERS")
SIGNERS_REL = Path("configs/owner-allowed-signers")

# The guard requires every PROTECTED_PATH to carry CODEOWNERS coverage, so
# these two changes are one atomic move. MEASURED on a throwaway copy
# 2026-08-18: patching only the guard makes verify say
# ".github/CODEOWNERS lacks @KTY137 coverage for configs/owner-allowed-signers"
# and the kit rolls back.
OLD_CODEOWNERS_LINE = "/daedalus/config.py @KTY137\n"
NEW_CODEOWNERS_LINE = (
    "/configs/owner-allowed-signers @KTY137\n"
    "/daedalus/config.py @KTY137\n"
)

TRUST_ROOT_DIGEST_FIELD = "owner_allowed_signers_sha256"

OLD_GUARD_BLOCK = '''    "daedalus/config.py",
    "daedalus/kairos/gated_writes.py",
    "daedalus/sensitivity.py",'''

NEW_GUARD_BLOCK = '''    "configs/owner-allowed-signers",
    "daedalus/config.py",
    "daedalus/kairos/gated_writes.py",
    "daedalus/sensitivity.py",'''

TEST_NODE = "tests/kernel/test_signed_approval_trust_root.py"

SUMMARY = (
    "The owner signer set is pinned by digest in the amendment chain, so "
    "resolve_trust_root refuses any allowed-signers file the owner has not "
    "approved; rotating the trust root becomes an amendment rather than a "
    "commit. configs/owner-allowed-signers also joins PROTECTED_PATHS."
)


def _load_guard(root: Path):
    spec = importlib.util.spec_from_file_location("iron_plan_guard_007", root / GUARD_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signers_digest(root: Path) -> str:
    """Exactly how TrustRoot.digest computes it: normalised newlines, sha256."""
    text = (root / SIGNERS_REL).read_bytes().decode("utf-8")
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def principals(root: Path) -> list[str]:
    text = (root / SIGNERS_REL).read_bytes().decode("utf-8")
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return [
        line.strip()
        for line in normalised.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def selftest(root: Path) -> bool:
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))
        ok = ok and passed

    check("allowed-signers file exists", (root / SIGNERS_REL).is_file(),
          str(SIGNERS_REL))
    if not (root / SIGNERS_REL).is_file():
        print("selftest: FAILED")
        return False

    named = principals(root)
    check("allowed-signers names at least one principal", bool(named),
          f"count={len(named)}")
    if not named:
        print()
        print("  ORDER OF OPERATIONS: this repository ships a principal-free")
        print("  trust root on purpose, so there is nothing to approve yet.")
        print("  1. Commit your PUBLIC signing key into "
              f"{SIGNERS_REL.as_posix()}")
        print("     as a line: <principal> <ssh-ed25519 AAAA...>")
        print("  2. Re-run this selftest and READ the printed key.")
        print("  3. Then apply, which pins that exact set in the chain.")
        print()

    guard_src = (root / GUARD_REL).read_bytes().decode("utf-8")
    check("guard anchor present exactly once",
          guard_src.count(OLD_GUARD_BLOCK) == 1,
          f"count={guard_src.count(OLD_GUARD_BLOCK)}")
    check("guard change not already applied",
          '"configs/owner-allowed-signers",' not in guard_src)

    codeowners_src = (root / CODEOWNERS_REL).read_bytes().decode("utf-8")
    check("codeowners anchor present exactly once",
          codeowners_src.count(OLD_CODEOWNERS_LINE) == 1,
          f"count={codeowners_src.count(OLD_CODEOWNERS_LINE)}")
    check("codeowners change not already applied",
          "/configs/owner-allowed-signers" not in codeowners_src)

    import ast
    try:
        ast.parse(guard_src.replace(OLD_GUARD_BLOCK, NEW_GUARD_BLOCK))
        check("patched guard parses", True)
    except SyntaxError as exc:
        check("patched guard parses", False, str(exc))

    plan_src = (root / PLAN_REL).read_bytes().decode("utf-8")
    rev = re.search(r"^Revision: (\d+)\s*$", plan_src, re.MULTILINE)
    ver = re.search(r"^Version: (\d+)\.(\d+)\.(\d+)\s*$", plan_src, re.MULTILINE)
    check("plan header parses", bool(rev and ver),
          f"rev={rev and rev.group(1)} ver={ver and ver.group(0).strip()}")

    records = [json.loads(line) for line in
               (root / LEDGER_REL).read_bytes().decode("utf-8").splitlines()
               if line.strip()]
    check("ledger parses", bool(records), f"records={len(records)}")
    check("no accepted amendment pins a signer set yet",
          not any(r.get(TRUST_ROOT_DIGEST_FIELD) for r in records
                  if r.get("status") == "accepted"))
    if records and rev:
        check("ledger tail matches plan revision",
              records[-1].get("result_revision") == int(rev.group(1)),
              f"ledger={records[-1].get('result_revision')} plan={rev.group(1)}")

    guard = _load_guard(root)
    check("guard verify clean before apply", not guard.verify(root))

    print()
    print("  THE SIGNER SET THIS AMENDMENT WOULD APPROVE:")
    for line in named:
        print(f"    {line[:100]}")
    print(f"  digest: {signers_digest(root)}")
    print("  If any key above is not yours, DO NOT APPLY.")
    print()
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return ok


def apply(root: Path) -> int:
    paths = [root / GUARD_REL, root / CODEOWNERS_REL, root / PLAN_REL,
             root / LEDGER_REL]
    originals = {p: p.read_bytes() for p in paths}

    def rollback() -> None:
        for path, payload in originals.items():
            path.write_bytes(payload)
        print("rolled back all changes")

    if not selftest(root):
        print("ABORT: selftest failed before any change")
        return 1

    digest = signers_digest(root)
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
        guard_src = originals[root / GUARD_REL].decode("utf-8")
        (root / GUARD_REL).write_bytes(
            guard_src.replace(OLD_GUARD_BLOCK, NEW_GUARD_BLOCK).encode("utf-8"))
        codeowners_src = originals[root / CODEOWNERS_REL].decode("utf-8")
        (root / CODEOWNERS_REL).write_bytes(
            codeowners_src.replace(
                OLD_CODEOWNERS_LINE, NEW_CODEOWNERS_LINE).encode("utf-8"))
        new_plan = plan_src.replace(
            f"Revision: {revision}", f"Revision: {revision + 1}", 1
        ).replace(f"Version: {old_version}", f"Version: {new_version}", 1)
        (root / PLAN_REL).write_bytes(new_plan.encode("utf-8"))

        digest_candidates = [guard.file_sha256(root / PLAN_REL)]
        if hasattr(guard, "normalized_text"):
            digest_candidates.append(hashlib.sha256(
                guard.normalized_text(new_plan).encode("utf-8")).hexdigest())
        verified = False
        for plan_digest in dict.fromkeys(digest_candidates):
            record = {
                "accepted_at": datetime.datetime.now(datetime.timezone.utc)
                    .astimezone().isoformat(timespec="seconds"),
                "approval_ref": "owner-approved-gate0-sealed-approval-trust-root-binding",
                "base_plan_sha256": last["result_plan_sha256"],
                "base_revision": revision,
                "owner": "repository-owner",
                TRUST_ROOT_DIGEST_FIELD: digest,
                "plan_id": "daedalus-master-plan",
                "previous_record_sha256": last["record_sha256"],
                "result_plan_sha256": plan_digest,
                "result_revision": revision + 1,
                "schema": "daedalus-master-plan-amendment/1",
                "scope": ["governance", "promotion"],
                "sequence": last["sequence"] + 1,
                "status": "accepted",
                "summary": SUMMARY,
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

        # An interpreter that actually has pytest -- the owner may run this kit
        # from a venv without it (measured 2026-08-17 during amendment 006).
        runner = None
        for candidate in ([sys.executable], ["py", "-3"], ["python"]):
            try:
                probe = subprocess.run(
                    candidate + ["-m", "pytest", "--version"],
                    capture_output=True, text=True, timeout=60,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode == 0:
                runner = candidate
                break
        if runner is None:
            rollback()
            print("ABORT: no interpreter with pytest found (tried the current "
                  "python, 'py -3' and 'python'); install pytest or run the "
                  "kit outside the venv. Rolled back.")
            return 1

        print(f"running the trust-root suite via {' '.join(runner)} "
              "(this takes ~60-90 s)...")
        proc = subprocess.run(
            runner + ["-m", "pytest", TEST_NODE, "-q"],
            cwd=root, capture_output=True, text=True, timeout=900,
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-4:])
        print(tail)
        if proc.returncode != 0:
            rollback()
            print("ABORT: trust-root suite red after apply; rolled back")
            return 1
    except Exception as exc:  # noqa: BLE001 -- roll back on anything
        rollback()
        print(f"ABORT: {exc}; rolled back")
        return 1

    token = last["result_plan_sha256"]
    print("\nAMENDMENT 007 APPLIED AND VERIFIED.")
    print(f"  approved signer-set digest: {digest}")
    print("\nTo commit:")
    print(f"  cd {root}")
    print(f"  $env:DAEDALUS_IRON_PLAN_AMENDMENT='{token}'")
    print("  git add tools/iron_plan_guard.py .github/CODEOWNERS "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.md "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
    print('  git commit -m "amend(promotion): the owner signer set is pinned by '
          'the amendment chain, not by whoever commits last" '
          '-m "Iron-Plan: amendment" -m "Iron-Gate: 0"')
    print("  Remove-Item Env:DAEDALUS_IRON_PLAN_AMENDMENT")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["selftest", "apply"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    resolved = args.root.resolve()
    if args.command == "selftest":
        sys.exit(0 if selftest(resolved) else 1)
    sys.exit(apply(resolved))
