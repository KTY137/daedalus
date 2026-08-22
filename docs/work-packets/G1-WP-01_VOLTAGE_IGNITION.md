# G1-WP-01 — Controlled `voltage` → `bias_voltage` Ignition Slice

## Classification

- Iron Plan: `ALIGNED`
- Target gate: `1`
- Base: `g0/sealed-promotion-runtime-sandbox`
- Status: wired through the canonical kernel (2026-08-22); authoritative Gate-1
  activation remains blocked on Gate-0 closure
- Promotion: forbidden

## Status — 2026-08-22 [MEASURED]

`python -m daedalus.ignition` runs the slice end to end
(`daedalus/ignition/gate1.py`) and writes
`runs/ignition/mission-gate1-voltage-ignition/receipt.json`.

| Gate-1 clause | before | now |
| --- | --- | --- |
| one MissionContract | absent — `mission_id` was the literal `"gate1-voltage-rename"` | `mission_contract_for_build_session` over a real `BuildSession`; `mission-gate1-voltage-ignition` |
| two typed WorkItems | two local `IgnitionWorkItem` records with hand-written ids and hard-coded paths | two `BuildTask`s, ids from `derive_work_item_id` (`wi-000-…`, `wi-001-…`), paths derived from `fourfold.json` |
| attempts in isolation | in-process `copytree` + string replace | two `spine.attempt.TaskAttempt` runs across the `python.attempt` boundary; state `clean`, policy `allow`, patches in the content-addressed store |
| tests / schema / link checks | none of the three existed | `daedalus/ignition/checks.py`; all three green on the composed candidate, each with a negative control measured red |
| one EvidencePacket | real packet, but `attempt_contract_sha256` / `policy_decision_sha256` were digests of literal placeholder dicts | `assemble_fourfold_evidence_packet` binding both attempts' real contract digests; 7 items, status `passed` |
| restart/replay | deterministic, unrecorded | receipt `replay` block: mission id, work item ids, base and candidate revisions, graph delta and check verdicts all stable; packet digest explicitly NOT stable (raw pytest output carries durations) |
| no auto-merge | no promotion call | `promotion.status = "nominated, not promoted"`; no promotion module is imported |

Open kernel gap, recorded in the receipt's `blocker` field: `TaskSpec` cannot
declare which paths state its gate's criterion, so `evaluator_assurance` marks
both attempt-level packets `unverified`/`inconclusive` even though each gate's
criterion is provably outside the work item's `target_paths`. The Gate-1 packet
derives its own assurance and binds the attempt packets with their real status
rather than promoting their verdicts.

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
