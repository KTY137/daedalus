# G1-IFACE-HTTP-01 - HTTP strangler facade

## Frozen packet metadata

- Packet ID: G1-IFACE-HTTP-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: d33b2c9436b2c7cbf357cc3435db8861370e48ee
- Dependencies: G1-IKARUS-14, G1-WEB-01, G1-HIER-02A
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Prerequisite: lazy kernel compatibility facade `575873fc` (cherry-picked
  without conflict as `864be2d0`)
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.web_api` remains the only registered HTTP/effect facade while
route parsing, read dispatch, mutation dispatch, and SSE delivery are owned by
`daedalus.interfaces.http`.

## Scope

The frozen parent held 2,422 lines in `daedalus/web_api.py`. This stage
reduces the facade to 1,325 lines and introduces four responsibility modules:

| Module | Responsibility | Explicit legacy seam |
|---|---|---|
| `router.py` | pure request-target parsing | raw encoded path retained before per-segment decoding |
| `read.py` | GET route dispatch and read projections | `ReadPorts` receives legacy helper owners |
| `effects.py` | body decoding and PUT/POST route dispatch | `EffectPorts` receives monkeypatch-sensitive helpers |
| `sse.py` | dashboard, Ikarus, task, and conversation-request streams | task timing/snapshot policy and stream state are injected |

Authentication, bind policy, static-file delivery, the concrete
`DaedalusHandler` class, `ThreadingHTTPServer` construction, and
`run`/`main` deliberately remain in the facade. The existing projection
helpers also remain there for this first stage and cross the boundary through
named ports. No server, store, scheduler, singleton, route, or effect entry was
added.

## Contracts and behavior

### Compatibility-shim register

| Shim | Owner/target | Preserved callers | Removal criterion |
|---|---|---|---|
| `daedalus.web_api` handler methods | `interfaces.http.{read,effects,sse}` | desktop runtime subclass/replacement, direct handler tests, installed console/module starts, Effect Registry | a separate registry-target migration packet is approved and the Effect Registry digest is intentionally revised |
| `daedalus.web_api._read_body` | `interfaces.http.effects.read_body` | restart and mutation tests monkeypatching the legacy name | runtime-string, monkeypatch, source, wheel, and external-caller audits find no legacy use |
| `daedalus.interfaces.http` lazy exports | exact objects from `daedalus.web_api` | new hierarchical imports during the strangler window | registry migration plus source/runtime-string/wheel/docs audit proves every legacy target removable |

The lazy package export does not cache the resolved value. A test replacing a
legacy monkeypatch seam therefore observes the same object through the new
path. The sole reverse runtime-string import is the documented compatibility
lookup `daedalus.interfaces.http -> daedalus.web_api`; implementation modules
do not import the facade. The production caller audit found one dynamic class
owner: `desktop_runtime.install_web_integration` subclasses and replaces
`web_api.DaedalusHandler` and reads `_read_body`, `_host_capabilities`,
`core`, and `runtime_registry`. Those names remain live on the facade, and
the desktop and UI integration suites are part of this packet's evidence.

### Frozen public contracts

- Registry targets remain `daedalus.web_api:run`,
  `daedalus.web_api:main`,
  `daedalus.web_api:DaedalusHandler.do_POST`, and
  `daedalus.web_api:DaedalusHandler.do_PUT`.
- The facade still contains the real `begin_effect` calls for PUT and POST.
- Routes, status codes, JSON/SSE fields, IDs, headers, and encoded-path
  behavior are unchanged.
- The frozen functional literal multisets are 542 read literals
  (`20e596b7...`), 392 mutation literals (`4ee4c3c7...`), and 207 SSE
  literals (`0f95a95b...`). Focused AST tests bind their complete digests.
- Existing private helpers and module objects remain available from
  `daedalus.web_api`; audited monkeypatch seams are injected rather than
  copied.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Stable effect authority | Registry digest/target and facade-AST tests | exact digest and four targets above |
| Stable wire contract | frozen functional-literal digests plus focused route tests | no missing or added route/JSON/SSE literal |
| Object compatibility | old/new identity and dynamic monkeypatch tests | exact same legacy objects |
| Directed hierarchy | implementation import AST | no implementation import of `web_api` |
| No new authority | implementation responsibility AST | no server, `begin_effect`, `run`, `main`, or handler class |
| Existing behavior | Web, SSE, project, restart, Effect Registry, and lazy-kernel suites | same status/body/event behavior |
| Provider/network budget | builder tests only | zero live provider or network calls |

Frontend sources are untouched, so npm/Playwright are outside this packet.
Historical evidence, persistent stores, Master Plan, amendment chain, Registry,
and generated distribution files are untouched.

## Migration and rollback

Rollback restores the handler bodies to `daedalus.web_api` and removes the
interfaces package/delegation tests. There is no persistent-data migration.
Shim retirement is explicitly outside this packet.

## Evidence expected failures and review

Builder evidence is expected to contain no test, compile, Registry, or
functional-literal failure and no live provider/network call. The focused
project suite retains one existing platform-dependent skip; it is not new
negative evidence. Independent review must confirm that the facade still owns
the real Registry anchors, that the lazy export follows the desktop runtime's
dynamic handler replacement, and that no implementation module imports the
facade or creates another server/effect authority.
