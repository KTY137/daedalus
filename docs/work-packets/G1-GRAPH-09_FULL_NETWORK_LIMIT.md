# Work Packet: G1-GRAPH-09 Full network display limit

Status: review packet  
Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 8  
Base revision: `98833bf7`

## Primary claim

The cockpit graph can request the whole indexed network or a bounded node count,
states which scope is shown, and never presents a capped projection as the whole
Project Twin.

## Allowed surfaces

- `apps/web/src/components/CodeMap.tsx` and its styles
- the canonical structure graph projection and `/api/structure`
- focused graph/API tests and generated web assets

## Acceptance

- The owner can select a useful node limit and an explicit `all` option.
- Changing the limit refetches/reprojects nodes and edges server-side.
- Visible, total, and truncation counts remain legible.
- A stale selection cannot survive a changed projection.
- TypeScript and the production frontend build pass.

## Forbidden

- No second graph authority or candidate identity.
- No claim that a bounded projection is the complete Project Twin.
- No automatic promotion, plan edit, or unrelated cockpit redesign.
