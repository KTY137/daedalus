# What may a candidate checkout write, and who says so?

Status: MEASURED — design question with evidence, no code proposed here
Date: 2026-08-24
Revision measured: `1fe04121a85346c0c1ddbd96b39066dbac3aa774`
Author: HERACLES-ATTEMPT-LEASE
Classification: `ALIGNED`, Gate 0. Invariants 3 (isolation), 4 (evidence
boundary) and 8 (bounded effects). No new subsystem is proposed; the
recommendation is a narrowing of an existing one.
Touches, and therefore does not change here: `daedalus/kernel/offload_lease.py`
and `scripts/declare_write_surfaces.py`, both held by other lanes.

## 0. Why this question has never been asked

`acquire_effect_lease` resolves its write fence from `repo_root`:
`<repo_root>/.agentenv/agentenv.json`, run through
`sensitivity.path_write_blocked` over the declared roots. That has been correct
for every lease ever issued, because until `11dc0195` exactly one registry row
was issuable — `python.offload` — and its caller was always the installation
itself. Authority and subject were the same tree, so nobody had to say which of
the two the fence belonged to.

`11dc0195` made `python.attempt` issuable. An attempt's subject is a *candidate
checkout*: for the Gate-1 slice, a `tempfile.mkdtemp` copy of a fixture
(`daedalus/ignition/gate1.py:681,772`). Authority and subject came apart, and
the fence went with the wrong one.

## 1. The question, stated properly

An attempt writes into an isolated worktree of a candidate repository. Three
different questions are conflated under the phrase "the write fence":

1. **Which tree** did the bytes land in? — `daedalus/primary_tree.py`.
   Filesystem identity, no policy, nothing can declare it away.
2. **Inside the declaration?** — did the patch stay within the task's declared
   `target_paths`? — `receipts.containment_escapes`.
3. **What kind of file** may a weak agentic writer touch at all? —
   `sensitivity.path_write_blocked`: a deny floor plus an optional `write_allow`
   confinement.

Only (3) takes a policy file, and only (3) is ambiguous about whose tree it is
about. This document asks exactly and only: **for question (3), at the
`python.attempt` door, whose policy, over which names?**

## 2. The subject, measured

The Gate-1 slice declares six paths. `[MEASURED]` — they are not a constant.
`daedalus/ignition/gate1.py:plan_work_items` reads `fourfold.json` **from inside
the candidate tree** and keeps the entries whose file text carries the retired
symbol:

```
work item ('code','type')       -> src/ignition_app/models.py, src/ignition_app/repository.py
work item ('data','knowledge')  -> data/events.csv, fourfold.json,
                                   schemas/event.schema.json, wiki/Event.md
```

The second item's scope contains `fourfold.json` itself. Section 6 shows what
that costs, executed rather than argued.

## 3. What already answers part of the question `[MEASURED]`

Written down first, because the recommendation in section 7 rests on how much of
the job is already done by instruments that need no policy file at all.

| instrument | question it answers | measured behaviour |
| --- | --- | --- |
| `primary_tree.write_blocked_reason` | which tree | candidate checkout `-> None`; `~/.daedalus/worktrees/<digest>/...` `-> None`; `agent_env_g0/daedalus/sensitivity.py` `-> "is inside the primary checkout ..."` |
| `primary_tree.planned_overlap_reason` | worktree disjointness, bidirectional, on a not-yet-existing dir | `(~/.daedalus/worktrees/2ea46e496ce4, agent_env_g0) -> None` |
| `receipts.containment_escapes` | inside the declaration | segment-anchored: declared `src/ignition_app` covers `src/ignition_app/evil.py`; declared `tests` does **not** cover `tests_evil.py`; declared `../../etc/passwd`, `/etc/passwd`, `C:/Windows/System32/x` each refuse the whole patch with a named reason |
| `sensitivity.path_write_blocked` deny floor | what kind of file | see section 5 |
| `attempt.READ_ONLY_REPO_VERBS` | which git verbs reach the primary | `{rev-parse, status, diff, log, show, cat-file, ls-files, config}`; every mutating verb refused before `subprocess` |
| `receipts._criterion_seal` + `gate_criterion_paths` | may the candidate write what judges it | separate seal; the criterion file and its collection path stay outside `target_paths` |
| `command_gate` MIC / Job Object containment | may candidate code write outside the worktree | hard refusal, never a downgrade to an uncontained run |
| `_capture_patch` `--no-ext-diff --no-textconv` | may a candidate-authored `.gitattributes` run a program | pinned; measured to suppress every spawn |

