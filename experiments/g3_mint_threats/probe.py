"""Feasibility probe: can the three threats MINT_CONFIRM_THRESHOLD names be
checked DIRECTLY, instead of waited out via a recurrence that never happens?

The threshold's own comment names exactly three failure modes a single mint
could be:
  T1 a reformat-only touch that shifts a docstring
  T2 a rename that round-trips to byte-identical source under a new name
  T3 a generated-file regen

It then predicts the threshold stays "low enough to actually accumulate ...
instead of never firing". Measured: zero confirmations across 400 commits, so
the prediction is false and the gate never opens.

This probe asks only whether the three are DECIDABLE per task, and what they
say. It changes nothing. Read-only. Deleted after use.
"""
import json
import pathlib
import subprocess
import sys
from collections import Counter

sys.path.insert(0, ".")
from daedalus.eval.mint import load_minted_tasks  # noqa: E402
from daedalus.eval.tasks import resolve_task_repo  # noqa: E402

ROOT = pathlib.Path(".").resolve()


def git(*args):
    """BINARY capture, decoded explicitly.

    The first version used text=True, which decodes with the console codepage
    (cp1252 here) and raised UnicodeDecodeError on the first non-UTF-8 byte in
    a blob. That surfaced as 35 of 48 tasks reporting NO_BLOBS -- a measurement
    of my own decode bug, not of the corpus.
    """
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                           timeout=30)
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def blob(sha, rel):
    return git("show", f"{sha}:{rel}")


GENERATED_MARKERS = ("dist/", "build/", "node_modules/", ".min.", "generated",
                     "_pb2", "runs/", "lock")


def t3_generated(rel):
    low = rel.lower()
    return any(m in low for m in GENERATED_MARKERS)


def normalize_py(src):
    """Structural identity for Python: AST dump with docstrings dropped."""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, annotate_fields=False)


tasks = load_minted_tasks()
rows = Counter()
detail = []

for t in tasks:
    sha = t.get("minted_at_sha")
    rel = (t.get("target") or "").split("::", 1)[0]
    prov = t.get("label_provenance")

    # T3 -- decidable from the path alone, always
    t3 = t3_generated(rel)

    # T1/T2 -- need before/after source at the mint revision
    parent = git("rev-parse", f"{sha}^") if sha else None
    parent = parent.strip() if parent else None
    after = blob(sha, rel) if sha else None
    before = blob(parent, rel) if parent else None

    sha_ok = git("cat-file", "-e", f"{sha}^{{commit}}") is not None if sha else False
    if not sha_ok:
        decidable = "SHA_UNREACHABLE"
        t1 = None
    elif after is None:
        decidable = "TARGET_ABSENT_AT_MINT"
        t1 = None
    elif before is None:
        # The anchor did not exist at the parent: the file was ADDED by this
        # commit. T1 ("a reformat-only touch") is IMPOSSIBLE on a file that did
        # not exist -- there was nothing to reformat. So this is not an
        # undecidable case, it is a decided one, and the first version of this
        # probe miscounted 34 tasks as unknown by lumping it with real failures.
        decidable = "FILE_ADDED"
        t1 = False
    elif not rel.endswith(".py"):
        # normalization for non-Python text is a different question; report it
        decidable = "NON_PY"
        t1 = None
    else:
        na, nb = normalize_py(after), normalize_py(before)
        if na is None or nb is None:
            decidable = "UNPARSEABLE"
            t1 = None
        else:
            decidable = "YES"
            # T1 fires when the file changed but its STRUCTURE did not:
            # the diff was cosmetic, so any label from it is noise.
            t1 = (na == nb) and (after != before)

    rows[(prov, decidable, "T1=%s" % t1, "T3=%s" % t3)] += 1
    detail.append({"id": t["id"], "prov": prov, "rel": rel, "sha": (sha or "")[:12],
                   "decidable": decidable, "t1_cosmetic": t1, "t3_generated": t3})

print("=== decidability x outcome, over %d minted tasks ===" % len(tasks))
for k in sorted(rows, key=lambda k: tuple(str(x) for x in k)):
    print("   %-24s %-12s %-11s %-9s  n=%d" % (k[0], k[1], k[2], k[3], rows[k]))

print()
print("=== summary ===")
dec = Counter(d["decidable"] for d in detail)
print("   decidable T1:", dict(dec))
print("   T1 fires (cosmetic-only diff):",
      sum(1 for d in detail if d["t1_cosmetic"]))
print("   T3 fires (generated path):",
      sum(1 for d in detail if d["t3_generated"]))
print()
print("=== any task where a threat FIRES (would be rejected) ===")
for d in detail:
    if d["t1_cosmetic"] or d["t3_generated"]:
        print("   ", d)
