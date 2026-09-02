# Docs drift audit — DESKTOP.md + COMMS_PROTOCOL.md

Repo: `C:/Users/Administrator/daedalus`, tree measured at `d17ea2fc` (branch `main`;
the task brief named `54f09753`, HEAD had already moved by the time this ran —
noted, not treated as a finding). Read-only inspection only; no files touched
besides this report.

## CONFIRMED

### [CONFIRMED] COMMS_PROTOCOL.md's entire "Lane semantics" section describes lanes that the canonical dispatcher hard-refuses
- **File:line**: `docs/COMMS_PROTOCOL.md:86-113` (section "Lane semantics"), reinforced by
  the `claude`/`codex` rows of the request-field table at lines 60-61 and the
  "Who does what in VS Code" section at lines 166-179.
- **Claim**: A reader would believe: (1) `auto` routes to the local Ollama bench
  and, on any ineligibility/failure, **falls through to Claude, "Claude is
  always the backstop"**; (2) the `claude` lane runs "the trusted senior lane
  (`ask_claude`, the original behaviour)"; (3) the `codex` lane forces
  `codex exec` after an egress check, runs in a read-only sandbox, and is
  usable today; (4) `strategy: "spawn"` "lets Ikarus decompose the objective
  and dispatch the local bench."
- **Measured reality**: `daedalus/core.py::process_bridge_payload` (the function
  `file_bridge.process_request` actually calls, via
  `_process_request_claimed` → `process_bridge_payload`) hard-refuses every one
  of these paths before any provider is touched:
  - `lane == "codex"` unconditionally returns
    `bridge_status: "failed"`, error `"codex dispatch is disabled: provider.codex
    has not adopted the canonical runtime-bound Effect Lease and broker
    authorization seam"` (core.py:1470-1491). The `_codex_report` function the
    doc's behavior actually matches (egress check, `codex_cli` provider,
    sandbox) is **dead code** on this path — kept, per its own neighboring
    comment, "for old read-only callers and evidence."
  - `lane == "claude"`, and `auto`/`local` when the local bench does not accept
    the assignment, both fall through to `_ask_claude_report`
    (core.py:1339-1359, 1501-1506), which unconditionally returns
    `bridge_status: "failed"`, error `"Claude dispatch is disabled on the
    canonical queue path: the bridge caller does not yet hold the mandatory
    runtime-bound Effect Lease and broker authorization"`. The dispatcher's own
    comment directly contradicts the doc: *"They may not turn an ineligible
    assignment into a legacy direct Claude call that has no caller-held broker
    authority."* — i.e. Claude is explicitly **not** the backstop.
  - `strategy == "spawn"` is refused inside `_try_ikarus`
    (core.py:1207-1212) with `"strategy='spawn' has no canonical leased
    multi-task adapter; refusing instead of dispatching outside WaveExecutor"`.
  - The bridge's own argparse help text already says this out loud:
    `daedalus/interfaces/bridge/cli.py:64-89` — `--lane` help: *"auto/local run
    accepted assignments through the leased executor with no direct Claude
    fallback; local_only exposes only trusted local Ollama; **claude/codex are
    refused until the queue caller holds broker authority**"*; `--strategy`
    help: *"spawn is currently refused until a leased multi-task adapter
    exists"*.
- **Evidence command**:
  `Grep -n "lane == \"codex\"|_ask_claude_report|strategy.*spawn" daedalus/core.py`
  then `Read daedalus/core.py:1200-1508` and
  `Read daedalus/interfaces/bridge/cli.py:43-98`. Also:
  `git log -1 --format="%H %ai %s" -L 1462,1491:daedalus/core.py` →
  `151b8d18 2026-08-31 12:18:28 +0200 chore(wip): freeze Gate-1 dirty tree
  before hierarchy refactor` (the refusal landed the day before this audit)
  vs. `git log -1 --format="%H %ai %s" -- docs/COMMS_PROTOCOL.md` →
  `4ae9aaf6 2026-07-11 19:11:50 +0200 feat(providers): codex CLI lane —
  egress-gated external provider` (the doc's prose is 51 days stale relative to
  the code it describes; it was written for the pre-refusal `_codex_report`
  direct-call behavior that a later commit deliberately removed from the
  reachable path).
- **Misleadingness**: HIGH. This is the doc's central "how do I get Claude or
  Codex to actually run my request" explanation. Every path other than a
  successfully-accepted local-bench assignment now returns a canned
  `bridge_status: "failed"` no matter what the doc promises, and the one path
  that still could reach Codex (`_codex_report`) is unreachable dead code.

### [CONFIRMED] DESKTOP.md: "Pull requests upload native bundles... runs the same matrix" — PRs only build one Linux validation bundle
- **File:line**: `docs/DESKTOP.md:151-153`: *"Pull requests upload native
  bundles as workflow artifacts. A merge to `main` that touches the desktop
  shipping surface runs the same matrix and creates/updates the
  `desktop-v<version>` GitHub prerelease."*
