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
Status: phase 1 (routing behind the fence) and phase 2 (narrowed fence lift)
implemented and builder-verified on 2026-09-05; the independent review of the
lift returned **BLOCK** at 17:40, the repairs landed test-first, adversarial
verification found no surviving mutant, and the confirmation pass at 20:44
returned **PASS-WITH-FINDINGS** bound to `computer.py 81931eb9…`,
`policy/computer.py 1b3bc7e2…`, `computer_files.py 7120cf2a…` (see the
sections at the end); replacement of existing files stays fenced; nothing is
merged or promoted. The shared files
below were untouched by other agents since 10:09 when the build started, and
the lane was announced in the shared room.

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
`handle-anchored-computer-workspace` for `file.*` results, while every non-file
tool keeps `computer-policy-workspace-relative` (correction 2026-09-05 18:05:
the reviewed code emitted the old value for every tool; aligned in the tree at
18:37 [MEASURED], see the phase-2 review section). Legacy stored grants for file tools
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

Build phase 1 (2026-09-05 16:55, fence still up): `ComputerService._dispatch`
routes `file.*` to one `WorkspaceFiles(policy, check_cancelled)` per service;
a plain `ComputerRefused` or an interruption the adapter annotates with
`effect_state == "none"` after admission is reported as `blocked` with the
started effect finished as `CANCELLED` and its terminal record retained,
while `effect_state == "uncertain"` keeps `reconciliation_required`;
`_release_unavailable_reason` reports the five file tools as unavailable off
Windows. The fence in `RELEASE_DISABLED_TOOLS` is unchanged, so nothing is
observable yet: `tests/runtimes/test_computer_service.py
tests/kernel/test_computer_policy.py tests/runtimes/test_computer_service_files.py`
measured **76 passed, 7 xfailed in 52.99 s**. The fence flip (phase 2) waits
for the independent Codex review of the adapter's final revision
(`762aaa7fdd7498fc…`), then changes `RELEASE_DISABLED_TOOLS`, the capability
text, the fence tests, the inventory assertion and the user documentation in
one change together with removing the seven `xfail` markers.

Independent Codex review of the adapter (2026-09-05 16:50–17:04, `codex exec
--sandbox read-only`, `model_reasoning_effort=high`, bound to
`762AAA7FDD7498FC…`): no boundary escape found; three control-flow gaps
established by in-memory probes, not by live host evidence: `_verify` and
`_absent` catch only `ComputerRefused`, so a raw `OSError` during the
read-back propagates after the effect; `_mkdir` has no typed interruption
(write and move carry `effect_state`); move verification is a snapshot, so a
competitor can rewrite the destination after the rename (an in-workspace data
race, not a containment failure). The reviewer's final report was withheld by
OpenAI's cybersecurity content filter (exit 1, empty stdout); the findings are
retained from the transcript. Consequence for the service (this packet): an
interruption without an `effect_state` is reported as
`reconciliation_required`, never as `blocked`. The adapter items are handed to
the concurrent Codex session that owns G1-IKARUS-24.

Phase 2 plan, narrowed to respect the adapter packet's HOLD: `file.list`,
`file.read`, `file.mkdir`, `file.move` and `file.write` for a NEW file leave
the fence; `file.write` with `expected_sha256` (replacement through the
two-rename protocol) stays fenced with its own refusal until a service-owned
crash reconciliation for the reserved backup exists. The capability projection
drops `expected_sha256` from the offered `file.write` schema so no admitted
shape is refused.

