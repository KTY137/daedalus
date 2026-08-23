# The write-surface dominance analysis cannot see a method body

Status: MEASURED
Date: 2026-08-24
Revision measured: `11dc0195c239c3462cb81b8bf96d9794aa6e5feb` (plus `31f69dc2`)
Instrument: `scripts/declare_write_surfaces.py`
Consumer of the instrument: `daedalus/gates/report_v3.py`, the Gate-0
repository-write classification chain
Author: HERACLES-ATTEMPT-LEASE
Classification: `ALIGNED`, Gate 0. This is a finding about a measuring
instrument. It changes no production path and proposes no new subsystem.

## The claim

`scripts/declare_write_surfaces.py` decides which blocking write surfaces a
centrally-wired door may classify. It does so by AST dominance: a surface is
declared only when its exact `(line, column)` node is a descendant of a
statement that provably executes after the door's `begin_effect` anchor.

**That analysis can never attribute a surface that lives inside a method, for
any door in the repository, no matter how the code is arranged.** Not "rarely",
not "unless the callee is shared" — never, by construction. Every door whose
work is organised as methods on a class therefore declares zero surfaces, and
its surfaces stay `unclassified`, which the reporter counts as a Gate-0 failure.

This is not a fact about the code being measured. It is a fact about the
measurement.

## Why: `_referenced_names` collects `ast.Name` only

The dominated region grows through `_expand_private_callees`, a fixpoint that
admits a module-private helper `_f` when `_f` is referenced from inside the
already-dominated region and every reference to `_f` anywhere in the module is
itself dominated. It discovers "referenced from inside" with
`_referenced_names`, which walks the region and collects `ast.Name` nodes.

A method call is not an `ast.Name`. `self._run_with_ledger(...)` parses as
`Call(func=Attribute(value=Name('self'), attr='_run_with_ledger'))`. The only
`Name` in it is `self`. So the fixpoint's `inside` set contains `self` and never
contains `_run_with_ledger`, and no `module_functions` entry can match a name
the scan does not produce.

