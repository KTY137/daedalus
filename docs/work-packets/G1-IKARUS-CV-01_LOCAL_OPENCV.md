# G1-IKARUS-CV-01: bounded local computer vision

Packet ID: G1-IKARUS-CV-01
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: owner-approved amendment 012 and G1-IKARUS-17; G1-IKARUS-COMPUTER-01 trusted activation and admission

Owner approval in the 2026-09-05 conversation: "ja implmenetierer".
Read authority: master-plan revision 11, SHA-256
`711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`, with
amendment 012 adoption owned by the parent implementation packet.

## Primary acceptance claim

Primary acceptance claim: supplied local image bytes can produce bounded,
deterministic OpenCV observations and coordinate transforms, without granting
host control or making a task-success claim. This pure module is independent
of the host adapter and tool-loop implementation. Host activation depends on
their separate green admission and effect matrices.

## Scope

Exact scope: `daedalus/runtimes/computer_vision.py`,
`tests/runtimes/test_computer_vision.py`, and this packet. Forbidden: capture,
camera, input simulation, filesystem/network operations, new routes, policy,
evaluator, artifact/event authority, promotion and shared dependency edits.

## Contracts and behavior

The module accepts supplied image bytes and returns bounded observations or
typed refusal/unavailability. It does not capture screens or perform host
effects. Coordinate transforms express image geometry only; input authority,
freshness and focus remain the trusted adapter's responsibility. Optional OCR
uses only a trusted injected local adapter and does not introduce a fallback
process or network call.

Baseline: no computer-vision runtime module; local Python has numpy and Pillow
but no cv2 or pytesseract. Previous Ikarus kernel baseline in amendment 012 is
29 passing tests; that is not vision evidence.

## Acceptance matrix

| Case | Expected |
| --- | --- |
| Optional cv2 missing or unloadable | explicit unavailable result; import remains usable |
| Valid PNG/JPEG fixture | dimensions, format and byte digest retained |
| Malformed/oversized/decompression-bomb header | typed refusal before oversized allocation |
| Unique non-flat template | coordinates and best score independently asserted |
| Duplicate/no-match/constant template | ambiguous/no_match/typed uninformative refusal |
| Nonfinite thresholds or native scores | typed refusal |
| Monitor origin, crop and DPI scaling | explicit correct transformed rectangle |
| Diff and unchanged image | changed pixel count and bounded regions, or unchanged |
| Differing shapes | explicit refusal, no inferred alignment |
| OCR adapter absent | explicit unavailable; no subprocess or network fallback |
| OCR adapter malformed or raises | typed failure, never invented text |

Budget: only small synthetic fixtures, zero screen/camera captures, zero model
or remote OCR requests, focused suite target below 120 seconds. OpenCV is an
optional local dependency; missing optional dependencies are reported honestly.

## Migration and rollback

Migration is additive and stateless. Rollback removes this module and its tool
registration in the parent packet; no evidence or user data is deleted. Image
digest is input provenance only, not an alternate canonical artifact identity.
Coordinates are observations, never authority to click; timestamp freshness and
target focus belong to the trusted admission adapter. OCR adapters must be
trusted local implementations supplied by that adapter, not candidate callbacks.

Independent review must check parser bounds, ambiguous peak handling, coordinate
semantics and import/effect absence.

## Evidence, expected failures and review

Builder evidence 2026-09-05: installed and exercised
`opencv-python-headless==4.11.0.86` with existing `numpy==1.26.4`; no numpy
migration. `python -m pytest -q tests/runtimes/test_computer_vision.py` produced
42 passed in 2.28 seconds, then 45 passed in 90.11 seconds after adding huge
JPEG, huge-number and native-decode refusal cases. All image algorithms use
real cv2 and deterministic numpy fixtures. OCR is an injected test adapter,
not evidence of an installed OCR engine. No host capture or real GUI evidence.

Retained negative evidence: initial 42-case run had 32 failures and 10 passes
because its import-safety test reloaded the shared module, invalidating imported
class identities in the remaining tests. Replacing that test with a fresh
subprocess import fixed the harness without weakening runtime type checks.
Review also caught that full-template nonmaximum suppression could conceal an
overlapping duplicate; the implementation conservatively preserves alternate
placements, with a real periodic-image regression fixture. Huge numeric input
is range checked before float conversion to avoid leaking OverflowError.

Primary API references consulted 2026-09-05:
- https://docs.opencv.org/4.13.0/de/da9/tutorial_template_matching.html
- https://docs.opencv.org/4.13.0/d4/da8/group__imgcodecs.html
