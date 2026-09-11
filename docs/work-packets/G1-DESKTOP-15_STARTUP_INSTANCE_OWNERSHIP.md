# G1-DESKTOP-15 — Windows startup instance ownership

Iron Plan: ALIGNED. Iron Gate: 1. Owner: repository owner, startup failure
report on 2026-09-06. Plan revision 12, digest
126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb.
Base: 585b7ea4 plus preserved source of the v0.1.6 local UI package.

Packet ID: G1-DESKTOP-15
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: preserved v0.1.6 UI and startup evidence

## Primary acceptance claim

The owner reported immediate disappearance, then confirmed the app had started.
The installed main process began at 01:58:52 Berlin; its backend started at
02:00:02. Startup log entries at 01:59:55 and 02:00:16 report Windows error 145
(directory not empty). The first process remained responsive. No matching WER
or ApplicationError event was found. Independent source review identified the
unprotected interval between the port precheck / generation-absence check and
the final staging-directory rename. An overlapping launch can publish first.

Primary acceptance: within one Windows session, only one Daedalus process reaches
startup verification/migration, including before a backend port or window exists.
Later launches exit cleanly and attempt to restore/focus the existing window.
The OS releases ownership on normal exit and process termination.

## Scope

Allowed: native desktop instance guard and its narrow Windows API dependency,
wiring before Tauri setup, focused process tests, affected packaging contracts,
local v0.1.6 repackage and this packet. Implement in the existing detached build
worktree. Preserve unrelated owner edits; compare source hashes before copying.
Forbidden: removing generation data, changing artifact identity/validation,
adopting an unrelated port listener, killing the user's running app, new runtime
state stores, kernel/policy changes, commit/merge/publication.

## Acceptance matrix

- Real cross-process contention: second owner refused before any UI/backend.
- Normal and abrupt owner exit release the OS object; no stale lock file.
- Matching window/executable check for best-effort focus; no unrelated process
  stop or service adoption. The existing foreign-port refusal remains.
- Existing 21 native lifecycle tests plus relevant Python packaging contracts.
- Release compilation and a native executable guard probe without disturbing
  the currently running installed app; retain limitations and exact results.
- Rebuild v0.1.6 locally and retain the morning schedule with the corrected
  snapshot. No claim that the user's running binary was replaced.

## Contracts and behavior

A Windows named kernel object held for the process lifetime avoids persistent
lock files and protects the entire startup interval. It is a local coordination
mechanism, not an authorization boundary. The standard Tauri single-instance
plugin 2.4.4 was reviewed but not adopted: its Windows path can enter setup when
the mutex exists but the first hidden message window does not yet exist, and its
notification waits on a busy UI thread. Preserve that negative evidence.

## Migration and rollback

The guard is additive and creates no persistent lock. Rollback removes the
native guard and its pre-setup wiring while retaining this packet and the
positive and negative startup evidence.

## Evidence, expected failures and review

`cargo test --offline --target x86_64-pc-windows-gnu --lib instance::tests --
--test-threads=1`: five passed, zero failed, 21 existing tests filtered, 0.65 s
after compilation. Real child processes verify refusal before any UI/backend,
reacquisition after handle drop, process exit without Rust destructors, and forced
termination. The fifth test checks exact executable path identity; the helper test
is a no-op unless launched with its isolated test environment.

Independent source review found no blocking ownership or handle-lifetime defect.
The `Local` named object coordinates the current Windows session, not different
Windows logon sessions. Focus is best-effort and does nothing before the first
window exists; a different installation can hold the common mutex but its window
is deliberately excluded by the executable-path check. This does not add a
loading window or claim faster generation verification. Actual minimize/restore
and foreground activation are not covered by the process tests.

## Completed local verification and delivery

The full canonical packaging pipeline completed all 12 stages successfully on
2026-09-06 at 02:39:50 Europe/Berlin, in 22.44 minutes. Results: 527 web app
checks, 145 motion checks, production build, 235 Python desktop/runtime checks
with one POSIX-only skip, and all 26 native tests passed. The frozen backend
served all six Blender scenes with exact packaged bytes on isolated port 63863.

The compiled Windows GUI executable was copied into a separate fixture directory
with its shipped WebView2Loader.dll. With the production instance object already
present, it exited with code 0 in 145 ms before backend setup. The active backend
pointer, generation directory set and startup log stayed identical. This verifies
the real release entrypoint, not only the test helper. It does not exercise a full
first-launch migration/window session or prove foreground/minimize behavior.

Retained negative evidence: the first fixture copied only the EXE, omitted its DLL,
and exited with 0xC0000135 before Rust entry. Adding the existing release DLL made
the same executable pass. Independent PE/NSIS review confirmed 17 unique imports,
WebView2Loader.dll as the sole non-system companion, and its inclusion beside the
EXE in the generated installer script (line 3126). This was a fixture omission.
The failed receipt is retained alongside the passing receipt. Existing GNU linker
resource warnings, the unused helper warning and Vite chunk-size warnings remain
in the successful build logs; they were not suppressed.

Local package (not installed or published):
`C:/Users/nukei/AppData/Local/Daedalus/packages/0.1.6/20260906T001723Z-96f5e10e/Daedalus_0.1.6_x64-setup.exe`
(96,718,705 bytes), SHA-256
`ca2075c02269db7a9340bc796832d7c2fe104e35cf3c26b2b23fe0943ccc7d8f`.
The adjacent result.json retains all stage commands, logs and toolchain details.
This is the existing unsigned local Windows GNU lane, using Node 24; it is not
the Windows MSVC / Node 22 CI release lane.

Native probe, failed fixture, independent review and scoped source-copy receipts:
`C:/Users/nukei/AppData/Local/Codex/Builds/daedalus-v0.1.6-20260906/startup-evidence/`
and the parent startup-delivery-files.json. Only the four native source/lock files
and this packet were copied after verifying that the original source hashes had
not changed. These final result notes are added in the owner workspace only;
the exact built snapshot and its bundled packet remain retained unchanged.

The existing morning task is still Ready for 2026-09-06 at 07:00 Europe/Berlin,
targeting readiness by 08:00, and points to that corrected snapshot. No running
user app was stopped or installed over. A later read-only query found the app
closed and no new crash events, but no exit receipt establishes the reason; this
packet does not claim to explain an unlogged later exit.
