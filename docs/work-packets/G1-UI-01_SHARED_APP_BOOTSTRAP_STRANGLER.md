# G1-UI-01 - Shared application bootstrap strangler

## Frozen packet metadata

- Packet ID: G1-UI-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 869922863bae01d00de37c117de92d24c22ca2ec
- Dependencies: G1-WP-INDEX-01 at b2e74d601ab1af274cf670c58be53645c1001114; themed Cockpit baseline at 0d3ea5d1b6357c78037a6a8837e0f778fac904c2; interrupted-stream contract G1-IKARUS-14 at ba1254ca3de171ca486f7d22b44981125df4e068
- Promotion authority: repository owner; no automatic merge, promotion, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The browser has one root-mount and application-composition owner under
`apps/web/src/app`. The default Cockpit and the retained `classic`/`legacy`
compatibility surface are selected only by that owner, so neither URL entry can
mint a second React root, provider composition, or bootstrap state authority.

This is the largest honest first Strangler stage, not a claim that Classic has
retired. Redirecting `?surface=classic` to Cockpit on the frozen base would
remove still-live control-plane, provider-status, Claude-bootstrap, dashboard,
and Mission Control behavior. Those contracts remain lazy, visible debt until
Cockpit owns them and the registered removal criterion is satisfied.

## Scope

The frozen tracked-only frontend inventory was:

| Set | Count |
| --- | ---: |
| `git ls-files -- apps/web` | 124 |
| tracked `apps/web/src` files | 82 |
| tracked Playwright files | 12 |
| tracked generated `apps/web/dist` files | 9 |
| `src/main.tsx` lines | 40 |
| classic `src/App.tsx` lines | 1,910 |
| Cockpit `src/cockpit/Cockpit.tsx` lines | 1,130 |

In scope are a thin `main.tsx` facade, `src/app` as the composition owner, an
executable surface resolver, a machine-readable compatibility-shim record, a
tracked-only architecture test, two focused browser checks, and this packet.
The existing `App.tsx`, Cockpit feature components, navigation, CSS, API client,
routes, JSON/SSE contracts, Tauri source, dependency versions, package lock,
and generated `apps/web/dist` are unchanged.

No API, backend, store, scheduler, provider, event stream, process, port,
singleton state, effect entry, or release path is added. Builder browser
evidence uses only a loopback Vite preview of a generated temporary outDir; no
provider or external network call is permitted.

## Contracts and behavior

### One bootstrap owner

`src/main.tsx` now delegates only to `bootstrapApp`. That owner creates the sole
React root, installs `StrictMode`, and renders `SurfaceRoot`. `SurfaceRoot` owns
both the Cockpit `ThemeProvider` composition and the lazy Classic import. A
tracked-files-only test rejects any second `createRoot`, `hydrateRoot`, or
`ReactDOM.render` call and rejects another direct path to the Classic root.

The URL contract remains exact and case-sensitive:

| Query | Selected implementation |
| --- | --- |
| absent, unknown, `surface=cockpit` | Cockpit |
| `surface=classic` | retained Classic implementation |
| `surface=legacy` | retained Classic implementation |

Other query fields, including `project`, `view`, and `context_ref`, are left in
the URL for their existing owners. Classic stays dynamically imported because
its `styles.css` contains global element selectors; eager loading it would
change Cockpit presentation without changing the rendered branch.

### Registered compatibility shim

`src/app/surface-shims.json` registers the two historical query values, the
shared app owner, the existing `App.tsx` target, its lazy compatibility kind,
and one evidence-based retirement criterion. The runtime resolver consumes the
same record the executable contract validates, avoiding a second alias list.

The shim may be removed only after Cockpit owns runtime and provider status,
control-plane inspection, Mission Control, and the draft inbox; their focused
browser contracts pass through the Cockpit route; and source plus built-chunk
audits find no Classic-only caller or stylesheet dependency.

### Frozen behavior and negative boundary

- `?surface=classic` and `?surface=legacy` still mount `.app-shell`; `/` and
  unknown values still mount `.cockpit`.
