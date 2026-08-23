# Amendment proposal 002 — guard repairability

Status: **PROPOSED — awaiting owner approval.** Nothing in this document has been
applied. Per master plan §15 step 1, this is the proposal; steps 2–7 (approval,
`DAEDALUS_IRON_PLAN_AMENDMENT`, revision bump, ledger record, atomic update,
verification) have not been performed.

Base plan revision: 1
Base plan sha256: `a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4`
Proposed result revision: 2
Owner: repository owner (@KTY137)
Scope: `governance` — the guard only. **No invariant, prior, gate, or plan
sentence changes.** All three points are defects in the *mechanism* that
projects the plan, not in the plan.

---

## Summary

Three measured defects in `tools/iron_plan_guard.py` and
`tests/test_iron_plan_guard.py (removed 2026-08-22)`. All three are protected artifacts, so no
ordinary task can repair them; §15 makes this an amendment.

| # | Defect | Effect today |
|---|---|---|
| A | the CI-history test reads its baseline from live `HEAD` | test fails; the adoption check tests nothing |
| B | `verify()` can print a repair command the guard itself denies | unrecoverable state; only escape is the amendment token |
| C | every parent directory of a protected artifact is treated as protected | `git add docs/` and `git commit -m "docs: …"` denied |

None of these weakens a protection. A and C *restore* checks that are currently
either vacuous (A) or displaced onto the wrong target (C); B removes a state in
which the guard cannot be repaired at all.

---

## Point A — the CI-history test reads its baseline from live HEAD

### What is wrong

`tests/test_iron_plan_guard.py:682`:

```python
old_plan = run_git(ROOT, "show", f"HEAD:{guard.PLAN_REL}") + "\n"
```

The test builds a synthetic repository whose *base* commit is supposed to hold
the **pre-adoption** plan, then commits the adoption on top and asserts
`verify_base()` accepts it. It sources that base from live `HEAD`.

Before 15fbcd2, `HEAD` held revision 0 and the test was meaningful. Since
15fbcd2, `HEAD` holds revision 1 — the same plan the test then commits as the
"adoption". The test compares the new plan with itself.

### Measured

```
$ python -m pytest tests/test_iron_plan_guard.py -k ci_history_check -q
AssertionError: Lists differ:
  ['initial adoption does not change the complete policy bundle: docs/IKARUS_ARIADNE_MASTER_PLAN.md',
   'initial adoption base digest does not match base revision'] != []
1 failed, 47 deselected
```

Both messages are `verify_base()` correctly observing that nothing changed.
The guard is right; the test is wrong.

This is not merely a red test. Any future adoption-path regression is now
invisible: the assertion can only pass again if `HEAD` stops matching the
adoption commit, which is the opposite of the condition it means to check.

### Why a fixture and not a commit pin

The base cannot be arbitrary. `verify_base()` cross-checks it against the
committed ledger record, which pins

```
base_plan_sha256 = f1acad3c9b2376e6ef0e88dbf6b3de82e9367232c361ba9f0c1da4d3ddf82cfa
```

Verified: the revision-0 plan at `946db82` is 59 495 bytes and hashes to exactly
that value. So the test needs those bytes, not merely *some* older plan.

### Proposed change

Add `tests/fixtures/iron_plan_revision_0.md` — the revision-0 plan verbatim
(`git show 946db82:docs/IKARUS_ARIADNE_MASTER_PLAN.md`, 59 495 bytes) — and:

```diff
-            old_plan = run_git(ROOT, "show", f"HEAD:{guard.PLAN_REL}") + "\n"
+            # The base must be the exact pre-adoption bytes: the committed
+            # ledger record pins base_plan_sha256 to their digest. Sourcing
+            # this from live HEAD made the test compare the adopted plan with
+            # itself the moment adoption landed (15fbcd2).
+            fixture = Path(__file__).parent / "fixtures" / "iron_plan_revision_0.md"
+            old_plan = fixture.read_text(encoding="utf-8")
+            self.assertEqual(
+                hashlib.sha256(old_plan.encode("utf-8")).hexdigest(),
+                json.loads(
+                    (ROOT / guard.LEDGER_REL).read_text(encoding="utf-8")
+                )["base_plan_sha256"],
+                "revision-0 fixture no longer matches the ledger's recorded base",
+            )
```

