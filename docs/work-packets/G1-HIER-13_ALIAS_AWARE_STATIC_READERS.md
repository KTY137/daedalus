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
**zero** of the 734 real committed files it reads, while still refusing every
invented import it was built to catch, including invented names reached through
the three legacy module aliases.

MEASURED at the base revision and again after the change, same script, same
interpreter (`.venv/Scripts/python.exe`, CPython 3.13.5), `repo_root` = the
packet worktree:

| reader | files scanned | offending files | distinct messages |
| --- | --- | --- | --- |
| `4efa2a53` (base, both rules off) | 734 | **134** | 46 |
| R1 only, follow the swap | 734 | 34 | 24 |
| R1 + R2, final | 734 | **0** | 0 |

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
  `_DYNAMIC_ATTRIBUTE_HOOKS`. Changed: `_exports` takes `root` and consults the
  two new rules; its one caller passes `root`; `Mapping` added to the existing
  `typing` import. No check was added to or removed from `BASELINE`, and
  `run_checks` keeps its three-parameter signature (pinned by
  `test_lane_cannot_disable_baseline_by_construction`).

In scope — the guard that was measuring the compiler:

- `tests/test_spine_gate0_writer_factory.py`. The hand-written
  `{"__module__", "__doc__"}` baseline is replaced by one derived from a
  module-level probe class, plus a red proof that the derived comparison still
  refuses an added member.

In scope — instruments and census artifacts:

- `tests/test_lanes_checks.py` (new `AliasedModuleTests`, 16 tests over a
  scratch package carrying every shape the reader must tell apart)
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

**R2, opaque.** A module that assigns `__class__` on its own
`sys.modules[__name__]` object **to a class this same file defines with a
`__getattr__` or `__getattribute__`** is unjudgeable, exactly as the eleven
modules in this tree that define a module-level `def __getattr__` already are.
Following `_AttemptFacade.__getattr__` through to `_owner` instead was
rejected: it would require proving statically that the method forwards
everything and synthesizes nothing, which is the one claim a reader of a class
body cannot make.

The hook requirement is not decoration; see the adversarial round under
Evidence. Retyping alone is not a reason to stop reading, because a
`ModuleType` subclass with no hook forwards nothing at all.

Both rules fail toward **refusal**, never toward acceptance. If the alias owner
cannot be opened — outside the tree, a namespace-package directory, the file
itself, or past `_MAX_ALIAS_HOPS` — the file is not treated as an alias and is
read literally. If the retyped-to class is not a hook-bearing class statement in
the same file, the module is read literally.

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

R2 is a real, bounded loss: `daedalus.spine.attempt` is no longer judged at all.
The trade is stated plainly rather than hidden — before this packet the reader's
judgement of that module was **100% wrong** (all 34 offenders, 24 distinct
messages, every one naming a name the facade forwards), and silence is better
than a gate that is always wrong about one module and cannot say so.

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
| alias cycle A → B → A, and a self-alias | terminates, then not an alias |
| a five-hop alias chain (budget is four) | past `_MAX_ALIAS_HOPS` → not an alias |
| retype to a class with no attribute hook | forwards nothing → read literally |
| retype to a class this file does not define | not resolvable → read literally |

and exactly one honest non-answer — opaque, no refusal, no crash:

| construct | |
| --- | --- |
| a module that installs a hook-bearing type on itself | R2, at parity with PEP 562 |

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
| 4 | the reader can still go red, fixture | `AliasedModuleTests` | 16 passed (`tests/test_lanes_checks.py`: 45) |
| 4a | every adversarial bypass is closed | the 11 constructs the review built, re-run | all refuse; both real names still pass |
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

The write-lane risk is worth stating precisely, because it is what the
adversarial round was for. After the fixes there is exactly **one** construct
for which the reader is more permissive than before: a module that installs a
type defining `__getattr__` or `__getattribute__` on its own module object. A
file could already buy the same silence with one module-level
`def __getattr__`, which the gate has always honoured, so the new rule adds no
surface a writer did not have. Every other unfollowable or unreadable case
falls back to reading the file literally, which refuses — the opposite of the
first version, and the reason the packet has an adversarial section.

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

- `daedalus/spine/attempt.py` is now unjudged by this gate. A lane writing a
  file that imports an invented name *from that module* would not be refused
  for it. Bounded: one module, and the alternative measured 100% false.
- The `if`-scoped swap refusal is a known, tested, deliberate false positive
  with no instance in the tree.
- `_alias_target` does not require the alias owner to be under the check's
  `first_party_roots`; it requires only that `_module_path` resolve it under
  `repo_root`. Dotted module names cannot contain `..`, so this is not a
  traversal surface, but a filesystem symlink planted inside the tree was not
  tested and is the one vector the adversarial round left open.
- `daedalus/lanes/checks.py` is a write-lane refusal path, and the first
  version of this change was measurably exploitable. It is not Jonas's file by
  the ownership enumeration and it sits close to the fence: **this packet
  should not be promoted without the safety owner's read**, notwithstanding
  that the final reader refuses everything the adversarial round could build.
