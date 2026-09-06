# Local Windows desktop package

`tools/package_desktop_local.ps1` runs the existing [desktop build path](DESKTOP.md)
for a local NSIS installer. It performs no publication, Git change, application
installation, scheduling, or automatic promotion. Gate 1, ALIGNED: this is a
maintainer wrapper around the current packaging tools and their effect guards.

Use a prepared isolated source copy for unattended execution. The canonical
builders regenerate `apps/web/dist`, `apps/web/src-tauri/backend`, icons and
`build/desktop-sidecar` inside that copy. The wrapper reuses Python and Cargo
build directories outside the source tree, preserving the development Python
environment. It never deletes source or cached build directories.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/package_desktop_local.ps1 -SourceRoot C:/path/to/isolated-source -ExpectedVersion 0.1.6 -PreflightOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/package_desktop_local.ps1 -SourceRoot C:/path/to/isolated-source -ExpectedVersion 0.1.6
```

Preflight checks all eight package/lock version mirrors, application identity,
the disabled updater, Python 3.12, uv 0.11.26, Rust 1.97.1, Node 22 or newer,
and the selected Rust target. `-PreflightOnly` does not install or build anything.
Immediately before the frozen-backend smoke test, the wrapper asks the OS for
an available numeric-loopback port and records it in the result. An existing
desktop app on port 8765 can remain running; no existing process is stopped.
The standalone smoke harness retains its default port 8765, with `--port` for
isolated checks. Its unique startup nonce binds readiness to the owned test
child. If the selected port is taken before that child binds, the smoke fails;
it never adopts another service. The shipped Tauri origin remains unchanged.

The default `x86_64-pc-windows-gnu` target matches the installed local GNU/GCC
toolchain. CI uses `x86_64-pc-windows-msvc`; that target is available through
`-Target` on a machine with its Rust target and Visual Studio C++ tools. The
result records this difference and the actual Node version. This local package
does not establish the full cross-platform release-acceptance CI result.

Stages use `npm ci`, application and motion specifications, the production
cockpit build, locked Python dependencies, focused desktop contracts,
`build_tauri_sidecar.py`, `smoke_tauri_sidecar.py`, icon generation, Rust
formatting/tests, and `tauri build --bundles nsis --ci`. Any failed stage stops
the pipeline. The wrapper includes neither the optional GPU nor computer extras.
It requires network/cache availability for npm, uv, Cargo and Tauri's NSIS tools.

Results go to `%LOCALAPPDATA%/Daedalus/packages/0.1.6/<UTC-run-id>/` by default:

- `Daedalus_0.1.6_x64-setup.exe`: fresh local installer, only after success.
- `result.json`: overall status, exact toolchain, stage results, installer hash,
  Authenticode status and the canonical backend `BUNDLE_ID`.
- `logs/`: one UTF-8 log per stage, including failed stages.

The reusable cache defaults to
`%LOCALAPPDATA%/Daedalus/packages/cache/<target>/`; `-CacheRoot` selects a
different location. Its `python/` and `cargo-target/` avoid a second cold build
and duplicate intermediates. One exclusive open handle on `package.lock` covers
the entire build. A concurrent build using the same cache is refused before
any build stage, with a failed result; the handle releases on success, failure,
or process termination. A leftover lock file alone does not block a later run.
Logs, receipts and copied installers remain separate for every run. The final
installer must have a fresh timestamp even when compilation uses the cache.

The installer remains unsigned unless platform signing is configured separately;
updater artifacts remain disabled. Schedule the verified command separately with
a finite execution limit and an explicit source-copy path. If the package must
be ready by a specific time, use the measured rehearsal duration plus headroom
to choose the start time. Keep the machine available during that interval. A
successful preflight alone is not evidence that the installer was built.

## Blender rooms in this package

Theme Studio → Szene → Darstellung switches a selected room between its
Cycles render and local interactive 3D. The light setting applies to either
mode and is saved with the theme. Image mode is the default and remains visible
if the GPU or a scene asset cannot load. Reduced motion disables camera motion.

All six GLBs and their camera/light manifest are copied from
`apps/web/public/scenes` into the built cockpit. The frozen-backend smoke check
fetches every GLB and compares the response with the packaged bytes, including
the GLB header; an HTML fallback is a failure. The editable Blender sources
remain in `docs/design/blender-scenes/blend`. From the scene directory,
`blender --background --python scripts/export_web.py -- --scene all` regenerates
the local derivatives without modifying those `.blend` files. Real-time
materials and lighting approximate the Cycles renders; volume scattering and
procedural bump shaders are not baked into these lightweight GLBs.
