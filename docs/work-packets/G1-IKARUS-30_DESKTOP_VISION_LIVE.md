# G1-IKARUS-30 — The Windows desktop and vision adapters, measured live

Packet ID: G1-IKARUS-30

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: isolated worktree `.claude/worktrees/lane10-desktop-adapter`, branch `loop/lane10-desktop-adapter`, own `.venv` with `daedalus[computer]`

Dependencies: `G1-IKARUS-26_COMPUTER_LOOP_LIVE` (the loop measurement whose stage-13 result — the local 7B planner cannot drive multi-step tasks on this host — is why this packet drives `ComputerService.execute` directly), the Revision-12 general computer assistance strand

This is a measurement packet. It changes no production code. It closes the
`desktop_validation` gap that `ComputerService.capabilities()` still declares
verbatim: *"live foreground input not yet measured; application support
requires verification"*.

## Primary acceptance claim

The Windows desktop and vision adapters were driven live for the first time —
no LLM planner, every step a direct `ComputerService.execute` call with a fresh
attempt id, on a throwaway authority root with its own armed kill switch — and
the complete observe → inspect → OCR → input → re-observe loop executes
end to end on this host: 17 completed effects, a verified typed postcondition,
and five refusals that each arrived as the plan's section 7.2 requires rather
than as a blind repeat. Four defects and limitations the run exposed are
described below with executed reproductions; none is fixed here, because
production code for these adapters belongs to other lanes.

## Measured

Host: Windows 11 Home 10.0.26200, interactive session 1, per-monitor DPI 240,
one 2850×1563 client window at desktop origin (783, 230). Python 3.13.14 in the
worktree venv; `opencv-python-headless 4.11.0.86`, `numpy 2.5.2`, `mss 10.2.0`,
`winrt-windows-media-ocr 3.2.1`. Windows OCR reports exactly one installed
recognizer language, `de-DE`. Execution-limit mode: `bounded` (the process
carried no `.env` policy).

Authority root `<USERPROFILE>\AppData\Local\Temp\daedalus-lane10\authority`,
control root `<USERPROFILE>\.daedalus\control\f03a8ab03a51` (fresh; the
`DAEDALUS_KILLSWITCH` override named exactly the derived permit path, armed via
`python -m daedalus.spine.killswitch arm`). Policy written with
`setup_computer(root, owner_confirmed=True)` followed by
`configure_computer(...)`: tools `app.launch, desktop.observe, vision.inspect,
vision.ocr, desktop.type, desktop.key`; one application `notepad` with a fixed
argv opening a fixture file whose sentinel words are `DAEDALUS ZINNOBER` /
`LANE10 SENTINEL 739104`. Evidence:
`docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/`.

### Round 1 — the owner-obvious application cannot be observed at all

Policy `7555b840…`, application argv `["C:\Windows\System32\notepad.exe",
<fixture>]`.

| Step | Result |
| --- | --- |
| `desktop.observe` before the launch | `ok:false`, `reconciliation_required`, "foreground executable is not owner-authorized", 5.049 s |
| `app.launch` | `ok:true`, `completed`, 6.868 s, a process id recorded |
| `desktop.observe` with the launched window in the foreground | `ok:false`, `reconciliation_required`, "foreground executable is not owner-authorized", 1.399 s |

The read-only probe `lane10_launch_probe.py` explains it and is the reproduction:
`CreateProcess("C:\Windows\System32\notepad.exe")` yields a process whose *own*
`QueryFullProcessImageNameW` already answers
`C:\Program Files\WindowsApps\Microsoft.WindowsNotepad_11.2607.14.0_x64__8wekyb3d8bbwe\Notepad\Notepad.exe`.
Windows 11 redirects at process creation. `_WindowsDesktop.snapshot` builds its
`allowed` set from `Path(argv[0]).resolve()`, so for every Windows application
whose `System32` name is a Store-app alias the foreground check can never match
and the tool is unusable — while `app.launch` still reports success.
**Defect 1**, and the reason the `desktop_validation` note is still true for the
application an owner would actually configure.

### Round 2 — a re-run is refused as a replay, with no ledger residue

Re-running with the same `mission_id`/`attempt_id` pairs: `desktop.observe` and
`app.launch` both returned `ok:false`, `blocked`, "lease identity was already
used for different content", in 0.318 s and 0.074 s. The lease identity is
`canonical_sha({mission, attempt})[:32]`, so attempt ids must be fresh across
runs, not only within one. Correct kernel behaviour, recorded because it costs a
measurement run to discover; the harness now stamps the mission id with the run
time.

### Round 3 — the full loop, with the packaged image authorized

Policy `a47e3b4f…`, application argv `[<packaged Notepad path>, <fixture>]`,
mission `lane10-desktop-live-202317`.