The docstring in the generator states the second-order limitation ("a
module-private helper `_f` defined at module top level") and is accurate about
it. The binding limitation is the one above, and it is stated nowhere.

## The measurement

Subject: `python.attempt`, anchored at
`daedalus.spine.attempt:TaskAttempt.run`, on an isolated `git archive HEAD`
snapshot at `11dc0195` with `31f69dc2`'s shape fix applied (Windows, py3.10).
`daedalus/spine/attempt.py` holds 6 blocking write surfaces at that revision.

After `31f69dc2` the anchor dominates two statements — the `try:` that calls
`_run_with_ledger` and `return self._reap(result)` — and:

```
_referenced_names(seed)                   -> ['base_revision', 'finish', 'ledger', 'result', 'self']
attribute names in the same region        -> ['_close_ledger', '_reap', '_run_with_ledger']
```

Three runs of the generator's own machinery, unmodified except where named:

| variant | methods admitted | statements | surfaces `python.attempt` declares |
| --- | --- | --- | --- |
| as shipped | — | 2 | **0** |
| `module_functions` extended with every method of `TaskAttempt` | `[]` | 2 | **0** |
| the above **and** the reference scan made attribute-aware | 21 | 142 | **2** |

The second row is the load-bearing one. Adding the method definitions to the
callee map changes nothing at all — `admitted` comes back empty — because the
fixpoint never asks for a name the scan cannot produce. Only widening the scan
to attribute names moves anything.

The two surfaces the third variant recovers are
`daedalus/spine/attempt.py:1492` and `:1494`, both `dataclasses.replace`
(operation `unresolved-tracked-terminal`), inside `TaskAttempt._reap`.

The other four surfaces in the file are correctly refused for reasons that have
nothing to do with this defect, and they are listed so the accounting is
complete:

| surface | callee | operation | enclosing | why it is not attributed |
| --- | --- | --- | --- | --- |
| `:528` | `subprocess.run` | `dynamic-command` | `_git` (module-level) | named from many places outside any dominated region; `_references_are_dominated` refuses it, correctly |
| `:962` | `low_temp.mkdir` | `rebound-or-conflicting-binding` | `_contained_gate_child` (module-level) | same |
| `:1047` | `tempfile.mkdtemp` | `mkdtemp` | `command_gate._gate` (closure) | belongs to `python.command_gate`, which already declares it |
| `:1085` | `open` | `wb` | `command_gate._gate` (closure) | same |

## What it costs

At `11dc0195` the isolated snapshot scans **433** blocking write surfaces and
the census is:

```
blocked:write-target-unknown+production-write-inventory_only   31
unclassified                                                  402
```

`31f69dc2` fixed a real defect — `python.attempt`'s anchor dominated exactly one
statement because `begin_effect` sat in a `try:` whose `else:` carried the whole
attempt — and moved `dominated_statements` from 1 to 2 while moving the census
by zero. That zero is this defect, and it is why the fix is worth having anyway:
the shape was wrong independently of whether any counter noticed.

How much of the 402 this explains is **not measured here** and must not be
guessed. What is measured is that the instrument is structurally blind to one
whole shape of code, and that the shape is the ordinary one for every class in
this repository.

## What must NOT be done about it

Do not restructure production code to make the counter move. Hoisting
`_run_with_ledger`'s body into `run`, or turning methods into module-level
functions, would change the census without changing a single fact about what
the code does or what bounds it — a number improved by editing the thing being
measured to suit the instrument. The census would then be measuring the
refactor.

## The two candidate repairs, and what each would cost

1. **Make the reference scan attribute-aware.** `_referenced_names` also
   collects `Attribute.attr`, and `module_functions` also carries the methods of
   the class the anchor's symbol names. Measured above: 21 methods, 142
   statements, 2 surfaces for this one door.
   The soundness argument the generator already makes must be re-derived, not
   assumed: its cross-module name check demands *zero* mentions of the helper
   anywhere in any Python source, including in strings, so a collision excludes
   a helper and never admits one. Attribute names are far more collision-prone
   than module-private function names (`_reap`, `_cleanup`, `_blob` are short
   and generic), so the same rule would exclude more, not admit more — which is
   the fail-closed direction. It should be measured before it is believed.

2. **Leave the analysis alone and say so in the report.** The reporter would
   emit, per door, "this door's writes live in methods, which the dominance
   analysis cannot reach", so `unclassified` stops reading as "nobody looked"
   for the population where somebody looked and the tool could not see. This
   costs no soundness and clears nothing.

Either is a labour of its own. Neither is a lease-wiring labour, and on the
evidence above the instrument outranks further wiring: no amount of correct
wiring can move a census that cannot see the code the wiring governs.

## Reproduction

The three runs above come from the generator's own functions —
`_find_symbol`, `_anchor_regions`, `_expand_private_callees`,
`_referenced_names`, `NameIndex`, `scan_repository_write_surfaces_v2` — loaded
from the snapshot with `importlib`, with only the two named substitutions. The
first row is reproducible directly:

```
python scripts/declare_write_surfaces.py --root <snapshot> \
       --source-revision 11dc0195c239c3462cb81b8bf96d9794aa6e5feb --dry-run --json
```

and reading `per_door` for `python.attempt`: `dominated_statements`, `declared`,
`lease_dominated`, `lease_refusal`.

Surface counts move with the tree — 410 at `21f21f2a`, 432 at `684b7503`, 433 at
`11dc0195` — so a before/after is only meaningful within one revision. Both
numbers above are from the same snapshot revision.

## Guard

`tests/gates/test_attempt_anchor_dominance.py` pins the shape `31f69dc2` fixed,
against the real registry row and the real file. Restoring the `else:` turns
both of its tests red (measured on an isolated snapshot: 2 passed armed, 2
failed mutated, `assert 1 >= 2`). It deliberately does **not** pin the census,
because the census is what this document says the instrument cannot yet
produce.

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: the three runs and the two tables above, on isolated `git archive`
snapshots at `11dc0195`; `tests/gates/test_attempt_anchor_dominance.py` armed
and mutated. `tools/iron_plan_guard.py` does not exist in this tree, so the
mandated verify step could not run; the gap is reported, not routed around.
