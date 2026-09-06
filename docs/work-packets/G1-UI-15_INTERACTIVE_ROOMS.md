# G1-UI-15 — Interactive Blender rooms and local v0.1.6 delivery

Classification: ALIGNED. Gate: 1. Owner request: 2026-09-05; package again on
2026-09-06 at 08:00 Europe/Berlin, explicitly confirmed. Plan revision 12.
Dependencies: G1-UI-11 verified Blender sources; G1-UI-12 through 14 existing
room selection and workspace composition. Source base: 585b7ea4 plus preserved
owner worktree changes, captured in the external build baseline receipt.

## Scope and baseline

Six static Blender renderings already live in the existing Theme Studio.
Version mirrors already read 0.1.6. Add optional real geometry rendering behind
the same glass, keeping image mode as the default and as a failure fallback.
Reuse ThemeProvider and its JSON persistence; no new store or product authority.

Implementation and verification take place in an isolated detached worktree:
`%LOCALAPPDATA%/Codex/Builds/daedalus-v0.1.6-20260906/source`.
Owner source changes were overlaid from the shared checkout; the original files
will only receive this packet's reviewed patch after conflict checks.

Allowed: shared/ui/scene, theme controls/schema/repair/tests, focused browser
tests, three.js lock-backed dependencies, GLB exports, this packet. Local native
packaging composes the canonical documented builder in an isolated checkout;
its runner, logs and schedule receipt remain separate operational artifacts.
Forbidden: runtime/kernel/policy/ledger authority changes, commit, tag, publish,
automatic promotion, installation of the built app.

## Acceptance

- Six self-contained GLBs load, retain cameras and optical glass materials.
- Image/3D mode and light level survive reload and JSON round-trip; malformed
  stored controls cannot enable an unbounded renderer or request arbitrary URLs.
- Renderer loads lazily, fetches only the selected local asset, uses an explicit
  pixel cap, stops while hidden/reduced motion, and disposes on selection changes.
- Load failure, cancellation, context loss and unavailable WebGL retain the
  selected rendering as fallback. Existing image-mode behavior stays intact.
- Narrow layout, keyboard selection, meaningful app/motion regressions and
  production bundling are verified. Actual browser rendering is inspected.
- A concrete local packaging invocation passes preflight and a native build
  rehearsal before its once-only Windows task is registered and read back,
  with measured headroom before the 08:00 ready-by time.
  Packaging failure keeps logs and cannot report a successful artifact.

No assertion of identical Cycles and real-time lighting. No public release is
implied by the timed local rebuild. The computer must be available for its local
task; the scheduler is configured to run after a missed start when possible.

Verification measurements and retained failures are appended after execution.

## Measured verification — 2026-09-05

- Preserved source baseline: app bootstrap 524/524. Final package build:
  app bootstrap 527/527, motion 145/145, TypeScript and Vite production build pass.
- Existing spatial browser regressions: 6/6. Final interactive browser tests:
  3/3 in 2.1 minutes, including all six models, persisted rendering/light,
  <=1,103,000 drawing pixels, reduced-motion idle, context loss, asset failure,
  mobile editor scrolling, and hidden loading past the 20-second deadline.
- Six self-contained GLBs total 7,777,244 bytes; largest is Techno Forest,
  4,836,184 bytes / 115,386 triangles. Three's actual GLTFLoader parsed all six.
- Renderer and Three are in a separate lazy production chunk (865.52 kB,
  262.09 kB gzip). Forest uses one cached 1024px shadow map; sky gradients and
  shadow resources are explicitly released on teardown.
- Focused desktop contracts: 235 passed, one Windows-inapplicable POSIX FIFO
  fixture skipped. The real frozen backend passed its startup nonce/self-project
  checks and served the manifest and all six GLBs with exact packaged bytes.
- Visual inspection retained: `%TEMP%/daedalus-v016-forest-depth.png` and
  `%TEMP%/daedalus-v016-dusk-gradient.png`. These are offline UI fixtures and
  establish visual behavior, not kernel/runtime health.

Native rehearsal receipt and complete raw stage logs:
`%LOCALAPPDATA%/Daedalus/packages/0.1.6/20260905T200705Z-deb1afb4/result.json`.
Final native result and timed task are recorded below after completion.

