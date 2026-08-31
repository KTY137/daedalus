# G1-IFACE-DESKTOP-01 - Desktop runtime strangler

## Frozen packet metadata

- Packet ID: G1-IFACE-DESKTOP-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e9cf58a9e97db93d8f2627b52a59e2d58808db4b
- Dependencies: G1-IDE-13 at fc4fdbfcf623e5659e349e2c81f709cd9afa3bea; G1-IFACE-HTTP-01 at e2f5e34714cad292963b6bb9e8b8fb11a09ad12d; G1-WP-INDEX-01 at b2e74d601ab1af274cf670c58be53645c1001114
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.desktop_runtime` remains the stable sidecar and compatibility facade
while desktop HTTP composition, read-only projection, and bounded
bootstrap/close orchestration gain their first implementation owners below
`daedalus.interfaces.desktop`, without changing any process, port, provider,
IDE authorization, nonce, JSON, CLI, or Effect Registry contract.

## Scope

The frozen base held 1,964 lines in `daedalus/desktop_runtime.py`. This packet
reduces the facade to 1,719 lines and adds three responsibility modules:

| Module | Responsibility | Explicit boundary |
|---|---|---|
| `interfaces.desktop.http` | subclass composition for the existing web handler | receives facade-owned URL, nonce, error, and registered-project ports |
| `interfaces.desktop.projection` | bridge, IDE, budget, cap, and service snapshots | reads the existing manager and canonical ledger/file-bridge projections only |
| `interfaces.desktop.lifecycle` | admitted bootstrap and ordered close calls | invokes existing manager methods; owns no process primitive |

In scope are those modules, lazy hierarchical compatibility exports, bounded
delegates in `desktop_runtime.py`, an architecture test, the stale desktop
readiness assertion's locator update to the existing HTTP read owner, and this
Work Packet.
The Tauri frontend, navigation, sidecar CLI, Registry, HTTP facade, project
registry, stores, schemas, provider admission, generated assets, historical
evidence, Master Plan, and amendment chain are forbidden paths.

No frontend source is touched, so npm, Playwright, and visual acceptance are
outside this packet. No live provider, network, Docker, SSH, IDE, or EDA call is
permitted in builder evidence.

## Contracts and behavior

### Stable facade and compatibility shims

| Shim | Implementation owner | Preserved callers | Removal criterion |
|---|---|---|---|
| `desktop_runtime.install_web_integration` | `interfaces.desktop.http.install_web_integration` | desktop sidecar, direct route tests, dynamic `web_api.DaedalusHandler` replacement | sidecar/runtime-string/monkeypatch/wheel audit and a separately approved facade retirement packet |
| `DesktopRuntimeManager.{bootstrap,close}` | `interfaces.desktop.lifecycle` | sidecar lifecycle, atexit bound method, cleanup tests | all lifecycle callers use an injected desktop service port and strict cleanup faults are independently reverified |
| manager projection methods | `interfaces.desktop.projection` | desktop settings/host capability JSON, tests monkeypatching manager probes and status methods | JSON golden fixtures, ledger/file-bridge caller audit, and projection-owner migration are green |
| `daedalus.interfaces.desktop` lazy exports | exact current objects from `daedalus.desktop_runtime` | hierarchical imports during the strangler window | Registry/sidecar/source/runtime-string/wheel/docs/pickle audits prove the facade removable |

The lazy package does not cache resolved values, so a replacement of an
audited facade monkeypatch name remains observable through the hierarchical
path. The HTTP facade delegate passes the current facade bindings for
`urlsplit`, `hmac.compare_digest`, `DesktopRuntimeError`,
`ProjectRegistryUnavailable`, and `resolve_registered_project_root` on every
installation. Existing tests and external callers therefore retain the same
patch point while the implementation module avoids a reverse import.

### Frozen behavior

- `scripts.daedalus_desktop_sidecar` continues importing manager, tunnel-policy
  installer, and web-integration installer from `daedalus.desktop_runtime`.
- `DesktopRuntimeManager`, configuration normalization, process discovery,
  bridge watcher ownership, IDE native/Docker starts, Ollama local/SSH starts,
  stop implementations, environment mutation, and all subprocess objects stay
  in the facade for this first slice.
- IDE start still resolves only a registered project name before
  `ensure_ide`; raw, malformed, missing, and unavailable registrations retain
  their existing `400`/`503` refusals before any process or RW mount.
- Desktop shutdown still requires the per-launch
  `X-Daedalus-Desktop-Nonce`, uses constant-time comparison, and calls strict
  cleanup with the same timeout.
- Route names, status codes, JSON keys, URLs, headers, defaults, CLI imports,
  process arguments, Docker labels, ports, and provider admission are
  unchanged. The complete non-docstring literal multiset for desktop route
  composition remains 69 literals with SHA-256
  `184e31150480c230aac851e1160871f1f6c0bd1204ffd249d44fefecc96cfb62`.
- The Effect Registry retains digest
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
  and the same four registered `daedalus.web_api` HTTP targets. This packet
  adds no server, effect entry, process, scheduler, store, singleton, port, or
  provider authorization.

### Retirement dependencies

The remaining facade is intentionally not presented as retired. Its next
slices require separate proof for configuration persistence and widening
consent, bridge watcher ownership, native/Docker IDE process management,
local/frozen Ollama process handling, SSH host-key/tunnel management, and
environment/egress composition. Each needs source, runtime-string, wheel,
monkeypatch, subprocess-fault, CLI, and Registry audits before ownership moves.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Registry and effect authority stable | digest plus exact web target assertions | exact frozen digest and targets |
| Sidecar facade stable | AST import and exact lazy-export identity tests | three imports remain at old path; hierarchical exports follow facade replacements |
| Wire contracts stable | full HTTP literal digest plus desktop/IDE/nonce tests | exact count/digest and status/body behavior |
| IDE-13 safety stable | registered-name route tests | raw/unregistered paths refused before manager call |
| Monkeypatch seams stable | injected resolver/nonce comparison test and legacy desktop suite | root replacements reach implementation owner |
| Directed ownership | facade-delegate and implementation AST tests | no implementation reverse import or process/server/effect primitive |
| No widened execution | AST responsibility checks and offline tests | no new process, port, provider, network, Docker, SSH, or EDA call |
| Supported interpreter smoke | focused architecture/import suite on Python 3.10 | imports and ownership contracts pass |

The frozen base reproduced 94 passing Desktop/IDE/nonce tests and Registry
digest `ac020278...`. Builder verification records exact post-change commands
and counts in the commit handoff; a green builder result is not promotion or an
independent review.

Builder evidence on 2026-08-31:

- the Python 3.13 Desktop/IDE/Web/Effect/Registry matrix reached `292 passed`,
  `12 skipped`, and `14 subtests passed`; its sole failure was the retained
  Registry scanner baseline named below;
- `tests/test_web_api_loop.py` added `39 passed` and `14 subtests passed`;
- the Python 3.10 desktop architecture, runtime, IDE-authorization, and nonce
  smoke completed with `104 passed`;
- all remaining new-door Registry tests completed with `8 passed` and the one
  retained baseline row deselected;
- the focused packaging suite completed with `42 passed` and `12` existing
  platform skips after its readiness assertion followed the already canonical
  HTTP read owner;
- runtime import evidence returned `True True` for exact old/new manager and
  web-installer objects, and the Registry digest remained the frozen value;
- `uv build` produced the source distribution and wheel, and an isolated
  `--no-deps` wheel installation imported all three implementation owners plus
  the exact facade manager/installer identities outside the checkout.

## Migration and rollback

There is no persistent-data migration. Rollback restores the delegated bodies
to `desktop_runtime.py` and removes `interfaces.desktop` plus its architecture
test. Configuration JSON, ledger/file-bridge data, process arguments, Docker
identity labels, nonce handling, Registry rows, and sidecar CLI remain
unchanged in either direction.

## Evidence expected failures and review

The base's tracked-only Work Packet index check is expected to stop first at
the already present post-index `G1-HIER-01` metadata gap; this packet does not
rewrite parallel Packet documents or their generated index. Its own document
must nevertheless pass the G1-WP-INDEX-01 artifact parser and required-section
contract.

The broad Registry scanner also retains five unrelated frozen-base findings:
`cli.progress` lacks a reachable `filesystem_write` witness, while
`cli.build_exec` lacks reachable `filesystem_write`, `network_egress`,
`secrets`, and `spend` witnesses. The exact failure was reproduced alone in a
clean detached checkout of
`e9cf58a9e97db93d8f2627b52a59e2d58808db4b`; this packet neither hides nor
repairs it.

The HIER-01 exact-baseline test also retains post-freeze locator drift entirely
outside this diff (`current=15`, `allowlisted=5`, `new=10`, `resolved=18`),
principally shifted `kernel/offload_lease.py` edges and already resolved
runtime-to-gate imports. The HTTP/Desktop implementation architecture tests
themselves completed with `26 passed`; this packet does not rewrite the HIER-01
allowlist.

Independent review must verify that the facade ports preserve the real
monkeypatch bindings, projection functions remain observational, strict close
propagates the same cleanup error, the IDE registered-name gate still precedes
every process/mount path, and no second HTTP/effect/process authority was
introduced.
