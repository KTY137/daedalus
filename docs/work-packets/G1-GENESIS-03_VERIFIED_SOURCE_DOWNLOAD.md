# G1-GENESIS-03 — Verified source download

## Frozen packet metadata

- Packet ID: `G1-GENESIS-03`
- Artifact role: primary
- Classification: `ALIGNED`
- Active gate: Gate 1 — owner-directed Genesis product strand
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Design authority: master plan Revision 12, SHA-256
  `126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`
- Dependencies: `G1-GENESIS-01`, `G1-GENESIS-02`
- Baseline: green candidates have a CAS preview but no source archive download.

## Primary acceptance claim

An owner can download the exact successful Genesis source candidate from the
cockpit, including Web/PWA and CLI outputs. The archive contains unchanged files
under `source/`, the canonical `source-tree.json`, and `genesis-run.json` as
provenance references. It is a reproducible transport representation of the
existing candidate identity, never a new source identity or deployment receipt.

The service reuses the preview's full terminal Attempt, candidate, evidence,
round-trip and outer EffectLease verification. The caller binds the expected
candidate SHA-256. Only `preview-ready` and `succeeded` may download; corrupt,
incomplete, failed or mismatched records refuse. Archive creation is in memory.
Read-only inspection remains available with the kill switch stopped.

## Scope

In scope: existing Genesis service/export facade, HTTP read facade and injected
port, Genesis UI/model/specs, focused service/HTTP/browser tests, packaged web
output, Windows interpreter resolution for Genesis candidate gates, and the
existing canonical SourceTree materialization publish primitive. A shared
resolver consolidates existing preview verification.

Out of scope: source-tree identity/capture, evaluator or policy changes, new
event stores, Git initialization or commits, project registration,
promotion/publication, new permissions, master plan/amendment changes, and
unrelated staged edits. The owner can unpack the download and register their
project through the existing project dialog. A fully automated repository
handoff remains a later canonical effect operation with destination and replay
bindings.

## Contracts and behavior

- The portable literal `python` remains in the canonical ToolchainManifest and
  `TaskSpec.gate_argv` and retained command observation. Only the argv handed
  to `command_gate` is resolved through the shared kernel helper. On Windows
  the spawn-time executable is the venv's existing real
  `sys._base_executable` when present; other hosts and fallback installations
  retain `sys.executable`.
- This resolution is valid for the admitted stdlib-only Genesis stacks. It
  removes the uv launcher subprocess without changing candidate bytes,
  evaluator source, timeout, containment, evidence identity or verdict rules.
  Command observation schema `/2` records implementation, version, platform
  and executable SHA-256, never the host-local executable path.
- SourceTree materialization still writes a complete sibling staging tree and
  publishes it atomically. It now wires the existing bounded
  `daedalus.atomic.replace_with_retry` primitive at the publish point. Every
  retry repeats the same atomic replace; exhaustion still raises and no partial
  destination is accepted.
- The preview entry URL redirects the opaque iframe to its exact
  capability-scoped asset root. Browser assertions bind the live frame to that
  verified CSP root, not to the pre-redirect entry URL.

## Acceptance matrix

| Claim | Evidence |
| --- | --- |
| Exact source bytes | ZIP entries match every canonical manifest blob, size and executable bit |
| Reproducible transport | repeated exports are byte-identical with fixed ZIP metadata and ordering |
| Existing authority | missing/corrupt candidate, evidence, Attempt or outer effect terminals refuse |
| Identity binding | malformed run/digest and a digest belonging to another candidate refuse |
| Read-only operation | missing runs create nothing; export needs no new lease, subprocess or kill-switch permit |
| Browser boundary | exact numeric loopback Host; same-origin Fetch Metadata; foreign/missing/duplicate metadata refuse before CAS reads |
| Safe response | attachment ZIP, no-store, nosniff, restrictive CSP, exact candidate header; no cross-origin CORS access |
| Usable interface | successful Web/PWA/CLI results expose download; pending/failed states do not; errors stay visible |
| Complete flow | real browser starts Genesis, downloads archive, and archive contents independently verify |
| Regression | existing Genesis preview, legacy IDs, HTTP architecture and frontend checks stay green |

## Migration and rollback

Run focused service, HTTP, frontend and browser checks; separate independent
review examines authority, corruption, path handling and memory bounds. Record
measured outcomes below. No claim of a complete autonomous self-improvement
loop follows from this packet.

Rollback removes the added archive/UI surface and retains all source and
negative evidence. No retained report or candidate digest is rewritten. The
existing preview and project registration stay available.

## Evidence expected failures and review

- Initial independent source-download review found no release-blocking defect
  in the service, HTTP or UI archive boundary. Fresh browser execution then
  exposed the separate Windows runtime and materialization reliability defects
  retained below; those findings were not erased by later green runs.
