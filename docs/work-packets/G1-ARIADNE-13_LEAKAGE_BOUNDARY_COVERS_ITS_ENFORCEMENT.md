# G1-ARIADNE-13 — the leakage boundary did not cover its own enforcement

Packet ID: `G1-ARIADNE-13`
Artifact role: `primary`
Active gate: Gate 1
Classification: `ALIGNED`
Owner: repository owner
Base revision: `02c2c527e936c17f62f84bc54d8cbfd13c4b154c`
Dependencies: G1-ARIADNE-10, G1-IKARUS-49

Stacked on G1-IKARUS-49 (PR #368) because both change `campaign.py`.

## Primary acceptance claim

Every module that **enforces** the self-Renovation leakage boundary is behind
it, and the guard is bound to the load-bearing symbol rather than to a path
string, so moving `promote_candidates` — or any of the five others — turns a
test red instead of silently un-protecting it.

## What was measured

On `main` at `5cb2b2d4`, `protected_prefix_for` answered **UNPROTECTED** for
every one of these:

| path | what it holds |
| --- | --- |
| `daedalus/kairos/gated_writes.py` | `promote_candidates` — the callable that puts a candidate into the checkout. Only `daedalus/kernel/promotion*` was covered, and that is the contracts, not the callable |
| `daedalus/config.py` | `WRITE_WAVE_POLICY_LEVELS = ("never",)` and `DEFAULT_WRITE_WAVE_POLICY` — the constants that stop a candidate writing at all |
| `daedalus/runtimes/computer_ariadne.py` | the campaign tool door: the leakage checks themselves, and the hardcoded `applied: False` |
| `daedalus/runtimes/computer.py` | `ComputerService._admit_release_capability`, the fence that admits the campaign tool |
| `daedalus/orchestration/ikarus/computer_schedule.py` | `_repeat_permission`, which decides whether a recurring campaign series continues |

and the boundary's own suites, because the `tests/test_ariadne` prefix covers
four files and misses `tests/kernel/test_sealed_promotion.py`,
`tests/runtimes/test_computer_ariadne.py`,
`tests/test_ikarus_computer_loop_ariadne.py` and both schedule suites.

## Why this is defence in depth and not a breach

A self-Renovation candidate could **nominate** an edit to its own door.
Landing one still required a consumed, authenticated `OwnerApproval`
re-checked against live HEAD, the planner has no promotion tool in its
inventory, and the tool door hardcodes `applied: False`. All three of those are
code and all three are reachable, so nothing here was one step from a merge.

It is worth closing anyway, and closing it *before* campaigns run unattended
rather than after: a candidate that can nominate a change to its own boundary is
one approval away from a candidate that has no boundary, and an owner approving
a batch at 3 a.m. is exactly the reviewer that shape is designed to slip past.
The repository's own review rules class "candidate access to its evaluator or
policy" as release-blocking; this is the same defect one indirection out.

## What changed

1. **Five module prefixes and four test prefixes** added to
   `SELF_RENOVATION_PROTECTED_PREFIXES`. Protection is by file where the risk is
   a specific constant or callable, and by directory (`tests/kernel/`) where the
   whole thing is boundary machinery.
2. **The guard is bound to the symbol.** `LOAD_BEARING` names six
   `(module, symbol, what it does)` triples; the test asks the interpreter which
   file defines each name and requires that file to be protected. A path list
   goes stale in silence — this does not. It earned its keep immediately: it
   caught a stale reference in its own first run, because
   `_admit_release_capability` is a method on `ComputerService`, not a
   module-level function.

## The cost, stated

Self-Renovation can no longer propose an improvement to any of these files.
Improving them stays human work. That is a real narrowing of the strand and the
right trade: the alternative is a boundary that protects its definition and not
its enforcement, which protects a document.

This list is **stricter** than what plan section 8.1 names. Section 0 permits
that explicitly — for effects the stricter mechanical policy wins — and the
plan is a floor for protection rather than a ceiling. No plan text changes, no
amendment is required, and nothing here relaxes any existing rule.

## Scope

In scope: `daedalus/ariadne/campaign.py` (the prefix tuple and its comment),
`tests/test_ariadne_leakage_boundary.py`, this document and the packet index.
Forbidden: the master plan, its amendment chain, `AGENTS.md`, the kill switch,
egress admission, write roots, secret and tool policy, and every path held by
another lane (`apps/web/dist/**`, `.gitignore`,
`apps/web/src-tauri/Cargo.toml`, `tests/test_desktop_*.py`, `vault/**`).

## Contracts and behavior

`SELF_RENOVATION_PROTECTED_PREFIXES` gains nine entries and
`protected_prefix_for` keeps its signature and semantics unchanged. No contract
is added, changed or deleted; no effect, lease, write root, evidence shape or
promotion path moves. The only observable difference is that nine more relative
paths answer with a prefix instead of `None`, which makes `_admit_target_path`
refuse them before the repository, HEAD or any effect lease is observed — the
same pure-refusal discipline the ignored-root rule already has.

## Acceptance matrix

1. each of the nine newly covered paths is refused by `_admit_target_path`,
   before the repository, HEAD or any effect lease is observed;
2. the refusal names the prefix it fell under;
3. the module defining each of the six load-bearing symbols is protected, and
   the assertion is made through the interpreter rather than against a literal;
4. the widening stays narrow: `computer_files.py`, `computer_desktop.py`,
   `computer_daedalus.py`, `computer_loop.py`, `orchestration/loop.py`,
   `kairos/scheduler.py`, `health.py` and their tests remain admissible
   self-Renovation subjects;
5. the ignored-root refusal keeps its own wording and precedence;
6. removing any one of the nine prefixes turns a named test red.

## Evidence, expected failures and review

`tests/test_ariadne_leakage_boundary.py`, 82 passed. Mutation table: 9/9 new
prefixes proven load-bearing — removing any one of them turns the suite red.

## What this does NOT close

**The list is still an enumeration**, and an enumeration of a growing tree
drifts. The symbol-bound test converts *one* class of drift — a symbol moving
out of a protected file — into a red test. It does not catch a *new* file
acquiring boundary responsibility. The structural answer is to derive the set
from what the code does rather than from a literal, which needs an import trace
this packet does not build. Recorded as the next question, not patched with a
longer list.

**`python.promote_candidates` remains `Wiring.LOCAL_GUARDS`** in the effect
registry rather than `CENTRAL`, with a stated migration debt. That is
pre-existing Gate-0 debt and a separate, larger packet.

## Migration and rollback

Revert the commit. No stored artifact changes shape; the boundary is computed,
never persisted. A campaign that named one of these paths would previously have
run and would now refuse before any effect — the correct direction, and no
existing campaign in the tree names one.
