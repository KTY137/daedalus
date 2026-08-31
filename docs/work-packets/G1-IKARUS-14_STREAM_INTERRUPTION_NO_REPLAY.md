# G1-IKARUS-14 - Stream interruption without replay

## Frozen packet metadata

- Packet ID: `G1-IKARUS-14`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: `repository owner`
- Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Dependencies: `G1-IKARUS-09 through G1-IKARUS-13 behavior frozen in the Gate-1 archive parent`
- Promotion authority: no automatic merge, promotion, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
## Primary acceptance claim

After the one-shot EventSource turn is attempted, a missing or interrupted
final is shown as incomplete and neither client nor backend automatically
starts a second provider request.

## Contracts and behavior

**Baseline reproduced.**

Classic `App.tsx` removed a partial bubble on `EventSource.onerror` and called
`POST /api/ikarus/ask`. The backend also called `_chat()` after an entered
provider stream returned no text. Either transition could repeat a completed
remote request and its spend without an idempotency key.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Mid-stream provider failure | mocked stream test | partial text retained; `stream_interrupted=true`; `_chat` not called |
| Empty provider stream | mocked stream test | halted result; no provider replay |
| Browser stream closes without final | Playwright fault test | halted bubble; no blocking POST |
| Interrupted final carries an action | Playwright fault test | no Apply/Confirm affordance |
| Completed stream/blocking response | contract tests and TypeScript build | `delivery_mode` and explicit false interruption flag |
| Provider/network budget | focused tests | zero live starts/calls |

## Scope

Forbidden: no new chat store, request identity, effect entrypoint, action path,
promotion path, or automatic retry. Routes and canonical conversation state
remain unchanged.

## Migration and rollback

Rollback restores the prior rendering only; it must not be used after a client
has relied on the no-replay guarantee. No persistent-data migration exists.

## Evidence expected failures and review

No live provider or network request is expected in builder evidence.
Independent review must verify that no entered stream path reaches blocking
POST replay and that interrupted action payloads remain non-executable.
