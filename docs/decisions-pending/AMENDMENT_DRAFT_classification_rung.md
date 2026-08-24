# Amendment draft: a vocabulary rung for "centrally started, no contract covers this effect"

Status: DRAFT for the owner. Ordinary sessions must not land this; it touches
the classification contract's vocabulary, which section 9.2 of
`docs/inventory/2026-08-22/WRITE_SURFACE_CLOSURE.md` deliberately refused to
stretch ("not worth an overclaim") and named as amendment-shaped.

## The measured gap

`SurfaceClassification` admits `central` only with all four receipt kinds and
`local_guards` only with a per-surface guard contract; every surface behind a
registered CENTRAL door whose effects no filesystem-write contract covers
therefore stays `inventory_only` with `candidate_blockers`, and
`authenticated_cleared` is 0 by construction (measured three times: sections
9.1/9.4, LEASED_RUN_CENSUS_DELTA.md, and the cut-D measurement in section 10 --
verdicts move, cleared cannot).

## The proposal (owner decides wording and admission rules)

One new disposition between `inventory_only` and `local_guards`, e.g.
`central_started` -- "the start is centrally guarded (anchor-dominated,
boundary receipt exists), but no declared contract covers this specific
effect". Admission requires: anchor dominance for the surface, the boundary
receipt kinds that DO exist (source_anchor, and effect_lease_receipt where a
lease terminalised), and an explicit `uncovered_effects` list. It clears
NOTHING on its own: it exists so the census can distinguish "nobody looked"
from "looked, started centrally, contract missing", which is the difference
between 405 unclassified and an honest work queue.

## What it must not do

- not count toward `authenticated_cleared`;
- not weaken `central` or `local_guards` admission;
- not be constructible from wire data alone (same replay discipline as
  NonRuntimeConformityAdmission).

## Evidence attached

- WRITE_SURFACE_CLOSURE.md sections 9.1-9.4 and 10;
- docs/inventory/2026-08-24/LEASED_RUN_CENSUS_DELTA.md;
- Momus verdict 2026-08-24 ("the classification vocabulary has no rung ...
  that gap is an amendment proposal, not a wiring commit");
- Codex room turn 60 (variant C as the authenticator's later shape).