The added assertion is the point: the fixture cannot silently rot, because the
test fails loudly if it ever stops matching the ledger.

### Alternatives considered

- **Pin the commit** (`git show 946db82:…`). Rejected: a literal sha in a test
  breaks under shallow clone, filter-branch, or any history rewrite — and
  history rewrite is exactly what this test exists to detect.
- **Synthesise both plan and ledger.** Fully isolates the test from repository
  history, but stops exercising the *real* accepted record. Rejected as a wider
  change than the defect warrants; worth revisiting separately.

---

## Point B — the guard can enter a state only a command it denies can leave

### What is wrong

`verify()` (lines 726–738) checks the git index mode of the two hook scripts and
emits, verbatim:

```
.githooks/pre-commit (removed 2026-08-22) is staged/tracked with mode 100644, not executable
(run: git add --chmod=+x .githooks/pre-commit (removed 2026-08-22) .githooks/commit-msg (removed 2026-08-22))
```

That printed repair names two protected paths. `protected_targets()` therefore
returns them, and the PreToolUse hook denies the command.

There is one escape hatch and it does not cover this case.
`activation_repairs_only_error` (line 1605) exempts `git config --local
core.hooksPath .githooks`, but **only when every live error is the hooksPath
error**. A mode error is not, so the exemption is off — for the activation
command too.

### Measured

`verify()` is clean today; the mode drift was simulated by forcing
`_git_index_mode` to return `100644`, which is what Git does on Windows when
`core.filemode` is false and the file is re-added. That is the exact condition
the check exists to catch.

```
verify() now reports 2 error(s), both about the mode.

DENY (fail-closed: verification broken)   git add --chmod=+x .githooks/pre-commit (removed 2026-08-22) .githooks/commit-msg (removed 2026-08-22)
DENY (fail-closed: verification broken)   git config --local core.hooksPath .githooks
DENY (fail-closed: verification broken)   git update-index --chmod=+x .githooks/pre-commit (removed 2026-08-22)
DENY (fail-closed: verification broken)   git commit -m "fix the mode"
allow                                     python -m daedalus.arch_memory
```

Every effectful path is closed, including the guard's own printed instruction
and the one command that was supposed to be the escape. The remaining exit is
`DAEDALUS_IRON_PLAN_AMENDMENT` — i.e. an owner-approved constitutional
amendment to restore a file permission bit.

Read-only work continues, so this satisfies "fail-closed protected effects,
fail-open read-only inspection" in the letter. It still leaves a reachable state
with no in-harness repair.

### Proposed change

Generalise the single hard-coded exemption into a small closed table: an error
that the guard knows how to repair declares the exact command that repairs it.

```diff
+# An error that names its own repair. The guard must never print an
+# instruction it then denies: a state whose only exit is a constitutional
+# amendment is a defect, not a protection. Exemption stays narrow --
+# the command must match a pattern here EXACTLY, and every live error must
+# be one of these. Any other error keeps every effectful tool closed.
+SELF_REPAIR = (
+    (HOOKS_ACTIVATION_COMMAND, "local core.hooksPath is not .githooks"),
+    (HOOK_MODE_REPAIR_COMMAND, "is staged/tracked with mode"),
+)
```

```diff
-        activation = is_exact_hooks_activation(shell_command(tool_input))
-        activation_repairs_only_error = bool(errors) and all(
-            error.startswith("local core.hooksPath is not .githooks")
-            for error in errors
-        )
+        repair = matching_self_repair(shell_command(tool_input))
+        repairs_every_live_error = bool(errors) and all(
+            any(marker in error for _, marker in SELF_REPAIR) for error in errors
+        )
```

with the deny condition becoming
`… and not (repair and repairs_every_live_error)`, and the protected-target
branch skipping the paths that this exact repair command is defined to touch.

`HOOK_MODE_REPAIR_COMMAND` is a `fullmatch` anchor over the literal repair
string, mirroring `HOOKS_ACTIVATION_COMMAND`. It admits one command and no
family of commands.

### What this does not open

