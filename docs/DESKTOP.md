# Daedalus Desktop (Tauri)

Daedalus Desktop is a **packaging layer**, not a second Daedalus runtime. The
native Tauri process starts the existing Python Web API on numeric loopback
`127.0.0.1:8765`, waits until the port is reachable, and only then opens a
WebView at that same origin. The Web API continues to serve both `/api/*` and
the compiled React/Vite cockpit, so browser and desktop use the same API,
contracts, effect boundary and canonical spine.

```text
Tauri process
  ├─ owns one frozen Python child
  │    └─ daedalus.web_api on 127.0.0.1:8765
  │         ├─ existing /api/* Trust/Orchestration path
  │         └─ existing apps/web/dist cockpit
  └─ WebView -> http://127.0.0.1:8765
```

The Tauri shell deliberately exposes **no JavaScript shell/process capability**.
The backend process path is fixed in Rust and a pre-existing listener on port
8765 is treated as a startup error rather than silently adopted. Closing the app
uses the nonce-authenticated backend shutdown route; desktop-owned provider
processes are contained as trees, so an Ollama runner cannot survive merely
because its immediate parent exits first.

## Integrated IDE on Windows

The cockpit's third `IDE` view embeds OpenVSCode Server in the same Daedalus
window. On Windows the desktop runtime defaults to Docker mode: the selected
registered checkout is mounted read/write at `/home/workspace`, Docker publishes
only `127.0.0.1:3000`, and the iframe uses the backend-reported workspace URL.
The native OpenVSCode executable mode remains available explicitly on other
platforms.

The NSIS installer packages the Daedalus shell, cockpit and Python backend. It
does **not** package Docker Desktop or a Docker image inside the installer. The
pinned local IDE image can be reproduced from the repository and is never
pulled or built by the running application:

```powershell
docker build --pull=false --tag daedalus/openvscode-server:1.109.5 packaging/openvscode
docker run --rm --entrypoint /home/.openvscode-server/bin/openvscode-server `
  daedalus/openvscode-server:1.109.5 --version
```

Docker Desktop must be installed and its Linux engine running before the user
presses `IDE starten`. Daedalus accepts only a version- or digest-pinned
`daedalus/openvscode-server` or `gitpod/openvscode-server` image, never performs
a runtime pull, and removes only the immutable ID it adopted after verifying
the image, project label, canonical mount source and loopback port binding.

## Runtime layout

CI freezes the Python backend with PyInstaller in `onedir` mode and embeds that
directory as a Tauri resource. The build writes a deterministic SHA-256
`BUNDLE_ID` plus a strictly sorted `BUNDLE_FILES` manifest; the Rust host is
compiled against that exact identity and refuses a mismatched resource before
copying or spawning anything. Only manifest-listed files are verified and
copied. This is intentional because an in-place NSIS upgrade can leave files
from an older resource directory behind: unlisted installer residue is inert
and can never enter an executable generation.

At launch, Tauri installs a bundle once through a private staging directory into
`backend-generations/<BUNDLE_ID>`. An existing generation is validated and is
never refreshed in place. This matters on Windows: a resident native provider
can hold DLL image mappings open, but those files are no longer overwrite
targets for a later package. The active marker is changed only after the new
backend has returned the exact startup nonce; the WebView is created only after
that commit point.

The frozen backend seeds `projects/daedalus.json` once. Existing Daedalus
repository-root semantics then place mutable state beside the frozen package:

```text
<app-local-data>/
|-- backend-current                         # active BUNDLE_ID
|-- desktop-startup.log                     # stable native startup failures
|-- desktop-backend.log                     # stable Python backend output
|-- backend/                                # retained legacy 0.1.3 layout
`-- backend-generations/
    `-- <BUNDLE_ID>/
        |-- BUNDLE_ID
        |-- BUNDLE_FILES
        |-- daedalus-web-api[.exe]
        `-- _internal/
            |-- daedalus/
            |-- apps/web/{dist,src}/
            |-- projects/daedalus.json
            |-- runs/
            |-- inbox/
            |-- outbox/
            |-- memory/
            `-- .env                        # optional; never shipped
```

No `.env`, `runs/`, queue contents, memory or machine-specific project
definitions are put into release artifacts. When a new generation is staged,
only those allowlisted state paths are migrated from the last ready generation
(or the legacy layout), and only where the target is missing. Links, special
files and type conflicts fail closed. Older generations are retained as
inactive migration snapshots; they are not a second live state authority, and
rollback requires explicit forward reconciliation rather than blindly treating
an old snapshot as current. The launcher refuses an already-installed inactive
generation. A freshly installed generation that fails before activation is
removed after its child exits, so a retry starts from the current state again.
The sidecar also rebinds only its schema-marked `projects/daedalus.json` record
to the new generation; operator-owned project records are left byte-for-byte
untouched.

On frozen Windows builds, external Ollama startup temporarily clears
PyInstaller's process DLL directory, removes bundle-rooted entries from the
child `PATH`, and restores the Python process immediately after creation.
Ollama starts in `runs/services/ollama` and is suspended until the existing
Daedalus process-tree container has assigned it to a kill-on-close Job Object.
A reachable Ollama that Daedalus did not start remains unowned and untouched.

## Local build

Prerequisites are Node/npm, Python 3.12, Rust stable, PyInstaller 6.22.1 and the
normal Tauri platform packages.

```bash
cd apps/web
npm ci
npm run build
cd ../..

python -m pip install -e ".[test]" pyinstaller==6.22.1
python tools/build_tauri_sidecar.py --target <native-rust-target>
python tools/smoke_tauri_sidecar.py

cd apps/web
npx @tauri-apps/cli@2.11.4 icon src-tauri/icons/icon.svg
npx @tauri-apps/cli@2.11.4 build
```

The committed npm lockfile pins the cockpit dependencies. Cargo uses
`src-tauri/Cargo.lock` after the first desktop CI build validates and commits it.

Linux additionally needs WebKitGTK 4.1, AppIndicator, librsvg and `patchelf`.
The GitHub workflow installs those packages explicitly.

## CI and releases

`.github/workflows/tauri-desktop.yml` runs native builds for:

- Windows x86-64: NSIS installer
- Linux x86-64: AppImage and `.deb`
- macOS Apple Silicon: `.app` and `.dmg`

Pull requests upload native bundles as workflow artifacts. A merge to `main`
that touches the desktop shipping surface runs the same matrix and
creates/updates the `desktop-v<version>` GitHub prerelease.

The updater is intentionally **disabled**. Tauri updater artifacts require a
separate signing key and would create an update trust root that Daedalus does
not yet provision. Windows installers are not Authenticode-signed and macOS
builds use ad-hoc signing only; macOS is therefore not notarized. Releases stay
marked as prerelease until platform signing/notarization is configured and
validated. This is a distribution limitation, not a reason to weaken the Trust
Kernel.

## Versioning

Keep these three versions equal for a desktop release:

- `apps/web/package.json`
- `apps/web/src-tauri/Cargo.toml`
- `apps/web/src-tauri/tauri.conf.json`

Bump the version before producing a new public desktop build; the release tag is
derived from it.