- Full service + archive cohort: 118 passed, including 27 new archive cases.
- HTTP Genesis/architecture/disconnect cohort: 101 passed; its new real archive
  fixture initially put control state inside the authority root and was refused.
  With control and authority as siblings, that remaining integration case passed.
- Frontend: 509 app checks passed (baseline 498); TypeScript and Vite build passed.
- Distribution/desktop packaging: 101 passed, 1 platform skip.
- Source and packaged web trees: five files with identical names and SHA-256.
  Three superseded generated package chunks were replaced by the current build.
- Wheel built with pinned setuptools 84.0.0 in a fresh, isolated build directory;
  installed resource smoke passed without source-checkout imports or stale chunks.
  SHA-256: `213a642a2c323665fd050cebba892df144a7a525e422bed0da27140bebe80c39`.
- Four UI/browser cases pass across the retained first matrix and a focused
  corrected mock case. The correction removed a test assumption that intercepted
  Playwright request headers already include browser-added Fetch Metadata;
  actual backend boundary tests remain intact.

Negative live evidence: run `genesis-4c3d09d41128b4431078f835` timed out in
test/runtime/package at 30.9–31.5 seconds; build passed at 27.0 seconds. Raw
output contained `warning: Making stdin inheritable failed` in both passing
and timed-out checks, with no traceback/assertion. Slow child startup under
concurrent host load is supported, but the exact contention source is not
proven. No evaluator timeout was changed. The failed run, candidate, report,
and first browser matrix remain under `build/genesis-source-download-smoke/`.
This failure precedes the source download and is not counted as a successful
end-to-end browser run.

The fresh live recheck produced `preview-ready` run
`genesis-633d44d6fdf3af221c38a553` after competing build/package work finished.
The browser downloaded 13 source files; an independent Python stdlib verifier
checked the canonical manifest digest, all blob digests/sizes/executable bits,
exact archive entry set, and report/run binding. Candidate SHA-256:
`7401250ef2f59f339a1ff70f813c3e562606c874f30066c71f491fadeb6bb726`.
Downloaded ZIP SHA-256:
`0835c8d64b47fd41bc14fe671a6b7ae356e2be4b507e6a976ca9ba7272e49776`.
Evidence is retained in `build/genesis-source-download-smoke/playwright/real-recheck/`.
That test then failed at a stale origin-wide preview CSP expectation, after
the verified download. The expectation now requires the existing narrower
run/capability-scoped asset directory; production CSP was not changed.

The next fresh browser run, `genesis-605f127fac8248729a4f84e4`, failed before
download on the runtime check alone. Runtime timed out at 30.759 seconds with
exit `3221225786`, `timed_out=true`, `cancelled=false`, despite already printing
`GENESIS_RUNTIME_OK`. Build (16.447 s), test (25.641 s; three assertions/tests
completed in 0.006 s), package (21.625 s), and template conformance (0.643 s)
passed. Package output also records a `gate.out` cleanup `WinError 32` (open
handle). At this point the evidence suggested a Windows process-exit/wait or
handle-lifecycle issue but did not yet discriminate launcher delay from the
separate cleanup-handle race. No runtime limit or evaluator was changed.
The report, failure screenshot and runtime evidence are retained in
`build/genesis-source-download-smoke/playwright/real-final/` and its scratch
control/evidence tree. This intermediate fresh end-to-end test was **0/1**;
the earlier real verified download did not erase that reliability gap.

A separate read-only browser smoke of existing successful candidate
`genesis-633d44d6fdf3af221c38a553` passed (exit 0): normal preview navigation,
exact capability-scoped CSP, opaque origin, blocked localStorage, add/Enter,
search, complete, edit, delete, and reset on reload. Seven GET requests, no POST
or foreign requests, no console/page errors; browser closed. Report and visual
evidence: `build/genesis-source-download-smoke/existing-preview-smoke/`.
This validates preview behavior without rerunning generation and is not
substituted for the failed fresh-run test.

### Release-blocker investigation and retained post-fix runs

The Windows venv executable on this host is a 45 KB uv launcher while
`sys._base_executable` is the real CPython binary. With containment's
deliberately null stdin the launcher adds a subprocess and emits
`warning: Making stdin inheritable failed`. Five cold copied-candidate probes
through that launcher took 2.002-5.143 seconds and included a cleanup lock;
five through the base interpreter took 0.384-0.819 seconds without the warning.
Twenty warm launcher probes nevertheless passed, so launcher overhead explains
the noisy extra boundary but is not claimed as the only source of every slow
run. Exit `0xC000013A` is the cancellation result after the unchanged 30-second
deadline, not a candidate assertion failure. Under severe concurrent host
load, the three Windows containment-provisioning `icacls` phases can still
consume that fixed budget. The transient `gate.out` `WinError 32` was also
reproduced with the direct base interpreter; its external handle holder remains
unproven and it is not conflated with the removed uv launcher process.