- Classic remains lazy and its stylesheet remains absent from Cockpit startup.
- Existing HTTP paths, request bodies, JSON/SSE fields, IDs, browser storage
  keys, theme behavior, navigation labels, and visual composition are untouched.
- `package.json` gains only the dependency-free `test:app` script. Neither
  dependency declarations nor `package-lock.json` change.
- No file below `apps/web/dist` is edited or committed. Two production builds
  are emitted outside the checkout and compared by relative path and SHA-256.

Static caller evidence for stopping this packet here is concrete: Classic
still calls `getControlPlane`, `getDashboard`, `getClaudeBootstrap`, and
`getProviderStatus`, while no file under `src/cockpit` references those API
owners. This packet does not hide that integration gap by relabeling a feature
deletion as consolidation.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| One root authority | tracked-only `test:app` source audit | exactly one root call, in `src/app/bootstrap.tsx` |
| Thin stable entry | source audit | `main.tsx` only delegates the existing root and search string |
| Query compatibility | executable resolver cases | exact `classic`/`legacy`; unknown values default to Cockpit |
| CSS isolation | source and built-chunk audit | Classic remains dynamic; separate `App-*` CSS/JS chunks exist |
| Browser mounting | focused Playwright against temporary production build | Cockpit and both compatibility aliases each mount exactly one expected surface |
| No presentation redesign | Git diff | no Cockpit, Classic, navigation, theme, or CSS implementation change |
| No API/effect drift | Git diff plus Registry digest | no backend/API/effect source change; exact frozen digest |
| Reproducible build | two external Vite outDirs | same ten relative files and byte digests |
| No generated-source edit | tracked diff | zero `apps/web/dist` paths |

Builder evidence on 2026-08-31:

- `npm.cmd run test:app`: 20/20 resolver, shim, tracked-source, and bootstrap
  contracts passed;
- `npm.cmd run test:motion`: 136/136 existing motion and source guards passed;
- `tsc --noEmit`: passed;
- focused Playwright against the generated production bundle: 2/2 tests
  passed, covering four navigations (`/`, unknown, Classic, and legacy);
- two `vite build --emptyOutDir --outDir <temporary path>` runs each emitted
  ten files; relative-path SHA-256 comparison found zero differences and
  aggregate manifest SHA-256
  `375e6b7e2cc204b509a3bd60f08b0bcb0aaa7ab6257e0f66cfe4ef40ebad989a`;
- the tracked Effect Registry digest remained
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

## Migration and rollback

There is no persistent-data or browser-storage migration. Rollback restores
the former inline `main.tsx` composition and removes `src/app`, its tests, and
this packet. Routes, query values, CSS chunks, API contracts, local-storage
keys, package lock, and generated distribution remain valid in either
direction.

The compatibility branch can be retired independently later: first migrate
and prove each named Classic-only capability in Cockpit, then change the shim
target or remove the query aliases in a dedicated packet. This packet does not
authorize that behavior change.

## Evidence expected failures and review

No focused UI test, type-check, browser-mount, build, digest, or generated-path
failure is accepted for this packet. The loopback preview deliberately has no
Daedalus API behind it: its API probes are refused locally while the focused
test measures only production-bundle boot and surface selection. That is not
evidence for API behavior; the packet changes no API caller or contract.

The shared parent already contains five tracked post-index Packet documents
that are absent from its committed registry: G1-HIER-06A/06B/06C,
G1-IFACE-DESKTOP-01, and G1-RUNTIME-PROVIDER-01. Adding this document makes the
tracked census 230 files while the inherited registry still records 224.
`tools/index_work_packets.py --render` accepted this Packet's metadata and
sections, but `--check` correctly reports the inherited registry stale. The
contract suite therefore retains two check-dependent failures with 20 tests
passing. Regenerating the registry here would silently bundle five foreign
Packets into G1-UI-01, so index regeneration remains a shared integration
step rather than part of this atomic UI commit.

Independent review must confirm that the shim registry is the resolver's only
alias authority, the Classic import remains lazy, exactly one React root is
possible, provider composition is branch-local, the generated build never
entered the checkout, and the explicitly named Classic-only capabilities
remain retirement blockers rather than silently disappearing.

No automatic merge, promotion, release, or Gate transition is authorized by a
green builder result.
