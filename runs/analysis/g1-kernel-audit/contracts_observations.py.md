# daedalus/kernel/contracts/observations.py  (24 lines)

Base 54f09753. Static read-only.

## What the file is for

A closed five-value vocabulary (`WORKING`, `PRESENT`, `DEGRADED`, `ABSENT`,
`UNKNOWN`) plus the tuple `OBSERVATION_STATES`, used to describe the
observed state of a subsystem or dispatch outcome. It is not a re-export of
`canonical.py` — it defines its own plain string constants and shares
nothing with the `CanonicalContract` machinery.

## Axis 1 — docstring truth

Grep for the target words over the module docstring: 0 hits. No claims to
check.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| none | — | — | — |

Five string constants and a tuple; no effect surface.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

Not applicable — no validators, no path construction.

## Axis 5 — dead / duplicate

- **Not dead.** `grep -rn "kernel\.contracts\.observations\b" --include="*.py" daedalus tests` →
  2 real importers plus 2 test references:
  - `daedalus/conversation.py:116-123` imports all six names
    (`ABSENT, DEGRADED, OBSERVATION_STATES as OUTCOME_STATES, PRESENT, UNKNOWN, WORKING`),
    all six subsequently referenced in the file (spot-checked, not exhaustively
    traced past the import).
  - `daedalus/health.py:87-93` imports all six names
    (`ABSENT, DEGRADED, OBSERVATION_STATES as STATES, PRESENT, UNKNOWN, WORKING`);
    all six are used directly in `health.py` (`WORKING`/`PRESENT`/`DEGRADED`/
    `ABSENT`/`UNKNOWN` each appear as a `Report(...)` state argument at
    `:263,267,271,275,279`; `STATES` at `:108`).
  - `tests/contracts/test_import_scc_hierarchy.py:217` and
    `tests/contracts/test_observation_state_hierarchy.py:12,69` exercise the
    module directly.
  The module docstring's claim — "consumed... below both consumers" — names
  its two readers as diagnostic implementation and conversation storage;
  `health.py` and `conversation.py` are exactly those two files. Docstring
  and code agree; not a promised-but-missing consumer (the brief's "seam"
  pattern does not apply here).
- **Not a duplicate.** `WORKING`/`PRESENT`/`DEGRADED`/`ABSENT`/`UNKNOWN` do
  not appear as class or constant definitions anywhere in `canonical.py`
  (confirmed by grep, see the `canonical.py` dossier's Axis-1 shadow check).
  No second copy of this vocabulary exists in the five files I audited.
- Not exposed through the package's lazy `__getattr__` name-export path
  (see the `__init__.py` dossier's Axis-5 note) — both real callers import
  directly from the submodule, matching how the module is actually used, so
  this is not a live gap.

## OWNED-FLAG

Not applicable.

## What I did not cover

- Did not read `daedalus/conversation.py` or `daedalus/health.py` in full —
  only grepped for the six imported names' subsequent use.
- Did not check whether any file outside `daedalus/` (e.g. `apps/web`)
  depends on these five string values by hardcoding them rather than
  importing the constants (a stringly-typed duplicate would not show up in
  an import grep).
