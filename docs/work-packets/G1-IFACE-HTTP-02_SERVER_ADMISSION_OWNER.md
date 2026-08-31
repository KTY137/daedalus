# G1-IFACE-HTTP-02 - Server admission owner

## Frozen packet metadata

- Packet ID: G1-IFACE-HTTP-02
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 013a945b122e160646d19a980dc1bbad09b9b003
- Dependencies: G1-IFACE-HTTP-01, G1-HIER-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

HTTP host-bind admission and desktop startup-nonce validation have one
canonical implementation in `daedalus.interfaces.http.server`.
`daedalus.web_api` retains the historical names as thin seams and remains the
only concrete server and registered effect facade.

## Scope and contracts

- Numeric loopback admission, explicit non-loopback opt-in, bearer-token
  length, refusal text, environment names and nonce grammar are unchanged.
- `NonLoopbackBindRefused` is the exact same class object through legacy and
  hierarchy imports. Public constants retain their values.
- `run`, `main`, `DaedalusHandler`, socket construction, static delivery and
  the real Registry anchors remain in `daedalus.web_api`.
- Importing the owner starts no server, opens no socket/store, calls no
  provider, and begins no effect.
- Existing callers may still monkeypatch `web_api._resolve_bind` because
  `run` and `main` continue to call the legacy seam at runtime.

## Compatibility shim and retirement

| Shim | Owner | Removal criterion |
|---|---|---|
| `web_api.{_resolve_bind,_desktop_startup_nonce,_refusal}` | `interfaces.http.server` | source, runtime-string, wheel, docs, desktop, Effect-Registry and monkeypatch audits show no legacy caller after an approved target-migration packet |
| bind constants and refusal class | `interfaces.http.server` | the same audit proves external callers use the hierarchy owner and serialized exception references are absent |

This packet does not retire the broader `daedalus.web_api` facade and does not
change the global Effect Registry target. The global shim registry is updated
with the interface family only in the combined HIER closeout, avoiding a
second concurrent authority over its frozen baseline.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Bind-policy parity | existing loopback/non-loopback suite | identical admissions and refusals |
| Desktop nonce parity | startup-nonce suite | identical value or fail-closed error |
| Thin legacy seams | facade AST test | exactly one owner call per seam |
| No second server/effect authority | owner AST and cold import | no handler, socket, effect, provider or facade import |
| Effect stability | Registry digest and existing target tests | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No persistent data or route migration exists. Rollback restores the three
function bodies, class and constants in `daedalus.web_api` and removes the
owner module. Historical evidence, CAS, ledgers, databases, generated web
artifacts, Master Plan and amendment chain are untouched.

## Retained negative evidence

The broad host-predicate matrix remains red for the pre-existing isolated
Hermes `tool_gateway.py` local-host table. The same single offender reproduces
on this packet's parent. This packet neither allowlists nor changes that row;
it introduces no additional predicate implementation and the HTTP-specific,
CLI, desktop and host behavior tests otherwise pass.
