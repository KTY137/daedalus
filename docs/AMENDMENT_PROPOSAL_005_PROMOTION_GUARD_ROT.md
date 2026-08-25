# Amendment proposal 005 — the promotion guard lost its subject

Status: **proposed, not applied**
Author: Athena (coordinator), 2026-08-17
Protected artifact touched: `tools/iron_plan_guard.py (removed 2026-08-22)`
Affected invariant: 4.5 (sealed promotion), 4.10 (no silent constitution change)
Active gate: Gate 0 — Canonical Kernel

## Summary

The guard's two sealed-promotion checks both target `daedalus/kairos/gated_writes.py`.
That module was refactored into a compatibility strangler on the consolidated
trunk, and the symbols the guard inspects no longer exist there. One check now
fails permanently; the other passes vacuously. Neither observes the promotion
authority that actually runs.

This is not a false alarm to be silenced. It is a guard that stopped watching its
subject and kept reporting.

## Measured evidence `[MEASURED]`

Worktree `C:/Users/nukei/Desktop/agent_env_g0`, branch `work/g0-trunk-20260817`
at `60b2bfe` (`origin/integration/g0-consolidated-20260807`), checked out LF.

### The trunk fails its own guard

```
$ python tools/iron_plan_guard.py verify (replaced by daedalus/hooks/, 2026-08-23)
IRON PLAN ERROR: daedalus/kairos/gated_writes.py exposes automatic promotion
exit: 1
```

`AGENTS.md` step 1 requires every agent to run this before any work. On the
consolidated trunk that step has been failing since the strangler landed.

### Why check 1 is permanently red

`tools/iron_plan_guard.py:711 (removed 2026-08-22)`

```python
if _literal_assignment(gated_tree, "AUTO_PROMOTE_LEVELS") != ("never",):
    errors.append("daedalus/kairos/gated_writes.py exposes automatic promotion")
```

**Correction (2026-08-17, after independent review).** An earlier revision of this
document claimed the constant "does not exist anywhere in the repository except in
this check", citing:

```
$ grep -rn "AUTO_PROMOTE_LEVELS" --include=*.py .
./tools/iron_plan_guard.py (removed 2026-08-23):711
```

That grep was wrong: `--include=*.py` excludes the retained blob. The constant
does exist, and it holds the sealed value:

```
daedalus/kairos/_gated_writes_legacy.py.src:1048:  AUTO_PROMOTE_LEVELS = ("never",)
daedalus/kairos/_gated_writes_legacy.py.src:1081:  def run_write_wave(...)
daedalus/kairos/_gated_writes_legacy.py.src:1130:  if auto_promote not in AUTO_PROMOTE_LEVELS:
```

At runtime:

```
AUTO_PROMOTE_LEVELS at runtime: ('never',)
run_write_wave present: True
```

**Nothing is unsealed.** The invariant holds at runtime; only the static check is
dead. This correction matters because it changes which remedy is right — see the
rejected alternatives below.

AST of the module's top level:

```
top-level assigns: ['_RETAINED_SOURCE_NAME', '_RETAINED_SOURCE_GIT_BLOB_SHA1',
                    '_retained_source', '_retained_source_bytes', '__doc__',
                    '_legacy', '__all__']
```

`_literal_assignment` can never return `("never",)`. The check cannot pass.

### Why check 2 is permanently green — the serious half

`tools/iron_plan_guard.py (removed 2026-08-22):715`

```python
if _function_calls_name(gated_tree, "run_write_wave", "promote_candidates"):
    errors.append("run_write_wave must not call promote_candidates automatically")
```

```
has run_write_wave def: False
```

There is no `run_write_wave` function in the module's AST, so the predicate is
always `False` and the check always passes. It would pass identically if the real
`run_write_wave` promoted on every call.

The reason is structural, not incidental: `gated_writes.py` now materialises its
implementation by `exec()`-ing a retained source blob verified by git-blob hash
(`gated_writes.py:40-45`). **Static AST analysis of this file cannot observe the
retained implementation at all.** Any guard phrased as "parse this file and look
for a function" is blind here by construction.

### Where promotion authority actually lives

`daedalus/kernel/promotion.py` and `daedalus/kernel/approvals.py`, neither of
which any guard check inspects:

- `authorize_promotion(...)` binds approval, evidence, candidates and a re-read
  target HEAD (`promotion.py:292`)
- `authorize_persisted_promotion(..., approval_ledger, owner_keyring, consumed_approval)`
  requires a persisted authenticated approval receipt (`promotion.py:363`)
- `ConsumedOwnerApproval` / `ApprovalLedger` (`approvals.py`)

The implementation is substantially *stronger* than what the guard was written
against. The invariant is being upheld; the guard simply is not the thing
upholding it. That distinction is the whole point of this proposal — the
repository is in better shape than the guard's output suggests, and worse shape
than the guard's silence on check 2 suggests.

## Proposed diff

Re-point both checks at the module that holds the authority, and make the second
check non-vacuous by asserting the symbol it depends on exists.

