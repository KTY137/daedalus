# G1-HERMES-01 - Shared loopback predicate

## Frozen packet metadata

- Packet ID: G1-HERMES-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 50324965bbc011941d2900a36f4f926a47569492
- Dependencies: G1-HIER-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The isolated Hermes tool-gateway descriptor no longer owns a second
local-host table. Its exact bare-host wire grammar is decided through the
canonical sensitivity predicate and remains byte-for-byte limited to
`127.0.0.1` and `::1`.

## Scope and boundaries

- `sensitivity.is_loopback_literal` exposes the existing canonical literal
  table for protocols that serialize a bare host. It accepts no URL, port,
  hostname, alternate 127/8 address or non-string value.
- The optional bracketed-IPv6 refusal lets the Hermes wire retain its previous
  exact grammar while other protocols can continue to recognize `[::1]`.
- `is_loopback_host`, `lane_for_host`, declared remote trust and every egress
  decision are unchanged.
- Hermes remains fixture-backed and explicitly constructed. This packet does
  not register it as a production provider, call a model, add an import-time
  registration, invoke an external network service, or claim live containment,
  unknown-outcome recovery or upstream materialization evidence.
- The gateway server still binds only `127.0.0.1`; the accepted `::1` value is
  retained solely as the existing descriptor compatibility contract.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single host predicate | structural host-owner audit | no Hermes inline table |
| Exact wire parity | positive/negative descriptor matrix | only `127.0.0.1` and `::1` |
| Gateway behavior | fixture-backed roundtrip/call-budget tests | unchanged |
| No production admission | Registry/import audit | no new target or registration |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder fixtures only | zero live provider/model/external-network calls; existing loopback gateway fixture only |

## Migration and rollback

No persistent format changes. Existing descriptor JSON, digests, token files,
IDs and gateway frames are unchanged. Rollback restores the descriptor's local
literal expression and removes the narrow helper; no historical evidence,
CAS, database, ledger, release artifact, Master Plan or amendment is touched.
