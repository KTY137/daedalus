# G1-IFACE-BRIDGE-13 - File Bridge CLI owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-13
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e1b06da5de46c6bd6badeac59704f8ff0596446b
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-12
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.cli` owns File Bridge argument parsing, command
dispatch, pending-outcome rendering, and human-readable status projection.
The registered `daedalus.file_bridge:main` facade still parses before deciding
whether the command mutates, starts `cli.file_bridge` centrally for every
mutating command, and only then delegates through current injected ports.

## Scope

Only CLI implementation ownership and the request-schema documentation test
move. Subcommand names, arguments, defaults, choices, output fields and text,
exit codes, exception classifications, paths, public callables, effect order,
Registry targets, queue documents, reports, stores, and persistent formats
remain unchanged. The status command remains read-only and fail-open.

## Contracts and behavior

- `watch`, `enqueue`, `once`, `status`, and `mark-read` keep their exact parser
  vocabulary and defaults; no category or other new public flag is introduced.
- The root `main` retains the literal `begin_effect` anchor required by the
  canonical Registry. Its guarded statement precedes the owner dispatch.
- `BridgeCliPorts` captures root paths, functions, compatibility exception
  classes, and pending labels on every call, preserving facade monkeypatch
  seams used by tests and existing embedders.
- `once` continues after classified pending outcomes, sends unknown failures
  to poison recovery, and never turns a pending result into success.
- Human status rendering receives the facade's current stale threshold and
  preserves watcher, queue, report, unread, quarantine, and arrival output.
- The COMMS protocol introspection now measures
  `interfaces.bridge.queue.read_request`, the implementation that owns the
  request fields, instead of introspecting a one-line compatibility wrapper.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| CLI compatibility | parser namespace contracts | exact commands, defaults and choices |
| Guard dominance | facade AST and Effect inventory | one `begin_effect` before one dispatch |
| Live seams | per-call port capture | patched root functions and paths observed |
| Pending honesty | synthetic once dispatch | labelled stderr; poison handler not called |
| Read-only status | status dispatch contract | no outbox creation or Effect start |
| Canonical schema docs | protocol introspection | fields derived from queue owner and documented |
| Architecture/Registry | frozen checks | zero forbidden edges; 20 shims; exact digest |

## Migration and rollback

There is no persistent migration. Rollback restores parser, dispatch, and
status-rendering bodies in `file_bridge.py`, removes the CLI owner and its shim
target, and points the protocol test back at the compatibility wrapper. No
queued request, archived report, journal, ledger, receipt, SQLite database,
CAS locator, evidence path, historical run, or registered Effect target moves.

## Evidence, expected failures, and review

- Python 3.13: 311 focused bridge-owner, queue, journal, projection, dispatch,
  conversation, watcher, crash-recovery, dynamic, envelope, hardening,
  architecture, CLI-effect, and Effect-inventory tests passed; two subtests
  passed.
- Python 3.10: the same 311 focused tests and two subtests passed.
- The facade shrinks from 1,224 to 1,110 lines while retaining all registered
  File Bridge effect doors and the exact `main` guard anchor.
- Changed modules compile, cold imports succeed on Python 3.13 and 3.10, and
  `git diff --check` is clean.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The inherited VS Code dashboard-source assertion still expects the retired
classic implementation's `active_agents` literal; it is outside this Bridge
packet and remains negative evidence for the Cockpit convergence packet. The
global Work-Packet index remains deferred to central integration because of
the inherited G1-HERMES-01 section defect. Review must reject moving the
registered guard into the owner, resolving facade ports at import time, or
turning a classified pending outcome into a completed command. This packet
does not edit the Master Plan, amendment chain, historical `runs/`, generated
web distribution, Registry targets, provider admission, or promotion state.
