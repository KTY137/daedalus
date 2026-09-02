# G1-ENV-01 - The producer scan grew a second shape

## Frozen packet metadata

- Packet ID: G1-ENV-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 515b5fce9a5a4392c6d7f6887fe4049f72f9cd53
- Dependencies: the thirteen G1-IFACE-BRIDGE packets, which moved bridge record production out of `daedalus/file_bridge.py` into `daedalus/interfaces/bridge/` and are the direct cause of the failure this packet repairs
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`tests/test_envelope_coverage.py::test_the_scan_finds_the_producers_that_were_actually_converted`
failed because the producer scan knew exactly one producer SHAPE - serialiser,
writer and run-state target all co-located in one module - and the bridge stopped
having that shape. The heuristic is not loosened and no calibration entry is
dropped to restore green. The scan gains a SECOND shape, `injected-writer`, which
recognises a module that receives its writer and its path as injected typed
ports. The drift detector below it gains four names it must now account for, and
those four are declared in the ledger.

Invariants touched: master plan §4 invariant 7 (provenance - material actions and
claims carry origin, revision, inputs, cost, outcome and evidence; a correlation
id that silently stops covering a producer is a provenance hole) and §4
invariant 9 (honest claims - the module's own stated blind spot had become false
and was still being read as an all-clear). No trust boundary is touched. No
effectful entrypoint is added, moved, or widened.

### The pattern, second instance

This is the same failure as the open Effect Registry CRITICAL, in a different
instrument. Both are static detectors walking a tree that the hierarchy refactor
gave facades, injected ports and a `sys.modules` swap. The registry lost 14 of 42
declared effects; this scan lost an entire producer. In both cases the wrong fix
is to widen until green.

The distinction that makes this fix not-a-widening: the co-located rule is
UNCHANGED and still finds exactly the 35 modules it found before (MEASURED, see
acceptance matrix). The second shape is a UNION term. It can only ADD names to
the set the drift detector demands be declared, never remove one.

### Options considered and why they were rejected

**(a) Recalibrate to whatever single file now carries record production.**
Rejected as impossible, not merely undesirable. MEASURED at 515b5fce, no single
file satisfies all three predicates:

```
daedalus/file_bridge.py                 serialise F  persist T  target T
daedalus/interfaces/bridge/journal.py   serialise T  persist F  target F
daedalus/interfaces/bridge/dispatch.py  serialise T  persist F  target T
daedalus/interfaces/bridge/queue.py     serialise T  persist F  target F
daedalus/interfaces/bridge/watcher.py   serialise T  persist F  target F
```

**(b) Change the scan's unit from file to package/owner-group.** Rejected on
measurement. The bridge package's only `_PERSIST` hit outside the facade is
`daedalus/interfaces/bridge/projection.py:62`, `log.open("a", ...)` - an
append to an unstructured log, in a module with `serialise F` and `target F`.
Grouping by package would have turned the bridge green on that line. It restores
green by coincidence and restores no sight: if `projection.py` were refactored
the same way as its siblings, the whole package would go dark again and the
grouped scan would report a clean tree. That is the widen-until-green failure
wearing a different costume.

**(c) Declare the bridge in the ledger and narrow the heuristic's stated claim.**
Rejected as the sole fix, though its honesty requirement is adopted (see the
docstring correction below). Declaring alone surrenders detection for the
`daedalus/interfaces/bridge/` tree permanently - and that tree is precisely where
record production now concentrates. A future fifth bridge record family would be
undetectable. The ledger would be accurate about today and blind to tomorrow.