Native rehearsal completed successfully at 20:23:21 UTC in 16.27 minutes.
All 12 stages exited zero; Rust tests passed 21/21. The local installer is
96,715,774 bytes, unsigned, SHA-256
`f1aee578a4c267400a499ce109f4dc02cc4ede403ee6099c853f6d96a5b0c710`.
Canonical backend BUNDLE_ID:
`4f1b5697384638552504f3a6b27342ae179de25160a84ae928a44339f7ba3276`.
PE version resources read 0.1.6; the required WebView2Loader DLL is present and
included by the generated NSIS script. Local GNU linking emitted duplicate
resource warnings; those remain in the build logs. This is a local GNU/Node 24
build, not a claim that the MSVC/Node 22 release CI or app installation was run.

The minified production UI also passed a separate browser check: image mode
requested no renderer/scene assets; opting into Forest requested just its GLB,
the manifest and lazy renderer chunk. Canvas: 1,100,083 pixels; keyboard light
100→105; zero page errors. Evidence:
`%TEMP%/daedalus-v016-production-qa-clean.json` and
`%TEMP%/daedalus-v016-production-forest-clean.png`. Both owned preview/browser
processes were closed. An initial wrongly quoted API fixture was corrected;
its first screenshot was retained rather than presented as app behavior.

## Retained failures and corrections

- First browser attempt: new lazy Three dependencies caused Vite's initial
  optimization reload, closing the editor. Its log records that reload. The
  mobile assertion also wrongly required an off-screen control without scrolling.
  Scroll assertion corrected; no retry configuration added. Original screenshots,
  error contexts and report remain in `%TEMP%/daedalus-v016-ui-artifacts` and
  `%TEMP%/daedalus-v016-ui-report.json`.
- Independent review found a real hidden-window defect: the load timeout was
  only cleared after the first painted frame. It is now cleared after setup;
  the final 21-second hidden-window regression passes.
- Initial real-time Forest had flat gray depth; retained screenshot is under
  `%TEMP%/daedalus-v016-ui-artifacts-v2`. Final lighting reduces ambient/fog
  brightness and uses one cached shadow map. Dusk's omitted gradient is restored.
- The first package wrapper wrote mixed UTF-8/UTF-16 stage logs under Windows
  PowerShell 5.1. Raw logs are retained; this affects log readability, not exit
  codes or the UTF-8 result receipt. A consistent-encoding fix is verified
  separately before scheduling.
- Validation failures also included initial Three import aliases, React ref
  initialization and a widened theme type; TypeScript caught all three before
  packaging. Corrected using the installed example-module paths and explicit types.

Scoped source integration checked every original file hash before copying the
reviewed patch back. Receipts live beside the isolated source as
`ui-source-baseline.json` and `ui-applied.json`. Unrelated owner changes remain.

## Timed local delivery

Windows task `Daedalus-Package-v0.1.6-20260906` was registered and read back in
Ready state: one scheduled start on **2026-09-06 07:00 Europe/Berlin**, with
60 minutes of headroom before the owner's **08:00** ready-by time. The measured
cold rehearsal took 16m16s. It invokes the reviewed runner against the prepared
isolated source and writes fresh per-run results under
`%LOCALAPPDATA%/Daedalus/packages/0.1.6/`.

The current-user task has wake/start-after-missed-start enabled, one retry after
10 minutes, and a two-hour execution limit. The user must remain logged in and
the computer available; screen lock is compatible. It builds locally without
installation or publication. The exported task XML and read-back receipt live
beside the snapshot in `scheduled-task.xml` and `schedule.json`.

Post-rehearsal runner corrections are independently verified: strict UTF-8 logs
preserve stdout/stderr and exit 23 with a failed receipt and no artifact; a real
frozen smoke passed on port 50628 while a separately owned listener stayed on
8765. The wrapper now selects a free loopback port immediately before smoke,
and the smoke uses a fresh nonce. Its default port and the shipped Tauri origin
remain unchanged. Evidence: `%TEMP%/daedalus-package-port-check-c8e9b9fdd12146aa8be6e9f1fb9c4bb4/result.json`.
The raw mixed-encoding rehearsal logs remain; `decoded-logs/` holds UTF-8 copies
with provenance. Final reviewed runner SHA-256:
`bb0370a449e5e347178afc8dc8a372d6373c9ddff4dc19b772cf1a3788749f63`.
