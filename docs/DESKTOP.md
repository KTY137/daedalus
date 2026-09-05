# Daedalus Desktop (Tauri)

Daedalus Desktop is a **packaging layer**, not a second Daedalus runtime. The
native Tauri process owns exactly one managed child: the frozen Python Web API
sidecar on numeric loopback `127.0.0.1:8765`. It waits until that port is
reachable and only then opens a WebView at the same origin. The Web API
continues to serve both `/api/*` and the compiled React/Vite cockpit, so browser
and desktop use the same API, contracts, effect boundary and canonical spine.

```text
Tauri process
  ├─ owns one frozen Python child
  │    └─ daedalus.interfaces.http.web_api on 127.0.0.1:8765
  │         ├─ existing /api/* Trust/Orchestration path
  │         └─ existing apps/web/dist cockpit
  └─ WebView -> http://127.0.0.1:8765
```

The Tauri shell deliberately exposes **no JavaScript shell/process capability**.
The backend process path is fixed in Rust and a pre-existing listener on port
8765 is treated as a startup error rather than silently adopted. Closing the
app uses the nonce-authenticated backend shutdown route. The Python desktop
runtime does not start Bridge, Ollama, IDE, Docker or SSH children in v0.1.6.
It therefore owns no service-process handle and its service-stop routes refuse
instead of turning an observed external PID into termination authority.

## External services in v0.1.6

The File Bridge remains an explicit canonical CLI workload. Start its
registered `file_bridge.watch` boundary from the Daedalus checkout when it is
required:

```bash
python -m daedalus.file_bridge watch --project <registered-project>
```

`daedalus watcher status --project <registered-project>` reports watcher state;
the desktop never starts or autostarts that process.

Local Ollama integration is adopt-only. Daedalus validates the configured URL
as numeric HTTP loopback, performs an exact readiness probe with environment
proxies and redirects disabled, and may use the already-running endpoint after
that probe succeeds. It never launches or later kills that Ollama process.
Managed Ollama start and remote SSH mode are unavailable in v0.1.6.

Managed IDE start is unavailable as well: no native OpenVSCode process, Docker
container, image pull or runtime build is started by the desktop. The read-only
desktop projection does not run IDE discovery or a reachability command; it
reports the configured endpoint as unprobed instead of claiming an installed
or reachable editor.

Legacy settings are not converted into authority. A persisted remote-Ollama
configuration remains readable so the Settings view can repair it by switching
back to local mode; until then the runtime reports the precise unsupported-mode
error, clears tunnel-derived environment state, and neither opens SSH nor adds
the remote host to the trusted provider set.

## Runtime layout

CI freezes the Python backend with PyInstaller in `onedir` mode and embeds that
directory as a Tauri resource. The build writes a deterministic SHA-256
`BUNDLE_ID` plus a strictly sorted `BUNDLE_FILES` manifest; the Rust host is
compiled against that exact identity and refuses a mismatched resource before
copying or spawning anything. Only manifest-listed files are verified and
copied. This is intentional because an in-place NSIS upgrade can leave files
from an older resource directory behind: unlisted installer residue is inert
and can never enter an executable generation.

The optional `gpu` research extra is never installed by desktop CI. The
PyInstaller invocation also excludes CUDA, PyTorch, CuPy, Newton, Warp, NVIDIA
and Triton modules explicitly, then scans the frozen tree and refuses known
accelerator modules or native CUDA-library payloads. This keeps the desktop
installer portable even if a maintainer accidentally builds from a
GPU-enabled Python environment.

Native v0.1.6 installers also exclude the optional `computer` dependency set.
Desktop capture/input, observation-backed vision/OCR and Playwright browser
capabilities therefore report unavailable in those bundles.

At launch, Tauri installs a bundle once through a private staging directory into
`backend-generations/<BUNDLE_ID>`. An existing generation is validated and is
never refreshed in place. This matters on Windows: a resident native backend
can hold DLL image mappings open, but those files are no longer
overwrite targets for a later package. The active marker is changed only after
the new backend has returned the exact startup nonce; the WebView is created
only after that commit point.

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

The frozen sidecar contains no provider launcher. Ollama, an IDE and the
explicit watcher remain outside its child-process tree. Observing a reachable
loopback service does not grant ownership, and shutdown leaves those external
services untouched.

## Local build

Prerequisites are Node/npm, Python 3.12, Rust 1.97.1, `uv` 0.11.26 and the
normal Tauri platform packages. PyInstaller 6.22.1 and Tauri CLI 2.11.4 are
installed from the committed Python and npm locks.

```bash
cd apps/web
npm ci
npm run build
cd ../..

uv sync --locked --extra test --extra desktop-build --no-extra gpu
uv run --no-sync python tools/build_tauri_sidecar.py --target <native-rust-target>
uv run --no-sync python tools/smoke_tauri_sidecar.py

cd apps/web
npm exec -- tauri icon src-tauri/icons/icon.svg
npm exec -- tauri build
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
that touches the desktop shipping surface runs the same matrix and creates one
immutable, commit-qualified `desktop-v<version>-g<short-sha>` GitHub
prerelease. Publication refuses a reused tag and binds all five asset names to
the manifest version before upload.

The updater is intentionally **disabled**. Tauri updater artifacts require a
separate signing key and would create an update trust root that Daedalus does
not yet provision. Windows installers are not Authenticode-signed and macOS
builds use ad-hoc signing only; macOS is therefore not notarized. Releases stay
marked as prerelease until platform signing/notarization is configured and
validated. This is a distribution limitation, not a reason to weaken the Trust
Kernel.

## Versioning

Keep the authoritative package versions and their lock mirrors equal for a
desktop release:

- `pyproject.toml` and Daedalus' package block in `uv.lock`
- `apps/web/package.json` and the root package in `apps/web/package-lock.json`
- `apps/web/src-tauri/Cargo.toml` and the `daedalus-desktop` block in
  `apps/web/src-tauri/Cargo.lock`
- `apps/web/src-tauri/tauri.conf.json`

`productName` remains `Daedalus`, the bundle identifier remains
`dev.daedalus.desktop`, and the native window title remains `Daedalus` across
upgrades. Release codenames such as ASAE belong in presentation metadata, not
in installation or application-data identity.

Bump the version before producing a new public desktop build; the release tag is
derived from it.