```diff
--- a/tools/iron_plan_guard.py
+++ b/tools/iron_plan_guard.py
@@
-    gated_tree = _python_tree(
-        root / "daedalus/kairos/gated_writes.py",
-        "daedalus/kairos/gated_writes.py",
-        errors,
-    )
-    if gated_tree is not None:
-        if _literal_assignment(gated_tree, "AUTO_PROMOTE_LEVELS") != ("never",):
-            errors.append(
-                "daedalus/kairos/gated_writes.py exposes automatic promotion"
-            )
-        if _function_calls_name(gated_tree, "run_write_wave", "promote_candidates"):
-            errors.append(
-                "run_write_wave must not call promote_candidates automatically"
-            )
+    promotion_rel = "daedalus/kernel/promotion.py"
+    promotion_tree = _python_tree(root / promotion_rel, promotion_rel, errors)
+    if promotion_tree is not None:
+        # Promotion must not be reachable without consuming an owner approval.
+        # Assert the gating symbols EXIST before asserting anything about them,
+        # so a rename cannot turn this check back into a vacuous pass.
+        required = ("authorize_promotion", "authorize_persisted_promotion")
+        defined = {
+            node.name
+            for node in promotion_tree.body
+            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
+        }
+        missing = [name for name in required if name not in defined]
+        if missing:
+            errors.append(
+                f"{promotion_rel} no longer defines the promotion authorization "
+                f"entrypoints {missing}; the sealed-promotion guard has lost its "
+                "subject and must be re-pointed, not deleted"
+            )
+        elif not _function_signature_requires(
+            promotion_tree, "authorize_persisted_promotion", "consumed_approval"
+        ):
+            errors.append(
+                f"{promotion_rel}:authorize_persisted_promotion no longer requires "
+                "a consumed owner approval"
+            )
```

`_function_signature_requires` is a small new helper (assert a named parameter is
present and has no default). It is added next to the existing `_function_calls_name`.

## Alternatives considered and rejected

**Delete both checks.** This is what "the guards only cause problems" would
produce in practice. Rejected: it removes the only mechanical statement in the
repository that promotion must consume an owner approval, and it removes it at
exactly the moment we learned the statement had stopped being enforced. The
failure mode this guards against is silent.

**Re-declare `AUTO_PROMOTE_LEVELS = ("never",)` literally in `gated_writes.py`**
so the existing check parses it. This is the cheapest fix and an independent
review recommended it. Rejected here, on reflection, for a reason the correction
above makes visible: the constant is *not* decorative — it is read at
`_gated_writes_legacy.py.src:1130` to gate the actual write wave. Declaring a
second copy in the outer module creates two sources for one policy value, and the
guard would then verify the copy while the blob keeps the one that decides. That
is a worse failure mode than a red guard: it reads green while watching the wrong
variable. It also does nothing for the `run_write_wave` check, which stays vacuous.

If the owner wants the trunk committable *today* and accepts that cost, the
re-declaration is a legitimate stopgap — but it should be labelled as one, with
this proposal still open behind it.

**Suppress the error and keep the check.** Rejected for the same reason —
a warning nobody can act on trains everyone to ignore the guard.

**Have the guard `exec()` or import `gated_writes` to inspect the real symbols.**
Rejected: a policy guard must not execute the code it polices. Re-pointing at the
statically analysable authority module achieves the same coverage without it.

## Migration, rollback, risk

No data migration, no schema change, no history rewrite. The change is confined
to one function in the guard plus one helper.

Rollback is a new amendment restoring the previous block, per section 15.

Residual risk, stated plainly: the retained-blob implementation inside
`gated_writes.py` remains outside static analysis. This proposal does **not**
close that. It moves the checks to where they can see something and makes the
blindness explicit rather than accidental. Covering the retained blob needs its
own work item and should not be smuggled in here.

## Verification required before this is accepted

1. `python tools/iron_plan_guard.py verify` exits 0 in the LF worktree.
2. A mutation test: rename `authorize_persisted_promotion` in a scratch copy and
   confirm the guard turns red. A check that cannot be made to fail is the defect
   this proposal exists to fix, so it must be demonstrated failing.
3. Remove the `consumed_approval` parameter in a scratch copy; confirm red.
4. `tests/test_iron_plan_guard.py (removed 2026-08-22)` extended with both mutation cases, and the
   existing suite still green.

## Related, not included

`tools/iron_plan_guard.py:1176` `git_command_is_mutating` classifies commands by
scanning the whole command string for tokens. Two consequences observed today:

- read-only `git merge-base` and `git branch --merged` are read as `git merge`
  (already reported by the previous session);
- a commit **message** containing the word `tests` or `docs` is read as a
  protected-directory argument and blocked, even when no such path is staged.
  Observed three times today; worked around with `git commit -F <file outside the repo>`.

This is a real usability defect and it is what makes the guards feel like pure
friction. It deserves its own proposal with its own evidence; folding it into a
sealed-promotion amendment would mix two unrelated changes in one record.
