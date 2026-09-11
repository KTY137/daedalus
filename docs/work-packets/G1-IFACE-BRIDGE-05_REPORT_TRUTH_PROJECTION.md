# G1-IFACE-BRIDGE-05 - File Bridge report-truth projection

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-05
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 4b8ef61631a667bda48fdea3b88a7aba78c4daef
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01, G1-IFACE-BRIDGE-02,
  G1-IFACE-BRIDGE-03, G1-IFACE-BRIDGE-04
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Provider-reported status extraction, retained write-evidence interpretation,
and conservative conversation fields are implemented once under
`daedalus.interfaces.bridge.projection`; the stable `daedalus.file_bridge`
names remain thin compatibility delegates used by HTTP and conversation code.

## Scope

This packet extends the existing projection owner with three pure report
interpretations. It does not move the canonical conversation-spine write,
reconciliation effect, queue retry, report publication, dispatch, poison
recovery, watcher, or CLI.

## Contracts and behavior

- Top-level and assignment-nested provider report shapes, status de-duplication,
  120/600/1000-character bounds, and `gated_held` wording are unchanged.
- Application truth remains evidence-driven: bridge completion alone does not
  imply apply, verify-fail/rollback ambiguity remains unknown, advisory and
  held work remain not-applied, and only measured writes plus a passed verify
  gate become true.
- Conversation states still use the canonical `conversation` constants passed
  by the facade. Unknown terminal words cannot become an accidentally green
  sixth state.
- No path, store, event, digest, route, JSON field, effect target, provider,
  process, network, or persistent artifact changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Stable public/private API | facade-delegation architecture test | each old name calls one owner |
| Conservative apply truth | Web/bridge and focused owner tests | no completion-to-applied inference |
| Conversation projection | canonical-spine and restart suites | same state, summary, detail and idempotency |
| HTTP projection | Web API suite | same report snapshot fields and reasons |
| Effect authority | Registry digest | unchanged |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No report, request, journal, conversation row, heartbeat, historical evidence,
Registry row, or persistent path is migrated. Rollback restores the three pure
function bodies in `daedalus.file_bridge` and removes them from the owner.

The facade remains until Dispatch and Conversation owners land and source,
runtime-string, wheel, documentation, Effect Registry, monkeypatch, and pickle
audits prove that the compatibility path can retire.

## Evidence expected failures and review

No bridge, Web, conversation, Registry, compile, or compatibility failure is
expected. The generated Work-Packet index is refreshed centrally after parallel
integration. Review must confirm there is no second report or conversation
store and that the implementation owner remains pure interpretation code.
