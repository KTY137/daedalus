# G1-IKARUS-18 — Computer host adapters

Packet ID: G1-IKARUS-18
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: reviewed G1-IKARUS-17 and G1-IKARUS-COMPUTER-01 canonical computer-use admission
Plan: revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Dependency: reviewed G1-IKARUS-17 governance packet; root-approved trusted
adapter interface behind the canonical computer-use effect admission.
Status: implementation and independent review complete; native desktop live
acceptance remains unmeasured.

## Primary acceptance claim

Private Windows desktop and isolated Playwright browser adapters use the
owner-scoped `ComputerPolicy` and a required trusted checkpoint before host
effects. No CLI, HTTP route, policy grant, ledger, scheduler or new authority is
introduced. Root integration owns canonical leases and policy admission.

## Scope

Allowed files: `daedalus/runtimes/computer_desktop.py`,
`daedalus/runtimes/computer_browser.py`, their focused tests under
`tests/runtimes/`, and this packet. Dependencies are root-owned. Other files
and unrelated changes are excluded.

## Contracts and behavior

Both adapters require the trusted service's policy checkpoint at the actual
effect boundary. Desktop input consumes a fresh, scoped observation; browser
actions use an isolated static-page context with fresh unique DOM targets.
Adapter observations do not establish general task success. The acceptance
matrix and retained limitations below define the supported behavior.

## Acceptance matrix

| Area | Required evidence |
| --- | --- |
| Desktop scope | Capture only approved foreground application's client rectangle; retain image bytes privately; foreign focus and overlap refuse |
| Target grounding | A fresh observation binds window, image, DPI, coordinates and timestamp; stale, changed or replayed target refuses before input |
| Cancellation | Required checkpoint before process creation, capture and each input group; interrupted input stops without blind replay |
| Serialization | Existing OS-held ExclusiveFileLock serializes desktop input; no lockfile deletion or parallel desktop state authority |
| Launch | Owner-fixed argv only; caller-supplied args refused |
| Browser egress | Isolated context; exact origin route checks, HTTP redirects guarded, websockets and service workers blocked; no stored login state |
| Browser target | Fresh unique DOM target; changed document, ambiguous selectors and submit controls refuse |
| Truth | Host API acceptance is observed, not independently verified task success; browser fill verifies resulting DOM field value only |
| Live evidence | Disposable local fixture where dependencies and host permit; unavailable host/dependency stated separately |

Baseline: neither adapter file existed. Local Python had cv2 and Pillow,
but mss and Playwright were absent at baseline. Windows is the only desktop
host supported by this packet. Browser tests run against a disposable local
HTTP fixture if the optional browser distribution is installed.

## Migration and rollback

Trusted application control is not candidate-process containment. An authorized
application can implement arbitrary behavior in response to input; the adapter
does not prove arbitrary host applications obey the scratch workspace. Scope
therefore requires explicit owner application grants. Desktop coordinates are
observations, and human focus changes remain a race whose detected outcomes
block the next action. No complete security guarantee is claimed.

Rollback disables the tools in owner policy and retains canonical evidence;
unknown interrupted effects are reconciled by the caller rather than retried.

API: `DesktopAdapter(policy, checkpoint, control_root).execute(tool, args)` and
`BrowserAdapter(policy, checkpoint, control_root).execute(tool, args)` return
JSON-safe observations. Desktop image bytes are private, available to trusted
local vision via `capture_png(observation_id)` only. No raw image appears in
default result metadata.

Implementation references: [Windows SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
and [Playwright network controls](https://playwright.dev/python/docs/network).

## Evidence, expected failures and review

Implemented private Windows and Chromium adapters. Initial focused acceptance
completed with **20 passed in 26.58 seconds**, including real Chromium against
a disposable localhost HTTP fixture. Desktop cases used a deterministic fake
host to verify stale/focus/coordinate/lock/cancel/replay refusal. The actual
Windows backend initialized in interactive session 1 without capturing or
injecting input. No live application success is inferred from fake-host tests.

Independent kernel reviewer on 2026-09-05 identified and repaired mixed-DPI
input coordinates, serialization across authority roots sharing one desktop,
page-script network channels and download anchors. The revised browser,
desktop and loop suites completed with **46 passed in 20.70 seconds**. The
browser now disables page JavaScript and documents that limit; a fixture test
confirms that an onclick handler is unavailable. Static DOM field readback and
admitted link interaction remain supported.

Native foreground screenshot/input acceptance was intentionally not performed
to avoid interfering with the current interactive desktop. Those tools remain
off in default configuration; this packet does not claim their full live matrix
is green. Human focus races, arbitrary server behavior behind GET requests and
an approved native application's own effects remain explicit limitations.
This is not an OS sandbox or complete network/security guarantee.
