# G1-HIER-13 — The write-lane gate learns the module alias, and the ledger-authority guard stops measuring the compiler

## Frozen packet metadata

- Packet ID: G1-HIER-13
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 4efa2a53a731a416c82b916639c67325fa339821
- Dependencies: G1-HIER-03A, G1-HIER-12
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`unresolved_first_party_imports` — the shared write-lane check that refuses a
model's output when it imports first-party things that do not exist — refuses
**zero** of the 734 real committed files in the control scope it is gated on,
while still refusing every invented import it was built to catch, including
invented names reached through the three legacy module aliases.

The census claim is **scoped**, on the third security review's instruction.
The control scope (what `test_no_false_positives_across_the_real_tree`
sweeps) is `daedalus/**/*.py` plus the top-level `tests/test_*.py` — 734
files, 0 offenders. Over the **whole worktree** (1459 `.py` files including
`scripts/`, `tools/`, nested test packages; the reviewer's own sweep counted
1143 under a narrower exclusion set, same substance) there are exactly **3
offenders, all pre-existing**: three `tests/kernel/` promotion tests refused
with `'daedalus.kairos.gated_writes' does not define 'GatedCandidate'`. That
module `exec`s a retained source blob into its own namespace
(`gated_writes.py:44`, `exec(compile(_retained_source_bytes, ...))`) — a
THIRD dynamic shape this reader models neither before nor after this packet.
MEASURED: the base-equivalent reader (both rules off) refuses the same three
files inside its whole-tree total of 239, and **no offender exists under the
fixed reader that is absent at base** — whole-tree, the packet only removes
false refusals. The `exec` shape is future-packet material, recorded here.

MEASURED at the base revision and again after the change, same script, same
interpreter (`.venv/Scripts/python.exe`, CPython 3.13.5), `repo_root` = the
packet worktree, control scope:

| reader | files scanned | offending files | distinct messages |
| --- | --- | --- | --- |
| `4efa2a53` (base, both rules off) | 734 | **134** | 46 |
| R1 only, follow the swap | 734 | 34 | 24 |
| R1 + R2, final (after all five review rounds) | 734 | **0** | 0 |

The middle row is the part worth keeping. The brief for this packet named the
`sys.modules[__name__] = _owner` swap in `daedalus/spine/{envelope,ledger,
durability}.py` as the cause of all 134. MEASURED, the 134 split:

| blamed on | files | distinct messages |
| --- | --- | --- |
| the swap only | 100 | 22 |
| the `daedalus.spine.attempt` facade only | 24 | 24 |
| both | 10 | — |
| anything else | **0** | 0 |

The facade is a **second, differently-shaped construct** in a fourth file that
the brief did not name: `daedalus/spine/attempt.py` installs a forwarding
`ModuleType` subclass on its own module object. Teaching the reader only the
swap would have left a gate that still refused 34 real files and still failed
its own control test, and the packet would have looked finished. The last row
is the reassuring one: nothing else in the tree false-positives at all.

### The second failure does not share the root

`tests/test_spine_gate0_writer_factory.py::test_factory_is_only_an_opening_profile_not_a_second_ledger_authority`
was red at the base revision, and the brief's hypothesis — "dunders leaking,
consistent with the swap" — is wrong. MEASURED: the two leaked keys are
`__firstlineno__` and `__static_attributes__`, and **CPython 3.13 puts them in
the `__dict__` of every class**, including a two-line probe class in a scratch
file that touches nothing in this repository:

```text
plain-subclass __dict__: ['__firstlineno__', '__static_attributes__']
gate0 subclass __dict__: ['__doc__', '__firstlineno__', '__module__',
                          '__static_attributes__', '_apply_pragmas']
```

`git log -p` confirms the assertion has been byte-identical since `bde0d0e1`
(2026-08-04), so on this interpreter it has never passed. It is a pre-existing
failure with an unrelated cause, fixed here because the brief named it, not
because it shared a root with the aliases.

## Scope

In scope — the taught reader:

- `daedalus/lanes/checks.py`. New: `_alias_target`,
  `_installs_dynamic_module_protocol`, `_ModuleScopeImports`,
  `_module_scope_imports`, `_is_own_sys_modules_slot`, `_MAX_ALIAS_HOPS`,
  `_DYNAMIC_ATTRIBUTE_HOOKS`, `_same_file`, `_IMPORT_MACHINERY_DUNDERS`.
  After five security review rounds the retype detector is a flow-sensitive,
  statement-ordered walk whose opacity flag survives only statements proved
  inert by a whitelist — class bodies, decorators, imports, calls, subscripts
  and every unmodelled shape kill it — and the alias hop parses its owner
  before following and compares OS file identity, not path spelling.
  Changed: `_exports` takes `root` and consults the two new rules;
  `_installs_dynamic_module_protocol` takes `root` so it can prove an
  imported name is a real module; its one caller passes both; `Mapping` added
  to the existing `typing` import. No check was added to or removed from
  `BASELINE`, and `run_checks` keeps its three-parameter signature (pinned by
  `test_lane_cannot_disable_baseline_by_construction`).

In scope — the guard that was measuring the compiler:

- `tests/test_spine_gate0_writer_factory.py`. The hand-written
  `{"__module__", "__doc__"}` baseline is replaced by one derived from a
  module-level probe class, plus a red proof that the derived comparison still
  refuses an added member.

In scope — instruments and census artifacts:

- `tests/test_lanes_checks.py` (new `AliasedModuleTests`, 43 tests over a
  scratch package carrying every shape the reader must tell apart: the six
  second-round laundering constructs, the seven third-round ones, the five
  fourth-round import/load ones, the three fifth-round store/dunder ones
  plus the rule-test that decides dunder-set membership, the facade-shape
  control that must stay opaque, the BOM'd-owner hop, and the case-spelled
  self-alias)
- `tests/test_deepseek_substitution_guard.py` (2 tests added beside the control
  they explain; the control itself is untouched)