Questions (1) and (2) are answered, fail-closed, by instruments that consult no
policy file and cannot be declared away. That is the fact section 7 turns on.

## 4. The four candidate answers

### (a) The authority's `write_allow`, as today

The fence is `<installation>/.agentenv/agentenv.json`, applied to the candidate's
repo-relative names.

`[MEASURED]` `write_allow = ('docs/', 'tests/', 'readme.md')`; `path_write_blocked`
against all six:

```
data/events.csv                True     src/ignition_app/models.py      True
fourfold.json                  True     src/ignition_app/repository.py  True
schemas/event.schema.json      True     wiki/Event.md                   True
```

`[MEASURED]` against the live issuer, `acquire_attempt_lease(PRIMARY_ROOT, ...,
writable_paths=('src/ignition_app/models.py','data/events.csv'))`:

```
provider.write_policy: sensitivity.path_write_blocked, under
  .../.agentenv/agentenv.json (sha256=9fb7cd958e57c58c), refuses 2 declared path(s)
```

- **Admits:** nothing a real candidate declares. The door is unusable.
- **Refuses:** everything, including the correct work.
- **What an attacker gets:** nothing directly — and that is the trap. The only
  way to make the door work is to widen the *installation's* fence to admit
  *candidate-shaped* names. `[MEASURED]`, adding `src/ data/ wiki/ schemas/
  fourfold.json` exposes nothing in this installation today (none of those exist
  here: `exists_in_installation=False` for all five) and `daedalus/sensitivity.py`,
  `runs/budget/ledger.json`, `scripts/declare_write_surfaces.py` and
  `tools/watchdog.py` all stay blocked. The scarier version of this argument is
  therefore refuted by measurement. What remains is still disqualifying: the
  installation's fence becomes a list of names that mean nothing in the tree it
  governs and everything in a tree it does not, it must be edited for every new
  candidate layout, and it silently becomes a real self-write permission the day
  the installation grows a `src/` or a `data/`. A fence whose safety depends on a
  directory continuing not to exist is not a fence.

### (b) The candidate's own `.agentenv`

`[MEASURED]` `resolve_write_policy(<ignition fixture>)`:

```
usable: False
origin: .../tests/fixtures/ignition/voltage/.agentenv/agentenv.json
error : no usable 'policy' block at ... (absent, unreadable, malformed, or without one)
```

The issuer's "never allow by absence" rule then denies — correctly. But the
absence is not the objection; **presence** is.

- **Admits:** whatever the candidate tree says it admits.
- **Refuses:** whatever the candidate tree says it refuses.
- **What an attacker gets:** the fence itself. This is self-granting, the same
  shape as a caller writing its own `INTENDED` row (section 6). Two distinct
  routes, both real: within one mission the candidate tree is authored by
  whoever produced the task, not by the operator; across generations, an Ariadne
  candidate that is promoted becomes the base whose `.agentenv` fences the next
  generation. The deny floor does refuse the file — `[MEASURED]`
  `path_write_blocked('.agentenv/agentenv.json', DEFAULT_POLICY) == True` — but
  that only stops a *patch* from authoring it; it does not stop the issuer from
  *reading* one already in the tree. **Dead. Not because the file is missing,
  but because reading it lets the tree being fenced choose its own fence.**

### (c) Declared `target_paths`, bounded by containment, with the operator's policy governing what may be DECLARED

The coordinator's prior. Right in shape; in its literal form, refuted by
measurement.

`[MEASURED]` the literal form — the authority's `write_allow` as the declaration
ceiling:

```
intersect_write_allow(('docs/','tests/','readme.md'), <the six>) == ()
```

An empty intersection means nothing may be written. So "let the operator's policy
govern what may be declared" is, with *this* policy, byte-identical to (a): all
six refused. The prior's instrument is wrong even though its shape is right.

`[MEASURED]` the shape, with the ceiling being the deny floor alone (`Policy()`,
`write_allow=()`, which `sensitivity` documents as UNCONFINED):

```
the six declarations:      all six admitted (blocked=False, every one)
.agentenv/agentenv.json    blocked=True      secrets/keys.py       blocked=True
.env                       blocked=True      id_rsa                blocked=True
devices/iseg_hv.py         blocked=True      daedalus/sensitivity.py blocked=True
.git/config                blocked=True
.gitattributes             blocked=False     tests/conformance/... blocked=False
```

