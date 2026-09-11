# G1-UI-02 - Cockpit single application implementation

## Frozen packet metadata

- Packet ID: G1-UI-02
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 1d13176180cd60f0f7ddffd8e161186f9f1f7cbb
- Dependencies: G1-UI-01 integrated at 1d13176180cd60f0f7ddffd8e161186f9f1f7cbb; G1-IKARUS-14 interrupted-stream contract at ba1254ca3de171ca486f7d22b44981125df4e068
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Cockpit is the browser's sole application implementation. The default URL,
`?surface=classic`, and the historical `?surface=legacy` value all compose the
same `Cockpit` object under the same `ThemeProvider` and React root. There is no
lazy `App.tsx` branch, second shell, provider composition, or application-state
authority.

The four contracts that blocked G1-UI-01 retirement -- `getDashboard`,
`getControlPlane`, `getClaudeBootstrap`, and `getProviderStatus` -- now have a
Cockpit feature owner. The same owner also preserves the Classic-only hierarchy
read, the three read-only loop projections, and the existing project-scoped
agent-autonomy mutation. It consumes the existing API functions and adds no
HTTP path, scheduler, store, provider, singleton, or effect entry.

## Scope

The frozen and post-strangler tracked-only frontend inventories are:

| Set | G1-UI-01 parent | G1-UI-02 result |
| --- | ---: | ---: |
| `git ls-files -- apps/web` | 131 | 100 |
| tracked `apps/web/src` files | 88 | 60 |
| tracked Playwright files | 13 | 10 |
| tracked generated `apps/web/dist` files | 9 | 9 |
| browser implementations | 2 | 1 |

In scope are the shared system contracts and injected API ports under
`src/features/system`, their projection inside the existing Settings drawer,
the one-implementation surface resolver and shim record, removal of `App.tsx`
and its proven unreachable closure, consolidation of its active browser
claims, and this Packet.

The closure was not guessed from directory names. A production esbuild
metafile rooted at `src/main.tsx`, tracked import searches, runtime-string
searches, and TypeScript compilation established that the removed Classic
components, views, hooks, and global styles had no Cockpit caller after
`App.tsx` retired. Type-only shared contracts in `types.ts` and
`theme/types.ts` remain.

Out of scope are HTTP/backend changes, new routes or JSON fields, navigation or
theme redesign, dependency upgrades, Tauri changes, generated distribution,
and external/provider calls. Existing Cockpit view labels, shortcuts, storage
keys, route/query parsing, JSON/SSE contracts, and API function signatures stay
unchanged.

## Contracts and behavior

### One implementation behind every query

`SurfaceRoot` statically imports only Cockpit and `ThemeProvider`. The resolver
still recognizes the registered `classic` and `legacy` query values, but its
closed result type contains only `cockpit`. Unknown, absent, Classic, and
legacy values therefore mount the same component tree below the same sole
`createRoot` call.

`surface-shims.json` remains the machine-readable compatibility register. Its
target is now `src/cockpit/Cockpit.tsx` and its kind is
`same_implementation_query_alias`. The visible "Alte Oberfläche" link stays in
the same navigation position to avoid an unrelated chrome redesign; it now
truthfully opens the same Cockpit. The query shim may retire after tracked
source, runtime-string, documentation, and external-caller audits find nobody
still emitting either value.

### Shared system feature and API ownership

`features/system/api.ts` is an injected consumer of existing functions from
`src/api.ts`. `loadSystemCapabilities` reads these independent contracts:

1. dashboard and governance;
2. control plane and agent profiles;
3. Claude session bootstrap;
4. provider configuration and measured reachability;
5. agent hierarchy;
6. loop queue, attempts, and architecture.

Each promise is captured separately before results are joined. A refused
provider sample is rendered as a typed failed read and cannot erase a
successful dashboard, control plane, bootstrap, hierarchy, or loop result.
`degraded_sources` remains visible, and configured versus available provider
state remains two separate fields. Expandable raw-contract blocks preserve all
additive JSON fields rather than rebuilding a narrower UI schema.

Agent autonomy continues to call the existing
`PUT /api/projects/{registered_name}/autonomy` owner. The patch copies all
sibling agent modes before replacing one named profile, and the canonical PUT
response replaces the local read projection. No optimistic second authority is
created.

### Test and source retirement audit

Classic-only Playwright files were consolidated only after their claims were
mapped:

