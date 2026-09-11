# Daedalus documentation map

`docs/` contains current operating documentation, authority documents, backlog,
and historical evidence. Do not infer freshness from location alone: a dated
finding is valuable because it records the tree at a particular revision and
must not be silently rewritten to look current.

This page is an index, not an authority. Semantic authority is
[`IKARUS_ARIADNE_MASTER_PLAN.md`](IKARUS_ARIADNE_MASTER_PLAN.md); current status
is [`STATUS.md`](STATUS.md).

## Start here

| Document | Purpose |
|---|---|
| [`STATUS.md`](STATUS.md) | Current truth pointers and unresolved items. |
| [`../README.md`](../README.md) | Product contract, invariants, entry points and operator quickstart. |
| [`IKARUS_ARIADNE_MASTER_PLAN.md`](IKARUS_ARIADNE_MASTER_PLAN.md) | Sole semantic authority for invariants, gates, priors and delivery order. |
| [`IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`](IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl) | Append-only amendment chain. |
| [`DAEDALUS_GESAMTPLAN.md`](DAEDALUS_GESAMTPLAN.md) | Build programme within the master plan's bounds. |
| [`architecture-narrative.md`](architecture-narrative.md) | Current architecture narrative. Pair with `architecture-state.json`. |
| [`CONTINUOUS_DAEDALUS.md`](CONTINUOUS_DAEDALUS.md) | Supported bounded continuous-run operator setup. |
| [`chip-design/README.md`](chip-design/README.md) | RTL/EDA/Tcl capability and hardware-workflow documentation. |

`ARCHITECTURE.md` and `MISSION_CONTROL.md` are compatibility tombstones for old
links. Their contents are historical; do not use them as implementation
contracts. The condensed Era-3 architecture record now lives under
[`archive/ARCHITECTURE_ERA3.md`](archive/ARCHITECTURE_ERA3.md).

## Document classes

**Current** documents describe the system as it is now and should be repaired
when code or operator behavior moves. This includes `STATUS.md`,
`architecture-narrative.md`, `PROJECT_SCOPE.md`, `COMMS_PROTOCOL.md`,
`FALLBACK.md`, `GUI_CATALOGUE.md`, `ENGINE_PARITY.md`, `CONTINUOUS_DAEDALUS.md`,
`chip-design/`, and `wiki/`.

**Authority** documents define project semantics rather than report them: the
master plan, its amendment chain, `DAEDALUS_GESAMTPLAN.md`, and the root
`AGENTS.md` / `CLAUDE.md`. Change them only through their amendment/governance
protocol; ordinary documentation cleanup must not rewrite policy.

**Evidence** is revision- or date-bound history: `archive/`, `inventory/`,
`recovery/`, `missions/`, `decisions-taken/`, `architecture_history/`,
`research/`, gate findings, `HANDOFF*.md`, and amendment proposals. Dead paths
inside evidence are usually part of the record, not a reason to modernize it.
If a historical page is still a live navigation target and contains an unsafe
or materially false instruction, add a correction banner rather than rewriting
its history.

**Backlog** names intended work and therefore may reference modules that do not
exist yet: `work-packets/`, `design/`, `decisions-pending/`, `adrs/`, and
`ABSORPTION.md`. ADRs and proposals never override the master plan.

## Maintenance rules

1. **Do not copy volatile counts into current prose.** Link the command or
   receipt that produces them. Use `MEASURED`, `INHERITED`, and `ASSUMED` when a
   number must be recorded.
2. **Archive superseded explanations; keep compatibility pointers short.** Old
   links should resolve to a tombstone that sends readers to the current source
   and to the archived record.
3. **Do not repair evidence into fiction.** Preserve dated findings and receipts
   as they were observed; append a correction when later evidence changes the
   interpretation.
4. **Keep one canonical explanation per contract.** Other pages should link to
   it instead of copying command lists, architecture diagrams, test counts or
   status tables.
5. **Generated artifacts are not prose.** Do not hand-edit generated snapshots
   to make them agree with a narrative; regenerate them through their owning
   command and review the result.

## Checks

```powershell
python tools/docs_reference_check.py
python -m daedalus.interfaces.cli.entry map --check
```

`docs_reference_check.py` checks resolvable references in current pages while
reporting evidence/backlog separately. `map --check` is the architecture gate;
its output is a measurement, so read `STATUS.md` before treating an old snapshot
as current.

A green reference check proves that links resolve, not that prose is true.
Semantic drift still requires comparing current documentation with code, tests,
configuration and recent commits.