| Step | Tool | Result | s |
| --- | --- | --- | --- |
| m00 observe, our application not running | `desktop.observe` | `reconciliation_required` — "foreground executable is not owner-authorized" (the owner's `explorer.exe` taskbar owned the foreground) | 0.353 |
| m01 | `app.launch` | `completed` | 0.886 |
| m02 observe, authorized image in the foreground | `desktop.observe` | `completed`; frame 2850×1563 at (783, 230), dpi 240, monitor `65537`, `coordinate_space: desktop`, scale 1.0, crop 0, `image_sha256 cd5c29a4…`, `captured_at 2026-09-05T18:23:26.717762+00:00` | 4.949 |
| m03 | `vision.inspect` | `completed` | 5.423 |
| m04 | `vision.ocr` | `completed`; found `DAEDALUS`, `ZINNOBER`, `SENTINEL`, `739104`; `LANE10` was read as `LANEIO` / `lanel(` and so failed a strict match. Every word's `confidence` is `null` | 2.356 |
| m05 same observation id, 31.0 s old | `vision.ocr` | `blocked` — "desktop observation is stale or unavailable", refused before the lease | 0.029 |
| m06 | `desktop.key` `END` | `completed` on the first attempt | 1.782 |
| m07 | `desktop.type` `" KARMESIN99"` | attempt 0 `reconciliation_required` — "desktop pixels or focus changed; observe again"; attempt 1 `completed` | 1.518 / 3.659 |
| m08–m09 independent verification | `desktop.observe` + `vision.ocr` | `completed`; OCR reads `KARMESIN991` (the trailing `1` is the caret), status bar column 29, 52 characters | 2.224 / 3.120 |
| m10 | `desktop.key` `BACKSPACE` | `completed` on the first attempt | 3.896 |
| m11–m12 second verification | `desktop.observe` + `vision.ocr` | `completed`; OCR reads `KARMESINS`, status bar column 28, 51 characters | 4.306 / 5.353 |
| m13 window minimized, application still running | `desktop.observe` | `reconciliation_required` — "foreground executable is not owner-authorized" | 1.193 |
| m15 kill switch engaged 0.400 s into a pending step | `vision.ocr` | `blocked` — "kill switch engaged: a stop marker is present beside the permit"; latched 0.05 s after the stop was written, before any effect started | 0.380 |
| m16 same service after the latch | `desktop.observe` | `blocked`, 0.000 s | 0.000 |
| m17 after `arm(force=True)` and a new `ComputerService` | `desktop.observe` | `completed` | 1.737 |

Postconditions were verified independently, not asserted: the typed text
appeared in a *second* observation's OCR (`postcondition_typed_text_visible:
true`), and the backspace is proven by the status bar going from 52 characters /
column 29 to 51 / column 28. The harness's own strict word assertion
`postcondition_backspace_applied` reads `false` — that is a harness artifact,
because `de-DE` OCR read `KARMESIN9` as `KARMESINS`, not an adapter failure. It
is retained unchanged rather than tuned away.

The effect ledger measures the outcome classification exactly. Round 3 added 17
`COMPLETED` executions and 3 `STARTED` ones (`effect_executions` went from
`{COMPLETED: 1, STARTED: 3}` to `{COMPLETED: 18, STARTED: 6}`). The three new
`STARTED` rows are precisely m00, m07 attempt 0 and m13 — the three refusals
raised *inside* the adapter. The three refusals raised *before* the lease (m05
stale, m15 kill, m16 kill) added no row at all.

### Defect 2 — a read-only refusal is reported as an unknown external outcome

`ComputerService.execute` sets `external_started = True` immediately before
`_dispatch`, so every refusal the adapter raises afterwards returns
`state: "reconciliation_required"` and its execution stays `STARTED` forever
with no terminal receipt. Three of this run's refusals performed no host action
whatsoever: `_WindowsDesktop.snapshot` refuses at the foreground identity check
before any capture, and `desktop.type` attempt 0 refused at the pixel-identity
check after consuming its observation and before any `SendInput`. `desktop.observe`
is not even in the service's own `host_mutation` set. Plan section 7.2 asks that
"changed focus" produce "re-observation or a visible blocked result"; what a
caller sees instead is the same signal as a genuinely interrupted effect, and
each occurrence permanently strands a lease execution. Reproduction: any
`desktop.observe` while another application owns the foreground; the ledger row
count before and after is in `lane10_measure_result.json`
(`ledger_states_before` / `ledger_states_after`).

### Defect 3 — the launch receipt cannot bind the observation to what it launched

`launched_pid_owns_the_window` is `false` in round 3: the packaged Notepad hands
the launch to a singleton app host, so the pid `app.launch` records in its
receipt is not the pid that owns the window the next `desktop.observe` captures.
The adapter authorizes by executable image only, so *any* window of that image
is observable — including one the owner opened themselves, containing their own
content. The measurement harness had to add its own precondition
(`preexisting_authorized_windows == 0`) to avoid capturing an owner window; the
adapter has no such check.

### Defect 4 — a window-scoped capture is only as scoped as the application

The packaged Notepad restored the tabs of the owner's previous session, so the
authorized, non-overlapped, window-scoped capture legitimately contained the
owner's file names in the tab bar, and the OCR returned them. Nothing in the
capture path is wrong; the *scope* claim is weaker than it reads. This packet
therefore retains only the words this measurement itself put on the screen; see
below.

### What was not established

Task completion by an assistant. This packet measures adapter mechanics with a
scripted caller. It says nothing about whether a planner can compose these steps
— stage 13 already measured that it cannot on this host. It also does not
measure `desktop.click` (no click target was needed for a text postcondition),
`vision.match` or `vision.changes` (both in `RELEASE_DISABLED_TOOLS` under the
v0.1.6 path-I/O lock), the browser adapter, or any application other than
Notepad. The kill-switch stop landed in the pre-lease checkpoint rather than
inside the OCR polling loop it was aimed at; a stop that arrives *after*
`begin_effect` is therefore still unmeasured.

## Scope

In scope: `docs/work-packets/G1-IKARUS-30_DESKTOP_VISION_LIVE.md` and
`docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/` (five measurement scripts and
their sanitized results). Out of scope and untouched: every file under
`daedalus/` and `tests/` — this lane is read-only on production code, and the
four findings above are handed over as reproductions, not patches. Also out of
scope: the v0.1.6 release lock, the planner, the browser adapter, the master
plan and its amendment chain.

## Contracts and behavior

No contract changes. The packet records the behaviour the current contracts
produce on this host:

- `desktop.observe` takes no arguments, captures only the foreground window of
  an owner-authorized executable, refuses when another visible window overlaps
  it (measured: no overlap on this host, `overlap_diagnostic_after_launch` is
  empty), and returns an observation token, a frame with monitor/window/DPI/
  origin provenance, an `image_sha256` and a `captured_at` — never pixels.
- The observation freshness window is 30 s; at 31.0 s `vision.ocr` refused
  pre-lease with "desktop observation is stale or unavailable".
- `vision.inspect` and `vision.ocr` accept exactly `{"observation_id": …}` under
  `RELEASE_OBSERVATION_ONLY_TOOLS`; both were exercised in that shape.
- Windows OCR publishes no calibrated confidence, and the adapter records that
  as an explicit `null` instead of inventing a score. Every word in this run has
  `confidence: null`. A packet that quotes an OCR "confidence" for this adapter
  is quoting something that does not exist.
- `desktop.type` and `desktop.key` require a fresh observation, an explicit
  `expected` string, and *bit-identical* pixels between the observation and the
  moment of the effect. One of two typing attempts failed that check; the blinking
  caret is the plausible cause. The refusal consumed the observation and
  performed zero input, which is the correct direction — but see defect 2 for how
  it is reported.
- The kill switch latches monotonically: after the trip the same service refused
  in 0.000 s, and only a new `ComputerService` after `arm(force=True)` worked
  again.

## Acceptance matrix

| Check | Result (2026-09-05, this worktree) |
| --- | --- |
| policy written through `setup_computer` + `configure_computer`, all six tools projected as available | `capability_unavailable: {}`, policy `a47e3b4f…` |
| `app.launch` of the owner-obvious `System32\notepad.exe` | `completed`, but the resulting window is unobservable (defect 1); reproduced independently by `lane10_launch_probe.py` |
| `desktop.observe` with the authorized image in the foreground | `completed` in 4.949 s with full coordinate provenance |
| `desktop.observe` with the application *not* in the foreground | refused twice, once before the launch and once with the window minimized |
| `vision.inspect` + `vision.ocr` on the fresh observation | both `completed`; 4 of 5 sentinels matched exactly, `LANE10` misread by the `de-DE` engine |
| stale observation past the freshness window | refused pre-lease in 0.029 s at 31.0 s of age, no ledger row |
| `desktop.key` / `desktop.type` into our own window, verified by a second observation | typed text visible in the verification OCR; backspace verified by the status-bar counters (52→51 characters, column 29→28) |
| kill switch engaged during a pending step | `blocked` 0.05 s after the stop was written, before any effect started; next call refused in 0.000 s; recovery after `arm(force=True)` `completed` |
| no image retained anywhere | `control_root_image_files_before/after` both `[]`; the adapter holds the PNG in memory only; the harness writes no image |
| effect-ledger classification | 17 `COMPLETED`, 3 `STARTED` from adapter-side refusals, 0 rows from pre-lease refusals |
| the fixture file on disk after the run | unchanged (`fixture_unchanged: true`); Notepad force-terminated, `cleanup_windows_remaining: 0` |
| production code touched | none: `git status` shows only `docs/` |

## Migration and rollback

Nothing to migrate: no production file changes. Rollback is deleting the packet
and its evidence directory. The scratch state lives entirely outside the
repository — authority root
`<USERPROFILE>\AppData\Local\Temp\daedalus-lane10`, control root
`<USERPROFILE>\.daedalus\control\f03a8ab03a51` — and can be removed without
affecting the repository or the main checkout's control root. The six `STARTED`
executions in that scratch ledger are the residue defect 2 describes; they are
left in place deliberately, as the evidence for it.

## Evidence, expected failures, and review

Evidence directory `docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/`:
`lane10_setup.py` (authority root, kill switch, policy), `lane10_launch_probe.py`
and `lane10_launch_probe.json` (the redirection reproduction),
`lane10_measure.py` (the live driver), `lane10_measure_result.json` (round 3,
every step with its timings and receipt digests), `lane10_measure_run1/2/3.log.txt`
(step lines), `lane10_round1_system32_notepad.json`,
`lane10_round2_lease_identity_collision.json`, `lane10_redact.py`,
`lane10_scrub_paths.py`, `MANIFEST.json`.

**Privacy.** No screenshot and no image of any kind is retained in this packet or
its evidence directory, and none was ever written to disk: the adapter keeps the
PNG in memory and the harness never saves one — measured, `control_root_image_files`
is empty before and after. Retained instead: image digests, frame/coordinate
provenance, adapter JSON results and OCR word lists, with `<USERPROFILE>`
substituted for the home path. Because the packaged Notepad restored the owner's
previous session tabs (defect 4), `lane10_redact.py` filtered every OCR word list
down to the tokens this measurement itself produced plus fixed Notepad chrome;
11, 12 and 12 words were dropped from the three OCR steps. The three OCR result
artifacts the kernel had written into the scratch control root
(`2fb0d0af…`, `419cbf4f…`, `448b7da7…`) were deleted after their digests were
recorded here, and the control root was re-scanned: 0 remaining occurrences of
owner content, 0 image files of any kind. Notepad was closed by force
termination, which is the only exit that cannot write the modified buffer back;
the fixture on disk is byte-identical to what the setup wrote.

**The first privacy pass was incomplete, and the correction is part of the
record.** Verification of commit `e3fcfb6f` found the owner's home path still
present in six files. Three causes, each fixed at its source rather than only in
the output: the three harness scripts carried the scratch root as a literal (they
now derive it from `DAEDALUS_LANE10_SCRATCH` or `%LOCALAPPDATA%\Temp`);
`run()` sanitized `arguments` and `result` but not `error`, and adapter refusal
text embeds absolute paths — the kill switch names its own permit file — which
put the path into `lane10_measure_result.json` and `lane10_measure_run3.log.txt`;
and `lane10_setup.py` dumped its report with no filter at all, which put it into
`lane10_setup_round2.log.txt`. `lane10_redact.py` had also replaced only one
spelling of the home directory. `lane10_scrub_paths.py` now rewrites all three
spellings — the plain path, the forward-slash form, and the JSON-escaped
doubled-backslash form — over every retained file and this packet; it made 12
replacements (2 + 2 + 8) and a second run made 0, so it is idempotent. Every
JSON file still parses and `MANIFEST.json` was regenerated so each digest matches
the corrected bytes. The confirming search, with the owner's account name written
here as a placeholder so that quoting the check cannot itself reintroduce what
the check looks for:

```
$ grep -rn <owner-username> docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/ \
      docs/work-packets/G1-IKARUS-30_DESKTOP_VISION_LIVE.md
$ echo $?
1
```

No output, exit status 1 — grep found nothing. A shape-based search that names
no account, `grep -rnE 'C:.?.?[\\/]Users[\\/][A-Za-z]'` over the same two
targets, is likewise empty. The `-text` byte pin for this evidence directory
belongs in the repository-root `.gitattributes`, which is outside this lane and
is left to integration.

Expected failures retained on purpose: round 1 (unobservable authorized
application), round 2 (lease identity replay), m00/m13 (foreground refusals), m05
(stale observation), m07 attempt 0 (pixel-identity refusal), m15/m16 (kill
switch), and the harness's own `postcondition_backspace_applied: false`, which
is an OCR misread and not an adapter failure.

Review questions this packet does not decide. Should a refusal raised inside the
adapter before any host action return `blocked` instead of
`reconciliation_required`, and if so, where exactly is the line between "entered
the adapter" and "touched the host"? Should `app.launch` refuse, rather than
report success, when the launched process's own image path differs from the
authorized `argv[0]`? Should an observation be bound to a launched instance
rather than to an executable image, given that a singleton application makes
those different things? And is bit-identical pixel equality the right
precondition for input into a window with a blinking caret, when it failed one
attempt in two here?

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
