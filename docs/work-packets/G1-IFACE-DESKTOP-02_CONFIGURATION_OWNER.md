# G1-IFACE-DESKTOP-02 - Desktop configuration owner

## Frozen packet metadata

- Packet ID: G1-IFACE-DESKTOP-02
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: b0d22beb0897690816fe699608274bcc4943b1e3
- Dependencies: G1-IFACE-DESKTOP-01 at bacd9e6e69d58de6aebde4847e6afd6101b2ca72
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.desktop.configuration` becomes the single implementation
owner for desktop defaults and whitelist normalization while
`daedalus.desktop_runtime` remains the stable CLI/effect/process facade. The
move changes no configuration value, validation refusal, route, JSON field,
process behavior, monkeypatch seam, Effect Registry target, or digest.

## Scope

The frozen base contains a 1,719-line `daedalus.desktop_runtime` facade after
G1-IFACE-DESKTOP-01. This packet moves its pure default construction, TCP-port
validation, loopback endpoint validation, numeric-host validation, and complete
configuration whitelist to the 321-line
`daedalus.interfaces.desktop.configuration` owner. The facade becomes 1,483
lines and retains bounded per-call wrappers for public and audited private
compatibility names.

Configuration persistence, widening consent, environment mutation, bridge
ownership, native/Docker IDE process management, local/frozen Ollama process
management, SSH/tunnel handling, sidecar startup, HTTP composition, lifecycle,
and projection remain with their current owners. The Tauri/frontend sources,
generated assets, packet index, stores, schemas, provider admission, Master
Plan, amendment chain, historical evidence, and `runs/` are forbidden paths.

No live provider, network, Docker, SSH, IDE, or EDA call is permitted in
builder evidence.

## Contracts and behavior

### Stable facade and compatibility shims

| Shim | Implementation owner | Preserved callers | Removal criterion |
|---|---|---|---|
| `desktop_runtime.normalize_config` | `interfaces.desktop.configuration.normalize_config` | direct tests/callers, manager load/save paths, lazy `interfaces.desktop` export | source/runtime-string/wheel/docs/pickle audit proves all callers use an injected configuration port |
| `desktop_runtime.DEFAULT_CONFIG` and `IDE_DOCKER_IMAGE` | exact owner objects/values | budget fallback, IDE process configuration, direct imports | manager persistence and process owners no longer read facade globals |
| `_defaults`, `_port`, `_loopback_endpoint`, `_ide_endpoint`, `_numeric_host` | corresponding configuration owner functions | legacy/private source callers and manager patch points | source/runtime-string/monkeypatch audit is empty and manager delegates directly through an approved port |

The facade looks up the owner functions on every call. Replacing the canonical
owner in a test is therefore visible at the legacy path, while the manager
continues resolving the legacy root names `normalize_config`, `_defaults`, and
`_numeric_host` at call time. The existing root monkeypatch seams are not
captured during import.

### Frozen behavior

- The combined non-docstring literal multiset for `_defaults`, `_port`, both
  endpoint validators, `_numeric_host`, and `normalize_config` remains 222
  literals with SHA-256
  `3c71d59a60d3860619c7c89d16b0d6f3461560ca4bb8efbbb03040a9a9b37ad7`.
  The canonical defaults and four allowlist patterns retain SHA-256
  `7d72e29939fdebcc1ea401de1928f79028abcc4b929a1be128d6b8eea6432c3e`.
- Default bridge, budget, cap, IDE, Docker image, Ollama, SSH, port, and model
  values are unchanged. Windows still selects Docker as its derived IDE
  default, and returned defaults remain deep JSON copies.
- Every existing invalid budget/cap/IDE/endpoint/image/remote-host setting
  raises the same `ValueError` text before persistence, service stop,
  environment mutation, process spawn, or network activity.
- The complete `DesktopRuntimeManager` AST remains byte-for-byte equivalent
  under version-neutral attribute-free AST serialization, with SHA-256
  `d8c94495a6f091da6e4031bce4546d95a677427723fcc8ef69bade60050f73c3`.
  The process, tunnel-policy, and web-install facade functions likewise retain
  SHA-256
  `122098f5f6b8f5b9e018c45e064e4ec420d3820d7dbbf08a16a074fc70846a96`.
- The configuration owner imports no desktop facade, process primitive, HTTP
  server, socket, or effect boundary and calls no persistence API. It cannot
  start a process, mutate an environment, write a file, open a socket, or
  register an effect. Its only repository imports are the existing canonical
  `kernel.policy.ledger` defaults and `kernel.policy.limits` value types; it
  does not route back through the `budget` or `limit_policy` root facades.
- The Effect Registry remains
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
  This packet adds no target, anchor, effect, server, process, scheduler,
  singleton, store, port, or provider authorization.

### Retirement dependencies

The root facade remains intentional. Configuration persistence and widening
consent are the next cohesive configuration-service boundary, but moving them
requires injected stop/save/environment ports and a separate failure-ordering
proof. Bridge, IDE, Ollama, SSH, and sidecar ownership retain the retirement
dependencies recorded by G1-IFACE-DESKTOP-01.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Configuration contract stable | literal digest plus full desktop settings tests | exact count/digest, defaults, outputs, and refusal text |
| Root seam stable | per-call owner replacement and manager AST-name tests | owner replacements reach root; manager still resolves root patch points |
| Process semantics stable | frozen manager/process AST digests plus IDE/nonce tests | exact digests and unchanged process/authorization behavior |
| Directed ownership | configuration-owner AST responsibility test | no reverse facade import or process/server/effect/persistence authority |
| Registry stable | semantic Registry digest | exact frozen digest |
| Packet contract valid | direct G1-WP-INDEX-01 artifact parse | unique ID, metadata, and required sections valid without index regeneration |
| Supported interpreters | focused tests and cold imports on Python 3.13 and 3.10 | both interpreters import facade/owner and pass contracts |

Builder evidence follows. A green builder run is not independent review,
merge, promotion, or a Gate transition.

Builder evidence on 2026-08-31:

- the Python 3.13 Desktop/IDE/nonce/packaging/Web/Effect matrix completed with
  `216 passed`, `12 skipped`, `1 deselected`, and `2 subtests passed`; the one
  deselected test is the frozen-parent packaging locator drift recorded below;
- the Python 3.10 configuration-owner, Desktop-01 architecture, runtime,
  IDE-authorization, and startup-nonce matrix completed with `111 passed`;
- fresh Python 3.13 and 3.10 processes imported the owner-first and
  facade-first orders respectively, proved the lazy hierarchical export is the
  exact facade function, proved the default dictionary is the exact owner
  object, and returned the frozen Registry digest;
- the direct Work Packet artifact parser, version-neutral AST digests, literal
  digest, source/runtime-string audit, and tracked index/schema scope checks
  completed without a packet-owned finding.

## Migration and rollback

There is no persistent-data migration. Rollback inlines the owner functions
and default dictionary back into `desktop_runtime.py`, restores its direct
stdlib imports, and removes the bounded wrappers, owner module, architecture
test, and this document. Configuration JSON, environment variables, ledgers,
processes, routes, nonce handling, Registry rows, and sidecar CLI are identical
on either side.

## Evidence expected failures and review

The global Work Packet index is deliberately not regenerated in this isolated
packet. The frozen integration parent already has a known Hermes metadata/index
baseline blocker, and this branch cannot honestly update a shared generated
index while parallel packets are in flight. This packet instead validates its
new artifact directly with the canonical G1-WP-INDEX-01 parser and leaves the
tracked index drift visible for the later integration owner.

The broad packaging run retains one frozen-parent locator assertion:
`test_desktop_backend_readiness_is_child_nonce_bound` expects the startup-nonce
constant as a literal in `web_api.py`, while the frozen parent already exposes
the same value through `http_server.DESKTOP_STARTUP_NONCE_ENV`. Both the test
and `web_api.py` are byte-identical to base revision `b0d22beb`; the unfiltered
run recorded `105 passed`, `12 skipped`, `1 failed`, and `2 subtests passed`.
This packet neither hides nor rewrites that HTTP packaging debt.

The code-ontology preflight was deterministic and read-only. Its Python
adapter was partial and explicitly does not prove dynamic imports, descriptor
dispatch, generated code, monkeypatching, or runtime metaprogramming. Those
limits are covered here by tracked source/runtime-string searches, per-call
monkeypatch tests, cold imports, and focused behavior tests; no ontology data
was persisted.

Independent review must verify that validation failures still precede every
effect, defaults remain deep-copied, manager and process AST digests match the
frozen parent, the root lazy export remains object-identical to the facade,
and no second configuration, process, HTTP, effect, or persistence authority
was introduced.
