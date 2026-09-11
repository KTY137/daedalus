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

The modules this packet found to **enforce** the self-Renovation leakage
boundary are behind it, together with the package door in front of it and the
two conftests under its protected suites; and the guard is bound to where each
load-bearing symbol is **actually defined** — `__code__.co_filename` for a
callable, a top-level binding in the named module's source for a constant — so
moving one out of a protected file turns a test red even when the move is
disguised by a re-export, a rewritten `__module__`, or a `functools.wraps`
decorator.

It does **not** claim that every enforcing module is covered. One is known to
be admissible and is named below.

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
2. **The guard is bound to the defining module of the symbol.**
   `LOAD_BEARING` names six `(module, symbol, what it does)` triples; the test
   walks the dotted name, reads `__module__` off what it finds, and requires
   the file of *that* module to be protected. A path list goes stale in
   silence — this does not.

   The first version asked `imported.__file__`, which is the file of the module
   *named in the tuple* rather than the file that *defines* the symbol. It was
   a name-**presence** test wearing a definition-site test's description, and an
   adversarial pass defeated it in the ordinary way: move `promote_candidates`
   into a new admissible module and re-export it from the old one — the only
   shape that keeps existing imports working — and 82 tests stayed green with
   the promotion callable sitting where a candidate may edit it. Now the same
   mutation fails and names the file.

   It earned its keep twice over: on its very first run it caught a stale
   reference in its own list, because `_admit_release_capability` is a method on
   `ComputerService`, not a module-level function.

3. **The binding is to the definition, not to self-report.** Round 1 replaced
   `imported.__file__` with `__module__`. Round 2 defeated that four ways:
   `__module__` is a writable string that lies in one line; a `functools.wraps`
   decorator copies it from an admissible module without lying at all; and
   **three of the six rows are constants, which have no `__module__` at all**,
   so the `or module_name` fallback preserved the original name-presence
   behaviour verbatim — including for the row labelled "this boundary itself",
   whose own tuple could be moved to an admissible module with 89 tests green.

   Two mechanisms now, because a callable and a constant are different objects.
   A callable carries `__code__.co_filename`, baked in at compile time and not
   forgeable by assignment. A constant carries no origin at all, so nothing
   attribute-based can work: the test parses the named module's source and
   requires a **top-level binding** of the name, which a re-export
   (`ImportFrom`) is not.

4. **The values are pinned, not only the file.** Nothing in the repository
   asserted `WRITE_WAVE_POLICY_LEVELS` or `DEFAULT_WRITE_WAVE_POLICY`. Opening
   the closed set to `("never", "apply")` and flipping the default left every
   test green, so `LOAD_BEARING`'s description — "the closed set that has no
   level except 'never'" — was a claim no test made. Protecting the file that
   holds a constant is worth little if nothing notices the constant changing.

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
drifts. The symbol-bound test converts one class of drift — a symbol moving out
of a protected file, with or without a re-export — into a red test. It does not
catch a *new* file acquiring boundary responsibility. The structural answer is
to derive the set from what the code does rather than from a literal, which
needs an import trace this packet does not build. Recorded as the next question,
not patched with a longer list.

**One enforcement surface remains admissible: `daedalus/interfaces/http/web_api.py`.**
Its `_campaign_runner()` at line 222 injects `protected_prefix_for` into the
`CampaignRunner`, and both of the tool door's checks use that injected callable,
so a candidate editing only that file disables both. Round 2 measured exactly
what survives:

```
LEG 1  door, canonical checker     -> refused: leakage boundary: daedalus/spine/
LEG 2  door, checker stubbed None  -> ADMITTED 'daedalus/spine/effect_boundary.py'
LEG 3  run_campaign(), same target -> refused, and left nothing in repo_root
```

So the loss is the **refuse-before-any-effect** property, not the boundary
itself: `_admit_target_path` in the protected `campaign.py` still refuses, with
no trace left behind. That is why this is left open.

**Round 1 recorded a false reason for leaving it open, and round 2 caught it.**
The packet said a prefix would have to cover `computer_loop.py`, which is on the
must-stay-admissible list. It would not: `computer_loop.py` owns only the
registry slot, and the injection lives in `web_api.py`, which is not on that
list. A prefix there contradicts nothing. The real argument is cost — it is a
large HTTP interface file with no other relationship to this boundary — and
that argument has to be made on its own terms rather than borrowed from a file
that is not involved.

`tests/runtimes/test_computer_service.py` **is no longer deferred.** Round 1
recorded it as admissible-and-accepted; round 2 pointed out that by this
packet's own cost standard — 87 files accepted for `tests/kernel/` on a
four-area justification — one more file is strictly cheaper per unit of
protection, and that the load-bearing repair was the conftest beside it anyway.
Both are protected now.

**`tests/kernel/` is over-broad in the safe direction.** It covers 87 files for
a justification naming four kernel areas, and roughly thirty of them import no
protected module. That costs self-Renovation subjects rather than safety, but it
produces an odd asymmetry worth naming: `daedalus/kernel/attempts.py` is
editable while `tests/kernel/test_attempt_lease.py` is not.

**`python.promote_candidates` remains `Wiring.LOCAL_GUARDS`** in the effect
registry rather than `CENTRAL`, with a stated migration debt. That is
pre-existing Gate-0 debt and a separate, larger packet.

## Migration and rollback

Revert the commit. No stored artifact changes shape; the boundary is computed,
never persisted. A campaign that named one of these paths would previously have
run and would now refuse before any effect — the correct direction, and no
existing campaign in the tree names one.


## Adversarial round 1 (2026-09-11, `83b2d139`)