The private Genesis interpreter copy was replaced by the canonical
`daedalus.kernel.interpreter.resolve_python_argv`. Frozen gate identity and
observed argv remain literal `python`; only the actual spawn argv is resolved.
The executed interpreter is retained path-free in command observation schema
`daedalus-genesis-command-observation/2`. No absolute user-profile interpreter
path enters the task identity or observation, and no timeout, evaluator,
containment rule or inherited-handle rule changed.

Three post-change red fresh runs are retained rather than hidden:

1. `genesis-87b162e7f14ce4d4bd20a78d` under
   `build/genesis-fresh-fix-20260905-1245/`: Playwright timed out waiting 240
   seconds for the POST while the heavily contended host continued gate work;
   the operation had not committed a terminal before the isolated server was
   stopped.
2. `genesis-b73146b107832487fb193fda` under
   `build/genesis-fresh-fix-quiet-20260905/`: build passed in 13.107 seconds,
   test in 28.666 seconds, package in 18.005 seconds and conformance in 9 ms;
   runtime was cancelled at its unchanged deadline after 30.854 seconds with
   empty output, `timed_out=true`, `cancelled=false`, and exit `3221225786`.
   The uv warning was absent, demonstrating that extreme provisioning/host
   contention can outlive removal of the launcher boundary.
3. `genesis-980fdcef434e9007a5ae36c4` under
   `build/genesis-fresh-fix-quiet2-20260905/`: the response failed before gate
   evidence when atomic SourceTree materialization hit `PermissionError:
   [WinError 5]` publishing `.package.tmp-*` to `package`. The publish point
   used a naked `os.replace`; it now reuses the existing bounded
   `daedalus.atomic.replace_with_retry`. A focused regression forces one
   transient publish conflict, then proves the second atomic replace publishes
   the exact manifest and bytes. Exhaustion still raises.

After the CSP-frame assertion and SourceTree publish wiring were corrected, a
fresh browser run `genesis-0e0f702773b4ec8de39b1933` passed 1/1 in 3.4 minutes
under `build/genesis-fresh-fix-quiet3-20260905/`. All gates were green (build
14.756 s, test 24.184 s, runtime 19.716 s, package 6.045 s, conformance 28 ms),
none timed out or were cancelled, and the independently verified download held
13 source files in 15 ZIP entries. Candidate SHA-256:
`7a483252cb5a74c87a61ea1df0c850de4476209fe0d696e207749c7a3af0242b`;
ZIP SHA-256:
`892a477818d01cae1c00dc7f816b4aaf436878cfaf302f55214e9553d67b5fee`.

The final fresh run after consolidation onto the shared kernel interpreter is
`genesis-889016663a62cd7de2508226`, retained under
`build/genesis-fresh-kernel-interpreter-20260905/`. Playwright passed **1/1**
in 40.909 seconds with no retry. Candidate
`29c0ec93ec0539cc9e9c4bafb83c16334f7cd11f29c519c0bcb9b5f9d8873050`
passed build (2.639 s), test (3.327 s), runtime (5.309 s), package (2.296 s)
and certified-template conformance (15 ms); all command observations have
`timed_out=false` and `cancelled=false`. Their stored argv remain portable and
their interpreter provenance is CPython 3.13.14 on win32 with binary SHA-256
`623f669041a962346e6a377408193e628bfc409d12e5851042a727685980813e`.
The browser independently verified 13 source files and 15 entries, then drove
the exact capability-scoped opaque preview through create/Enter, search,
complete, edit, delete, blocked form egress and reload reset. ZIP SHA-256:
`7f8cf7f2691528ff21751d160fa88e84682f14993b5610114ab1d9fdb4e8e678`.
Server PID 2108 exited and loopback port 8892 was confirmed closed.

One independently retained residual remains: the final green run's test gate
reported a transient `gate.out` cleanup `WinError 32` after its three tests had
passed. The designed gate contract reports this scratch cleanup failure but
does not convert a valid candidate verdict to red. It neither reintroduced the
launcher warning nor affected runtime/download/browser acceptance; the precise
external handle holder is not claimed as proven by this packet.

Focused final checks after the shared-helper integration:

| Check | Result |
| --- | --- |
| Shared interpreter contract plus Genesis spawn/identity/provenance edge | 9 passed |
| Real Genesis service E2E plus transient SourceTree publish regression | 2 passed |
| Genesis source archive suite | 27 passed |
| HTTP `source_download` selection | 28 passed, 24 deselected |
| Final fresh Chromium Genesis/source/preview case | 1 passed in 40.909 s |

Packet decision: **GO for G1-GENESIS-03**. This establishes the verified source
download and its fresh browser path; it is not an automatic promotion, a claim
that all release work is complete, or permission to erase the retained red
runs. Iron Plan classification remains **ALIGNED**, active gate **Gate 1**.