- The repair set is two entries, each an exact full-string match.
- Both remain denied whenever any error outside the set is live.
- `pre_commit()` still refuses to commit while `verify()` has errors, so a
  repaired mode still cannot smuggle anything past the commit gate.
- Nothing about protected *content* changes; `--chmod=+x` alters a mode bit and
  cannot alter a byte of policy.

### Alternatives considered

- **Stop printing the repair.** Honest but worse: the state stays unrecoverable
  and merely stops advertising it.
- **Drop the index-mode check.** Rejected: a non-executable hook is a real
  bypass on POSIX, which is why the check exists.
- **Let any command touching only `.githooks` through when verify() is broken.**
  Too wide — that admits editing the hook bodies.

---

## Point C — every parent directory of a protected artifact is locked

### What is wrong

`protected_parent_paths()` (line 998) walks every protected path and returns
each ancestor directory. `protected_targets()` (line 1366) then flags any
mutating command in which one of them appears as a standalone token.

Measured output of `protected_parent_paths()`:

```
.agents/skills/enforce-iron-plan/agents   .agentenv   .git       docs
.agents/skills/enforce-iron-plan          .agents     .githooks  templates
.agents/skills                            .claude     .github    tests
.git/iron-plan-hook-state                 .codex      daedalus   tools
.github/workflows                         daedalus/kairos
```

`docs`, `tests`, `tools`, `daedalus`, `templates` are ordinary working
directories that happen to contain one policy file each. Locking them locks the
repository.

### Measured — including why the owner could not commit

```
DENY  git add docs/
DENY  git add tests/
DENY  git add tools/
DENY  git add daedalus/
DENY  git add docs/ tests/ daedalus/
DENY  git commit -m "docs(handoff): four stale claims corrected"
DENY  git commit -m "tests: cover the funnel"
DENY  git commit -m "chore(tools): bump the guard"
DENY  git commit -m "refactor(daedalus): fold the router"
DENY  git commit -m "fix: stop writing to docs"
DENY  git commit -m "feat: add a templates dir"

pass  git add -A
pass  git add .
pass  git add docs/research/GEPA_REFLECTIVE_EVOLUTION.md
pass  git commit -m "feat(gate0): canonical contracts"
```

Two separate defects sit in that table.

**C1 — a commit message is scanned as if it were a pathspec.** The check runs
over raw command text, so the word `docs` inside `-m "docs(handoff): …"` is read
as a path. Every conventional-commit prefix that collides with a directory name
— `docs:`, `tests:`, `tools:`, and any message merely *mentioning* one — is
refused. This is the immediate cause of tonight's blocked commits.

**C2 — the rule is inverted with respect to risk.** `git add docs/` is denied
while `git add -A` and `git add .` pass. The narrow, auditable command is
blocked; the one that stages every protected artifact in the repository is not.
The rule does not achieve its own stated goal.

### Why removing it loses no protection

The real defence is path-accurate and lives at commit time, where the set of
staged paths is known exactly rather than guessed from a command string.
`pre_commit()` computes `staged.intersection(PROTECTED_PATHS)` and requires
`DAEDALUS_IRON_PLAN_AMENDMENT` to match the HEAD plan digest, plus atomic
plan+ledger staging and exactly one appended record. `commit_msg()` independently
requires a protected change to be labelled `amendment` or `adoption`.

`git add -A` already proves the point: it stages protected files today, passes
the directory rule, and is still stopped at commit. The directory rule adds no
coverage that these two do not already have — it only fires on a *different*,
mostly innocent, set of commands.

### Proposed change

**C1** — strip message-carrying arguments before path extraction:

```diff
+# -m/-F values are prose, not pathspecs. Scanning them made a conventional
+# commit prefix ("docs:", "tests:", "chore(tools):") read as a protected
+# path and refused the commit. Everything after `--` stays scanned: there
+# a pathspec is exactly what it is.
+MESSAGE_ARGUMENT = re.compile(
+    r"""(?xi)(?:^|\s)(?:-m|-F|--message|--file)(?:\s+|=)(?:"[^"]*"|'[^']*'|\S+)"""
+)
```

applied in `protected_targets()` and `governed_targets()` before
`command_paths()`.