**(d) Chosen: teach the detector the shape it went blind to.** The scan did not
break because a file moved; it broke because the *persistence call site* became
an injected parameter, so the greppable name at the call site is `write_text`,
not `write_text_atomic`. The file's own docstring already anticipated exactly
this class of rot for helper extraction ("every time a write is factored out
into a helper, the helper's name has to arrive here or the detector goes blind
to its callers"). Dependency injection is that same move one level more
abstract, and the port's declared TYPE is the stable artifact it leaves behind.

## Scope

In scope:

- `tests/test_envelope_coverage.py` - the second shape, per-shape calibration,
  the composition-root test, and the docstring correction.
- `daedalus/kernel/events/envelope.py` - four ledger rows and the prose tables
  they mirror.
- `docs/work-packets/G1-ENV-01_INJECTED_WRITER_SHAPE.md`, `docs/work-packets/index.json`,
  and the pinned counts in `tests/contracts/test_work_packet_index.py`.

Forbidden and untouched:

- `tests/test_registry_new_doors.py` and `tests/test_registry_retired_rows.py`.
  The gate is deliberately red on these five; repairing the Effect Registry's
  AST derivation is a different packet with a different owner.
- Any file under `daedalus/interfaces/bridge/` or `daedalus/file_bridge.py`.
  This packet changes what the instrument can SEE, not what the bridge does.
  No production behavior is modified by this packet at all.
- The master plan, the amendment chain, and the Effect Registry.

## Contracts and behavior

The scan is now a union of two shapes, reported separately.

`producers_by_shape(root) -> dict[str, set[str]]` is new and is the primitive;
`record_producers(root)` is its union and keeps its old signature and meaning.
Grouping is the point: a single aggregate count cannot say WHICH channel is
dead. On 2026-09-02 the co-located half was still finding 35 modules and looking
healthy while the injected case was invisible, so an aggregate would have read
as good news. An instrument that cannot report which of its channels is dead
reports its own blindness as normal operation.

`CO_LOCATED` (unchanged): `_SERIALIZE` and `_PERSIST` and `_TARGET`.

`INJECTED_WRITER` (new): a parameter or dataclass field named `write_*`
annotated as a callable over a `Path`. Two independent signals - the name and
the type - which is what preserves selectivity. It covers both injection styles
the bridge actually uses, because a detector that saw only one would report the
other's absence as a clean tree:

- keyword port, `write_text: WriteTextPort` (journal, queue, watcher);
- frozen dataclass ports bundle,
  `write_json_atomic: Callable[[Path, dict[str, Any]], None]` (dispatch).

A dict-shaped writer counts alone: the port's contract IS the serialisation, and
`journal.write_journal` hands over a dict containing no `json.dumps` at all. A
str/bytes-shaped writer counts only alongside a serialiser, or every log writer
matches - `projection.py` being the live example.

The `INJECTED_WRITER` shape carries no `_TARGET` requirement. That is the
definition of the shape and not a loosening: the target arrives as an injected
`Path`, so requiring a `runs/` literal would require the one thing this shape
structurally cannot have. The permission is only sound while some module still
pins the destination, which is what
`test_the_bridge_composition_root_still_owns_the_run_state_target` asserts on the
other end of the injection.

### Where `daedalus/file_bridge.py` went

It is removed from the producer calibration list and given its own test. This is
not the forbidden "delete it to restore green": the module contains no
`json.dumps` or `canonical_json` at all, so asserting the *producer* scan can see
it would assert something false about the code. What it still owns - the `runs/`
paths and the concrete atomic writer - is now asserted directly, including a
third assertion that fires if serialisation ever moves BACK into the facade and
it becomes a co-located producer again. It remains a `CONVERTED_PRODUCERS` row so
a reader grepping `file_bridge` lands on the reason rather than on silence.

### Ledger rows

Four bridge record families, four different answers to "does this carry a trace",
which is why they are four rows and not one collapsed row:

- `interfaces/bridge/queue.py` - CONVERTED. Where the trace ENTERS: `stamp_trace`
  (injected as `envelope.stamp`) writes it into the outbox request.
- `interfaces/bridge/dispatch.py` - CONVERTED. The other end of the join:
  `adopt_trace` then `stamp_report` onto the inbox report.
- `interfaces/bridge/journal.py` - CONVERTED, with a caveat recorded rather than
  smoothed: the field is present but is set by `dispatch` before `write_journal`
  is called, so grepping this module for a stamp call finds nothing.
- `interfaces/bridge/watcher.py` - UNCONVERTED. `runs/bridge_heartbeat.json` is
  liveness state; the watcher outlives every request it dispatches, so there is
  no single run for a trace to name.

Nothing was converted by this packet. The trace was already in all three records;
what changed is that the scan can now see them, so they had to be declared.

### Docstring correction

The file previously stated as a known blind spot: "a producer that builds its
path entirely from variables with no `runs/` or `.jsonl` literal anywhere in the
module is invisible. Nothing in the tree looks like that today." The second
sentence became false when the bridge packets landed - four modules look exactly
like that - and it went on reassuring readers while the detector was blind to all
four. A named blind spot that is never re-measured decays into a false all-clear,
which is worse than an unnamed one because attention gets budgeted for it. The
correction is recorded in place, with the residual blindness the new shape still
has stated alongside it: a writer taken under a parameter not named `write_*`, or
annotated `Any` or not annotated, is still invisible. Both halves of the new
predicate are name-based, and that is the honest cost of detecting an injected
port statically.

### A second stale number, found while correcting the first

`daedalus/kernel/events/envelope.py` claimed in prose that "the scan also flags
twelve modules that ... are NOT run records". MEASURED 2026-09-02: 26. It was
already wrong before this packet - only one of the 26 was added here - and it is
corrected in place with that history stated. The instructive part is WHY it
drifted: the CONVERTED count in the same docstring is pinned by
`test_the_converted_producers_are_the_ones_the_docstring_claims` and stayed
correct for over a month, while this number is pinned by nothing and did not.
An unpinned number in prose is a claim nobody re-measures. This packet does not
add a test for it, which is a deliberate limit rather than an oversight: the set
it counts is a judgement-laden partition of the ledger, and a pinned count would
turn every honest re-classification into a test edit. It is flagged here so the
next reader knows the number is hand-maintained.

## Acceptance matrix

All rows MEASURED on this branch at base `515b5fce9a5a4392c6d7f6887fe4049f72f9cd53`
with `.venv/Scripts/python.exe`. No timing claim is made anywhere in this packet.

| # | Claim | Method | Result |
|---|---|---|---|
| 1 | The reported failure reproduces at base | `pytest tests/test_envelope_coverage.py -q` before any edit | `1 failed, 6 passed`; message names `daedalus/file_bridge.py` |
| 2 | No single file satisfies all three predicates | direct predicate probe over the bridge tree | table above; option (a) is impossible |
| 3 | Package-grouping would restore green on a log append | located every `_PERSIST` hit in the bridge package by line | only `projection.py:62` `log.open("a")`, serialise F target F |
| 4 | The new predicate is selective | union probe over all scanned modules | 4 matches out of 470 scanned; all 4 genuine bridge producers; 0 false positives |
| 5 | The co-located half is unchanged in behavior | count its finds after the reshape | 35, the same 35 the original rule found |
| 6 | Both shapes are calibrated in-tree | `test_the_scan_finds_the_producers_that_were_actually_converted` | each entry asserted against ITS OWN shape, not the union |
| 7 | Suite green | `pytest tests/test_envelope_coverage.py -q` | `8 passed` |
| 8 | Planted co-located producer is caught | scratch tree outside the worktree | reported as a surprise |
| 9 | Planted injected text-writer producer is caught | same | reported as a surprise |
| 10 | Planted injected JSON-port producer, no serialiser, is caught | same | reported as a surprise; proves the JSON branch is live |
| 11 | NEGATIVE CONTROL: an injected text writer with no serialiser is NOT caught | same | absent from the surprise list; the detector discriminates |
| 12 | Only the drift detector goes red on a plant | same run | `1 failed, 7 passed` |
| 13 | Killing the injected-writer branch reds exactly the calibration test | logic mutation in scratch | `1 failed, 7 passed`, message names `'injected-writer'` and `dispatch.py` |
| 14 | Killing the co-located branch reds exactly the calibration test | logic mutation in scratch | `1 failed, 7 passed`, message names `'co-located'` and `loop.py` |
| 15 | The composition-root test can go red | removed every `runs/` literal from `file_bridge.py` in scratch | `1 failed, 7 passed`, exactly that test |
| 16 | Deterministic | `producers_by_shape` digest under `PYTHONHASHSEED` 0/1/42/1337/90210 | identical digest, 35 + 4 every time |
| 17 | Contracts and boundaries hold | `pytest tests/contracts/ tests/test_architecture_boundaries.py tests/test_effect_boundary.py -q` | `108 passed, 28 subtests passed` |
| 18 | Gate unchanged | `tools/run_gate_checks.py g1` before and after | exit 1, exactly the same five failures, `132 passed` not reduced |

Row 13 is the strongest single result. Disabling only the JSON-port branch left
journal, queue and watcher still found via the text branch, and the calibration
test correctly isolated `dispatch.py` as the one loss. `dispatch.py` therefore
calibrates the JSON branch in-tree; it is not a branch kept alive only by a
synthetic plant.

## Migration and rollback

No migration. Nothing is renamed, moved, or deleted; the ledger gains rows and
the scan gains a disjunct. No production code path changes, so there is no
runtime behavior to roll forward or back.

Rollback is `git revert` of the single commit. The consequence of reverting is
precise and worth stating: the scan returns to one shape, the four bridge
producers become invisible again, and
`test_the_scan_finds_the_producers_that_were_actually_converted` returns to red
naming `daedalus/file_bridge.py`. Reverting restores the red; it does not restore
a working detector.

If the bridge is refactored again such that the port convention changes, the
correct response is a new shape or an amended predicate - never deleting a
calibration entry. The calibration list is what makes a name-based heuristic
safe, and every entry in it is there because something once went blind.

## Evidence expected failures and review

### Pre-existing failures on this base, named separately

`tools/run_gate_checks.py g1` exits 1 at base `515b5fce` with
`5 failed, 132 passed, 1 skipped, 28 subtests passed`. All five are the Effect
Registry's AST effect-derivation CRITICAL and are untouched by this packet:

```
FAILED tests/test_registry_new_doors.py::test_no_declared_effect_is_painted_on
FAILED tests/test_registry_new_doors.py::test_the_derivation_is_not_vacuous
FAILED tests/test_registry_new_doors.py::test_a_planted_effect_and_a_deleted_one_are_both_caught
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_body_only_delegates
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_row_equals_the_ast_derived_effect_set
```

The gate is deliberately red and this packet does not attempt to make it exit 0.
Zero failures are introduced here.

### The mutation proof

The reshaped detector was proven able to go red in a scratch copy of the tree at
`C:\Users\Administrator\daedalus-scratch\env01-mutation`, outside the worktree,
whose `daedalus/` and `runs/` `.py` counts match the source exactly (433 and 37)
and whose `daedalus.spine.envelope` import was confirmed by `__file__` to resolve
into the scratch tree rather than the main checkout's editable install. Four
producers were planted simultaneously: co-located, injected text-writer with a
serialiser, injected JSON-port with no serialiser, and a negative control that
takes an injected text writer but serialises nothing. Exactly the first three
were reported and the control was not. Raw output is in the packet evidence.

### Expected failures

`test_no_new_record_producer_has_appeared_undeclared` is EXPECTED to go red for
anyone who adds a bridge record family without a ledger row. It did exactly that
mid-packet, naming all four bridge modules at once before they were declared -
live evidence that the reshaped detector has teeth, produced before the ledger
was written rather than after.

### Review questions

1. Is `write_*` plus a `Callable`-over-`Path` annotation too narrow a signal for
   an injected writer? It is name-based on both halves and this is stated, not
   glossed. The counter-argument is that the calibration test is what makes a
   name-based heuristic survivable, and both shapes are now calibrated.
2. Should `journal.py` be CONVERTED when it does not itself stamp? Recorded with
   the caveat in the row rather than resolved by omission.
3. Is the composition-root test asserting the right module? It asserts the end of
   the injection that holds the destination. If the bridge composition root moves,
   that test's failure message says to move the assertion and the ledger row with
   it.

### What was not verified

- No timing, throughput, or performance number is claimed by this packet, so
  none was measured. The suite durations printed by pytest are incidental output,
  not measurements, and are not cited as evidence of anything.
- Whether the Effect Registry's AST derivation would also be repaired by an
  injected-port-aware pass is NOT established here. The two instruments share a
  root cause but not an implementation, and that packet is a different owner's.
- The `sys.modules` swap in `daedalus/spine/envelope.py` is the third leg of the
  same refactor pattern and is untouched. It is not currently causing a
  detection failure in this instrument; the ledger is reached through the alias
  without issue.