**Odysseus: may merge, after correcting the primary acceptance claim.** The
change is purely additive, all nine prefixes reproduced load-bearing in an
isolated copy, and 204 tests across the newly protected suites pass. Both doors
were confirmed to refuse before the repository, HEAD or any effect lease is
observed — 18 executed probes with `read_repository_source`, `subprocess`,
`os.stat`, `Path.exists` and `Path.open` all booby-trapped. No unintended
`startswith` extension exists across all 6379 tracked files.

| # | finding | repair |
| --- | --- | --- |
| defeated claim | the symbol test asked `imported.__file__` — the module *named*, not the module that *defines*. Move-plus-re-export left it green with the callable in an admissible file | binds to `__module__` via `sys.modules`; the same mutation now fails and names the file |
| D1 (high) | `daedalus/ariadne/__init__.py` was **admissible** and re-exports `run_campaign`. Both the HTTP door and the tool-door runner resolve through it, so one conditional shim there disabled the entire boundary — all nine additions included — with this suite green | the whole `daedalus/ariadne/` package is protected |
| D2 (high) | `tests/conftest.py` was **admissible** and every protected suite loads it. One edit and the protected suites collected nothing: "no tests ran in 0.23s" — it removes the evidence rather than changing it | protected |
| mutation C | nothing in the tree pinned the write-wave policy **values**; opening the closed set and flipping the default left 82 tests green | pinned |

D1 and D2 are not the "a new file acquires boundary responsibility" case this
packet excused itself from. Neither file is new or peripheral: one is the
package door in front of the protected module, the other the conftest root under
every protected suite. They are the same class this packet set out to close,
findable the same way — ask what *enforces*, not what *defines* — and they were
missed.

**Severity assessment confirmed.** All three legs of "defence in depth, not a
breach" hold on measurement: `promote_candidates` fails closed without an
approval ledger and re-authenticates under the promotion lock against a freshly
resolved live HEAD; the planner's tool inventory contains no promotion tool
(worth stating precisely: `FILE_TOOLS` *does* include `file.write`, so "no
promotion tool" is true and "no write capability" is not); `applied: False` is a
literal, not derived. That assessment stood for the six paths the packet found —
it did **not** stand for D1 and D2, where the bypass needs no promotion at all.


## Adversarial round 2 (2026-09-11, `510e6952`)

**Odysseus: `block` — on the claim, not the code.** "The prefix widening itself
is additive, load-bearing under mutation, and regression-free; I have no
objection to the code." Every claim below was executed against an isolated copy.

### The round-1 repair was defeated four more ways

| # | shape | why it worked |
| --- | --- | --- |
| A2 | A1 plus one line: `promote_candidates.__module__ = "daedalus.kairos.gated_writes"` | `__module__` is a writable string |
| A3 | a `functools.wraps` decorator applied from an admissible module | `wraps` copies `__module__`; **no deception at all** |
| A4 | move `WRITE_WAVE_POLICY_LEVELS` and `DEFAULT_WRITE_WAVE_POLICY` and re-export | a constant has no `__module__`, so the fallback used the named module |
| A6 | move **`SELF_RENOVATION_PROTECTED_PREFIXES` itself** and re-export | same, on the row labelled "this boundary itself" |

A4 and A6 required no deception either. Three of the six rows are constants, and
for those the round-1 guard was the round-0 guard with a longer comment.

**Repaired and re-measured, all five defeats rebuilt against the repair:**

```
baseline (unmutated copy)                             rc=0  93 passed
A1 move + re-export                                   RED
A2 A1 + a lying __module__                            RED
A3 functools.wraps from an admissible module          RED
A4 move the write-wave constants + re-export          RED
A6 move THIS BOUNDARY'S OWN tuple + re-export         RED
5/5 defeats closed
```

### D2 survived one directory down, on this packet's own protected suite

`tests/runtimes/conftest.py` was admissible while
`tests/runtimes/test_computer_ariadne.py` is protected here. Eleven lines of
`pytest_collection_modifyitems`:

```
BEFORE  tests/runtimes/test_computer_ariadne.py   rc=0   66 passed
AFTER   tests/runtimes/test_computer_ariadne.py   rc=5   no tests ran in 0.35s
```

That is D2 verbatim — it removes the evidence rather than changing it — and the
round-1 fix stopped one level too high. Both that conftest and
`test_computer_service.py` are protected now.

### A comment of mine that was backwards

The needle in `test_the_tuple_covers_every_class_the_plan_names` went from
`daedalus/ariadne/campaign.py` to `daedalus/ariadne/`, and I commented that it
was "a wider needle than before" — implying a strengthening. It is the
opposite: `assert needle in joined` gets **looser** as the needle gets shorter.
Proven rather than argued: under a mutation narrowing the prefix back to the
file, that test stayed green while five others went red. The edit stays, because
the narrowing is covered by `test_the_package_door_is_protected_with_the_module_it_guards`
and the two `PROTECTED` rows — but the comment now says which it is.

### Verified and left alone

The prefix sweep over all 6380 tracked files found zero paths matched by a
prefix they do not literally start with; `daedalus/ariadne/` catches exactly
three files and no sibling (`daedalus/ariadne.py`, `daedalus/ariadne_sibling.py`
both admissible); a future `daedalus/ariadne/anything_new.py` inherits the
protection. No collateral: `tests/runtimes` 1629 passed, the protected suites
plus `test_computer_service.py` 181 passed, the three suites elsewhere that name
`tests/conftest.py` 83 passed.

### Still not closed, and now stated precisely

The constant check requires a **top-level binding in the named module's
source**. It does not follow a conditional binding, a binding produced by
`exec`, or one built inside a function — all of which would fail the check
rather than pass it, which is the safe direction, but means the message may name
the wrong cause. And the callable check trusts `co_filename`, which is correct
for anything compiled from a file and absent for a C-implemented callable: those
raise rather than assert, so the failure is loud but not self-explaining.
