# G1-IFACE-BRIDGE-06B - Claimed dispatch state-machine owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-06B
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 888c08361104c0cf8052ce389ead2a1420ff47dc
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01,
  G1-IFACE-BRIDGE-02, G1-IFACE-BRIDGE-03, G1-IFACE-BRIDGE-04,
  G1-IFACE-BRIDGE-05, G1-IFACE-BRIDGE-06A
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The full crash-safe claimed-request state machine is owned by
`daedalus.interfaces.bridge.dispatch.process_claimed_request`. The registered
`daedalus.file_bridge` facade starts the existing effect in `process_request`,
retains the compatibility and monkeypatch surface, constructs explicit ports,
and delegates the claimed transaction exactly once.

## Scope and authority

- Journal recovery, request-body binding, poison replay, terminal-report reuse,
  attempt bounding, provider dispatch, report publication, conversation
  projection, and terminal bookkeeping move together as one state machine.
- `ClaimedDispatchPorts` receives paths, constants, exception classes,
  persistence operations, projection operations, the effect identity resolver,
  trace adoption, stamping, and the already-admitted bridge-payload dispatcher.
- The owner imports no Daedalus facade, effect boundary, process, network,
  database, provider, or store implementation.
- The root facade resolves every legacy seam per call. Existing tests and
  integrations that patch those seams therefore observe the same objects.

## Preserved contracts

- The `file_bridge.process` registry row and its admission order are unchanged.
- Request/report filenames, normalized request digest, trace field, attempt
  bound, journal states, JSON shape, conversation projection identity, archive
  path, and crash-recovery ordering are unchanged.
- A complete report remains the no-second-spend receipt. A crash after provider
  completion and before journal completion heals from that report and never
  dispatches the provider again.
- No request, report, journal, conversation row, artifact, historical evidence,
  Registry row, persistent path, or digest is migrated.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single owner call | facade AST and delegation test | exactly one claimed-state-machine delegation |
| Crash safety | restart, signal, queue, journal and projection suites | no duplicate work or spend |
| Legacy seams | facade delegation test and existing monkeypatch suites | ports resolve current facade objects per call |
| Directed imports | owner AST test | no reverse facade or effect authority |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

Rollback restores the claimed state-machine body inside `file_bridge.py` and
removes `ClaimedDispatchPorts` plus `process_claimed_request`. The registered
facade remains until Conversation ownership and source, runtime-string, wheel,
documentation, Effect Registry, monkeypatch, and pickle audits prove the
compatibility path can retire.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, registry target, provider
admission, or promotion state.

## Measured evidence

- Python 3.13: 250 focused bridge, crash, queue, journal, projection, Effect,
  envelope, and hardening tests passed; 2 subtests passed.
- Python 3.10: the same 250 tests and 2 subtests passed.
- The focused dispatch-owner contract has 7 passing tests, including the
  exactly-once facade delegation and absence of state-machine calls.
- Both changed Python modules and the focused contract compile; the shim JSON
  parses; `git diff --check` reports no whitespace defect.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- The repository architecture suite has one inherited failure on this packet's
  base: the pre-existing budget shim names the untracked locator
  `daedalus.runtimes.adapters.process`. The six remaining architecture tests
  pass. This packet neither created nor edits that budget row; its correction
  is a separate integration packet.
- One parallel Python 3.10/3.13 run raced over the suite's shared
  `runs/_test_outbox_guard` fixture. The required sequential rerun is green and
  no runtime artifact is tracked.
