"""Does the acceptance suite actually REJECT wrong implementations?

Codex's ruling after the first A/B, and it is the right one: *"fix the gate
first -- a repair loop is meaningless when its oracle accepts wrong
implementations."* The first run produced two implementations that passed the
gate, scored an identical 21/23, and contained **no tests at all**, because the
gate given to the arms (`tsc --noEmit && vite build`) cannot fail for a
wrong-but-compiling implementation.

So before any second feature runs, the oracle gets the same treatment every
guard in this repo gets: it is not trusted because it passes, it is trusted
because a KNOWN-BAD input makes it fail, verified by actually breaking one.

Method. Take a real implementation that scores 21/23 (an arm's own output, not
a strawman), seed exactly ONE defect into it, and require the specific test that
covers that rule to go red. A seeded defect that nobody catches is a hole in the
suite, and it is reported as such -- an unfalsifiable rule is worse than a
missing one, because it reads as covered.

    python runs/ab/oracle_check.py [--base artifacts/armA]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE / "conformance" / "conformance.test.ts"

# (name, file, find, replace, the test that MUST go red, the rule it defends)
MUTATIONS: list[tuple[str, str, str, str, str, str]] = [
    ("secret_leaks_as_redacted", "visibility.ts",
     'return { kind: "not_found" }; // secret',
     'return { kind: "redacted" }; // SEEDED DEFECT',
     "visibility: SECRET never leaks its existence -- not_found, never redacted",
     "a secret object rendered as a locked row confirms it exists"),

    ("gm_only_becomes_not_found", "visibility.ts",
     'if (visibility === "gm_only") return { kind: "redacted" };',
     'if (visibility === "gm_only") return { kind: "not_found" };',
     "visibility: redacted and not_found stay distinguishable states",
     "collapsing the two denial states into one"),

    ("public_can_read_open", "visibility.ts",
     'if (role === "public") return { kind: "not_found" };',
     'if (role === "public") return { kind: "ok", role };',
     "visibility: open is visible to members, never to public",
     "campaign content exposed to a public viewer"),

    ("player_is_gm_tier", "visibility.ts",
     'return role === "owner" || role === "gm" || role === "co_gm";',
     'return role !== "public";',
     "visibility: GM tier is exactly owner, gm, co_gm",
     "widening the GM tier"),

    ("slug_in_canonical_form", "objectRef.ts",
     "return `${ref.type}:${ref.id}@${ref.revision}`;",
     "return `${ref.type}:${ref.slug ?? ref.id}@${ref.revision}`;",
     "objectRef: canonical form is built from type and id, never the slug",
     "identity built on a slug breaks across renames"),

    ("revision_becomes_identity", "objectRef.ts",
     "return a.type === b.type && a.id === b.id && scopeEquals(a.scope, b.scope);",
     "return a.type === b.type && a.id === b.id && a.revision === b.revision;",
     "objectRef: sameObject ignores revision but respects identity",
     "two revisions of one object treated as two objects"),

    ("scope_is_not_identity", "objectRef.ts",
     "return a.type === b.type && a.id === b.id && scopeEquals(a.scope, b.scope);",
     "return a.type === b.type && a.id === b.id;",
     "objectRef: scope is part of identity",
     "the same id in a different campaign treated as the same object"),

    ("recipe_mapping_wrong", "viewRecipe.ts",
     'tisch: "actor-sheet"', 'tisch: "collection-table"',
     "viewRecipe: every required mapping from the document resolves",
     "a documented object/workspace mapping silently changed"),

    ("role_accepted_as_workspace", "viewRecipe.ts",
     "export function resolveRecipe(objectType: string, workspace: Workspace)",
     "export function resolveRecipe(objectType: string, workspace: any)",
     "viewRecipe: roles are not recipes",
     "a role accepted where a workspace belongs"),

    ("scope_parse_throws", "scope.ts",
     "export function parseScope",
     "export function parseScope_DISABLED_BY_MUTATION",
     "scope: malformed input returns null and never throws",
     "the never-throws contract"),
]


def _rewrite_imports(text: str) -> str:
    return re.sub(r'(from\s+["\'])(\.\.?/[^"\']+?)(["\'])',
                  lambda m: m.group(1) + m.group(2)
                  + ("" if Path(m.group(2)).suffix else ".ts") + m.group(3),
                  text)


def materialise(base: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for src in base.glob("*.ts"):
        (out / src.name).write_text(_rewrite_imports(
            src.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")


def failing_tests(core: Path) -> set[str]:
    proc = subprocess.run(
        ["node", "--test", "--test-reporter=tap", str(SUITE)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=900,
        env={**__import__("os").environ, "ARM_CORE": str(core)}, shell=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    failed = set()
    for line in out.splitlines():
        m = re.match(r"^not ok\s+\d+\s+-\s+(.*?)(?:\s+#.*)?$", line.strip())
        if m and not m.group(1).startswith("Subtest"):
            failed.add(m.group(1).strip())
    return failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="artifacts/armA",
                    help="an implementation that already scores well; defects "
                         "are seeded into a COPY of it")
    args = ap.parse_args()
    base = (HERE / args.base).resolve()
    if not base.is_dir():
        print(f"no such base: {base}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="oracle-"))
    clean = tmp / "clean"
    materialise(base, clean)
    baseline_failures = failing_tests(clean)
    print(f"baseline ({base.name}): {len(baseline_failures)} failing test(s) "
          f"before any defect is seeded")

    results = []
    for name, fname, find, repl, expect, rule in MUTATIONS:
        work = tmp / name
        materialise(base, work)
        target = work / fname
        text = target.read_text(encoding="utf-8")
        if find not in text:
            results.append({"mutation": name, "status": "NOT_APPLICABLE",
                            "reason": f"pattern not present in {fname}",
                            "rule": rule})
            continue
        target.write_text(text.replace(find, repl, 1), encoding="utf-8")

        failed = failing_tests(work)
        newly = failed - baseline_failures
        caught = expect in newly
        results.append({
            "mutation": name, "file": fname, "rule": rule,
            "expected_test": expect,
            "status": "CAUGHT" if caught else "SURVIVED",
            "newly_failing": sorted(newly),
        })

    shutil.rmtree(tmp, ignore_errors=True)

    caught = [r for r in results if r["status"] == "CAUGHT"]
    survived = [r for r in results if r["status"] == "SURVIVED"]
    skipped = [r for r in results if r["status"] == "NOT_APPLICABLE"]

    print(f"\nseeded {len(results)} defect(s): {len(caught)} caught, "
          f"{len(survived)} SURVIVED, {len(skipped)} not applicable\n")
    for r in results:
        mark = {"CAUGHT": "ok  ", "SURVIVED": "MISS", "NOT_APPLICABLE": "n/a "}[r["status"]]
        print(f"  [{mark}] {r['mutation']:28s} {r['rule']}")
        if r["status"] == "SURVIVED":
            print(f"           nothing went red -- this rule is UNFALSIFIABLE "
                  f"and reads as covered")
        elif r["status"] == "CAUGHT" and r["newly_failing"] != [r["expected_test"]]:
            print(f"           (also newly red: "
                  f"{[t for t in r['newly_failing'] if t != r['expected_test']]})")

    (HERE / "receipts" / "oracle_check.json").write_text(
        json.dumps({"base": str(base), "baseline_failures": sorted(baseline_failures),
                    "results": results}, indent=2), encoding="utf-8")

    # A surviving defect means the suite is not an oracle for that rule.
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
