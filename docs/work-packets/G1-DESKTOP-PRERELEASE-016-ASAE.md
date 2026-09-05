# G1-DESKTOP-PRERELEASE-016 — Daedalus v0.1.6 ASAE prerelease

- **Packet ID:** G1-DESKTOP-PRERELEASE-016
- **Artifact role:** primary
- **Active gate:** 1
- **Classification:** ALIGNED
- **Owner:** Daedalus owner
- **Base revision:** 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
- **Dependencies:** G1-UI-08, G1-UI-09, G1-IKARUS-16, G1-IKARUS-COMPUTER-01, G1-ACCEL-01, G1-GENESIS-01, G1-ARIADNE-01

## Primary acceptance claim

Daedalus v0.1.6 can be published as the commit-qualified prerelease
“Autonomous Super Assistant Evolver (ASAE)” without creating a second product
identity, bypassing the canonical kernel, or embedding opt-in GPU research
runtimes in native desktop installers.

## Scope

The packet covers synchronized Python, npm, Cargo and Tauri versions; the
existing Windows x86-64, Linux x86-64 and macOS arm64 desktop matrix; exact
release-asset selection; ASAE release presentation; Python wheel/sdist output;
the single frozen Python Web API sidecar owned by Tauri; the deliberately
adopt-only external-service surface; and the explicit exclusion of CUDA,
PyTorch, CuPy, Newton, Warp, NVIDIA and Triton runtime payloads from desktop
bundles.

It does not rename Daedalus, Ikarus or Ariadne, does not change the Tauri bundle
identifier or application-data root, and does not promote any experiment.

## Contracts and behavior

- `Daedalus` and `dev.daedalus.desktop` remain the native upgrade identity.
- Package versions and lock mirrors agree exactly on `0.1.6`.
- The GitHub prerelease tag is immutable and commit-qualified as
  `desktop-v0.1.6-g<short-sha>`.
- Publication admits exactly the five version-bound native asset names.
- Desktop CI installs only the test/build extra. PyInstaller exclusions and a
  frozen-tree scan independently refuse accelerator runtime payloads.
- Tauri owns only the frozen Python Web API sidecar. The Python desktop runtime
  starts no Bridge, Ollama, IDE, Docker or SSH child.
- Bridge execution remains explicit through the registered `file_bridge.watch`
  boundary (`python -m daedalus.file_bridge watch --project <registered-project>`);
  `daedalus watcher status --project <registered-project>`
  and the desktop only reports its externally observable state.
- Local Ollama use is limited to probing and adopting an already-running
  numeric-loopback HTTP endpoint with proxies and redirects disabled. Adoption
  grants neither process ownership nor stop authority.
- Managed Ollama start, managed IDE start and remote SSH are unavailable.
  Persisted legacy remote settings remain readable and repairable by switching
  to local mode, without opening a tunnel or extending the trusted-host set.
- The desktop runtime owns no service-process handles in v0.1.6. Stop requests
  refuse; external process discovery never becomes lifecycle authority.
- A browser-local preference cannot dispatch work. Ikarus suggestions require
  the visible `Loslegen` action, and a running project conversation remains
  observed while the reader visits Map, IDE or Genesis.
- Default stream cancellation is thread-safe and has one atomic winner against
  final persistence. `confirmed` means local delivery and persistence stopped;
  it never invents termination of an already-blocking external provider.
- ASAE does not imply automatic merge, automatic promotion or candidate access
  to policy, evaluators, evidence or the ledger.
- Fresh setup grants no computer tools. The v0.1.6 release fence neither admits
  nor advertises workspace file tools, path-based vision or local
  skill-directory reads. Observation-backed, non-path computer surfaces remain
  bounded by the canonical policy, lease and evidence path.
- The native installers do not bundle the optional computer dependency set.
  Consequently desktop capture/input, observation-backed vision/OCR and
  Playwright browser tools report unavailable in those bundles; source or wheel
  environments must install `daedalus[computer]` and Chromium for browser
  tools. This does not affect the separate owner-configured Windows
  `app.launch` surface.

## Acceptance matrix

- Python: complete test suite, lock check, dependency check, wheel/sdist build
  and metadata inspection.
- Web: app and motion specifications, TypeScript compile, production build,
  dependency audit and the full GUI harness.
- Desktop: packaging contracts, sidecar smoke, Rust format/tests and a native
  Windows NSIS build; GitHub Actions supplies Linux and macOS evidence.
- Runtime: live Web API settings, precise unavailable-service errors, local
  Ollama adopt-only behavior, no-child/refusal checks, Ikarus Voice, mutation
  confirmation, cancellation observations, path-fence/capability projection
  and dependency-unavailability refusal.
- Release: GitHub Actions succeeds, the prerelease targets the pushed commit,
  and all five assets are present.

## Migration and rollback

The unchanged product name, bundle identifier and generation-based backend
layout make v0.1.6 a forward upgrade of Daedalus. The updater remains disabled;
installation is explicit. Older backend generations remain inactive migration
snapshots. Rollback means installing a prior prerelease and explicitly
reconciling forward state, never treating an old snapshot as a second live
authority. A failed CI build or publication creates no promotion and blocks the
release rather than weakening checks.

## Evidence, expected failures and review

Retain test output, bundle identities, artifact hashes, GitHub workflow URLs
and signing observations. Windows is expected to be unsigned and macOS ad-hoc
signed/not notarized, so the release remains a prerelease. The MX330 research
host exceeded the declared eight-GiB environment ceiling; that negative result
is retained and the GPU extra stays an isolated Gate-1 experiment. Missing
platform assets, mismatched versions, wrong-version filenames, accelerator
payloads, registry drift, an advertised path capability or a moving shared
worktree are release-blocking.

This packet is plan-aligned release wiring at Gate 1. It is not an amendment
and does not authorize automatic merge or promotion.