The deny floor is the tree-independent half of `path_write_blocked`
(`GENERIC_DENY_SUBSTRINGS` plus the denylists) and it needs no policy file. It
already refuses the self-granting path of (b) and the git admin directory. The
two `False` rows are not gaps in this answer: `.gitattributes` is neutralised by
`--no-ext-diff --no-textconv` in `_capture_patch`, and the criterion file is
sealed by `gate_criterion_paths`, a different instrument (section 3).

- **Admits:** exactly what the task declared, provided the declaration clears the
  ceiling, the patch stayed inside the declaration (`containment_escapes`), and
  the bytes landed in the candidate tree (`primary_tree`).
- **Refuses:** an undeclared path, a declaration with no normal form inside the
  tree, a write outside the worktree, and any file the deny floor names.
- **What an attacker gets:** *the declaration*, if the declaration is
  candidate-supplied. Which it currently is — section 6.

### (d) Everything else in the tree

Enumerated in section 3. Three of them (`primary_tree`, `containment_escapes`,
the MIC gate) are already fail-closed and policy-free, and together they answer
questions (1) and (2) completely. `intersect_write_allow` is a real composition
primitive and is measured above: it composes two confinements correctly and,
here, correctly returns "nothing". No fourth *policy* answer exists in the tree;
there are only the three trees a policy could be read from — authority, subject,
and neither (the floor).

## 5. The four answers, side by side `[MEASURED]`

| answer | admits the six? | refuses `.agentenv`, `.env`, `secrets/`, `id_rsa`, `.git/config`? | who chooses the fence |
| --- | --- | --- | --- |
| (a) authority `write_allow` | **no — 0 of 6** | yes | operator |
| (b) candidate `.agentenv` | absent here, so deny; if present, whatever it says | whatever it says | **the candidate** |
| (c) ceiling = authority `write_allow` | **no — 0 of 6** (`intersect -> ()`) | yes | operator |
| (c′) ceiling = deny floor | **yes — 6 of 6** | yes, all five | nobody — it is the floor |
| deny floor alone, no declaration | yes | yes | nobody |

## 6. The same defect wearing three coats

Each is measured, and they are one sentence: **the candidate supplies the
material against which it is judged.**

**Coat 1 — the policy that fences it.** Answer (b), section 4.

**Coat 2 — the ledger it writes its intent to.** The `spine.intent_ledger`
contract requires an `INTENDED` row for the attempt's `effect_key` before the
lease is issued. Three locations are in play and no two agree:

- the attempt writes to `TaskAttempt(ledger_path=...)` — a **constructor
  parameter**, so the caller chooses; `daedalus/ignition/gate1.py:777` passes
  `<mkdtemp>/spine.sqlite3`;
- the contract reads `picker.resolve_spine_db_path(root)` =
  `<root>/runs/spine/spine.sqlite3`;
- `[MEASURED]`, the live refusal for the slice: `no intent in
  .../runs/spine/spine.sqlite3 names effect_key '...'; the intent must be
  recorded before the capability that acts on it`.

A caller that chooses where its own precondition lands can satisfy the
precondition by choosing where to write it — and separately, the row it must
write is the row it is judged by.

**Coat 3 — the declaration that scopes it.** `[MEASURED]`, executed on a copy of
the real fixture. `fourfold.json` is a declared `target_path` of work item 2, and
`plan_work_items` derives every `target_paths` from it:

```
before:  (src/ignition_app/models.py, src/ignition_app/repository.py)
         (data/events.csv, fourfold.json, schemas/event.schema.json, wiki/Event.md)

  a patch touching only fourfold.json — inside item 2's declared scope —
  adds "src/ignition_app/smuggled.py" to code_files

after :  (src/ignition_app/models.py, src/ignition_app/repository.py,
          src/ignition_app/smuggled.py)
         (data/events.csv, fourfold.json, schemas/event.schema.json, wiki/Event.md)
```

The scope widened by one file, through a write that never left its declared
scope. Nothing was bypassed; the declaration was *edited from inside*. Within one
ignition run this is not reachable — `plan_work_items` runs once, on the base,
before any attempt — so it is **not a live exploit today**. It becomes one the
moment a candidate tree is carried forward, which is exactly what the Ariadne
loop does (plan section 8: candidate tree, candidate Forest, next generation).

## 7. Recommendation

**Adopt (c′): the fence at the `python.attempt` door is an authority-declared
candidate policy applied to the DECLARED `target_paths`, and the declaration must
not come from the candidate.** Four parts, in dependency order; only the first is
not already true.

