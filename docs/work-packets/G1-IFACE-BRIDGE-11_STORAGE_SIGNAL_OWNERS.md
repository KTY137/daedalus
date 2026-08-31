# G1-IFACE-BRIDGE-11 - Storage and signal owners

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-11
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 7d0a89d90da92e792e7696aada77d1b53cde2b38
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-10
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The remaining bridge storage and arrival-signal implementations are owned by
the existing directed modules: journal owns atomic JSON/report reads,
projection owns read-state/arrival locators and append semantics, and dispatch
owns memory replay probing plus fixed-destination archive moves. The root
module contains compatibility wrappers only.

## Ownership

- `interfaces.bridge.journal`: `write_json_atomic` and `completed_report`.
  The actual atomic publisher remains an injected canonical `daedalus.atomic`
  operation; the owner creates no second store.
- `interfaces.bridge.projection`: `seen_dir`, `latest_log`, and
  `note_report_arrival`. Clock and canonical trace lookup are injected.
- `interfaces.bridge.dispatch`: `memory_already_recorded` and
  `archive_request_once`. The canonical memory path and filesystem move
  operations are injected by the facade.
- Every legacy helper resolves its path/clock/hash/move/atomic seam per call,
  preserving tests and supported compatibility callers.

## Preserved behavior

- JSON continues to use `indent=2` and the same random-suffix atomic writer.
- A report is reusable only when it parses to one complete JSON object.
- Seen markers and `LATEST.log` stay beneath the patched/current inbox.
- Arrival lines retain timestamp, filename, status, lane, request key, and
  trace formatting; key-bearing lines remain content-deduplicated.
- The expensive memory-log scan still occurs only for a `memory=pending`
  replay and ignores malformed lines.
- Archive uses the same fixed key-derived destination, atomic replacement, and
  cross-device fallback; move failure returns `False` for retry.
- No file name, content, ordering, report, journal, memory, archive, trace,
  effect, Registry target, or persistent format changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Thin facade | journal/projection/dispatch AST contracts | one owner delegation per helper |
| Report authority | restart suite | partial reports never suppress work |
| Signal idempotency | crash/restart suite | one key-bearing arrival line |
| Memory recovery | terminal-bookkeeping tests | no duplicate memory append |
| Archive recovery | signal/restart tests | one fixed archived copy |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration, rollback, and evidence

There is no persistent migration. Rollback restores these small helper bodies
inside `file_bridge.py`; existing reports, journals, read markers, arrival
lines, memory records, and archive files are not moved.

- Python 3.13: 301 focused bridge, storage, signal, crash, Effect, envelope,
  hardening, and HTTP-loop tests passed; 16 subtests passed.
- Python 3.10: the same 301 tests and 16 subtests passed.
- Changed modules compile and `git diff --check` reports no whitespace defect.
- G1-HIER-06E's zero forbidden-edge architecture contract is unchanged.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.
