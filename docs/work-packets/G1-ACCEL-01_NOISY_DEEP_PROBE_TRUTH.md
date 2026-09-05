# G1-ACCEL-01 - Noisy deep-probe truth

## Frozen packet metadata

- Packet ID: G1-ACCEL-01
- Artifact role: primary
- Status: implemented locally; builder and adversarial verification green;
  independent review pending
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
- Dependencies: G1-UI-07; live environment evidence from
  G1-EXP-GPU-ENV-01 (evidence only)
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

The canonical accelerator status surface decodes an isolated deep probe even
when imported frameworks write diagnostic text to standard output, reports
the installed framework rows truthfully, retains bounded transport diagnostics
in the public status/CLI JSON, and distinguishes a failed top-level probe from
evidence that six individual frameworks are absent.

## Scope

This packet changes only `daedalus/foundation/accelerators.py`, adds focused
regressions in `tests/test_accelerators.py`, and records this packet. It does
not change accelerator policy, lane readiness rules, package requirements,
lockfiles, bootstrap behavior, chat, settings, runtime orchestration, stores,
effects, or promotion authority.

The public JSON change is additive: `framework_probe_diagnostics` is added to
the existing `daedalus-accelerators/1` payload. The six keys under
`frameworks`, all six lane rows, and their readiness policy are unchanged.

`docs/work-packets/index.json` is explicitly excluded from builder edits; its
canonical regeneration remains with the current registry owner.

## Contracts and behavior

- The child process emits its JSON result behind one versioned, exact sentinel.
- Parent parsing accepts ordinary standard-output noise before or after that
  sentinel and retains bounded stdout/stderr diagnostics separately from the
  six framework rows.
- `accelerator_status()` exposes those diagnostics under the explicitly
  operational `framework_probe_diagnostics` field. Its `transport_outcome`
  describes only whether the child-process envelope was decoded, failed, or
  was not requested; it makes no backend-readiness or semantic-validity claim.
- Public stdout, stderr, and failure values each retain at most 4,000 source
  characters plus an omission marker. `retained_char_limit` makes that bound
  explicit in the payload.
- A missing, duplicated, malformed, or non-object sentinel payload is a probe
  failure, not framework-absence evidence.
- On a top-level probe failure, every expected framework row is marked
  `probed: false`, has unknown CUDA readiness, and carries the failure detail.
- Successful framework rows keep the existing installed/readiness tristate
  and lane-selection behavior.
- The deep probe remains isolated, read-only, timeout-bounded, and free of
  provider or network calls.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Noisy stdout parses | mocked subprocess emits framework noise plus one sentinel payload | installed/readiness rows match payload |
| Diagnostics retained | mocked subprocess emits stdout and stderr noise | bounded diagnostics remain available without corrupting rows |
| Public success/noise path | CLI JSON over a decoded noisy payload | diagnostics are present and oversized output is truncated; six framework and six lane rows remain |
| Public top-level failure | `accelerator_status()` over a failed child probe | outcome is `failed`, bounded stdout/stderr/failure are visible, all framework readiness stays unknown |
| Probe failure is unknown | mocked top-level failure feeds `_framework_rows` | six rows are `probed: false`, CUDA readiness unknown, failure visible |
| Import-only remains tri-state | existing isolated fake-module probe | cuVS/cuGraph/Newton stay installed with unverified CUDA readiness |
| Live installed truth | local `accelerators --deep --json` | Torch/CuPy/Warp/Newton are installed; supported CUDA checks are truthful |
| Lane policy unchanged | accelerator unit suite | pre-Volta tensor refusal and lane logic remain intact |

## Migration and rollback

There is no persistent-data or package migration. The wire change is one
backward-compatible additive JSON field; existing keys and schema identifier
stay stable. Rollback removes `framework_probe_diagnostics`, restores the
previous whole-stdout JSON decoder, and removes the focused tests. No stores,
artifacts, ledgers, routes, clients, or compatibility translations are added.

## Evidence expected failures and review

The retained pre-change failure is a real Warp import/init banner on stdout:
the parent attempted `json.loads()` on the entire stream, returned `invalid
probe output`, and then rendered every framework as absent and successfully
probed. That is negative evidence about the transport envelope, not evidence
that Torch, CuPy, Warp, or Newton are missing.

No focused failure is expected after the change. Independent review must
confirm the sentinel is explicit and unambiguous, public diagnostics remain
bounded and operational-only, top-level failure stays distinguishable from
per-framework absence, and no readiness or policy criterion was relaxed.

Builder verification on 2026-09-04:

- The focused accelerator suite reports `15 passed`, including public CLI
  success/noise truncation and public top-level-failure regressions. Earlier,
  after integration hardening expanded the packaging refusals, the combined
  accelerator and GPU-extra contract run reported `18 passed`; the parent
  release verification owns the updated combined count.
- A real `.venv/Scripts/daedalus.exe accelerators --deep --json` run exits 0
  and reports Torch `2.14.0+cu126`, CuPy `14.2.0`, Warp `1.17.0`, and Newton
  `1.5.1` as installed. Torch, CuPy, and Warp report CUDA ready; Newton remains
  explicitly import-only with unknown CUDA readiness. cuVS and cuGraph report
  their real `ModuleNotFoundError` results.
- The retained non-payload stdout diagnostic is Warp's initialization banner,
  including the MX330 `sm_61` device. It no longer corrupts the JSON record and
  is now visible under `framework_probe_diagnostics.stdout`; the live transport
  outcome is `decoded` and the declared retained-character bound is `4000`.
- The existing silicon gate remains unchanged: the MX330 is compute capability
  6.1 and the tensor lane remains `unsupported` because it has no tensor cores;
  the Warp lane is `ready` and Newton remains `unverified`.
- Python compilation and `git diff --check` pass. `uv pip check` examined 83
  installed distributions and reports all compatible.
- The broader live UI-contract file retained one unrelated concurrent failure:
  `/api/genesis` is reachable from the cockpit but absent from that test's
  audit/exemption registry. This packet does not own or mask that endpoint.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