1. **The operator declares a candidate-tree fence explicitly**, as a new block in
   the *installation's* `.agentenv/agentenv.json` — not a second file, not a
   default, and never `DEFAULT_POLICY` reached by absence. This distinction is
   the whole of it: `Policy()` and "no policy found" are the same object and
   opposite facts, and the issuer already refuses the second by name ("a write
   lease is refused rather than issued under `sensitivity.DEFAULT_POLICY`, whose
   empty `write_allow` means UNCONFINED"). A candidate fence *positively declared*
   to be the deny floor is an operator decision with a digest in the receipt; the
   same values arrived at by absence are the exact defect `WritePolicySource` was
   written to record. **This recommendation is worthless if it is implemented as
   "fall back to `DEFAULT_POLICY`".**
2. **The fence judges the declaration, not discovered paths.** `target_paths` is
   what may be written; `path_write_blocked` under the candidate policy decides
   whether that declaration is admissible. The deny floor still runs on top, as
   under any confinement.
3. **Separate the lease's subject root from its authority root** (the split
   lease-wall is already building), so `containment.worktree` measures the pair of
   roots this attempt actually uses, and the fence is *chosen by* the authority
   while being *about* the subject.
4. **`target_paths` and the intent ledger must be authority-bound.** For the
   Gate-1 slice that means the mission compiler's manifest read becomes a read of
   a *pinned* revision recorded in the MissionContract, so the declaration is a
   fact about a revision the operator approved rather than about whatever is in
   the tree now — and `TaskAttempt`'s `ledger_path` stops being a free constructor
   parameter. Until part 4, (c′) does not yet have the property (c) is supposed to
   buy: the declaration is still candidate-supplied.

The corollary, because it is the finding and not the fix: **an installation path
allowlist is the wrong instrument at this door.** Not set too narrowly — wrong.
Questions (1) and (2) are already answered by `primary_tree` and
`containment_escapes`, fail-closed, without a policy file; what is left for a
policy is the *kind* question, and the kind question is tree-independent, which is
exactly what the deny floor is. The coordinator's prior is **confirmed in shape
and refuted in instrument**: the ceiling belongs on the declaration, and the
ceiling is not `write_allow`.

## 8. Kill criteria

The recommendation is wrong, and must be withdrawn rather than patched, if any of
these is measured:

1. **The deny floor admits something a candidate must never write.** The probes in
   section 4 are not a proof. Run the floor over a real corpus of candidate-tree
   paths — CI configs, lockfiles, `.github/workflows/`, git hooks, `setup.py`,
   `conftest.py`, anything on an evaluator's import path — and if it admits a file
   that lets a candidate reach its evaluator or the host, the floor is not a fence
   and (c′) collapses into (b) with extra steps.
2. **`containment_escapes` can be defeated by a declaration the ceiling admits.**
   If some declared spelling admits a changed path outside the tree, or a symlink
   inside the worktree resolves outside it and the patch still passes, then
   question (2) is not answered and the ceiling was carrying weight it cannot
   carry.
3. **Part 4 cannot be built.** If `target_paths` cannot be bound to an
   operator-approved revision — because the mission compiler must read the live
   tree — then the declaration stays candidate-supplied and (c′) is not better
   than (a); it is (a) with the refusal moved somewhere less visible. Prefer the
   honest refusal in that case.
4. **The split does not survive the receipt.** If a lease issued with authority
   and subject apart produces a receipt in which a reader cannot tell which root
   each decision was about, provenance (Invariant 7) is worse than before and the
   two-root design is refuted regardless of what it admits.
5. **A positively-declared candidate fence is indistinguishable in the receipt
   from an absent one.** If `WritePolicySource` cannot show, in the receipt, that
   the candidate fence was declared rather than defaulted, part 1 has not been
   implemented and the recommendation has become the defect it claims to fix.

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: every `[MEASURED]` block above, taken at `1fe04121` — the six-path
tables under the authority policy, the candidate policy and the deny floor; the
live `acquire_attempt_lease` refusal; `intersect_write_allow(...) == ()`; the
`containment_escapes` admit/refuse matrix including the three root-escaping
declarations; the widening probe; the `primary_tree` verdicts; and the executed
`fourfold.json` scope-widening in section 6. `tools/iron_plan_guard.py` does not
exist in this tree, so the mandated verify step could not run; the gap is
reported, not routed around.
