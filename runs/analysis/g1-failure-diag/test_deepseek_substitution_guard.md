# Diagnosis: `tests/test_deepseek_substitution_guard.py::InventedImports::test_no_false_positives_across_the_real_tree`

Tree: `C:/Users/Administrator/daedalus`, branch `wip/g1-freeze-2026-08-31`.
HEAD before AND after every measurement below: **`54f0975398fd77120383c3af0ac5bb9291ef7064`** (unchanged — no VOID needed).
`git status --porcelain | wc -l` = 1 both before and after (this output directory).
Nested-worktree count both before and after: `.claude/worktrees/agent-*` = 6, `.daedalus_worktrees/*` = 2 (unchanged).

All temp artifacts under `/tmp/diag_deepseek/` (git-bash) == `C:\tmp\diag_deepseek\` (Windows/python view — the two tools resolve `/tmp` to different real directories on this box; every command below used the Windows-visible path for `.venv/Scripts/python.exe` invocations).

## TASK 1 — MEASURED count: exactly 134

```
cd /c/Users/Administrator/daedalus
.venv/Scripts/python.exe -m pytest tests/test_deepseek_substitution_guard.py -q
```
Output (excerpt):
```
AssertionError: Lists differ: [('cli.py', ["'daedalus.spine.envelope' does not define 'canonical_json'", ...])] != []
First list contains 134 additional elements.
1 failed, 24 passed in 6.71s–7.38s (3 runs)
```
**MEASURED: 134.** Matches the number given in the prompt; no drift.

## TASK 2 — is a third construct contributing? NO. Two known constructs explain 134 of 134.

The two constructs the `packet/g1-hier-13` fix (commit `b8c44a55`, message below) blames:

1. **Construct 1 — `sys.modules[__name__] = _owner` swap** in `daedalus/spine/{envelope,ledger,durability}.py`: each file hands its own module-object identity to a module under `daedalus/kernel/events/`, so at runtime `daedalus.spine.envelope` *is* the owner module object and every owner-defined name resolves through the old import path. The guard's `_exports()` reads the file **literally** (AST of `envelope.py`'s own body, which only defines `_sys`/`_owner`-style names), so it reports the module as not defining `canonical_json`, `canonical_sha`, etc., even though they resolve at runtime.
2. **Construct 2 — forwarding `ModuleType` facade** on `daedalus/spine/attempt.py`: a `class _AttemptFacade(ModuleType): def __getattr__(...)` is installed as `sys.modules[__name__].__class__`, so unknown attribute access on `daedalus.spine.attempt` is dynamically forwarded. `_exports()` again reads the file literally and cannot see this.

**Full enumeration** (script: `C:/tmp/diag_deepseek/enumerate.py`, run against `.venv/Scripts/python.exe` importing `daedalus.providers.deepseek._unresolved_first_party_imports` directly, same function the test calls):

```
TOTAL FILES SCANNED: 734
TOTAL OFFENDERS: 134
```

Per-file classification by which offending first-party module(s) appear in that file's `bad` list (script: `C:/tmp/diag_deepseek/per_file_classify.txt`):

| Bucket | Files | Definition |
|---|---:|---|
| Construct 1 only (envelope / ledger / durability) | 100 | every `bad` entry names one of `daedalus.spine.{envelope,ledger,durability}` |
| Construct 2 only (attempt facade) | 24 | every `bad` entry names `daedalus.spine.attempt` |
| Both constructs in the same file | 10 | file imports from both groups |
| **Unexplained (candidate third construct)** | **0** | any `bad` entry naming something outside the two groups above |
| **SUM** | **134** | equals TOTAL OFFENDERS |

Raw bad-import-string counts (secondary view, by offending module — one file can carry >1 bad import), `C:/tmp/diag_deepseek/module_breakdown.txt`:
```
Distinct offending modules: 4
112  daedalus.spine.envelope   (canonical_json, canonical_sha, current_trace_id, ...)
 91  daedalus.spine.attempt    (ATTEMPT_STATES, AttemptResult, GateResult, ...)
 69  daedalus.spine.ledger     (Intent, STATE_COMPLETED, STATE_FAILED, ...)
 18  daedalus.spine.durability (Gate0DurabilityError, enforce_gate0_durability, ...)