- `tests/contracts/test_import_scc_hierarchy.py` (census comment only; both
  totals re-measured, both unchanged, reason recorded)
- `tests/contracts/test_work_packet_index.py` and
  `docs/work-packets/index.json` (this document's registry entry)

Forbidden paths — untouched, and verified untouched in the final diff:

- `daedalus/spine/envelope.py`, `daedalus/spine/ledger.py`,
  `daedalus/spine/durability.py`, `daedalus/spine/attempt.py`. **No runtime
  construct changed.** The instrument was taught; the code was not bent to it.
- `daedalus/spine/effect_boundary.py`, `killswitch.py`, `containment.py`,
  `writer_inventory.py`, `docref_gate.py`, `cancel.py` — other owners' guard
  files.
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`.
- `tests/test_registry_new_doors.py`, `tests/test_registry_retired_rows.py` —
  another packet's open CRITICAL, red on purpose in the `g1` profile.

## Contracts and behavior

### Why the swap stays: the docstrings' four claims, measured

The alias docstrings claim the swap preserves object identity, legacy
monkeypatch, private-name, and pickle-global resolution semantics. Option (b)
of the brief — replace the swap with explicit re-exports — was tested before it
was rejected, in a synthetic package that mirrors the construct exactly
(`owner` module with a public class, a public function, a private module-level
`_SECRET`, and a private `_helper` that reads it; one alias by swap, one by
explicit re-export listing the privates by hand, which is the *best case* for
re-export). Executed, both variants, one script:

| claimed semantic | swap | explicit re-export |
| --- | --- | --- |
| module object identity | preserved | **LOST** — `sys.modules[alias] is owner` → False |
| monkeypatch of a private module-level name | preserved | **LOST** — the patch lands on the alias; `owner.read_secret()` still returns `'orig'` |
| private-name access `from alias import _helper` | preserved | preserved **only for names enumerated by hand** |
| a private added to the owner later | preserved | **LOST** — `ImportError: cannot import name '_late'` |
| pickle round-trip of a legacy stream naming the alias | preserved | preserved (for enumerated names) |
| class object identity through the alias | preserved | preserved |
| monkeypatch of a *class* attribute through the alias | preserved | preserved |

So three of the four claims are real and are not reproducible by re-export.
**Option (b) is off the table**, and the docstrings are not overclaiming — with
one correction worth recording: *pickle-global resolution is not an independent
semantic*. Pickle's `GLOBAL` opcode is `getattr(sys.modules[name], attr)`; it is
the private/public-name claim under another name, and a fresh pickle of an
object whose class lives in the owner never names the alias at all (measured:
`fresh stream names owner=True, names alias=False`). Its value is confined to
pre-existing legacy streams.

Two independent facts make the rejection of (b) stronger than the synthetic
experiment alone:

- `daedalus/kernel/effect_replay.py:40` is production code doing
  `from daedalus.spine.ledger import _uri_path` — a **private** name through the
  legacy locator, used at line 367. The private-name claim is load-bearing
  today, not merely asserted.
- `tests/kernel/test_event_hierarchy.py` already pins the alias contract:
  `assert legacy is owner` for all three modules, `legacy_ledger._uri_path is
  owner_ledger._uri_path`, and hand-built protocol-0 streams
  `b"cdaedalus.spine.ledger\nIntent\n."` asserted to resolve. Deleting the swap
  would mean deleting a committed acceptance assertion to make a change fit —
  the shape `AGENTS.md` calls release-blocking.

### The two rules

**R1, follow.** A module whose module-scope body contains
`<sys>.modules[__name__] = <name a module-scope import bound>` is read *through*
to that owner. This is what an importer of the old locator actually receives.

**R2, opaque.** A module whose **surviving module-scope state** is a
`__class__` assignment on its own `sys.modules[__name__]` object, to a class
this same file defines with a **surviving** `__getattr__` or
`__getattribute__`, is unjudgeable — exactly as the eleven modules in this
tree that define a module-level `def __getattr__` already are. Following
`_AttemptFacade.__getattr__` through to `_owner` instead was rejected: it
would require proving statically that the method forwards everything and
synthesizes nothing, which is the one claim a reader of a class body cannot
make.

Neither qualifier is decoration; each is a fix for a measured bypass and both
adversarial rounds are under Evidence. The **hook** requirement exists because
retyping alone is not a reason to stop reading — a `ModuleType` subclass with
no hook forwards nothing at all (round one). The **surviving** requirement
exists because the first fix was flow-insensitive and name-based while
`_alias_target` modeled last-write-wins, and that one-line asymmetry inside
this packet's own diff admitted six laundering constructs (round two, with a
working end-to-end exploit through the real write gate). The detector now
walks the module body once, in statement order, tracking what each name
currently holds — the slot, a hook-bearing class, a hookless class, other —
and grants opacity only for the state a module actually ends in. A statement
shape the walk does not model kills the bindings it assigns, so every unknown
biases toward reading the file literally, which refuses.

Both rules fail toward **refusal**, never toward acceptance. If the alias
owner cannot be opened, **parsed**, or distinguished from the aliasing file
itself — outside the tree, a namespace-package directory, unparsable text
(e.g. a UTF-8 BOM), the same file under another spelling, or past
`_MAX_ALIAS_HOPS` — the file is not treated as an alias and is read
literally. The self-comparison is by OS file identity (`Path.samefile`), not
path spelling, because a case-insensitive filesystem, 8.3 short names, and
directory junctions all give one file several spellings. If the retyped-to
class is not a surviving hook-bearing class statement in the same file, the
module is read literally.

R1 buys **precision**, not silence, and that distinction is the packet. A reader
taught to follow aliases could as easily have been taught to stop judging those
locators, which would have handed every module behind one a free pass. It does
the opposite:

```text
passed  | from daedalus.spine.envelope import canonical_json      | []
REFUSED | from daedalus.spine.envelope import canonical_jsonn     | ["'daedalus.spine.envelope' does not define 'canonical_jsonn'"]
REFUSED | from daedalus.spine.ledger import SpineLedgerManager    | ["'daedalus.spine.ledger' does not define 'SpineLedgerManager'"]
REFUSED | from daedalus.spine.durability import verify_durability | ["'daedalus.spine.durability' does not define 'verify_durability'"]
```

R2 is a real loss, and its true bound must be stated honestly:
`daedalus.spine.attempt` is no longer judged at all, and opacity is
**transitively acquirable** — any freshly written module can buy the same
silence, either by carrying a surviving hook-bearing retype of its own, or by
R1-aliasing itself to any of the ~11 PEP 562 modules already in the tree.
MEASURED: `from daedalus.kernel import TOTALLY_INVENTED_XYZ` is accepted at
base too, because `daedalus/kernel/__init__.py` defines a module-level
`__getattr__` — so the alias chain adds *indirection to* that pre-existing
concession rather than new authority a writer lacked, but through-the-alias
acceptance where the base reader refused is still introduced by this packet
and is recorded as such. The trade remains right for the same reason as
before: the reader's judgement of the one real facade module was **100%
wrong** (all 34 offenders named a name the facade forwards), and silence is
better than a gate that is always wrong and cannot say so.

### The hops the reader must not take

Every one of these is a committed test, not an argument.
`AliasedModuleTests` builds a scratch package in a `TemporaryDirectory` and
requires a REFUSAL for each:

| construct | why it must not be followed |
| --- | --- |
| a swap inside a `def` | it has not happened; reading literally is correct |
| a swap inside an `if` | see the deliberate-strictness note below |
| `sys.modules["other.module"] = _owner` | writing another slot is not an alias for this locator |
| `__class__` assigned on another module's object | ditto |
| `__class__` assigned inside a `def` | ditto |
| alias target that names nothing in the tree | cannot be opened → not an alias |
| alias target that is a namespace-package directory | cannot be opened → not an alias |
| alias target that does not parse (UTF-8 BOM) | a hop must not inherit the pre-existing unreadable-file fail-open |
| alias cycle A → B → A, and a self-alias | terminates, then not an alias |
| a self-alias spelled in a different case | `samefile` identity, not path spelling |
| a five-hop alias chain (budget is four) | past `_MAX_ALIAS_HOPS` → not an alias |
| retype to a class with no attribute hook | forwards nothing → read literally |
| retype to a class this file does not define | not resolvable → read literally |
| hook class shadowed by a same-named hookless one | the surviving class has no hook |
| slot holder rebound before the retype | the retype lands on a scratch object |
| retype written before the slot binding | `NameError` at import; the module never loads |
| chained slot targets with the retyped one rebound | ditto rebinding |
| retype later undone | only the surviving state counts |
| `def __getattr__` then `del __getattr__` in the class body | the surviving class body has no hook |

and the honest non-answers — opaque, no refusal, no crash — are exactly the
states a module really ends in:

| construct | |
| --- | --- |
| a surviving hook-bearing retype of the module's own object | R2, at parity with PEP 562 |
| the same retype reached through a *copied* slot reference | the copy really reaches the module |
| a hook class that shadows an earlier hookless one and is installed | the surviving class has the hook |

A four-hop chain to a readable terminal resolves and judges normally; five does
not. That boundary is measured, not assumed, and both sides are tested.

### Blast radius, enumerated rather than argued

Both rules were run over every `.py` file under `daedalus/`, `tests/` and
`tools/`. They fire on **four files in the entire repository**, and on nothing
else:

```text
R1 alias modules: 3
    daedalus/spine/durability.py -> daedalus.kernel.events.durability
    daedalus/spine/envelope.py   -> daedalus.kernel.events.envelope
    daedalus/spine/ledger.py     -> daedalus.kernel.events.ledger
R2 opaque modules: 1
    daedalus/spine/attempt.py
```

In particular no module acquires opacity by accident: several files define a
class with a `__getattr__`, and none of them is treated as opaque, because none
installs that class on its own module object.

The `if`-scoped swap is the one case where strictness costs a false positive: a
conditional swap *might* run. It is refused anyway, because no module in this
tree spells it that way — measured 2026-09-01, three swaps, all unconditional,
all at module scope — and the test records that widening the rule later must be
a decision taken on purpose rather than a hole discovered.

### The derived compiler baseline

`test_factory_is_only_an_opening_profile_not_a_second_ledger_authority` now
compares against `frozenset(_CompilerMetadataProbe.__dict__) - {"_apply_pragmas"}`,
where the probe is a module-level class with a docstring and one method, based
on a local `_ProbeBase` rather than `object` (a direct `object` subclass also
gets `__dict__` and `__weakref__` descriptors, which the class under test
inherits instead). Measured: probe keys and real keys are equal sets.

Adding `__firstlineno__` and `__static_attributes__` to the literal set was
rejected. It goes green while re-arming the identical trap for CPython 3.14,
and widening a guard's expected set until it passes is precisely the shape this
branch already carries one open CRITICAL for. Deriving the baseline keeps the
claim the test actually makes — *this subclass adds one method and nothing
else* — and `test_the_opening_profile_check_can_still_go_red` proves the
comparison still rejects a subclass that grew a `record_intent`, and rejects it
**for the added member**, not for a dunder.

## Acceptance matrix

| # | claim | check | result |
| --- | --- | --- | --- |
| 1 | the control test passes | `tests/test_deepseek_substitution_guard.py` | 27 passed, 3 subtests (was 24 passed / 1 failed) |
| 2 | offender count 134 → 0 | census script, 734 files, before and after | 134 → 0 |
| 3 | the reader can still go red, real aliases | `test_an_invented_name_behind_a_module_alias_is_still_caught` | 3 subtests, all refuse |
| 4 | the reader can still go red, fixture | `AliasedModuleTests` | 26 passed (`tests/test_lanes_checks.py`: 55) |
| 4a | every round-1 bypass is closed | the 11 constructs that review built, re-run | all refuse; both real names still pass |
| 4b | every round-2 bypass is closed, RED first | 6 constructs + BOM hop: `8 failed` at `b8c44a55`, then all refuse | 55 passed |
| 4c | every round-3 bypass is closed, RED first | 5 reviewer constructs + n7: `7 failed` at `3e212da8`, then all refuse | 62 passed |
| 4d | every round-4 bypass is closed, RED first | r1-r4 + the r5 attribute variant: `5 failed` at `be19e9bc`, then all refuse | 68 passed |
| 4e | the fix is not a stone that always refuses | the real facade shape stays opaque | `spine/attempt.py` opaque=True; census 0 |
| 4f | whole-tree containment | fixed vs base-equivalent reader, 1459 files | 3 vs 239; **zero new**; 236 false refusals removed |
| 5a | every round-5 bypass is closed, RED first | s1-s3 + the derived rule-test: `4 failed` at `bd37f16d`, then all refuse | 72 passed |
| 5b | the dunder set holds its own argument | every member checked against a real plain module | `__path__` dropped; 6 members verified present |
| 5c | narrowing refused no real file | containment re-measured after the narrowing | identical: 3 vs 239, zero new, R1=3 / R2=1 |
| 5 | the ledger-authority guard passes | `tests/test_spine_gate0_writer_factory.py` | 9 passed (was 7 passed / 1 failed) |
| 6 | that guard can still go red | `test_the_opening_profile_check_can_still_go_red` | passed |
| 7 | the alias contract is intact | `tests/kernel/test_event_hierarchy.py` | 9 passed |
| 8 | no runtime construct changed | final diff | no `daedalus/spine/*` file touched |
| 9 | kernel, contracts, boundaries, spine attempt | `pytest tests/kernel/ tests/contracts/ tests/test_architecture_boundaries.py tests/test_spine_attempt.py -q` | 1037 passed, 8 skipped, 8 xfailed, exit 0 |
| 10 | effect boundary instruments | `pytest tests/test_effect_boundary.py tests/test_cli_effect_boundary.py tests/test_ikarus_os_boundary.py -q` | 103 passed, exit 0 |
| 11 | the g1 gate is still red for the right five | `tools/run_gate_checks.py g1` | exit 1, 5 failed, 140 passed, 1 skipped |
| 12 | effect registry digest unchanged | `registry_sha256()` | `ac02027836…6211ec` |
| 13 | import census | `_tracked_module_graph()` | 433 modules / 1624 edges, both unchanged |
| 14 | full suite, node IDs vs base | `pytest tests -q -p no:randomly`, both trees | 16 → 14; the two targets fixed, one flake each way, neither attributable |
| 15 | work-packet registry | `tools/index_work_packets.py --check` | clean: 279 tracked files, 213 packet IDs |

## Migration and rollback

There is no migration. No runtime construct, contract, schema, or effect path
changed; the packet edits one static reader and four test files.

Rollback is `git revert` of the single commit. Reverting restores the 134
false positives and the two red tests, and nothing else: no consumer imports
`_exports`, `_alias_target` or `_retypes_own_module` outside
`daedalus/lanes/checks.py`, whose only caller of `_exports` is
`unresolved_first_party_imports` in the same file.

The write-lane risk is worth stating precisely, because both adversarial
rounds existed to measure it — and the first version of this very paragraph
claimed "exactly one construct got more permissive", which the security review
proved **wrong by six**: the flow-insensitive first fix additionally accepted
six retype-laundering constructs that this packet's second round then
eliminated (see Evidence). After the flow-sensitive fix, the deliberate
permissive surface is: a module whose surviving state installs a hook-bearing
type on its own module object (directly or through a copied slot reference),
and an R1 alias whose readable owner is itself opaque. A file could already
buy the same silence with one module-level `def __getattr__`, which the gate
has always honoured, so neither adds authority a writer lacked — but the
claim of a single construct is retracted, not defended. Every unfollowable,
unparsable, or non-surviving case falls back to reading the file literally,
which refuses.

## Evidence, expected failures, and review

Interpreter for every run: `.venv/Scripts/python.exe -m pytest`, CPython
3.13.5. Probes used an explicit `sys.path.insert(0, <worktree>)`. No exit code
was read through a pipe. No `-x` on any baseline run.

### Baseline, at 4efa2a53, before any edit

```text
tests/test_deepseek_substitution_guard.py tests/test_spine_gate0_writer_factory.py
  -> 2 failed, 31 passed        EXIT=1
  InventedImports::test_no_false_positives_across_the_real_tree
     AssertionError: ... First list contains 134 additional elements.
  test_factory_is_only_an_opening_profile_not_a_second_ledger_authority
     AssertionError: assert {'__firstline...attributes__'} == set()
```

### Expected failures that remain, named separately

`tools/run_gate_checks.py g1` exits 1 with exactly five failures, all of them
another packet's open CRITICAL and all present at the base revision:

```text
FAILED tests/test_registry_new_doors.py::test_no_declared_effect_is_painted_on
FAILED tests/test_registry_new_doors.py::test_the_derivation_is_not_vacuous
FAILED tests/test_registry_new_doors.py::test_a_planted_effect_and_a_deleted_one_are_both_caught
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_body_only_delegates
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_row_equals_the_ast_derived_effect_set
5 failed, 140 passed, 1 skipped, 28 subtests passed
```

Not touched by this packet, and the `140 passed` did not drop.

### A measurement of mine that was wrong, recorded because it nearly stood

The first run of the over-following fixture reported all twelve cases as
"refuse", five of them marked BAD. The cause was not the reader: the probe
passed `repo_root="/tmp/overfollow"`, which CPython on this box resolves to a
drive-relative `\tmp\overfollow` that does not exist, so `_module_path` returned
`None` for every module and every case refused with `module 'pkg.X' does not
exist`. Seven cases were reported "ok" — for entirely the wrong reason. The
committed fixture builds its root with `tempfile.TemporaryDirectory()` and the
ad-hoc probe derives it from `__file__`. This is the same family of defect the
packet exists to fix, produced while fixing it.

### Full suite, compared by node ID against a pristine base worktree

`pytest tests -q -p no:randomly`, run once on a detached worktree at
`4efa2a53` and once on the packet tree, sequentially, never concurrently, each
redirected to a file. Randomization is disabled on **both** so the comparison is
of node IDs and not of orderings.

| | failed | passed | skipped | xfailed | wall |
| --- | --- | --- | --- | --- | --- |
| base `4efa2a53` | **16** | 9562 | 276 | 9 | 32:36 |
| packet tree | **14** | 9583 | 276 | 9 | 39:43 |

The count is not the evidence; the ID diff is. `comm` over the sorted `FAILED`
lines:

```text
FIXED (base, not packet)
  tests/test_deepseek_substitution_guard.py::InventedImports::test_no_false_positives_across_the_real_tree
  tests/test_spine_gate0_writer_factory.py::test_factory_is_only_an_opening_profile_not_a_second_ledger_authority
  tests/test_gate_containment_job_caps.py::test_the_process_cap_refuses_a_fork_bomb_without_killing_the_job

NEW (packet, not base)
  tests/test_conversation_requests.py::test_cancel_is_requested_then_confirmed_only_after_worker_stops
```

The first two are this packet's two targets. The other two are one flake in each
direction, and the new one was run down rather than assumed:

- **It is a thread-timing race.** The assertion is
  `assert status["cancellation"]["status"] == "confirmed"` and it got
  `'requested'`, after a `release.wait(1)` in a worker thread and a polling
  `_wait_for`. The packet run was 22% slower in wall time than the base run
  because the box was more loaded.
- **The changed module is not in that test's import closure.** MEASURED, cold
  interpreter, explicit `sys.path.insert`: importing
  `daedalus.conversation_requests` loads 69 `daedalus.*` modules and
  `daedalus.lanes.*` is **empty** — `daedalus.lanes.checks` is never imported.
  There is no path by which this packet can reach that code.
- **It does not reproduce.** 3/3 green in isolation and 5/5 green as a whole
  file, on the packet tree AND on the base worktree.
- `test_gate_containment_job_caps` is the same phenomenon mirrored: it failed at
  base and passed on the packet tree. Neither result is attributable to a diff
  that touches one AST reader.

Two corrections to the brief's stated numbers, both measured: the base failure
set is **16**, not 15, under `-p no:randomly`; and at least two of its members
are load-sensitive rather than stable, so any future comparison should expect
±1 flake regardless of the change under test.

### Adversarial round: the first version of both rules was broken

An independent delegate was given the code and one instruction — get an
invented import past the gate. It did, four ways, all in the permissive
direction, none of them exotic. Every one is fixed and pinned.

1. **The most serious.** R2 originally treated *any* `__class__` assignment on
   the module's own `sys.modules` slot as opaque. Nine lines defeated it:

   ```python
   import sys
   from types import ModuleType

   class _Facade(ModuleType):
       pass

   def real_function():
       return 1

   sys.modules[__name__].__class__ = _Facade
   ```

   An ordinary module that imports cleanly and works, where
   `from pkg.evil3 import NOT_REAL_AT_ALL` raises `ImportError` at runtime — and
   the gate accepted it. The subclass has no `__getattr__`, so it forwards
   nothing and the module's own top level was still the whole truth. R2 now
   requires the retyped-to class to be a class statement in the same file
   defining `__getattr__` or `__getattribute__`. That is exactly the cost of the
   PEP 562 rule beside it and buys no new surface.
2. **Namespace-package escape.** An alias whose target resolved to a directory
   made `_exports` fail on `read_text` and answer opaque, in one hop, with no
   fake class. This repository really has two namespace packages, `tools` and
   `tests` — named in `_module_path`'s own docstring.
3. **Hop-budget boundary failed open.** A five-file chain exhausted
   `_MAX_ALIAS_HOPS` one hop before a perfectly readable terminal and returned
   opaque, accepting everything behind it. Measured precisely: four hops safe,
   five a blanket bypass.
4. **Self-alias.** `owner == path` returned opaque; three lines.

All four had the same root, and it is worth naming because it is the mistake
this whole packet is about: **a guard whose job is to refuse must not answer
"I cannot judge" when what it means is "I could not follow a pointer".** Every
unfollowable case now falls back to reading the file literally, which refuses.

Re-run of the delegate's eleven constructs against the fixed reader — every
bypass refused, both genuine names still accepted:

```text
REFUSED | evil2.TOTALLY_MADE_UP         | __class__ = object
REFUSED | evil3.NOT_REAL_AT_ALL         | the most serious finding
passed  | evil3.real_function           | the real name
REFUSED | nsalias.ANYTHING_INVENTED_NS  | namespace-package escape
REFUSED | selfalias.ANYTHING            | self-cycle
REFUSED | a1.TOTALLY_INVENTED_VIA_CHAIN | 5-hop chain
REFUSED | a2.TOTALLY_INVENTED_VIA_CHAIN | 4-hop chain, real terminal
passed  | a2.REAL_NAME                  | 4-hop chain, real name
REFUSED | rebind.INVENTED               | import sys as os
REFUSED | rebind2.INVENTED              | from sys import modules as m
REFUSED | twostep.INVENTED              | a = b = sys.modules[__name__]
```

The delegate also reported no crash from any construct, including mutual and
self cycles, and two findings that fail *closed* rather than open: an
`AnnAssign` spelling of the retype (`... .__class__: type = _F`) is not
recognised, so such a module is read literally and refuses. That is a narrower
detector than the runtime it models, not a hole, and it is left as it is.

### Second adversarial round: the fix itself was broken, six ways

An independent security review of the committed first fix returned CRITICAL —
merge blocked, R2 only. R1 passed every probe, the option-(b) rejection held,
and the `first_party_roots` gap measured CLEAR. The root cause, in the
reviewer's words, was a one-line asymmetry inside this packet's own diff:
`_alias_target` modeled last-write-wins, while
`_installs_dynamic_module_protocol` collected "names that ever held the slot"
and "class names that ever had a hook" in two unordered passes. Six
constructs, plus a working end-to-end exploit written by the lane through the
real write gate, all ACCEPTED by the first fix, all REFUSED at base, none
serving a single forwarded name at runtime:

1. hook class shadowed by a same-named hookless class — reopening round one's
   own "most serious finding" with three lines;
2. slot read into `_m`, `_m` rebound to a scratch module, scratch retyped
   (the end-to-end exploit; the first line is dead);
3. retype written *before* the slot binding — `NameError` at import, the
   module never loads at all;
4. `_a = _b = sys.modules[__name__]`, then `_a` rebound before the retype;
5. retype then undone (`__class__ = _F; __class__ = ModuleType`);
6. `def __getattr__` then `del __getattr__` in the same class body.

All six were REPRODUCED here against `b8c44a55` before any fix (six
`ALLOWED`), their runtime truth measured (five plain-typed modules, one
import crash), then committed as fixtures whose tests were run RED first:

```text
8 failed, 18 passed, 29 deselected          # at b8c44a55, pre-fix
55 passed                                    # after the flow-sensitive fix
```

The 8 RED include the six constructs, the BOM hop below, and the true-positive
copied-name case the ordered walk had to *gain*. Discrimination note, per the
review: these fixture tests also pass at base (base refuses everything), so
the tests that discriminate the detector from a stone that always refuses are
the three opaque-accepting complements
(`retype_via_copied_name`, `retype_shadowed_to_hook`, `retype_ok`).

The same review found one HIGH the first fix *introduced*: the recursive hop
inherited `_exports`' pre-existing "unreadable file → opaque" fail-open, so a
freshly written alias to a UTF-8-BOM'd owner was accepted where base refused.
Fixed by parsing the owner before continuing the walk — an unparsable owner
terminates the hop as *not an alias*, and the aliasing file is judged on its
own literal top level. And one hardening: the self-alias comparison was an
unresolved, case-sensitive Path equality on a case-insensitive filesystem;
it is now OS file identity (`Path.samefile`), with the case-spelled self-alias
pinned as a fixture (it refused even before the hardening, via the hop
budget — the fix makes the refusal immediate instead of accidental).

The reviewer also confirmed the detector errs in the SAFE direction for a
lambda-valued `__getattr__` and an inherited hook: both genuinely opaque at
runtime, both refused by the gate. Harmless, and left as is — a refusal
costs a retry; an accept costs a laundered import.

After the fix: all six constructs REFUSED through the real gate, the offender
census still 0 of 734, the blast radius enumeration unchanged (3 + 1 files),
and every round-1 probe still passing.

### Third adversarial round: the same lesson one level deeper, three times

The review of the second fix returned CRITICAL again — narrowly. The six
round-2 constructs were confirmed closed with the reviewer's own fixtures
against both revisions, the BOM propagation fix and `samefile` verified, and
the regained copied-name true positive independently confirmed. Five
constructs survived, three root causes, all inside the round-2 code itself:

1. **`class_has_surviving_hook` was still a flat scan** — the exact defect
   the module walk had just shed, reproduced one scope level down. A hook
   `del`-eted (n2) or overwritten with `None` (n3) inside `if 1:` *in the
   class body* was invisible; the runtime class forwards nothing (n3 raises
   `TypeError` on every miss).
2. **`decorator_list` was ignored.** A decorator can replace the class
   outright; n1's decorator returns plain `ModuleType`, the runtime module
   type stays `module`, and the reader had trusted the body's hook.
3. **`hooked` was not part of the killed state.** `kill_bound_names` reset
   name bindings on unmodelled statements, so the round-2 claim "unknowns
   bias to refuse" was true of the env and FALSE of the opacity flag itself —
   the only output that matters. Eight lines (retype, then the undo inside a
   module-scope `if`/`for`/`try` — n4/n5/n6) kept opacity while the runtime
   module ends plain.

All five were reproduced here against `3e212da8` before any fix — plus a
sixth of the same third root cause found locally (n7: the undo reaches the
module through a container subscript the walk cannot attribute) — with
runtime truth measured for each, committed as fixtures, and run RED first:

```text
7 failed, 26 passed, 29 deselected      # at 3e212da8, pre-fix
62 passed                                # after
```

The fix follows the reviewer's exact direction and generalizes it one step in
the same refusing direction: compound statements in a class body kill hook
survival at their position; a decorated class binds as unknown; and `hooked`
now dies on every statement shape the walk does not fully model — compound
statements, `Expr`, `Assert`, non-Name delete/annotation/augmentation
targets, any unattributable `__class__` store, any class statement after a
retype (a class body executes at import and may contain the undo), any
function definition with decorators or parameter defaults (those execute at
`def` time), and any statement containing a call. The bias is uniform now:
anything unprovable costs the ACCEPT. The real facade in
`daedalus/spine/attempt.py` stays provable because the only statement after
its retype is a plain attribute assignment.

**Known model bound as recorded at the time** — a subscript or attribute
*load* with no `Call` node was not reset. The fourth round showed this framing
was wrong in a way worth preserving rather than editing away: it reads as an
exotic `__getitem__` corner, when in fact it is the import hole below wearing a
different hat, and it was weaponisable in eight lines. It is CLOSED in round
four. See the restated bound there.

After the fix: all thirteen constructs from all three rounds REFUSED through
the real gate, control-scope census still 0 of 734, whole-tree census 3
pre-existing `exec`-shape offenders identical to base, blast radius still
3 + 1 files, registry digest and import census unchanged.

### Fourth adversarial round: an import runs a module body and contains no call

The gap sat exactly between round three's commit message — which claimed to
close "the adjacent import-time-execution family" — and its dispatch table.
`ast.Import` and `ast.ImportFrom` were the only two branches that never
touched `hooked`, and **an import statement executes an entire module body
while containing zero `Call` nodes**, so the Call-based reset never fired
either. Four constructs, each a handful of lines, all ACCEPTED at `be19e9bc`:

| # | construct | runtime type |
| --- | --- | --- |
| r1 | `import pkg.h1` after the retype | plain `module` |
| r2 | `from pkg import h2` | plain `module` |
| r3 | `from pkg.h3 import marker` | plain `module` |
| r4 | the documented subscript bound, weaponised | plain `module` |

where each helper reaches back through `sys.modules` and retypes the
partially-initialised importer. Every probe carried a self-check — the undo
verified to have landed on *that* module, `real_func()` still working — held
to the bar the reviewer set when it withdrew its own AnnAssign finding for
targeting the wrong module name. Controls behaved: `print()` (a `Call`)
refused, and the round-3 `if 1:` undo refused.

**Two corrections to the fix direction, both measured, both mine to make.**
The instruction was to reset `hooked` in the two import branches — one line
each. That closes r1–r3. It does **not** close r4: MEASURED, the `ImportFrom`
that puts the malicious object in scope sits *before* the retype, so the reset
is a no-op there and r4 stayed accepted. And closing only subscripts would
have been theatre — r5, built here, is the identical attack one keystroke
away (`EVIL.__file__` instead of `EVIL[0]`, running `__getattr__` instead of
`__getitem__`), also ACCEPTED at `be19e9bc` with the undo verified to land.

So the Call heuristic is replaced by an **inertness whitelist**: after a
retype, `hooked` survives only statements whose every expression is provably
incapable of running user code — constants, name loads, tuples/lists of
those, and one narrow attribute case. A whitelist is the right shape for a
guard because syntax the reader has never heard of defaults to "not inert",
i.e. to refusing. Calls, subscripts, comprehensions, f-strings, operators,
walruses, awaits, imports, class bodies, and decorated/defaulted `def`s all
fall outside it.

The one attribute case is sound rather than convenient. Reading an
import-machinery dunder (`__file__` and friends) off a name this file bound to
a module **that resolves under `root`** cannot reach a PEP 562 `__getattr__`,
because the import machinery has already written that name into the module
`__dict__` and module `__getattr__` runs only when `__dict__` lookup fails.
Both halves are required: `from pkg.h5 import EVIL` does not resolve
`pkg.h5.EVIL` as a module, so `EVIL.__file__` is not inert and r5 refuses.
This is exactly the shape the real facade ends with —
`_module.__file__ = _owner.__file__` — and
`test_the_real_facade_shape_survives_the_inertness_rule` pins it, because if
that goes red the packet's primary claim dies with it.

RED first, as every round:

```text
5 failed, 34 passed, 29 deselected      # at be19e9bc, pre-fix
68 passed                                # after
```

**Restated bound, now much narrower.** The remaining shape is a single one:
an attribute *store* on the retyped module runs that module's own
`__setattr__` if the installed facade class defines one — which
`daedalus/spine/attempt.py` does. A file granted opacity can therefore run
its own code in the one statement form the whitelist admits after a retype.
Closing it would refuse the real facade and return the 34 measured false
positives, so it is kept open deliberately and named here rather than
discovered later. It is strictly narrower than "any load": the code that runs
is a method of the same class the gate is already trusting to forward names,
in the same file the reader has already parsed.

*(Round five found that the CODE was wider than this paragraph claimed — the
whitelist admitted the store on any imported object, not only on the retyped
module. The paragraph described the intended surface; the implementation did
not match it. Both now do.)*

After the fix: all eighteen constructs from all four rounds REFUSED through
the real gate; `daedalus/spine/attempt.py` verified still opaque; control
census 0 of 734; whole-tree containment re-verified at 3 offenders vs 239
base, **zero new under fixed, 236 false refusals removed**; blast radius
still 3 + 1 files; registry digest and import census unchanged.

### Fifth adversarial round: both holes were in the hand-widened clauses

The fifth review returned CRITICAL on three constructs, and the pattern is
the packet's sharpest lesson about itself: **round four's whitelist held
everywhere it was derived from a rule and failed in both places it was
widened by hand.**

| # | construct | why it passed | runtime type |
| --- | --- | --- | --- |
| s1 | `EVIL.anything = 1` after the retype | `inert_store` allowed an attribute store on ANY Name | plain `module` |
| s2 | `_y = h.__path__` (`from pkg import h`) | `__path__` was in the machinery-dunder set | plain `module` |
| s3 | `_y = M.__path__` (`import pkg.h as M`) | same, other binding spelling | plain `module` |

All three reproduced here against `bd37f16d` with the undo verified to land
on that module and `real_func()` still working.

**s1 is r4/r5 with LOAD replaced by STORE**, and it sat *outside* the bound
this document had written down — the residual note scoped the `__setattr__`
risk to the retyped module's own facade class, while the code accepted the
store on an arbitrary imported object. `inert_store`'s attribute case is now
`value_of(node.value) is _SELF or is_own_slot(node.value)`: the module's own
slot and nothing else, which is exactly what
`_module.__file__ = _owner.__file__` needs. The doc and the code now describe
the same surface.

**s2/s3 broke half one of the machinery-dunder argument.** That argument has
two halves and only one failed. MEASURED 2026-09-02, every candidate checked
against a plain file-backed module and a package:

```text
dunder         | in PLAIN module __dict__ | in PACKAGE __dict__
__name__       | True                     | True
__file__       | True                     | True
__doc__        | True                     | True
__package__    | True                     | True
__loader__     | True                     | True
__spec__       | True                     | True
__path__       | False                    | True
```

`__path__` is the only one of the seven that a non-package does not carry, so
reading it off a plain module misses the `__dict__` and fires exactly the
PEP 562 `__getattr__` the set exists to prove unreachable. It entered because
"the import machinery writes it" is a true sentence — about packages. It is
dropped, and `test_the_machinery_dunder_set_holds_its_own_argument` now
checks every member against a real plain module, so membership is decided by
the property rather than by the description. Half two of the argument —
requiring the base name to resolve as a module under `root` — was verified
independently by the reviewer and holds: `from pkg.h5 import EVIL` binds
`_OTHER` and `EVIL.__file__` is refused.

RED first, as every round:

```text
4 failed, 39 passed, 29 deselected      # at bd37f16d, pre-fix
72 passed                                # after
```

The fourth RED is the derived rule-test itself, which is the point: it fails
against the old set without any attack fixture, so the next `__path__`-shaped
mistake is caught by the rule rather than by a sixth review round.

**Narrowing can only hurt in one direction** — by newly refusing a real file
— so containment was re-measured rather than assumed. Identical to round
four: 1459 files, **3 offenders vs 239 at base, zero new under fixed, 236
false refusals removed**, blast radius still exactly R1=3 / R2=1, and
`daedalus/spine/attempt.py` still opaque. All twenty-one constructs from all
five rounds refuse.

### Delegated measurement contaminated by my own edit

The census sweep was dispatched to a read-only delegate against the same
worktree I was editing. It measured 34 offenders where I had measured 134
minutes earlier, detected the discrepancy itself, found the uncommitted
in-flight change to `daedalus/lanes/checks.py`, and reported the contamination
rather than the number. Both figures were real; they are the first two rows of
the table under the primary claim. The dispatch was my error — a read-only
delegate still needs a frozen tree — and the delegate's refusal to report a
moving measurement as a fact is why the second construct is documented at all.

### Residual risk

- `daedalus/spine/attempt.py` is now unjudged by this gate, and opacity is
  **transitively acquirable**: a freshly written module can carry a surviving
  hook-bearing retype, or R1-alias itself to any of the ~11 PEP 562 modules
  in the tree. MEASURED: `from daedalus.kernel import TOTALLY_INVENTED_XYZ`
  is accepted at base — the chain adds indirection to a concession the gate
  already made, not new authority, but through-the-alias acceptance where
  base refused is introduced by this packet and is on the record.
- **The one shape still admitted after a retype**, as narrowed by round four
  and *enforced* by round five: an attribute store **on the module's own
  slot** runs that module's own `__setattr__` when the installed facade class
  defines one — which `daedalus/spine/attempt.py` does. A file granted
  opacity can therefore run its own code in the single statement form the
  inertness whitelist allows after a retype. Closing it refuses the real
  facade and returns the 34 measured false positives, so it is kept open
  deliberately, and the fifth security review judged that trade **acceptable**
  on grounds worth recording: exploiting it requires the writer to define
  *both* hooks on their own class, and a module already carrying a
  `__getattr__` is one that a bare module-level `def __getattr__` would make
  opaque at base anyway. It is not new authority.

  Round five is also why this bullet is trustworthy at all. Until then the
  code was *wider* than this paragraph: `inert_store` accepted the store on
  any imported object, so the documented bound and the implemented bound were
  different surfaces and the difference was a working bypass. A residual note
  is only as good as the test that pins it, which is now
  `test_a_store_on_another_object_after_a_retype_kills_opacity`.
- **The `exec`-into-namespace shape, third dynamic construct, not this
  packet's:** `daedalus/kairos/gated_writes.py:44` executes a retained source
  blob into its own namespace. It causes the 3 whole-tree offenders above and
  is invisible to every AST walk in this repository — the coordinator
  measured its wider cost on `main` (`124d4647`): the blob hides **seven
  import edges and three modules**, so the real cross-domain SCC is 21
  modules where `tests/contracts/test_import_scc_hierarchy.py` reports 18.
  That census is pinned in this packet as re-measured-and-unchanged, which is
  true of the instrument and does not certify the instrument's blind spot.
- **Pre-existing fail-open, recorded not fixed:** a file whose text does not
  parse (e.g. a UTF-8 BOM read as utf-8) is opaque when imported directly —
  base behavior, measured, at `_exports`' top-level `except` and the
  `opaque` acceptance in `unresolved_first_party_imports`. This packet's hop
  no longer inherits it (an alias to a BOM'd owner refuses, tested), but the
  direct hole predates the packet and belongs to whoever owns a fix for it.
- **Directory junctions, measured 2026-09-02, pre-existing, low:**
  `cmd /c mklink /J` needs no privilege on this box, and a junction planted
  inside the tree makes `_module_path` resolve `pkg.jlink.leaked` to a file
  **physically outside `repo_root`** (`resolve()` confirmed the escape). The
  gate then judges that outside file normally — a real name passes, an
  invented one refuses — so the vector steers *which* file the reader trusts,
  not whether judgment happens. Base `_module_path` behaves identically; a
  writer able to plant junctions inside the checkout already has direct
  write authority. Recorded per the security review's instruction.
- The `if`-scoped swap refusal is a known, tested, deliberate false positive
  with no instance in the tree.
- `_alias_target` does not require the alias owner to be under the check's
  `first_party_roots`; it requires only that `_module_path` resolve it under
  `repo_root`. The security review measured this gap CLEAR. The self-alias
  identity check now uses `Path.samefile`. Case variations and junction
  spellings were measured in round two; the 8.3 short-name spelling was
  MEASURED 2026-09-02 via `GetShortPathNameW`
  (`C:\Users\ADMINI~1\DAEDAL~2\G1AB30~1\...` vs the long path:
  `samefile` and `_same_file` both return True). DOS device names
  (`CON`, `NUL`, ...) remain UNVERIFIED -- plausible, not proven.
- `daedalus/lanes/checks.py` is a write-lane refusal path, and ALL THREE
  earlier versions of this change were measurably exploitable — the second by a
  working end-to-end exploit through the real write gate. It is not Jonas's
  file by the ownership enumeration and it sits close to the fence: **this
  packet should not be promoted without the safety owner's read**,
  notwithstanding that the final reader refuses every construct all four
  adversarial rounds could build. On the false-POSITIVE axis the fix is
  proven to have made nothing worse (whole-tree: zero new offenders, 236
  removed); every block in this packet's history was on the
  false-NEGATIVE axis.