- **Claim**: A new reader would believe PRs exercise the same three-platform
  (Windows/Linux/macOS) matrix as a `main` push, just without publishing a
  release.
- **Measured reality**: `.github/workflows/tauri-desktop.yml` defines two
  disjoint jobs. `pr-linux` (`if: github.event_name == 'pull_request'`,
  lines 50-136) builds only `ubuntu-22.04` with `--bundles appimage,deb`. The
  three-platform matrix job `desktop-release` (lines 138-283) explicitly
  guards `if: github.event_name != 'pull_request'` — it never runs on a PR.
  The workflow's own top-of-file comment states the intended policy directly:
  *"pull requests validate one Linux desktop build only; trusted main pushes
  and explicit manual runs exercise the full platform matrix"*
  (tauri-desktop.yml:38-41). `git log --oneline -- .github/workflows/tauri-desktop.yml`
  shows this split was introduced by `31814846 2026-08-30 09:46:33 +0200 ci:
  make desktop PR validation Linux-only` — one day before DESKTOP.md's own
  last edit (`151b8d18 2026-08-31`), so the doc was touched *after* the split
  landed and still describes the pre-split behavior.
- **Evidence command**: `Read .github/workflows/tauri-desktop.yml` (full file);
  `git log --oneline -- .github/workflows/tauri-desktop.yml`;
  `git log -1 --format="%H %ai %s" 31814846`.
- **Misleadingness**: HIGH. A contributor relying on this doc would expect a PR
  to validate Windows NSIS packaging and macOS signing/archiving before merge;
  it does not — only the Linux AppImage/deb path is exercised pre-merge.

### [CONFIRMED] DESKTOP.md: "Cargo uses `src-tauri/Cargo.lock` after the first desktop CI build validates and commits it" — no CI step commits it
- **File:line**: `docs/DESKTOP.md:137-138`: *"The committed npm lockfile pins
  the cockpit dependencies. Cargo uses `src-tauri/Cargo.lock` after the first
  desktop CI build validates and commits it."*
- **Claim**: A reader would believe the desktop CI workflow has a mechanism
  that generates/validates `Cargo.lock` and commits it back to the repository
  on a first run.
- **Measured reality**: `.github/workflows/tauri-desktop.yml` contains no
  `git commit`, `git push`, `git add`, or any write-back step anywhere in the
  file (verified by reading it in full — the only git-adjacent action is
  `actions/checkout@v4` with `persist-credentials: false`). Both build jobs
  (`pr-linux`, `desktop-release`) declare `permissions: contents: read`; only
  the separate `release` job (which only creates a GitHub Release, not a
  commit) has `contents: write`. `Cargo.lock` is tracked in git and its last
  change (`git log -1 -- apps/web/src-tauri/Cargo.lock`) is a normal human
  commit (`151b8d18 chore(wip): freeze Gate-1 dirty tree before hierarchy
  refactor`), not a bot/CI commit.
- **Evidence command**: `grep -n "Cargo.lock" .github/workflows/tauri-desktop.yml`
  → no matches; `git log -1 --format="%H %ai %s" -- apps/web/src-tauri/Cargo.lock`.
- **Misleadingness**: MEDIUM. The lockfile *is* committed and used (`cargo test
  --locked` at tauri-desktop.yml:125,233 does enforce it stays in sync), so the
  practical build behavior is fine — but the doc invents a CI auto-commit
  mechanism that would surprise anyone trying to find or reproduce it.

## PLAUSIBLE

### [PLAUSIBLE] DESKTOP.md local-build Tauri CLI pin (`2.11.4`) vs. Rust crate pin (`2.11.5`) — one minor version apart, unclear if intentional
- **File:line**: `docs/DESKTOP.md:133-134` (`npx @tauri-apps/cli@2.11.4 icon
  ...` / `build`) vs. `apps/web/src-tauri/Cargo.toml:19` (`tauri = { version =
  "=2.11.5", ... }`).
- **Claim**: A reader building locally would assume the pinned JS CLI version
  and the pinned Rust core version are the intended matching pair for this
  release.
- **Measured reality**: The JS CLI (`@tauri-apps/cli`) is pinned to `2.11.4` in
  both the doc and the CI workflow (`npm install --global
  @tauri-apps/cli@2.11.4`, tauri-desktop.yml:115,223 — so this part is at
  least internally consistent), while the Rust `tauri` crate and
  `tauri-build` are pinned one patch version ahead at `=2.11.5`/`=2.6.3`. Tauri
  CLI/core versions are not required to be numerically identical, so this may
  be an intentional/acceptable skew rather than drift — I could not find a
  changelog or comment in this repo asserting they must match, so I cannot
  confirm this either breaks the build or is simply normal.
- **Evidence command**: `Read apps/web/src-tauri/Cargo.toml`;
  `grep -n "tauri-apps/cli" .github/workflows/tauri-desktop.yml`. No dynamic
  build was run (out of scope — read-only, no dev server/build allowed), so
  actual CLI/core interop could not be verified.
- **Misleadingness**: LOW. Both numbers are individually correct and pinned
  consistently with CI; only their mutual relationship is unverified.