290  SUM (bad-import strings, not files)
```
All 4 offending modules fall inside exactly the two construct groups above; there is no fifth module and no `module '...' does not exist` (missing-module) shape at all — every offense is the `'<mod>' does not define '<name>'` shape, consistent with both being *alias-shaped*, not *invented-module*-shaped, failures.

**VERDICT: the two known constructs explain 134 of 134.** No third construct hides in the set. This is independently corroborated by `packet/g1-hier-13`'s own commit message (`b8c44a55`, quoted verbatim below), which reports the identical split measured at the branch's own base commit `4efa2a53`: *"the 134 split: 100 blamed the `sys.modules[__name__] = _owner` swap ... 24 blamed a second ... construct ... and 10 blamed both. Nothing else in the tree false-positived at all."* My independent re-measurement at current HEAD `54f09753` reproduces the exact same 100/24/10/134 partition.

## Environmental hypothesis (nested worktrees) — RULED OUT for this test

```
find /c/Users/Administrator/daedalus/daedalus -iname "*worktree*" -type d   # empty
find /c/Users/Administrator/daedalus/tests -iname "*worktree*" -type d     # empty
```
The nested duplicate checkouts live at the **repo root**: `.claude/worktrees/agent-*` (6 dirs) and `.daedalus_worktrees/*` (2 dirs). This test's walk is:
```python
files = [p for p in root.joinpath("daedalus").rglob("*.py") ...]   # recursive, but rooted at <repo>/daedalus
files += list(root.joinpath("tests").glob("test_*.py"))            # non-recursive, rooted at <repo>/tests
```
Both roots (`<repo>/daedalus`, `<repo>/tests`) contain **no** nested-worktree subdirectories, so neither walk can descend into `.claude/worktrees/` or `.daedalus_worktrees/` — those sit as siblings of `daedalus/` and `tests/` at the repo root, never inside them. This is structurally different from the `test_spend_coverage.py` sibling case, which walked `Path(ROOT).rglob("*.py")` starting at the repo root itself.

Confirmed by direct measurement, not just structural argument — the per-file classification above (`enumerate.py`) tagged every one of the 734 scanned files with `in_worktree = ".claude/worktrees" in rel or ".daedalus_worktrees" in rel`:

```
WORKTREE OFFENDERS: 0
CANONICAL OFFENDERS: 134
```

**Split: 0 worktree / 134 canonical, summing to 134.** The worktree hypothesis is refuted for this specific test; "134" is not a box artifact here — it is the real canonical-tree number, and the canonical-tree number and the measured number are identical.

## Determinism: deterministic across 3 runs

```
RUN 1 RC=1   ...  1 failed, 24 passed in 6.86s   134 additional elements
RUN 2 RC=1   ...  1 failed, 24 passed in 7.00s   134 additional elements
RUN 3 RC=1   ...  1 failed, 24 passed in 7.38s   134 additional elements
```
Count is exactly 134 all three times. `git status --porcelain | wc -l` and nested-worktree counts were re-checked after the 3 runs and after the enumeration script: unchanged (1 dirty file — this output dir — 6 + 2 worktree dirs) throughout. HEAD stayed `54f09753` throughout. No non-determinism observed; this guard's false-positive set is stable because it depends only on `daedalus/` and `tests/test_*.py`, which no other agent touched during this measurement window (confirmed by unchanged HEAD/status).

## First failing commit: PRE-EXISTING, predates the entire given range — not bisected within it

Both offending constructs, and the guard function itself, predate `f60ffd3d` — the **oldest** commit in the given first-parent list (`54f09753 ... f60ffd3d`, 26 commits):

```
git merge-base --is-ancestor 358f5b62 f60ffd3d   -> true   (358f5b62 = "refactor(events): move canonical
                                                              spine ownership under kernel", the commit
                                                              that introduced the sys.modules[__name__]=_owner
                                                              swap on envelope/ledger/durability)
git rev-list --count 358f5b62..f60ffd3d          -> 62     (62 commits ahead, well before the named range)

git show f60ffd3d:daedalus/spine/attempt.py | grep ModuleType/__getattr__/sys.modules
                                                  -> present at f60ffd3d already (the attempt.py facade
                                                     already exists at the oldest named commit)

git merge-base --is-ancestor 967c7c30 f60ffd3d   -> true   (introduced daedalus/lanes/checks.py's
                                                              unresolved_first_party_imports)
git merge-base --is-ancestor 8c7bc0c1 f60ffd3d   -> true   (shared write-lane baseline)
```
All four prerequisites for the failure (the guard function, the envelope/ledger/durability swap, the attempt.py facade, and the shared-baseline plumbing) are already present at `f60ffd3d`, the oldest commit named in the given range. **This is legitimately PRE-EXISTING relative to the whole named range** — none of `54f09753 b3cc415b 851ff43c dc321950 74008fab 3b78fe85 1262109e d7ba2a43 843367e3 9502bf09 1077d63c 0810d39e 4efa2a53 4c370f2a 6776731b f088f40e 515b5fce e7354c8f 36bfc3e4 aeef64bf baf17207 d9baa6c0 1959cda4 35c409fd 1b577a70 39039b7f f60ffd3d` introduced this failure; archaeology inside that range is moot and was not attempted further (would require walking commits older than `f60ffd3d`, out of the given scope).

## Fix sketch and owner

**Owner of the fix:** unmerged branch `packet/g1-hier-13` (author KTY, `Co-Authored-By: Claude Opus 5 (1M context)`), two commits on top of `4efa2a53`:

- `b8c44a55` *"fix(lanes): teach the write gate the module alias instead of bending the code to it"* — adds `_alias_target()` (recognizes construct 1: a module-scope `sys.modules[__name__] = <imported name>` assignment) and `_installs_dynamic_module_protocol()` (recognizes construct 2: a module-scope class with `__getattr__`/`__getattribute__` retyped onto the module's own `sys.modules` slot) to `daedalus/lanes/checks.py`'s `_exports()`. Both resolve through to the aliased owner (or mark opaque) instead of reading the aliasing file literally. Commit message reports the identical 100/24/10/134 split independently measured here, and "offender census 734 files: 134 -> 0".
- `3e212da8` *"fix(lanes): make the retype detector flow-sensitive; a hop never inherits fail-open"* — a same-day **security review follow-up** on `b8c44a55` that found the first version's R2 (dynamic-module-protocol detection) was flow-INsensitive (order-independent name collection instead of a single ordered walk), permissive on 6 adversarial constructs (e.g., a hook class shadowed by a later hookless same-named class), all 6 reproduced as working exploits against `b8c44a55` and fixed by rewriting the detector as a single ordered walk with last-write-wins semantics. Also closes a fail-open on unparsable alias owners and hardens self-alias detection to `Path.samefile` (case/8.3/junction-safe). Confirms "offender census 734 files: still 0" after the hardening.

**Sketch:** the false positive is entirely a static-analysis blind spot in `_exports()` (`daedalus/lanes/checks.py`) — it AST-reads a module's own top-level body and has no notion of a module that retypes or reassigns its own `sys.modules[__name__]` slot to point at a different owner object. The fix teaches `_exports()` to recognize exactly these two aliasing idioms (statically, no execution) and either resolve names through the owner or fall back to `opaque=True`, at parity with the existing PEP 562 (`__getattr__`) handling the gate already grants 11 other modules.

## Is the `g1-hier-13` fix complete?

**Yes, for the false-positive set measured here.** Both commits together (`b8c44a55` + `3e212da8`) cover all 134 offenders — my independent re-enumeration at HEAD found 0 files unexplained by the two constructs the fix targets, matching the fix's own before/after claim ("134 -> 0") exactly. The second commit exists specifically because the *first* version of the fix, while covering all 134 false positives, introduced 6 new **false negatives** (security regressions: invented imports let through) that a same-day adversarial security review found and closed — so "complete" is with respect to *this* false-positive census; the branch's own commit message additionally records residual, deliberately-not-fixed gaps outside this test's scope (directory-junction escapes of `_module_path`, and opacity being transitively reachable through any PEP-562 module) as known, retained limitations, not oversights.

Since `packet/g1-hier-13` is **unmerged**, main's `54f09753` still has all 134 false positives and the test still fails there.