| Retired Classic test surface | Continuing evidence |
| --- | --- |
| Classic stream POST replay | existing `ide.spec.ts` durable-turn test proves closing observation never repeats POST; the new alias spec proves no legacy `/api/ikarus/stream` call |
| Mission Control/provider health | `system-capabilities.spec.ts` proves exact four-port calls, configured/reachable separation, and explicit partial failure |
| loop surface | the system spec proves bounded calls and visible `degraded_sources`; the pure feature spec proves one failed source cannot erase loop evidence |
| Classic spaces and shell load | `cockpit.spec.ts`, rewritten app-load/backend-down/degraded/spaces checks, and `surface-bootstrap.spec.ts` cover the sole Cockpit |

Historical Work Packet text remains historical and is not rewritten. No
production import or dynamic import reaches `App.tsx`; no production source
contains the retired `app-shell` runtime marker.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Cockpit is sole implementation | tracked architecture audit | `App.tsx` absent, zero App importers, zero `app-shell` production strings |
| Query compatibility | executable resolver plus browser checks | default, unknown, Classic, and legacy all mount one `.cockpit` |
| Four required contracts preserved | injected port contract and browser request audit | exact dashboard, control-plane, Claude-bootstrap, and provider-status calls |
| Remaining Classic reads preserved | pure/browser contract checks | hierarchy and all three loop reads use existing bounded endpoints |
| Partial failure is honest | provider fault injection | explicit failed source while other results remain visible |
| Autonomy contract preserved | pure patch and browser PUT assertions | sibling modes retained; registered project endpoint and canonical response used |
| Interrupted work not replayed | focused existing IDE browser check | closing observation performs no second turn POST |
| No navigation redesign | diff and Cockpit space test | Karte, Gespräch, IDE, shortcuts, theme, and chrome remain the existing Cockpit |
| Deterministic generated output | two external Vite outDirs | identical relative paths and SHA-256 values |
| Effect boundary unchanged | semantic Registry digest | exact frozen digest |
| No generated/dependency churn | Git diff | zero `apps/web/dist`, `package.json`, or lockfile paths |

Builder evidence on 2026-08-31:

- `tsc --noEmit`: passed;
- `npm.cmd run test:app`: 33/33 resolver, feature-contract, shim, root,
  source, and runtime-string assertions passed;
- `npm.cmd run test:motion`: 118/118 continuing Cockpit motion/source
  invariants passed after the dead Classic closure was removed;
- focused Playwright against a loopback preview of the temporary production
  bundle: 10/10 passed, including sole-app loading, backend/runtime-negative
  paths, unchanged three-view navigation, default/unknown/Classic/legacy
  mounting, all migrated system contracts, partial failure, autonomy PUT, and
  no-repeat turn observation;
- two `vite build --emptyOutDir --outDir <temporary path>` runs each emitted
  the same four files; SHA-256 comparison found zero differences and the
  sorted relative-path/hash manifest digest was
  `7fdb554a3bd50b6cedc764d0278dc533bdca515be8dddedb91e0729823e4a44b`;
- semantic Effect Registry digest remained
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

## Migration and rollback

There is no persistent-data, route, JSON, SSE, local-storage, or package
migration. Existing Classic and legacy links now resolve to Cockpit while the
query values remain accepted. Rollback restores the G1-UI-01 `App.tsx` lazy
branch and its source/test closure; it does not require a data migration or
effect target change.

The remaining shim is only the same-implementation query alias. Its removal is
independent: remove the legacy link and registry entry only after the stated
caller audits pass. The shared system feature itself is a deletable read
projection; removing it does not alter any API or execution authority.

## Evidence expected failures and review

No focused type, contract, browser, reproducibility, Registry-digest, generated
path, or dependency-diff failure is accepted. The browser builder uses a
loopback Vite preview and fixture-intercepts every system endpoint; it performs
no provider or external network call. Preview-only Cockpit probes without a
fixture may be refused on loopback and are not evidence of backend behavior.

The inherited Work Packet index cannot currently validate or render this new
Packet because the parent document
`docs/work-packets/G1-HERMES-01_SHARED_LOOPBACK_PREDICATE.md` is already missing
the required `Scope`, `Contracts and behavior`, and
`Evidence expected failures and review` sections. `tools/index_work_packets.py
--check` fails closed on that exact parent blocker before reaching index drift.
This UI Packet does not rewrite the foreign Hermes Packet or regenerate a
shared index that cannot satisfy its schema.

Independent review must confirm that all aliases mount object-identical
Cockpit composition, the API port defaults are the existing exported
functions, partial failure never becomes an empty result, the test mapping did
not discard the no-replay or degraded-source claims, the deleted closure is
absent from the production metafile, and the historical G1-UI-01 document was
not rewritten.

No automatic merge, promotion, release, or Gate transition is authorized by a
green builder result.