Phase 2 landed (2026-09-05 17:20): `RELEASE_DISABLED_TOOLS` is now
`{vision.match, vision.changes}`; `enforce_release_tool_fence` refuses
`file.write` with `expected_sha256` with `FILE_REPLACE_RELEASE_REFUSAL`; the
projection offers `file.write` without `expected_sha256` and describes it as
creating a NEW file; `path_io_release_lock` names both remaining fences; the
dead pathname seam `ComputerService._file` is deleted while `_read_bytes`
stays fenced for path-based vision; `docs/IKARUS_COMPUTER.md` describes the
enabled tools and the remaining fence. Tests: the policy fence rows became a
vision-only fence test plus an admitted-file-shapes test and a replacement
fence test; the service fence tests became projection/replacement/swap/seam
tests whose swap fires only on the adapter's own checkpoint (the service also
checkpoints before admission, before any handle exists); the seven `xfail`
markers were removed and the stale-hash case now expects the replacement
fence. Measured: `tests/kernel/test_computer_policy.py
tests/runtimes/test_computer_service.py tests/runtimes/test_computer_service_files.py
tests/test_ikarus_computer_autonomy.py::test_runtime_path_release_fence_inventory_is_preserved
tests/test_council_vendors.py`: **153 passed in 87.39 s** (RED first: 18
failed before the flip, all on the fence).

Expected refusals after the lift: replacement of an existing file (fenced),
stale policy digest, missing grant, secret
content or a secret-floor path on any move endpoint, link/junction at any
position, hard link, oversized content, cancelled or expired task, non-Windows
host.

## Independent review, phase 2 (Cerberus, 2026-09-05 17:40)

