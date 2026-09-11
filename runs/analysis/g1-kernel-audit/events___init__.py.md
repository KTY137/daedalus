# daedalus/kernel/events/__init__.py  (94 lines)

Base 54f09753. Static read-only. Auditor: parent (W3 slice, subagent cap hit).

## What the file is for

Lazy facade for the `events` subpackage. Maps 44 export names to one of three
owner modules (`envelope`, `ledger`, `durability`) and resolves them on first
attribute access, so importing a pure envelope helper does not load the SQLite
durability machinery.

## Axis 1 — docstring truth

### Checked and TRUE

- `:3-4` "The owner package is lazy so importing one pure envelope helper does
  not also load SQLite durability machinery." Verified: `__getattr__` (`:81-90`)
  is the only import path; there is no module-level `from .ledger import ...`.
  The `_EXPORTS` dict (`:15-76`) is built from string literals only, so
  constructing it imports nothing. The claim holds.

  This is a real trust property, not just an optimisation: `events/ledger.py`
  documents at `:322-327` ("HONEST LIMIT") that merely opening the ledger
  creates `-wal`/`-shm` sidecars. Laziness here means importing
  `canonical_json` cannot trigger that.
- `:4-5` "``daedalus.spine`` remains the historical compatibility surface while
  callers migrate to this hierarchy." Consistent with
  `events/durability.py:3-4`, which says the same in the other direction
  ("the historical ``daedalus.spine.durability`` locator is a compatibility
  facade only").

### No overclaims

No `always`/`guaranteed`/`never`/`authenticated` claims in this module.

## Axis 2 — effect surface

None. Only `importlib.import_module` (`:10`, `:83`, `:88`). Correctly absent
from the Effect Registry.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

Not applicable. `__getattr__` resolves `name` through the frozen `_SUBMODULES`
set (`:13`) and `_EXPORTS` dict (`:15`) and raises `AttributeError` on a miss
(`:87`); caller input is never interpolated into an import path. Correct — same
discipline as `contracts/__init__.py`.

## Axis 5 — dead / duplicate

### Checked — the enumeration here is COMPLETE, unlike the parent facade

`_SUBMODULES = frozenset({"durability", "envelope", "ledger"})` (`:13`) matches
the directory exactly: `events/` contains `__init__.py`, `durability.py`,
`envelope.py`, `ledger.py` and nothing else.

This is worth recording because the **parent** facade one level up has the same
construction and is *not* complete: `daedalus/kernel/__init__.py`'s
`_LAZY_MODULES` declares 27 modules while 29 exist, omitting `attempt_execution`,
`events`, and `policy` (measured — see `kernel___init__.py.md`). And
`contracts/__init__.py`'s `_MODULES` is also complete (14/14, measured).

So of the three sibling lazy facades in the kernel, two enumerate their
submodules completely and one has drifted. That localises the defect precisely
rather than leaving it as a general complaint about the pattern.

### Note on the export tables

The three `_EXPORTS` groups (`:16-45` envelope, `:46-65` ledger, `:66-75`
durability) are hand-maintained name lists. The `durability` group lists exactly
the five names in `durability.py:227-233`'s `__all__` — verified by direct
comparison. I did not verify the envelope (24 names) and ledger (14 names)
groups against their owners' `__all__`; that is the same cheap mechanical check
I flagged as worthwhile for the parent facade, and it would catch a rename that
silently broke a compatibility name. Not claiming either way.

## What I did not cover

Whether all 44 declared export names resolve (see above) — requires importing
the owners, which this static-only audit does not do.
