# G1-DESKTOP-PRERELEASE-012 - Publish the final v0.1.3 Gate-1 desktop prerelease

## Classification

- Master Plan: `ALIGNED`
- Target gate: `1`
- Promotion: forbidden; this is a product prerelease, not candidate promotion
  or a Gate transition.

## Reason for the patch release

The first v0.1.2 trusted-main run proved the Windows, Linux, and macOS bundle
lanes but exposed one publisher-environment defect: the tested selector imports
the canonical effect boundary, while the publish job had neither installed the
package nor placed the checkout root on `PYTHONPATH`. After adding that explicit
path, run `33321096897` published the five-asset `desktop-v0.1.2` prerelease at
`ac6f33c0f04984c6946e76a4532734b650c62182`. That release is retained as the
pipeline proof and is not overwritten. The repository then retained the final
dynamic child-nonce race tests, the sealed 07D4 broker cutover, its exact-head
Windows/Ubuntu runtime-admission workflow, and the bounded ignition-receipt
closure. Hosted evidence for the final combined revision remains required. The
next honest package identity for final delivery is therefore `0.1.3`.

## Change

- align Python, npm, Tauri, Cargo, and Cargo-lock package identity on `0.1.3`;
- reuse the tested five-asset publisher from G1-DESKTOP-PRERELEASE-011;
- expose the checked-out `daedalus` package to the selector through the
  publisher job's explicit `PYTHONPATH`, without rerunning build hooks under a
  write-capable token;
- retain the unsigned Windows and ad-hoc-signed/not-notarized macOS warning;
- bind Managed Bridge ownership to one crash-released OS lock plus an exact
  process identity and owner token, so a stale heartbeat, PID reuse, concurrent
  desktop start, or failed watcher start cannot be reported as `managed=true`;
- fail closed unless the macOS runner, declared Rust target, Tauri application
  binary, source PyInstaller sidecar, bundled sidecar, and both retained
  `BUILD_TARGET` markers all agree on native arm64 / `aarch64-apple-darwin`;
- publish only after the exact trusted-main Windows, Linux, and macOS matrix
  passes.

## Acceptance

1. Package manifests and the desktop packaging contract all report `0.1.3`.
2. Frozen-backend nonce smoke and desktop contract tests pass on Windows,
   Linux, and macOS at one exact trusted-main revision. The macOS lane also
   proves a native arm64 runner and thin-arm64 Mach-O headers for both the app
   executable and its source/bundled PyInstaller backend before archiving.
3. `desktop-v0.1.3` is a prerelease targeting that revision.
4. The release contains exactly one `.exe`, `.AppImage`, `.deb`, `.dmg`, and
   `.app.tar.gz` asset, with no expanded application internals.
5. The installed Windows application reports version `0.1.3`, starts its
   nonce-authenticated child backend, and exposes a working Managed Bridge
   status.

## Pre-push architecture audit

The v0.1.2 workflow proved artifact production but only labelled the macOS lane
as Apple Silicon. PyInstaller builds natively, while Rust can cross-compile; an
Intel `macos-latest` runner could therefore have produced an arm64 Tauri shell
containing an Intel backend. The v0.1.3 workflow now rejects that mixed bundle
after the Tauri build and before the `.app` archive is admitted. Local synthetic
tests cover the accepted arm64 tuple plus wrong runner, host, target, app,
source-sidecar, bundled-sidecar, fat-binary, and `BUILD_TARGET` cases. Exact
hosted runner and Mach-O evidence remains pending until the final main revision
runs.

Final synthetic architecture evidence is `34 passed, 10 skipped` on Windows;
the skips are the real symlink-ancestor cases unavailable without local link
privilege. Those same cases pass under Linux on CPython 3.10 and 3.12 (`44
passed` each). The complete local desktop-workflow selection is `123 passed,
10 skipped`. The selector requires a complete little-endian 64-bit ARM64
`MH_EXECUTE` header with bounded load commands and rejects fat, swapped,
truncated, dylib, symlink-ancestor and reparse-point inputs. Workflow YAML,
changed Python, Ruff import checks and `git diff --check` are clean.

The independent Managed Bridge fault selection is `276 passed` plus two
cross-process subtests. Real Windows and WSL races produce exactly one owner;
lock release/reacquisition, POSIX PID overflow, Windows exit code 259, PID
reuse and start-failure reporting are covered. These local results do not
substitute for the native hosted macOS or installed-Windows system proofs.

## Rollback

Do not overwrite or retarget an existing release. Revert the version bump and
retain hosted failures and already published prereleases as historical
evidence.
