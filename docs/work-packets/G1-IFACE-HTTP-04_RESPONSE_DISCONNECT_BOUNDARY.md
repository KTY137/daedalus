# G1-IFACE-HTTP-04 - Response disconnect boundary

## Frozen packet metadata

- Packet ID: G1-IFACE-HTTP-04
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
- Dependencies: G1-IFACE-HTTP-01, G1-IFACE-HTTP-02,
  G1-IFACE-HTTP-03
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

The existing `DaedalusHandler` treats a broken, reset, or aborted response
socket as terminal transport control flow. JSON, unauthorized, preflight, and
static responses whose client has gone away never cause a redundant JSON error
response, while genuine request-handler and static-file failures still produce
their existing JSON status and body.

## Scope

This packet changes only the concrete response boundary in
`daedalus/interfaces/http/web_api.py`, adds focused offline tests under
`tests/interfaces/`, and records this packet. It does not add another handler,
server, route, store, effect entrypoint, transport module, or authority.

Chat, settings semantics, desktop composition, provider/runtime behavior,
frontend sources and distribution artifacts, package metadata and lockfiles,
GPU work, persistent formats, historical evidence, the Master Plan, amendment
chain, and the global Work Packet index are explicitly out of scope.

## Contracts and behavior

- `BrokenPipeError`, `ConnectionResetError`, and `ConnectionAbortedError`
  raised while sending JSON, unauthorized, preflight, or static response
  headers/body mean that the peer is gone. The handler marks the connection
  closed and returns without another write.
- Classification is tied to the response write boundary. The same exception
  classes raised by backend/route computation remain handler failures and are
  translated through the existing HTTP error path; exception type alone is
  not evidence that the client socket was the origin.
- A non-transport exception from GET/PUT/POST retains the established status
  mapping and attempts exactly one JSON response.
- Other `OSError` instances remain ordinary failures; this packet does not
  broadly suppress filesystem, configuration, or handler errors.
- Authorization, bind admission, effect admission, routes, JSON fields,
  status codes, static-file selection, SSE ownership, and Effect Registry
  targets are unchanged.
- One private handler helper owns the bounded non-SSE header/body write. It is
  not a route, server, transport, effect, or new authority; SSE retains its
  established streaming owner and framing.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| No duplicate response | fake wire raises each supported disconnect from the first JSON write | one write attempt and no propagated exception |
| Unauthorized disconnect | fake 401 header/body raises each supported disconnect | one 401 attempt, closed connection, no JSON fallback |
| Static disconnect | existing and fallback static response header/body raises each supported disconnect | one 200 attempt, closed connection, no 500 fallback |
| Preflight disconnect | fake 204 header write raises each supported disconnect | one 204 attempt and closed connection |
| Provenance stays narrow | route delegate raises each supported exception class before a response write | exactly one existing 500 JSON envelope |
| Handler failures remain visible | delegate raises a non-transport exception | exactly one existing 500 JSON envelope |
| Narrow classification | delegate raises an unrelated `OSError` | one 500 JSON envelope; error text retained |
| Existing wire/effect authority | HTTP architecture and Web API suites | unchanged route literals, Registry digest, and effect anchors |
| Provider/network budget | focused builder tests | zero provider calls; fake handler only, no live network |

## Migration and rollback

There is no persistent-data or wire-format migration. Rollback removes the
narrow disconnect catches and the focused tests. No store, artifact, ledger,
route, client, or compatibility translation is required.

## Evidence expected failures and review

The live baseline on Windows emitted nested `ConnectionAbortedError [WinError
10053]` tracebacks after Playwright closed requests while slow health/API
responses were completing. The first deterministic baseline run retained 12
failures and 2 passes: three failures reproduced the double JSON write for the
three supported disconnect classes; nine deliberately synthetic tests raised
those classes directly from route delegates. Review rejected the latter as an
over-broad acceptance rule before implementation because an exception class
without response-write provenance can also describe backend I/O. The frozen
implementation test therefore requires the write-boundary failures to become
terminal while direct route failures keep their existing JSON error mapping.
Independent review of the first implementation found two more direct-write
gaps: `_deny` and `_send_static` could still propagate or translate a response
disconnect into a redundant 500 write; `do_OPTIONS` also wrote headers outside
the boundary. Their focused red baselines are retained by the expanded matrix
before consolidating all non-SSE responses behind the same private helper.

No focused failure is expected after the change. Independent review must
confirm that only the three peer-disconnect exception classes are terminal,
that real handler failures still reach the existing response mapping, and that
the patch neither changes effect admission nor introduces a second HTTP owner.
