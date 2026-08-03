# Daedalus documentation

This index is navigation, not a second source of project truth.

## Authority and active delivery

- [Iron Plan](IKARUS_ARIADNE_MASTER_PLAN.md) is the sole semantic authority for
  architecture, invariants, research priors, and delivery order.
- [Amendment ledger](IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl) records the
  accepted amendment chain.
- [Fourfold v2 execution plan](FOURFOLD_V2_EXECUTION_PLAN.md) is the active
  derived status and evidence projection. It cannot override the Iron Plan.
- [Work packets](work-packets/) contain bounded implementation and review
  packets. Their status is subordinate to the two documents above.

## Evidence and design history

- [Experiments](experiments/) retain frozen specifications and outcomes,
  including invalid and negative results.
- [Research](research/) contains non-authoritative findings, surveys, and
  retained evidence.
- [ADRs](adrs/README.md) are derived decisions and design history.
- [Project wiki](wiki/index.md) is Knowledge-plane material, not orchestration
  state or policy authority.
- [Archive](archive/README.md) retains superseded and foreign-project material
  with source identities.

## Operational and generated material

- [Local models](LOCAL_MODELS.md), [environment switches](ENV_SWITCHES.md),
  [communications protocol](COMMS_PROTOCOL.md), and
  [fallback policy](FALLBACK.md) describe operator-facing surfaces.
- `FEATURE_INVENTORY.json`, `architecture-state.json`,
  `architecture-narrative.md`, and `architecture-map.html` are generated or
  load-bearing projections. Their embedded revision and freshness checks must
  be inspected before using a claim.
- [Historical handoff redirect](HANDOFF.md) exists only to route old links to
  current authority and the preserved original.

ADRs, TODOs, handoffs, inventories, generated maps, and archive files may
supply evidence. They do not amend the Iron Plan or close a delivery gate.
