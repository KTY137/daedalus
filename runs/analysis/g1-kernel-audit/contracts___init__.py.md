# daedalus/kernel/contracts/__init__.py  (85 lines)

Base 54f09753. Static read-only.

## What the file is for

A lazy-loading package facade. `_EXPORT_GROUPS` maps every public contract
name to the domain submodule that owns it (`base`, `resources`, `missions`,
`attempts`, `evidence`, `campaigns`, `policy`, `runtime`, `promotion`,
`registry`, `security`, `evaluation`); `__getattr__` (PEP 562) resolves a
name on first access via `import_module` and caches it into `globals()`.
`_MODULES` additionally lets a caller reach a whole domain submodule (e.g.
`contracts.observations`) as a plain attribute even if none of its names are
individually exported. No contract class is defined here.

## Axis 1 — docstring truth

Grep for the target words over the module docstring: 1 hit.

### CONFIRMED
- none.

### PLAUSIBLE
- none beyond the item checked below.

### Checked and honest
- **"``canonical`` remains the single implementation nucleus during the
  strangler split, so every legacy and new import resolves to one class
  object and one serialization authority."** (`__init__.py:3-5`). Verified
  three ways:
  1. AST-parsed `_EXPORT_GROUPS` (36 exported names across 14 owner
     modules) and checked for a name assigned to two different owners —
     zero collisions (`runs/analysis/g1-kernel-audit/w1-scratch/` script
     run inline, see canonical.py dossier's Axis-4 method note for the
     tooling pattern). Every exported name has exactly one owner, so
     `__getattr__` cannot return two different objects for the same name
     across two calls.
  2. Read the four owner facades reachable from my slice plus two adjacent
     ones for a spot check: `base.py` (my file, pure re-export from
     `.canonical`), `resources.py`, and `registry.py` (both pure one-line
     re-exports from `.canonical`, confirmed by reading them). `evaluation.py`
     (my file) and `observations.py` (my file) are *not* re-exports — they
     define their own classes/constants that do not exist in `canonical.py`
     (confirmed no `class Evaluation*`/`WORKING =`/`OBSERVATION_STATES`
     definitions anywhere in `canonical.py` via grep) — so there is no
     shadowing between the facade-style owners and the implementation-style
     owners.
  3. `security.py` (12,626 bytes, not in my slice, spot-read only) is a
     third pattern: a real implementation module that itself imports
     `CanonicalContract`, `_identifier`, `_revision`, `_sha256` etc.
     straight from `.canonical` and subclasses `CanonicalContract` for its
     own additive records (`OwnerApproval`, `EffectLeaseRequest`,
     `EffectLease`). This still resolves to one class object per name; it
     is a second *implementation location*, not a second *definition* of an
     existing name.
  The claim holds for everything I could check. Note in passing (not part
  of this file, flagged for whoever owns `security.py`):
  `security.py:3` says "These records inherit
  ``daedalus.schemas.CanonicalContract``" but the actual import
  (`security.py:14-17`) pulls `CanonicalContract` from
  `daedalus.kernel.contracts.canonical`, not `daedalus.schemas` — a stale
  docstring reference in a file outside my slice, reported here only
  because I opened the file for this check.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| none | — | — | — |

`import_module` (`__init__.py:8, 74, 78`) is a Python import, not a listed
effect category; no subprocess/network/fs-write/env-read in this file.

## Axis 3 — unreleased resources

None. No resource acquisition in this file.

## Axis 4 — validator gaps (W4 class)

Not applicable — this file defines no validator and constructs no path. It
is pure name-routing metadata.

## Axis 5 — dead / duplicate

- `observations` is listed in `_MODULES` (`__init__.py:58`) but has **no**
  entry in `_EXPORT_GROUPS`. Consequence: `daedalus.kernel.contracts.WORKING`
  (or any of the other four observation constants) does not resolve via
  `__getattr__`'s name-export path — only `daedalus.kernel.contracts.observations`
  (the submodule itself) resolves, then the caller must dot into it. This
  matches how the two real callers actually import it
  (`daedalus/conversation.py:116`, `daedalus/health.py:87` both use
  `from .kernel.contracts.observations import (...)`, not the package-level
  facade) — so this is an intentional, exercised asymmetry, not dead
  routing. Not a finding.
- Every name in `_EXPORT_GROUPS` was checked against the file listing of
  `daedalus/kernel/contracts/` (14 files) and every owner string matches an
  existing module — no dangling facade entry.
- No duplicate regex/validator/digest helper in this file (it has none).

## OWNED-FLAG

Not applicable.

## What I did not cover

- Did not verify that every one of the 36 exported names actually exists as
  an attribute on its claimed owner module (spot-checked `base.py`,
  `resources.py`, `registry.py`, `evaluation.py`, `observations.py`;
  `attempts.py`, `campaigns.py`, `evidence.py`, `missions.py`, `policy.py`,
  `promotion.py`, `runtime.py`, `security.py` were not opened beyond the one
  `security.py` docstring spot check above — not in my assigned slice).
- Did not check whether `__getattr__`'s caching into `globals()` interacts
  correctly with `importlib.reload` or circular-import edge cases.