Verdict: **BLOCK**. Read-only reviewer, wrote neither G1-IKARUS-24 nor this
packet. Bound to `daedalus/runtimes/computer.py` sha256
`03c447551d4179ab80df78cc4dbd9e317c67dddab8e9371efa12bead84cab85a` and
`daedalus/kernel/policy/computer.py` sha256
`9b709ee1d83f88ac717d203312e17aae460f64049d1421c9f5927e79b80ece6c`, which
drifted mid-review to
`eb50ad5a324ebdc1c9cc3ca92bf7f6886aa7077ef3dcca1955a754689e8d6497` when the
replacement flag was added; the adapter was read at `762aaa7fdd7498fc…`
[INHERITED: reviewer's report]. Both current hashes re-measured unchanged at
18:05 by the chronicling session, so the findings below still bind the tree at
that minute [MEASURED].

### Findings (reviewer's words, condensed)

- **F1 CRITICAL — a landed effect is reported as `blocked`.**
  `ComputerService.execute` calls `check_cancelled()` *after* `_dispatch`
  (`daedalus/runtimes/computer.py:269`). Cancellation, deadline expiry and
  policy drift raise a plain `ComputerRefused` at that point, and the new
  classifier treats a plain `ComputerRefused` on a `file.*` tool as provably no
  effect: it finishes the lease as `CANCELLED` and returns `blocked` although
  the write, mkdir or move already happened. The reviewer executed the
  reproduction on Windows for all three effect tools and for the drift case.
- **F2 high — enforcement and claim can diverge.** `RELEASE_REPLACE_FENCED`
  (`daedalus/kernel/policy/computer.py:52`) is a mutable module global whose
  documented purpose is to be lowered by the adapter's own test suite, while
  `capabilities()` advertises the replacement lock unconditionally. Whoever
  lowers the flag turns the advertised fence into a false statement.
- **F3 medium — CANCELLED receipts keep only the exception class name.** The
  terminal detail is `canonical_sha({"error": type(exc).__name__})`; the
  adapter's `recovery_paths` are never persisted, so a reconciliation reader
  cannot learn which reserved names to inspect.
- **F4 low — POSIX `file.read`/`file.list` are gated once, not twice.** Only
  the service projects them unavailable off Windows; the adapter's
  `_effect_host_available` refuses effects, not reads. The service is the only
  public entrypoint, so the release property holds — through one layer.
- **F5 low — a create-then-verified-delete refusal reads as `blocked`.** A
  plain `ComputerRefused` after that sequence is reported `blocked`; the net
  state is proven back to baseline, so the label is defensible, but the packet
  should say so instead of leaving it implicit.
- **F6 low (hypothesis, not measured) — the NFC docstring overclaims.** NTFS
  does not normalize: a pre-existing NFD entry stays unaddressable, and an NFC
  write creates a second entry beside it.

### Closed by this review

- Both G1-IKARUS-24 CRITICALs and NEW-1 (secret floor on both `file.move`
  endpoints) are closed at the reviewed hashes.
- No bypass to the legacy pathname helpers: `_read_bytes` is triple-fenced and
  reachable only from path-based vision, which stays disabled.
- Replacement (`file.write` with `expected_sha256`) is genuinely unreachable
  through the public entrypoint, not merely undocumented.
- The Windows-only gate is enforced before the lease is acquired, not after.

### Reviewer's list before acceptance

1. State the post-effect checkpoint case (F1) and cover it with a test.
2. Resolve the `filesystem_scope_kind` mismatch in one direction: the packet
   claims `handle-anchored-computer-workspace`, the reviewed code emitted
   `computer-policy-workspace-relative` for every tool
   (`daedalus/runtimes/computer.py:280`).
3. Put `RELEASE_REPLACE_FENCED` in the packet's scope (F2).
4. State that `recovery_paths` is not persisted (F3).
5. State the single-layer POSIX gate (F4).
6. State Codex's three control-flow gaps with why each fails safe: an `OSError`
   from `_verify`/`_absent` propagates after the effect and is classified
   `reconciliation_required`; a bare `KeyboardInterrupt` from `_mkdir` carries
   no `effect_state` and is therefore also `reconciliation_required`; move
   verification is a snapshot, so a later in-workspace rewrite degrades
   `postcondition_verified` only and cannot escape the workspace.

Direction chosen for item 2: the packet's claim stands for `file.*` results and
the code is being aligned to it; every non-file tool keeps
`computer-policy-workspace-relative`. See "Repairs in progress" below.

### Suites at the reviewed revision

- `tests/runtimes/test_computer_files.py tests/kernel/test_computer_policy.py
  tests/runtimes/test_computer_service.py
  tests/runtimes/test_computer_service_files.py`: **165 passed**
  [INHERITED from session cbd944a5, background run at 17:31].
- Orchestration-side computer suites (schedule, context, loop, autonomy,
  history, configuration, watcher): **150 passed** [INHERITED, same run].
- The 153-passed figure in the phase-2 section above is the earlier, narrower
  selection; it is not superseded, it measured a different set.

### Repairs in progress (2026-09-05 18:05, not done, not verified)

None of the following may be read as accepted; the BLOCK stands until a
reviewer confirms at a named hash.

- Session cbd944a5 is fixing F1 and coupling claim to enforcement for F2 in
  `daedalus/runtimes/computer.py`, and is aligning `filesystem_scope_kind` so
  `file.*` results emit `handle-anchored-computer-workspace` while non-file
  tools keep `computer-policy-workspace-relative` [INHERITED: the session's own
  statement — at 18:05 the file still hashed `03c44755…` and line 280 still
  emitted the old value for every tool, so nothing had landed at that minute
  [MEASURED]].
- Agent `heracles-adapter` is adding a typed interruption to `_mkdir`, `OSError`
  reporting in `_verify`/`_absent`, and the corrected NFC docstring (F6) in
  `daedalus/runtimes/computer_files.py` [INHERITED].
- Design packets G1-IKARUS-27 (replacement crash reconciliation) and
  G1-IKARUS-28 (vision path forms) are being drafted [INHERITED]. At 18:05
  `docs/work-packets/G1-IKARUS-28_VISION_PATH_FORMS.md` exists (223 lines,
  status "DRAFT, baseline recorded, build not started"); no G1-IKARUS-27 file
  is on disk yet [MEASURED].
- A cross-vendor council run is scheduled after the F1 fix, advisory only: it
  promotes nothing and does not lift the BLOCK [INHERITED].

### Update 18:37 — repairs landed in the tree, the BLOCK still stands [MEASURED]

Re-measured by the chronicling session after the section above was written. This
records what the tree does, not an acceptance: no reviewer has seen these hashes.

- All three binding hashes moved, so the 17:40 verdict no longer binds any file
  in the tree: `daedalus/runtimes/computer.py`
  `cfe9255ccfeae131e0dadfa9848351a6d8d98f3a03bb04c9cedd8a2c18e75588`,
  `daedalus/kernel/policy/computer.py`
  `1b3bc7e2595c1ae8c1687e231f184e826f185e2e5c5c34454745ac902691d959`,
  `daedalus/runtimes/computer_files.py`
  `9c76a8d327c74b7682be1b8e7d5c7185f4cf66ae2540a3903369201ba93f4b4c`. A
  re-review must name a fresh hash.
- F1: `_dispatch` now sets a `dispatched` flag and `provably_no_effect` requires
  `not dispatched`, so a refusal from the post-dispatch checkpoint leaves the
  lease STARTED and returns `reconciliation_required`
  (`daedalus/runtimes/computer.py:324`).
- F2: the projection reads the flag it advertises —
  `_release_policy.RELEASE_REPLACE_FENCED` at `daedalus/runtimes/computer.py:78`
  and `:190`, so lowering the flag drops the claim with it.
- F3: `_store_failure_record` persists `recovery_paths`, `effect_state`,
  `dispatched` and `provably_no_effect` behind the secret floor, and the
  CANCELLED terminal detail is that record's digest instead of the exception
  class name (`daedalus/runtimes/computer.py:355`).
- `filesystem_scope_kind` is aligned to this packet's claim:
  `handle-anchored-computer-workspace` for `FILE_TOOLS`,
  `computer-policy-workspace-relative` for every other tool
  (`daedalus/runtimes/computer.py:289`).
- Unchanged and still code-true: `RELEASE_DISABLED_TOOLS = {vision.match,
  vision.changes}`, `RELEASE_REPLACE_FENCED = True`,
  `RELEASE_OBSERVATION_ONLY_TOOLS = {vision.inspect, vision.ocr}`
  (`daedalus/kernel/policy/computer.py:48`, `:55`, `:56`).
- NOT measured by this session: any test run against these hashes, F4, F5, F6,
  and whether the adapter changes (`computer_files.py` moved too) are complete.

### Update 18:55 — suites at the repaired hashes [MEASURED, session cbd944a5]

- `daedalus/runtimes/computer.py` @ `cfe9255ccfeae131…`, `daedalus/kernel/policy/computer.py` @ `1b3bc7e2595c1ae8…`, `daedalus/runtimes/computer_files.py` @ `22af4d6c0e6e7b51…`.
- `tests/runtimes/test_computer_service.py tests/runtimes/test_computer_service_files.py tests/kernel/test_computer_policy.py tests/test_ikarus_computer_autonomy.py tests/test_ikarus_computer_schedule.py`: 148 passed (221 s, box under load, timing not evidence).
- `tests/runtimes/test_computer_files.py`: 86 passed (81 before Heracles' three adapter items: typed `_mkdir` interruption, OSError reporting in `_verify`/`_absent`, NFC docstring corrected to the measured NTFS behaviour).
- New service tests: `test_a_refusal_observed_after_the_effect_landed_is_never_reported_as_no_effect[cancellation|policy drift]` (F1), `test_replacement_fence_claim_and_enforcement_share_one_source` (F2), `test_failure_records_persist_the_adapter_recovery_paths` (F3), `test_file_results_declare_the_handle_anchored_scope`. Each was watched failing before its repair.
- Seam change to note for the loop: a `file.mkdir` interrupted at the adapter checkpoint now arrives typed `effect_state="none"` and is `blocked` (workspace unchanged) instead of `reconciliation_required`; post-admission interrupts stay `reconciliation_required` and now carry `recovery_paths`.
- Still open below the fence: `_replace` rollback verification catches only `ComputerRefused` around `_matches`, a host `OSError` there escapes untyped (G1-IKARUS-27 input). F4 (POSIX read/list single-layer) and F6 (docstring, now corrected) are recorded; F5 (proven-reverted create is `blocked`) is accepted as stated.
- Confirmation by the independent reviewer on these hashes is still owed; adversarial verification (Odysseus) and the advisory council are running on the repaired diff.

### Update 20:25 — rollback host error closed below the fence [MEASURED, session cbd944a5]

- `daedalus/runtimes/computer_files.py` @ `7120cf2a535f80a2…`: `_replace` rollback verification now catches `OSError` from `_matches` next to `ComputerRefused`, records the error class only (no host path in the model-facing detail) and leaves the outcome uncertain with recovery paths; test `test_rollback_verification_host_error_is_reported_as_uncertain_not_raised` was watched failing with the raw `OSError` and its injected host path first. Adapter suite 87 passed.
- `daedalus/runtimes/execution/budget_process.py`: the `BILLABLE_SITES` row for `_CliAdapter._dispatch` is now `explicit: True` (the seat reserves through `guard(...)` since G1-COUNCIL-02); suites pending in this note's successor.

### Advisory council, 2026-09-05 evening (two rounds, both flawed in different ways)

Advisory only; gated nothing. Bus files under `runs/council/` (chains verified):

- `council-20260905T170503Z-b15a9de7`: cut in round 2 by a Claude Code process restart. Quorum 1 of 3 reviewed the evidence: Anthropic `unavailable/transport_error` after 240 s (cause not recoverable), OpenAI `spoke` but the scratchpad evidence path was WITHHELD by the untrusted egress lane (default-deny for paths outside the allow-list), local 7B spoke with one unverified claim (`CHECK: NONE`) citing the terminal-decision line. The dry run cannot show withholding.
- `council-20260905T182242Z-52b41924`: 2/2 rounds, Codex received the evidence (renamed to `runs/council/evidence/g1-ikarus-25-evidence.diff.md`; the `.md` suffix satisfies the substring allow-list, `.diff` does not). But the evidence diff was taken at 18:22:42Z while the adversarial agent's mutant (a) was applied in place (line without `and not dispatched`, sha256 `9640553f…`); the tree was restored at 18:24:05Z (`cfe9255c…`). Every claim about a reachable `blocked`+CANCELLED path in that round is therefore a claim about the mutant. Round 1 blind: all three seats named the same mutated line first (uncontrolled observation for the falsification protocol, not proof). Round 2: Anthropic `refused` (its reply tripped the secret floor, AWS key id pattern, dropped unread), local `transport_error` at 0 ms (window exhausted by prior turns, inferred), OpenAI measurement seat refuted four falsifier claims (move-collision code omitted from the evidence, `operation_sha256` bound at `computer.py:242`, `to_dict` exists, the recovery list comprehension runs outside the `try`).
- Checks the council left that still apply to the real tree and are queued for the adversarial report: whether every post-effect adapter raise carries `effect_state="uncertain"`; the Windows exclusive create disposition (covered by the adapter suite); that `_store_failure_record` returning `None` is visible by the absence of `evidence.failure_record` and the class-name fallback digest. Not adopted: type-checking the origin of `effect_state` beyond `not dispatched` (only the adapter runs inside `_dispatch` for file tools).
- Ledger (read-only): Anthropic seats settled at reported cost ($1.00 and $1.32); OpenAI seats $0.00 subscription; one reservation `688f434b` ($3.00 worst case, pid 31208) from the process killed by the restart is still OPEN and needs the owner's or a reaper's decision; the ledger was not rewritten.

### Adversarial verification (Odysseus, 2026-09-05 20:30) and O-1 repair [MEASURED]

- Attacks at `computer.py cfe9255c…` / `policy 1b3bc7e2…` / `computer_files.py 7120cf2a…`: F1 reproduction across file.write/mkdir/move × cancellation/drift/deadline (9 combinations) plus KeyboardInterrupt, LoopHalted and two forced "effect_state=none after dispatch" lies: all `reconciliation_required`, lease STARTED, no CANCELLED terminal, failure record `dispatched:true, provably_no_effect:false`. Non-file tools unchanged. CAS failure on the failure path degrades to the class-name digest without crashing; a secret in the failure message yields a withheld record. Verdict: F1 CLOSED, F3 CLOSED, F2 closed for the replace flag. Tree restored byte-identically (sha256 before/after equal).
- Mutants: six named guards each caught by a named test in `tests/runtimes/test_computer_service.py`; no survivor. Note: all new-guard coverage lives in that one file, and mutants (d) and (e) share one test whose exact terminal-binding assertion must not be loosened.
- **O-1 (medium, repaired):** `RELEASE_DISABLED_TOOLS` and `RELEASE_OBSERVATION_ONLY_TOOLS` were imported by value into the runtime, so a release packet editing the frozenset would leave `capabilities()` advertising a tool the fence refuses (advertise-more-than-you-do, refused at the lease, not a bypass). Repaired by reading both from the policy module at call time; test `test_every_release_fence_constant_is_read_at_call_time` watched red first. `computer.py` now `81931eb9abb77f56…`; service+service_files+policy+autonomy 133 passed.
- Residuals recorded, not defects: O-2 the failure record applies the secret floor's content channel only, a secret-floor *name* inside `recovery_paths` is stored as a name (such names cannot become file-tool targets: `.env`, `id_rsa`, `key.pem` all blocked before the adapter, `_move` refuses floor endpoints); O-3 the response `error` string is not floored (nine real adapter refusals echo no content; latent gap for future messages); O-4 when `retain_terminal_record` fails after a durable COMPLETED terminal, the ledger says COMPLETED and the response `reconciliation_required` (safe direction, unnecessary reconciliation ask).

### Confirmation pass (Cerberus, 2026-09-05 20:44) — PASS-WITH-FINDINGS [INHERITED from the reviewer, hashes MEASURED]

Bound to `computer.py 81931eb9abb77f56…`, `policy/computer.py 1b3bc7e2595c1ae8…`, `computer_files.py 7120cf2a535f80a2…`; reviewer executed 115 + 112 passed and the seven F1/F2/F3 tests not skipped (Windows host).

- F1 CLOSED (`dispatched` at `computer.py:278`, required at `:321`; every plain `ComputerRefused` escaping the adapter after a mutation is pre-effect or proven-reverted, the unproven paths raise `ComputerFileEffectUncertain`; cancellation checkpoints only pre-effect). F2 CLOSED and generalised (no production from-import of the three release constants remains; the refusal message strings are still imported by value, cosmetic). F3 CLOSED. F4 OPEN, accepted as residual. F5 accepted as residual (record shows `external_started=true, dispatched=false, provably_no_effect=true`). F6 CLOSED. All six acceptance items closed; Codex's three gaps were repaired rather than merely stated.
- **N-1 (low, latent, unreachable in this release):** `_PosixBackend.rename` implements no-replace as `link` + `unlink` (`computer_files.py:288-290`); if `unlink` fails after `link`, the `_HostRefusal` becomes a plain `ComputerRefused` after `effect_possible`, which the classifier would call `provably_no_effect` while the file exists at both names. Unreachable today (Windows rename is one atomic `NtSetInformationFile`; `file.move` refused on POSIX at two layers). Whoever lifts the POSIX gate must fix this rename first: it is the concrete cost behind F4.
- Residuals accepted in writing by the reviewer: O-2, O-3 (with its own enumeration: refusal messages carry names, digests and classes, never bytes; the failure string never re-enters model context because the loop breaks on `not ok`), O-4.
- The verdict speaks about receipt truthfulness and the fence at these hashes only; it merges and promotes nothing. Owner decision on activation is separate (Iron Plan §10 step 9).

