# G1-IKARUS-19 — Explicit computer policy configuration

Packet ID: G1-IKARUS-19
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: reviewed G1-IKARUS-17 and G1-IKARUS-COMPUTER-01 ComputerPolicy and registered effect admission
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Parent: reviewed G1-IKARUS-17 and root-defined canonical ComputerPolicy.
Status: implementation, focused verification and independent review complete.

## Primary acceptance claim

An explicit owner command updates an existing computer policy atomically,
bound to the expected current policy digest. No model tool can configure its
own authority. The helper neither starts computer work nor clears a stop.

## Scope

Scope: `daedalus/interfaces/computer_configuration.py`, focused tests under
`tests/interfaces/`, this packet, configuration usage docs; root owns the
registered effect row and the command handler. No modification to instructions,
master plan, candidate workspaces, personal configuration or unrelated code.

## Contracts and behavior

The explicit owner command supplies a complete policy and its expected current
digest. Validation and registered effect admission precede replacement under
the existing setup lock. Atomic publication changes future authority only;
canonical evidence reports whether replacement happened, including uncertain
finalization. The helper is absent from model tools.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Authorization | Missing/non-boolean owner confirmation refuses before effects |
| Current policy | Missing policy, stale expected digest or competing update refuses |
| Schema and scope | Full ComputerPolicy schema; roots disjoint from control/install; no linked workspace; origins/apps use existing strict parsing |
| Guard | Registered filesystem-write entrypoint requires process guard and actual validated configuration evidence |
| Persistence | Existing setup lock; fsynced temporary file and atomic replacement; exact readback digest |
| Evidence | Canonical admitted/completed artifact references bind old/new policy digests; no second configuration history authority |
| Failure | Pre-replacement fault leaves original bytes; concurrent policy update retained; no stop-marker change |
| Interface | Explicit `/computer configure` only; command is absent from model tool inventory |

Historical pre-fence baseline: initial setup created a fixed files/vision
policy, and no supported configuration helper existed for owner-selected
applications/origins. Current v0.1.6 contract: fresh setup stores `tools=[]`.
Configuration may retain disabled legacy names for migration, but cannot
advertise or admit `file.*`, path-based vision, or local skill reads. Runtime
availability remains separately measured.

## Migration and rollback

Rollback is an explicit configuration command binding the new current digest
and the previous policy values. It does not rewind completed computer effects.

## Evidence, expected failures and review

Implemented the helper, exact full-policy validation, setup-lock serialization,
atomic fsynced replacement, canonical admitted/completed references, and
explicit unknown-finalization reporting. The root-owned entrypoint declares
only filesystem write. The independently owned conversation handler supplies
owner confirmation only from the explicit configuration command.

`python -m pytest -q tests/interfaces/test_computer_configuration.py` completed
initially with **17 passed in 2.03 seconds**. Tests covered stale/invalid/unconfirmed
requests before effects, process-guard refusal, exact policy readback and
canonical evidence, pre-replace failure, competing update, unchanged sticky
stop, no-op preservation, and post-replace evidence failure truthfulness.
All policy fixtures used isolated temporary profile/control/workspace paths.
No personal policy was changed. Added missing-policy and supplied-symlink
checks, then native-application/candidate/interpreter refusals after the root
policy review tightened host execution. The final focused suite completed
with **21 passed in 3.17 seconds**.

Retained negative evidence: the new link test initially expected the word
`linked`, while the consolidated policy constructor correctly rejected it with
`links or junctions`; the assertion now matches the stable reason. The first
success fixture's Python version probe became correctly refused after the
parent forbade trusted-host interpreters; it now uses a native-editor data
fixture outside the writable workspace. These changes did not relax policy.

Independent root review accepted explicit owner confirmation, current-digest
binding, setup-lock serialization, atomic policy replacement, retained evidence
and unchanged stop state. The kernel reviewer separately verified that only
the explicit command supplies owner confirmation and the model tool inventory
contains no configuration entrypoint.

Usage and complete policy template:
`docs/IKARUS_COMPUTER_CONFIGURATION.md`.
