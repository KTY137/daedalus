# G1-IFACE-DESKTOP-03 - Desktop settings owner

## Frozen packet metadata

- Packet ID: G1-IFACE-DESKTOP-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 0ce7414a3c22e3357816e08a76ed0b1478f3e41d
- Dependencies: G1-IFACE-DESKTOP-02 at 0ce7414a3c22e3357816e08a76ed0b1478f3e41d
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.desktop.settings` becomes the single implementation owner
for desktop settings loading, atomic persistence, execution-limit widening
consent, and environment projection. `daedalus.desktop_runtime` remains the
stable Effect/CLI/process facade and retains every manager method, per-call
monkeypatch seam, route, JSON field, nonce, process action, and Registry target.

## Scope

The frozen base contains a 1,483-line `daedalus.desktop_runtime` after
G1-IFACE-DESKTOP-02. This packet moves the five cohesive settings methods to a
355-line internal owner and leaves bounded delegates at the existing class
paths. The facade becomes 1,256 lines.

In scope are budget/cap fallback reads, configuration load and atomic replace,
transient widening confirmation, route-change stop ordering, save rollback,
environment projection, and post-save autostart ordering. The owner receives
all policy, filesystem, environment, error, normalization, and process/service
operations through ports resolved by the facade on every call.

Bridge ownership, native/Docker IDE implementation, local/frozen Ollama,
SSH/tunnel implementation, logging, sidecar startup, HTTP composition,
lifecycle, projection, and pure normalization remain with their current
owners. Frontend/Tauri sources, generated assets, the global packet index,
stores, schemas, provider admission, Master Plan, amendment chain, historical
evidence, and `runs/` are forbidden paths. No live provider, network, Docker,
SSH, IDE, Ollama, or EDA call is permitted in builder evidence.

## Contracts and behavior

### Stable facade and compatibility shims

| Shim | Implementation owner | Preserved callers | Removal criterion |
|---|---|---|---|
| `DesktopRuntimeManager._read_budget_environment` | `interfaces.desktop.settings.read_budget_environment` | constructor and tests | manager construction uses an injected settings service and environment/default contracts are independently versioned |
| `DesktopRuntimeManager._load/_save` | `interfaces.desktop.settings.load/save` | constructor, save flow, private patches | source/runtime-string/wheel/monkeypatch audit is empty and persistence is reached only through an injected settings port |
| `DesktopRuntimeManager.save_settings` | `interfaces.desktop.settings.save_settings` | HTTP PUT route, direct tests/callers | route and callers depend on a settings-service contract rather than the concrete manager |
| `DesktopRuntimeManager.apply_environment` | `interfaces.desktop.settings.apply_environment` | constructor, save flow, direct tests | environment projection has its own admitted effect contract and facade retirement packet |

The root wrappers pass their current `json`, `os`, budget, policy, error,
normalization, default, numeric-host, and environment bindings on every call.
The implementation owner imports no repository module and never imports the
facade. Process and service actions remain dynamic calls on the injected
manager, preserving instance-level patches and the existing single process
owner.

### Frozen behavior

- The combined non-docstring literal multiset for the five moved methods
  remains 145 literals with SHA-256
  `9cd1426a7902482cd2fc8593eb0c42b69a7a986b72c8de1e97994a704e64251d`.
- The 42 non-settings manager methods retain version-neutral AST SHA-256
  `0d20d6880be9d539b68a2ed4854c085680e9e8e50dda6c6becd892a805e4f489`.
  Top-level process, tunnel-policy, and web-install functions retain SHA-256
  `122098f5f6b8f5b9e018c45e064e4ec420d3820d7dbbf08a16a074fc70846a96`.
- Validation and widening consent still complete before every service stop,
  write, environment mutation, ledger access, or autostart. Route changes stop
  Ollama before IDE, a failed atomic save restores the exact prior config
  object and skips environment/autostart, and success orders save, environment,
  bridge, Ollama, IDE, then snapshot.
- The configuration locator, JSON structure, indentation/newline, temporary
  filename, `os.replace` atomicity, error texts, migration rules, cap semantics,
  environment keys/values, trusted-host handling, and response projection are
  unchanged.
- `settings` imports no process, server, socket, network, effect-boundary, root
  facade, or repository module. It creates no class, singleton, process, port,
  store, scheduler, provider authorization, or callable effect entrypoint.
  Filesystem/environment effects remain reachable only through the existing
  manager facade and injected ports.
- The Effect Registry remains
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

### Retirement dependencies

The manager/root facade remains intentional. Its remaining cohesive slices are
bridge watcher ownership, native/Docker IDE process management, local/frozen
Ollama process management, SSH host-key/tunnel management, and logging/process
support. Each requires a separate subprocess-fault, ownership, runtime-string,
wheel, CLI, monkeypatch, and Registry audit before moving.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Settings contract stable | frozen literal digest plus full desktop settings suite | exact digest, JSON/defaults/refusals/environment behavior |
| Root seams stable | AST delegate bounds and runtime replacement-port capture | all five old methods resolve current facade bindings per call |
| Failure order stable | rejection, save-failure rollback, and success-order tests | no pre-consent effect; exact stop/save/environment/autostart order |
| Process semantics stable | 42-method and top-level process AST digests plus IDE/nonce tests | exact frozen digests and behavior |
| Directed ownership | owner AST responsibility test | no reverse import or process/server/network/effect entry authority |
| Registry stable | semantic Registry digest | exact frozen digest |
| Packet contract valid | direct G1-WP-INDEX-01 artifact parse | metadata and six required sections valid without global index regeneration |
| Supported interpreters | focused tests and cold imports on Python 3.13 and 3.10 | both interpreters pass and old/new import order is stable |

Builder evidence on 2026-08-31:

- the Python 3.13 Desktop/settings/IDE/nonce/packaging/Web/Effect matrix
  completed with `223 passed`, `12 skipped`, `1 deselected`, and `2 subtests
  passed`; the one deselected test is the inherited locator assertion recorded
  below;
- the Python 3.10 settings, Desktop-01/02 architecture, runtime,
  IDE-authorization, and startup-nonce matrix completed with `118 passed`;
- fresh Python 3.13 and 3.10 processes exercised owner-first and facade-first
  imports and returned the exact frozen semantic Registry digest;
- tracked source/runtime-string/pickle and forbidden-path audits, the direct
  packet parser, literal/AST digests, and `git diff --check` completed without
  a packet-owned finding.

A green builder result is not independent review, merge, promotion, or a Gate
transition.

## Migration and rollback

There is no persistent-data migration. Rollback inlines the five settings
functions into their unchanged manager paths and removes the owner import,
architecture test, and this document. Existing configuration JSON, temporary
files, environment, ledger state, processes, routes, nonce, Registry rows, and
sidecar CLI require no conversion in either direction.

## Evidence expected failures and review

The global Work Packet index is deliberately not regenerated in this isolated
packet. The parent retains the known Hermes metadata/index blocker, and a
parallel packet branch cannot safely claim the shared generated index. This
artifact is validated directly with the canonical G1-WP-INDEX-01 parser.

The inherited
`test_desktop_backend_readiness_is_child_nonce_bound` locator assertion remains
red at the exact parent: it demands a duplicate startup-nonce literal in
`web_api.py`, while the stable facade already aliases the canonical
`http_server.DESKTOP_STARTUP_NONCE_ENV`. This packet must not make it green by
reintroducing a second literal authority. The baseline run recorded `1 failed`;
both the test and HTTP facade remain outside this diff.

The code-ontology preflight was deterministic and read-only over 1,438 Python
files, with three excluded directories and 29 sensitive-name skips. Its Python
adapter is partial and cannot prove dynamic imports, descriptor dispatch,
generated code, monkeypatching, or runtime metaprogramming. Tracked source and
runtime-string audits, per-call replacement tests, cold imports, and behavior
tests cover those relevant limits; no ontology workspace was created, target
code was not executed, no direct network request occurred, and no optional LLM
enrichment was used. RDF/Turtle would be the portable export if a future
authorized snapshot were persisted, with store extensions mapped separately;
static proximity does not establish runtime causation.

Independent review must verify consent-before-effect ordering, exact rollback
identity, atomic replace behavior, environment fail-closed state, process AST
digests, the dynamic manager patch seams, and absence of a second settings,
process, HTTP, or effect authority.
