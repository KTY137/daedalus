# G1-UI-03 - Frontend directed hierarchy strangler

## Frozen packet metadata

- Packet ID: G1-UI-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e133e09b85534ff3350fce982ee1aa2ad57ebb9e
- Dependencies: G1-UI-02 integrated at e133e09b85534ff3350fce982ee1aa2ad57ebb9e; G1-WP-INDEX-01 schema and metadata contract present in the base
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Every module in the shipping frontend import graph is owned by the directed
hierarchy `src/app`, `src/features`, or `src/shared`, except the intentionally
thin `src/main.tsx` bootstrap facade. The existing Cockpit remains the only app
implementation and its routes, query aliases, HTTP/JSON/SSE contracts,
navigation, visual behavior, local-storage keys, and React root are unchanged.

Established source paths remain only where a tracked caller, catalogue
locator, Work Packet, attachment fixture, architecture document, component
registry convention, or package command proves a compatibility obligation.
Those paths are machine-registered and contain only ES/CSS reexports or the
existing motion test-command adapter; none is reachable from the production
esbuild graph.

## Scope

The G1-UI-02 base contained 60 tracked files under `apps/web/src` and 100 under
`apps/web`. This Packet has 75 source files and 115 Web files before commit:
the active implementation count does not grow, while fourteen import/source
facades and one shim register make the compatibility debt explicit. A
production esbuild metafile rooted at `src/main.tsx` contains the same 52
First-Party inputs measured before the move.

The canonical owners are:

| Responsibility | Canonical owner |
| --- | --- |
| React root, Cockpit composition, status and cascade order | `src/app` |
| Conversation and Markdown rendering | `src/features/conversation` |
| Registered project creation | `src/features/projects` |
| Project-Twin graph, layout and stage | `src/features/twin` |
| Context-plan inspection | `src/features/knowledge` |
| Draft decision handoff | `src/features/mission` |
| Registered-name IDE surface | `src/features/ide` |
| Runtime, autonomy and theme settings | `src/features/settings` |
| Control-plane and provider projection | `src/features/system` |
| Existing HTTP client and wire contracts | `src/shared/api` and `src/shared/contracts` |
| Glass, motion and theme primitives | `src/shared/ui` |

In scope are pure file ownership moves, canonical import rewiring, the
machine-readable hierarchy-shim register, source/esbuild responsibility tests,
and this Packet. Forbidden paths are `apps/web/dist`, `package.json`,
`package-lock.json`, backend/runtime code, the Master Plan, amendments,
historical evidence, and every route or wire contract. No dependency, process,
port, provider, effect entry, store, scheduler, or second singleton is added.

## Contracts and behavior

### Directed runtime graph

`SurfaceRoot` statically composes `app/Cockpit` under the shared theme provider.
Cockpit imports feature owners and shared ports through the existing `@/`
alias. Feature modules may read shared contracts and UI primitives; shared
modules do not import app or feature implementation. CSS remains one ordered
cascade: the app stylesheet imports feature sheets at the same positions where
the previous Cockpit directory imported them, preserving source order.

The API implementation and all public TypeScript interfaces moved byte-for-byte
to `shared/api/index.ts` and `shared/contracts/index.ts`. Public function names,
types, URLs, request methods, query fields, timeouts, SSE decoding, and error
classes are unchanged. The old root modules are pure star reexports, so their
runtime exports are the same objects rather than wrappers or copies.

The React best-practices review found no changed hook, effect, state, data-fetch,
rendering, or async control flow: the TSX diff changes import ownership only.
Direct feature/component imports remain direct; the shared API barrel is the
pre-existing public contract surface and does not introduce a new dependency
or initialization path.

### Compatibility and retirement register

`src/app/hierarchy-shims.json` freezes owner, old paths, canonical targets,
evidence-backed reason, and removal criteria for four groups:

1. root API and contract imports;
2. the Cockpit/query and source-attachment paths;
3. catalogue/documented shared-UI paths;
4. the unchanged `test:motion` package-command adapter.

The classic/legacy query record in `surface-shims.json` is unchanged and still
targets `src/cockpit/Cockpit.tsx`. That file now reexports `app/Cockpit`, so the
query aliases and canonical import resolve to one component object without
moving the registered query target. Source guards compare every TypeScript
shim with its exact allowed reexport body and reject implementation drift.

### Removal and negative boundaries