**C2** — restrict the directory rule to directories whose *entire* contents are
policy artifacts:

```diff
-def protected_parent_paths() -> tuple[str, ...]:
+POLICY_ONLY_DIRECTORIES = (
+    ".agentenv",
+    ".agents/skills/enforce-iron-plan",
+    ".githooks",
+    ".github/workflows",
+    ".git/iron-plan-hook-state",
+)
```

`docs`, `tests`, `tools`, `daedalus`, `daedalus/kairos`, `templates`,
`.claude`, `.codex`, `.github`, `.git`, `.agents`, `.agents/skills` drop out:
each holds ordinary work, and each individual protected file inside them stays
protected by exact path as before.

### Alternatives considered

- **Keep the rule, exempt `-m` only.** Fixes tonight's symptom, leaves the
  inversion: `git add docs/` still denied, `git add -A` still allowed.
- **Extend it to `-A`/`.` as well.** Would make it consistent, but consistently
  wrong — it forbids ordinary staging in every governed directory and pushes
  people toward `--no-verify`, which the plan already names as outside the
  guard's reach (§1).
- **Parse pathspecs properly per git subcommand.** The correct long-term
  answer, and much larger. The staged-path check at commit time already *is*
  that answer, computed by git itself.

---

## Affected invariants and priors

None. §4 invariants 1–10 are untouched; no gate definition, kill criterion, or
research prior changes. Invariant 10 ("no silent constitution change") is the
reason this is an amendment rather than a fix: the artifacts are protected, so
the change must be recorded even though the plan's meaning is unchanged.

## Migration

None. No stored artifact, receipt, ledger record, or event changes shape. The
new fixture is additive.

## Rollback

A subsequent amendment restoring the three code sites and deleting the fixture.
Per §15 rollback is a new amendment, never a history rewrite.

## Evidence required before acceptance

1. `python tools/iron_plan_guard.py verify` → OK.
2. `python -m pytest tests/test_iron_plan_guard.py -q` → all pass, including the
   repaired `test_ci_history_check_accepts_adoption_and_rejects_rewrite`.
3. New regression tests, each failing before the change:
   - the revision-0 fixture digest equals the ledger's `base_plan_sha256`;
   - with a simulated `100644` hook mode, the printed repair command is
     permitted and every other mutating command is still denied;
   - `git commit -m "docs(handoff): …"` is permitted while
     `git add docs/IKARUS_ARIADNE_MASTER_PLAN.md` is still denied;
   - `git add -A` staging a protected file is still refused by `pre_commit()`.
4. `python -m pytest tests/ -k "kernel_contracts or artifact_store or
   effect_boundary or reference_audit or funnel_truth or iron_plan or
   self_policy or substitution" -q` → no new failures.

---

## Recorded, not proposed: the guard checks a classification only for presence

Raised by the owner; **not part of this amendment.** Recorded here so the
decision is deliberate rather than forgotten.

`commit_msg()` accepts any of `aligned|experiment|amendment|adoption` and
verifies only that the trailer *exists* and that the gate number matches the
plan. The single semantic tie-in is that a staged protected path forces
`amendment` or `adoption`. Nothing checks whether a commit labelled `aligned`
actually was.

Tonight's four commits, as landed:

| commit | trailer | remark |
|---|---|---|
| 15fbcd2 | `Iron-Plan: adoption` | accepted; `adoption` is a guard token that §14 does not list |
| 536f91e | `Iron-Plan: aligned` | unverified by any mechanism |
| 967c7c3 | `Iron-Plan: aligned` | unverified by any mechanism |
| 7064c3b | `Iron-Plan: experiment` | §14 also requires spec, scope, budget, evaluator, expiry; the guard checks for none of them |

Two observable gaps: the guard's token set (`adoption`) is wider than the plan's
(§14 names three), and an `experiment` trailer carries none of the five
attributes §14 demands of an experiment.

A mechanical check of *correctness* of a classification is not obviously
possible. A mechanical check of *completeness* is: an `experiment` trailer could
be required to name its spec, and the token sets could be reconciled. Both are
amendment-shaped and belong in their own proposal, with the question of whether
`adoption` should exist at all settled first.
