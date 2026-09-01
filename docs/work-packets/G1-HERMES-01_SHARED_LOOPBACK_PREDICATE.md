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

## Scope

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

## Contracts and behavior

`sensitivity.is_loopback_literal(host, *, allow_bracketed_ipv6=True)` returns
whether `host` is one of the canonical numeric loopback literals held in the
single `_LOOPBACK_LITERALS` table (`127.0.0.1`, `::1`, `[::1]`). It fails
closed on any non-string, strips and lowercases before comparison, and accepts
no URL, port, hostname, or alternate 127/8 address. The keyword-only
`allow_bracketed_ipv6=False` narrows the result to the bare-host forms.

`HermesGatewayDescriptor.__post_init__` now decides its host through that
predicate with `allow_bracketed_ipv6=False` instead of an inline
`{"127.0.0.1", "::1"}` set. The accepted wire grammar is therefore unchanged:
`127.0.0.1` and `::1` construct, and `[::1]`, `127.0.0.2` and `localhost`
still raise `HermesToolGatewayError("gateway descriptor is not loopback-only")`
before any descriptor, token file, or socket exists.

`is_loopback_host`, `lane_for_host`, `declared_trusted_hosts`, the
`DAEDALUS_TRUSTED_HOSTS` declaration path, and every egress lane decision are
untouched; this packet adds a narrower reader over the existing table and
removes a duplicate, it does not widen any trust boundary. Descriptor JSON
fields, canonical serialization, and digest computation are unchanged, so
previously written descriptors validate identically.

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

## Evidence, expected failures and review

Evidence is builder-level and offline. `tests/test_host_predicate.py` covers
the predicate directly: the canonical literals, the bracketed-IPv6 opt-out,
and the fail-closed non-string and near-miss cases.
`tests/integrations/test_hermes_tool_gateway.py` covers the descriptor wire
grammar as a positive/negative matrix — `127.0.0.1` and `::1` construct,
`127.0.0.2`, `[::1]` and `localhost` refuse with the unchanged
`loopback-only` message — plus the pre-existing roundtrip, call-budget and
digest-tamper cases.

Expected failures retained as negative evidence: `[::1]` is deliberately
refused by the Hermes wire although the shared table contains it, because the
descriptor's historical grammar is bare-host only; widening it would be a
separate packet. `localhost` is refused because the predicate resolves no
names by design.

Budget: zero live provider, model, container or external-network calls. The
gateway is exercised only through the existing loopback fixture. Hermes gains
no production registration and no import-time side effect in this packet.

Review questions: does any caller reach `is_loopback_literal` expecting name
resolution or 127/8 range semantics (it must not); does the Effect Registry
digest `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
still hold; and is `_LOOPBACK_LITERALS` now the only loopback table in the
tree.