The old parallel directories no longer own application logic. They may not
gain state, effects, functions, classes, styles, wrappers, lazy imports, or
conditional implementations. The app contract test builds a production
metafile and rejects any old-path input, any TypeScript implementation outside
the hierarchy, any unregistered shim, and any second root or app shell.

No historical document, experiment, catalogue, attachment payload, route,
JSON/SSE field, navigation label, shortcut, theme preset, CSS selector, or
visible layout was rewritten as part of this structural Packet.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Directed source ownership | executable tracked-source audit | no TypeScript implementation outside app/features/shared |
| Shipping graph is hierarchical | production esbuild metafile | 52 First-Party inputs; zero legacy-path inputs |
| Old imports are honest shims | exact-body and registry checks | all retained paths registered; TypeScript shims are reexports only |
| One app and query compatibility | resolver/source/Playwright checks | default, unknown, classic and legacy mount the same Cockpit |
| API and contracts unchanged | TypeScript plus focused API browser specs | existing URLs, methods, fields, bounds and errors remain accepted |
| Navigation/visual behavior unchanged | motion and focused browser checks | Karte, Gespraech, IDE, theme/motion and reduced-motion contracts remain |
| Interrupted turn safety retained | focused IDE browser check | closing observation issues no second POST |
| Deterministic output | two external Vite outDirs | identical relative paths and SHA-256 values |
| Effect boundary unchanged | semantic Registry digest | exact frozen digest |
| No generated/dependency churn | Git path diff | zero dist, package or lockfile changes |

Builder evidence on 2026-08-31:

- `npm.cmd exec tsc -- --noEmit`: passed;
- `npm.cmd run test:app`: 40/40 resolver, API-feature, hierarchy,
  exact-shim, production-metafile, root and runtime-string assertions passed;
- `npm.cmd run test:motion`: 122/122 token, reduced-motion and recursively
  discovered app/feature/shared-UI source guards passed;
- focused fixture-backed Playwright against the temporary production bundle:
  9/9 app/backend/degraded/navigation/query/system tests plus 1/1 IDE no-replay
  test passed;
- two `vite build --emptyOutDir --outDir <temporary path>` runs each transformed
  428 modules and emitted the same four files; SHA-256 comparison found zero
  differences and the sorted manifest digest was
  `10aaedfc42d4ab3e703fd74ba4418f85a1b162ceb07701bdd72f09f9eb8dd68d`;
- semantic Effect Registry digest remained
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`;
- `git diff --check` passed and the forbidden dist/package path diff was empty.

## Migration and rollback

There is no persistent-data, HTTP, JSON, SSE, query, local-storage, package, or
Effect Registry migration. Source consumers may continue importing registered
old paths while new code imports only canonical owners. Rollback delegates the
app imports to the old implementation locations and removes the new hierarchy;
it requires no data rewrite and no registry-target change.

Shim retirement is deliberately separate. A later Packet may remove one group
only after its stated tracked-source, runtime-string, attachment, catalogue,
package and downstream-consumer audits are green for the required cycle. The
classic/legacy query shim retains its own G1-UI-02 removal criterion.

## Evidence expected failures and review

No type, app-contract, motion, fixture-backed browser, reproducibility,
Effect-Registry, generated-path, or dependency-path failure is accepted.
Builder tests use only the local temporary Vite preview and intercepted fixture
responses; they do not call live providers or external networks.

Negative evidence is retained: two live-data cases from `cockpit.spec.ts` were
started against the static Vite preview and timed out before the run was
stopped. The preview honestly showed no reachable checkout because its proxy
could not connect to the intentionally absent API at `127.0.0.1:8765`. Those
cases require the repository-owned real-server harness documented in
`playwright.config.ts`; they are not fixture-backed preview checks and were not
relabeled green. The ten in-scope fixture-backed cases passed against the same
bundle.

The inherited Work Packet index remains blocked before candidate-index drift:
`tools/index_work_packets.py --check` reports that
`G1-HERMES-01_SHARED_LOOPBACK_PREDICATE.md` lacks the required `Scope`,
`Contracts and behavior`, and `Evidence expected failures and review`
sections. This Packet does not rewrite that foreign document and, per packet
scope, does not regenerate the global index.

Independent review must confirm that the old files contain no implementation,
the hierarchy register covers every retained path exactly once, the CSS import
order is unchanged, all 52 shipping inputs resolve under the target hierarchy,
the query registry still reaches object-identical Cockpit composition, and no
generated, dependency, plan, amendment, route, or backend path changed.

No automatic merge, promotion, release, or Gate transition is authorized by a
green builder result.
