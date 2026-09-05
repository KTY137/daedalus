# G1-IKARUS-25 — Wire the handle-anchored file adapter and lift the file-tool fence

Packet ID: G1-IKARUS-25
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-24 green AND independently reviewed; G1-IKARUS-COMPUTER-01
service, lease and evidence contracts; existing ComputerPolicy admission
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: acceptance frozen before implementation. Build is blocked until (1) the
independent review of G1-IKARUS-24 returns without a blocking finding and (2)
the shared files below are not being edited by another agent (the tree is
shared live with Codex sessions on 2026-09-05).

## Primary acceptance claim

`file.list`, `file.read`, `file.write`, `file.mkdir` and `file.move` become
executable computer tools again, but only through `WorkspaceFiles`
(G1-IKARUS-24) behind the unchanged canonical admission: policy digest binding,
persisted effect lease, start and terminal receipts, kill switch, cancellation
probe, secret floor. Path-based vision (`vision.match`, `vision.changes`, the
`path` form of `vision.inspect`/`vision.ocr`) and local skill-directory reads
stay release-disabled: they are not anchored by this packet.

## Scope

In scope: `daedalus/kernel/policy/computer.py` (shrink `RELEASE_DISABLED_TOOLS`
to the vision path forms; keep `enforce_release_tool_fence` for them; keep
`refuse_workspace_path_io` for the skill seam), `daedalus/runtimes/computer.py`
(replace `_file`/`_read_bytes` with the adapter; keep secret-floor checks on
read text and write text in the service; capability projection lists file
tools; `path_io_release_lock` describes the remaining vision fence),
`tests/kernel/test_computer_policy.py`, `tests/runtimes/test_computer_service.py`,
the one fence-inventory assertion in `tests/test_ikarus_computer_autonomy.py`,
`docs/IKARUS_COMPUTER.md`, and this packet. Forbidden: the adapter's boundary
logic (owned by G1-IKARUS-24), `computer_context.py`, loop, schedule, shell,
plan, instructions, `apps/web`, effect registry rows.

## Review obligations inherited from the G1-IKARUS-24 security review

Cerberus (2026-09-05) blocked the first adapter revision and named what this
packet must satisfy before `file.*` leaves `RELEASE_DISABLED_TOOLS`:

1. Containment, not identity: on Windows the whole directory chain is held
   without `FILE_SHARE_DELETE` for the duration of every operation, so no
   process can rename, move or delete the root, an ancestor or the parent while
   the tool runs (measured: leaf, middle, root and the ancestor above the root
   all refuse with sharing violation / access denied). On POSIX the chain is
   verified before and after but cannot be pinned; therefore file tools are
   **Windows-only in this release**: the adapter itself refuses every effect
   on a non-Windows host (`_effect_host_available`), and the service must
   project the five file tools as `unavailable` with a Windows reason there.
2. `file.read` and `file.list` run the checkpoint, verify the chain and compute
   `postcondition_verified`; content read while the chain is unverified is
   withheld, never returned.
3. The adapter admits through `ComputerPolicy.admit` itself (grant + fence +
   lexical rules) and cannot execute a disabled or ungranted tool. Done in
   G1-IKARUS-24; the service keeps its own admission in front of it.
4. The secret floor keyed by the requested path stays on read text and write
   text in the service AND in the adapter (done in G1-IKARUS-24); the generic
   result floor does not subsume it.
5. `file.list` omits entries the policy would refuse (protected names, links,
   hard-linked files), as the fenced service did.
6. POSIX stays unmeasured and disabled until a Linux host runs the suite.
7. The service-level acceptance asserts "nothing was created outside
   `policy.workspace`", not merely a false verification flag.

## Contracts and behavior

`ComputerService._dispatch` routes `file.*` to one `WorkspaceFiles` instance
per service, constructed with the service's `check_cancelled` as checkpoint,
so cancellation, deadline, kill switch, policy drift and lease re-admission run
after the parent handle is open and before every effect. Secret-floor
filtering stays in the service: `file.read` text is withheld by
`secret_floor_rule(path, text)` and `file.write` text is refused before the
adapter is called, exactly as before the fence. Results keep the
`daedalus-computer-result/1` shape; `host_mutation` stays true for write,
mkdir and move; `filesystem_scope_kind` becomes
`handle-anchored-computer-workspace`. Legacy stored grants for file tools
become effective again; no setup or configuration change is required to lift
the fence, because the fence was never a policy grant.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Baseline preserved | `tests/runtimes/test_computer_service.py` + `tests/kernel/test_computer_policy.py`: 76 passed in 14.30 s before the change; every non-fence case still passes after |
| Fence narrowed | `enforce_release_tool_fence` refuses `vision.match`, `vision.changes` and any `path` form of `vision.inspect`/`vision.ocr`; accepts every `file.*` shape that `ComputerPolicy.admit` accepts |
| Service ancestor swap | The retained `sub -> junction` race at `check_cancelled` (existing fixture) now reaches the adapter and refuses with "changed during the operation"; no file inside or outside; lease and terminal receipt retained as a blocked/refused operation, never `reconciliation_required` |
| Service round trip | Real persisted lease: write, read back, mkdir, list, move with exact digests and `postcondition_verified`; secret-bearing write text refused before the adapter; secret-bearing read withheld |
| Capability projection | `capabilities()` lists the five file tools with their schemas on Windows; on other hosts they are `unavailable` with a "Windows" reason; `vision.match`/`vision.changes` absent; `path_io_release_lock` names only the remaining vision fence |
| Move-out containment | A checkpoint that tries to rename the parent out of the workspace fails with a sharing violation while the tool runs (pinned chain); nothing appears under the outside tree in any outcome |
| Kernel issuer | `admit_operation` still binds the current policy digest; a file operation with a stale digest or a tool not in `policy.tools` has no lease |
| Cancel / deadline / drift | Existing `test_policy_drift_and_cancel_prevent_all_file_effects` and `test_deadline_refuses_before_admission` pass against the live adapter with zero effect |
| Inventory | `tests/test_ikarus_computer_autonomy.py::test_runtime_path_release_fence_inventory_is_preserved` updated to the narrowed inventory; skill seam tests in `tests/test_ikarus_computer_context.py` unchanged and green |
| Docs | `docs/IKARUS_COMPUTER.md` states which tools are enabled, that setup still grants nothing, and that vision path forms and skills stay locked |
| Independent review | A reviewer who did not write G1-IKARUS-24 or this packet checks kernel bypass, secret placement, receipt truthfulness and false-success paths |

## Migration and rollback

Rollback restores `FILE_TOOLS` into `RELEASE_DISABLED_TOOLS` and the fenced
service seams; the adapter module stays dormant. Owners who stored file grants
before v0.1.6 regain them on upgrade without a settings change; owners who
never granted file tools stay without them (`/computer configure` adds them).
No completed effect, lease or evidence record is rewritten.

## Evidence, expected failures and review

To be recorded during the build: focused suites, the service-level swap
acceptance, capability projection, and the independent review. Expected
refusals: stale policy digest, missing grant, secret content, link/junction at
any position, hard link, oversized content, cancelled or expired task.
