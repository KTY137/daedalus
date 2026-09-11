# G1-IFACE-BRIDGE-10 - Terminal bookkeeping owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-10
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 8bc85e6a9b89a46c239b1c981594f33985e2ea7c
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-09
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.dispatch.finish_terminal_report` owns the ordered
arrival, memory, and archive projections below an already durable terminal
report. `daedalus.file_bridge` reexports the exact pending exception and
injects all local projection operations per call.

## Scope

This packet extracts the terminal report bookkeeping ownership into a dedicated
module under `daedalus.interfaces.bridge.dispatch`. The scope covers ordered
arrival, memory replay, and archive projections applied after a report is
already durably stored.

## Contracts and behavior

### Authority and preserved seams

- `TerminalBookkeepingPorts` receives the clock, existing crash-journal writer,
  arrival projection, memory replay probe, canonical memory recorder, and
  archive move.
- The dispatch owner imports no facade, Effect Registry, memory store, provider,
  network, subprocess, database, or second journal implementation.
- `TerminalBookkeepingPending` is the canonical dispatch-owner class reexported
  by the legacy facade. Old and new imports are the same object; old pickle
  lookups remain resolvable.
- The facade resolves `_write_journal`, `_note_report_arrival`,
  `_memory_already_recorded`, `record_from_bridge_report`, `_archive_once`, and
  `_now_iso` on every call, preserving monkeypatch seams.

### Preserved behavior

- The report remains authoritative before all bookkeeping. Arrival is deduped
  by request key, memory uses the same `pending` crash probe, and archive is
  last.
- Failures are classified as `log`, `memory`, or `archive`; the latest 20
  diagnostics remain retained in the existing journal field.
- A failed diagnostic journal write is attached as `journal_error` and cannot
  authorize report replacement or provider replay.
- Permanent conversation-projection failures retain `projection_failed`;
  ordinary failures retain `bookkeeping_pending`. Successful completion keeps
  the caller-selected terminal state.
- No order, journal state/field, report, arrival line, memory record, archive
  path, exception message, effect, Registry target, or persistent format
  changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Exception identity | focused dispatch contract | old/new object identical |
| Single owner | facade AST contract | exactly one bookkeeping delegation |
| Crash replay | restart and signal suites | no duplicate log/memory/archive/provider |
| Bounded evidence | restart failure tests | last 20 diagnostics retained |
| Directed owner | dispatch import contract | no reverse store/effect authority |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent migration. Rollback restores the bookkeeping body and
exception definition inside `file_bridge.py`; retained reports, journals,
arrival lines, memory records, conversation events, and archives stay put.

## Evidence, expected failures and review

- Python 3.13: 301 focused bridge, bookkeeping, poison, quarantine,
  conversation, crash, Effect, envelope, hardening, and HTTP-loop tests passed;
  16 subtests passed.
- Python 3.10: the same 301 tests and 16 subtests passed.
- Changed modules compile and `git diff --check` reports no whitespace defect.
- G1-HIER-06E's zero forbidden-edge architecture contract is unchanged.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.
