# G1-WP-01 — Controlled `voltage` → `bias_voltage` Ignition Slice

## Classification

- Iron Plan: `ALIGNED`
- Target gate: `1`
- Base: `g0/sealed-promotion-runtime-sandbox`
- Status: stacked rehearsal; authoritative Gate-1 activation remains blocked on Gate-0 closure
- Promotion: forbidden

## Objective

Exercise the first complete Fourfold renovation loop on a bounded fixture:

```text
base repository
→ base FourfoldSnapshot
→ two explicit WorkItems
→ isolated candidate tree
→ candidate FourfoldSnapshot
→ graph delta
→ behavior verification
→ EvidencePacket
→ exact OwnerApproval binding
```

## WorkItems

1. `rename-code-type`
   - `src/ignition_app/models.py`
   - `src/ignition_app/repository.py`
2. `rename-data-knowledge`
   - `data/events.csv`
   - `schemas/event.schema.json`
   - `wiki/Event.md`
   - `fourfold.json`

## Acceptance criteria

- the base and candidate compile into four complete planes;
- the base fixture contains the trusted `voltage` concept;
- the candidate contains `bias_voltage` at all expected Code, Type, Data, and Knowledge locations;
- no old trusted symbol remains in the declared work-item scope;
- the candidate behavior parses and exposes `bias_voltage` and no legacy `voltage` attribute;
- the candidate source bundle and Fourfold snapshot differ from the base;
- the graph delta contains additions and removals;
- the source fixture tree digest is identical before and after materialization;
- replay from identical inputs produces identical candidate, snapshot, delta, behavior, and evidence digests;
- OwnerApproval binds the exact candidate and EvidencePacket;
- no approval is consumed and no promotion function is invoked.

## Deliberate non-goals

- LLM-generated edits;
- general repository compilation;
- automatic promotion;
- Gate-0 closure or bypass;
- large Polyglot repository validation.
