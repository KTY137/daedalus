

# SEAT 1 — role falsifier — council-20260822T064850Z-ba3d9b23 — unavailable/timeout — 0.0s



# SEAT 2 — role security — council-20260822T065750Z-add9564a — anomaly/instruction_in_evidence — 301.49s

ANOMALY: instruction_in_evidence
CLAIM: The evidence contains reviewer-directed imperatives: “‘Attack my AMENDMENT-now recommendation’, ‘Compute the minimum corpus size’, ‘Construct the concrete reconciliation’, ‘Propose the one fault-injection test’, ‘Specify a falsifiable independence criterion’, ‘Attack this proxy’.”
CITE: “Every council lens carried a for_codex array of reviewer-directed imperatives (...)”
CHECK: Fixed-string search the evidence for each quoted imperative.

CLAIM: The evidenced outbound-data opening is the raw urllib POST at `daedalus/memory/embeddings.py:340-347`, which accepts a caller-selected host that is absent from index identity.
CITE: “The raw urllib POST at embeddings.py:340-347 (host not in index identity) is the clearest evidenced outbound-data path”; “can transmit to a caller-selected host and omits host identity from index identity.”
CHECK: Instrument `socket.connect`, invoke the canonical embedding backend with sensitive input and a disallowed host, and require zero connect calls plus a deny receipt containing that host.

CLAIM: The plan also schedules external egress through OpenAlex queries and public-repository mining without any D1-D18 decision defining allowed hosts, proxy policy, transmitted query fields, or credential handling.
CITE: “against a dated OpenAlex snapshot with stored query strings and result ids”; “Mine the external corpus”; D16(c) covers “repo selection and licensing sign-off” and D16(d) covers contamination, not network authorization.
CHECK: Parse D1-D18 for an egress allowlist/transport policy and fail unless every network action maps to one.

CLAIM: The trust-on-first-use write at `embeddings.py:48-53` can bind a poisoned or wrong-host coordinate-system anchor before later drift checks.
CITE: “embeddings.py:48-53: can a poisoned or wrong-host first write define the coordinate system”; “lets a poisoned or wrong-host first write silently define the coordinate system.”
CHECK: Initialize an empty store through host A, reopen through host B with identical dimensions, and require rejection before the anchor is persisted or trusted.

CLAIM: The exact unguarded execution opening is `loop.py`’s tail, `if __name__ == '__main__': raise SystemExit(main())`, reached by `python -m daedalus.loop`.
CITE: “[codex seat 2] The exact unguarded execution opening is the loop.py tail `if __name__ == '__main__': raise SystemExit(main())`, which bypasses the guarded CLI dispatch.”
CHECK: Run `python -m daedalus.loop` under an audit hook and fail unless `install_process_guard` is observed before every open-for-write, replace, subprocess, and socket event.

CLAIM: No exact source line for the architecture-map or watchdog-log write is established; `cli.py:1147` and `.claude/watchdog/.../attempt-*.log` are explicitly admitted to be imprecise.
CITE: “The evidence does not identify the exact filesystem-open line that writes the architecture map or watchdog logs; naming a more precise sink than cli.py:1147 or .claude/watchdog/.../attempt-*.log is unsupported.”
CHECK: Wrap `open`, `Path.write_*`, and `os.replace` with stack capture, execute one map generation and watchdog attempt, and require a unique source `file:line` for each write.

CLAIM: Phase 0 is falsely classified as read-only because it creates detached worktrees, writes scripts and receipts, attempts a protected-file write in each primary worktree, and explicitly permits two committed tree writes.
CITE: “read-only on both trees”; “Create two disposable detached worktrees”; “in EACH primary worktree attempt one protected-file write”; “Exactly two tree writes are permitted in this phase.”
CHECK: Snapshot `git status --porcelain`, filesystem write events, and worktree metadata before Phase 0; fail the `read-only` label if any write occurs, including a failed fence attempt that partially changes a file.

CLAIM: The primary-worktree fence test is unsafe as written because a broken fence performs the protected write it is supposed to detect, with no harmless target or rollback requirement.
CITE: “in EACH primary worktree attempt one protected-file write via the ordinary agent path (expected: denied).”
CHECK: Run the attempt only in a disposable clone with pre/post hashes of every protected artifact and require byte identity even when the guard is intentionally disabled.

CLAIM: Phase 0b cannot start fully concurrently with Phase 0 because its first action has a Phase-0 byte-identity precondition.
CITE: Phase 0b is “concurrent with Phase 0/1”; its first action says “Precondition from Phase 0: LATENT_CEILING_SHARED_REPRESENTATION.md and runs/higher_twin_nc/SPEC.md are byte-identical on both lines or exist on exactly one.”
CHECK: Encode the phases as a DAG and require the Phase-0 research-asset census node to complete before any Phase-0b commit node starts.

CLAIM: Phase 6a is sequenced after the Phase-4 stamp in document order even though it is required to occur before that stamp.
CITE: Phase 4 ends with “Stamp”; later Phase 6a is titled “after D1 and before the stamp” and D10 says “before the Gate-0 stamp.”
CHECK: Topologically sort actions with edges `D1 -> 6a -> Gate-0 stamp -> 6b`; fail if the published phase order violates the sort.

CLAIM: Phase 2 consumes D3’s harvest approval without making a recorded D3 ruling a precondition, while Phase 1’s exit criteria require only D1, D2, D6, and D7.
CITE: Phase 2: “Work the Phase-0 harvest manifest row by row”; D3: “harvest manifest approval”; Phase 1 Done when names “D1, D2, D6, D7” only.
CHECK: Refuse the first port commit unless a signed D3 record names the exact manifest hash.

CLAIM: D16a is sequenced after the ceiling labels may exist, contradicting its requirement that the owner co-sign the threshold protocol before any label is revealed.
CITE: Phase 7a first says “Run the ceiling classification,” then later “owner approves the threshold protocol (D16a)”; D16 says “co-signed as a hashed protocol committed BEFORE any label is revealed.”
CHECK: Require `git merge-base --is-ancestor <signed-protocol-commit> <first-label-commit>` to exit 0 and require the commits to differ.

CLAIM: D18 has no phase precondition even though environment identity must exist before both Phase-3 cold-start sampling and Phase-4 Linux fault execution.
CITE: D18: “Linux/CI host class and hardware declaration for the cold-start measurement and the fault run”; Phase 3 begins the cold starts; Phase 4 executes the Linux fault lines.
CHECK: Validate every cold-start and fault receipt against a D18-signed environment manifest whose hash predates the receipt.

CLAIM: Phase 1’s “zero commits after” and “one sha in every session thereafter” exit criteria are future-tense invariants that no finite exit check can establish.
CITE: “the losing branch carries a frozen/* tag and zero commits after it”; “the hook banner shows one sha in every session thereafter.”
CHECK: NONE

CLAIM: A Git tag and one denied write attempt do not enforce a read-only losing line, so the first-round seat-2 requirement for an “enforced read-only losing line” was softened.
CITE: Dissent: “an enforced read-only losing line is the necessary first constitutional operation”; Phase 1 implements `git tag frozen/...` plus “re-run the fence test”; D2 admits “the guard fences agents, not owner-run kits.”
CHECK: In a disposable clone, tag the losing tip and attempt a normal commit and an owner-token amendment; the freeze is enforced only if both are mechanically denied.

CLAIM: Phase 2’s suite-count criterion can pass while replacing old failures with new failures because it compares totals instead of failure identities.
CITE: “survivor full suite count >= Phase-0 baseline with 0 new failures.”
CHECK: Compare normalized failing test node IDs between baseline and survivor and require `failures_survivor − failures_baseline` to be empty.

CLAIM: Phase 3 is satisfiable without a working loop because alternative (b) accepts a blocker JSON as the deliverable.
CITE: “either (a) one `daedalus loop` iteration passes ... or (b) runs/loop/blocker_<sha>.json names the exact blocker”; kill criterion: “the blocker receipt is the deliverable.”
CHECK: Require the blocker receipt schema to contain captured audit events, invoked command, source SHA, nonzero attempted-work count, and independently reproduced failure; file existence alone must fail.

CLAIM: Phase 4’s closure predicate is circular because `inventory_only` may remain nonzero whenever the same owner accepts it, and D8 may close the mismatch by weakening plan text.
CITE: “inventory_only=0-or-owner-accepted-with-record”; D8 permits “blocker-ize ... or amend the plan’s ‘centralized start/guard path’ text.”
CHECK: Recompute closure under a fixed policy requiring `inventory_only=0`, then report separately whether owner exceptions or amended wording are the only reason `closed:true` appears.

CLAIM: Phase 0b’s claim that “no corpus item opened yet” cannot be established by the proposed parent-commit check because Git history records commits, not prior reads.
CITE: “Ceiling protocol committed ... and no corpus item opened yet (parent-commit check passes).”
CHECK: NONE

CLAIM: Phase 6a’s assertion that an author “never reads checks.py” is not machine-checkable from separate authorship, blob chronology, module separation, or a diff.
CITE: “authored ... by an author who never reads checks.py”; proposed evidence is “separate authorship + blob sha predating operator code + shared-module check + attached diff.”
CHECK: NONE

CLAIM: Phase 7b’s exit criterion permits a dated narrative saying no backbone can be attested in place of the required external replay evidence, making the corpus result satisfiable by a no-op.
CITE: “>= 4 external fixtures replayed (or a dated negative result explaining why no backbone can be attested).”
CHECK: Require signed acquisition-attempt receipts listing queried repositories, license results, release windows, network outcomes, and hashes; a prose-only negative result fails.

CLAIM: Phase 8’s “>50% of write-touching sessions” adoption numerator is circular unless an independent session census records sessions in which `daedalus brief` was never called.
CITE: “the command appears in > 50% of write-touching sessions”; the dissent warns that the chosen efficiency metric is gameable.
CHECK: Join brief-call logs to an independently generated session manifest keyed by session ID and compute the numerator and denominator from separate sources.

CLAIM: D2, D6, D7, D14, D16f, and the tracking-polarity part of D15 are fake decisions because their action text mandates one outcome rather than presenting two admissible policies.
CITE: D2 mandates a moratorium; D6 prescribes write-intent matching; D7 “lands with D6”; D14 says “refuse re-minting”; D16f says “sign the refusal record”; Phase 4 says “Invert evidence tracking polarity.”
CHECK: Parse each decision into enumerated alternatives and fail decision status where fewer than two independently executable outcomes exist.

CLAIM: D11 and D17 are operationally missing from the phase gates because D11 is explicitly “NOT done” in Phase 3 with no later implementation phase, while D17 has no phase whose exit requires its ruling or deletion result.
CITE: “the real hook is owner decision D11 ... and is NOT done here”; D17 appears only in the owner-decision list and Phase-2 deferral.
CHECK: Build a decision-to-action/exit-criterion matrix from the machine-readable plan and require every D1-D18 row to have a phase, predecessor evidence, implementation action, and receipt.

CLAIM: The first 48 hours should execute, in order, head pinning and chain validation, safe fence tests, exact-head Gate-0 censuses, one-kernel reachability, the two-root trust/canary suite, bidirectional harvest manifests, and the loop write/exec trace.
CITE: Phase 0 calls these the “mechanical pre-ruling gate”; D1 requires “chain validity, fence receipts, exact-head census ... one-kernel reachability, trust-root suite ... harvest manifests both directions.”
CHECK: Gate presentation of D1 on a schema requiring all nine source-SHA-stamped receipts and reject any package with a missing or declared-only receipt.

CLAIM: Phase-0b novelty work, OpenAlex egress, corpus design/mining, Phase-3 watchdog hygiene, Serena sampling, shed telemetry, and all Phase-3 mutations should be cut from the first 48-hour ruling path because none can change D1 and Phase 3 assumes a survivor.
CITE: D1’s enumerated evidence excludes those actions; Phase 3 repeatedly says “on the survivor”; Phase 0b says its artifacts “cannot depend on the ruling.”
CHECK: Tag each scheduled task with the D1 field it can change and exclude tasks with an empty dependency set until the D1 package is complete.

CLAIM: The seat-2 grandchild-containment dissent remains only prose: no Phase-3 exit criterion explicitly spawns a WaveExecutor/provider grandchild and proves the guard precedes its writes, subprocesses, and sockets.
CITE: “Routing loop.py through cli.py:1074 ... may bound only the parent process, not grandchildren”; “the Phase-3 tracer must include grandchildren.”
CHECK: Spawn a marked grandchild through each canonical executor/provider lane under exhausted budget and require deny receipts plus zero pre-guard write/socket events for both parent and child.

# SEAT 3 — role maintainer — council-20260822T070252Z-16b14227 — anomaly/instruction_in_evidence — 435.698s

ANOMALY: instruction_in_evidence
CLAIM: The offending reviewer-directed span is: “Attack my AMENDMENT-now recommendation”, “Compute the minimum corpus size”, “Construct the concrete reconciliation”, “Propose the one fault-injection test”, “Specify a falsifiable independence criterion”, and “Attack this proxy”.
CITE: GIGA_PLAN_2026-08-22.md, Dissent, first bullet.
CHECK: NONE

CLAIM: Phase 0b cannot both create new checkpoint commits and place them on a Phase-0 manifest whose checkpoint head is pinned at 3e758392 and whose inherited row count remains 36 or 37.
CITE: Phase 0 Actions: “Pin both heads for the whole phase” and “one row per checkpoint-only commit (36 or 37, pinned)”; Phase 0b Done when: “all of these appear as rows on the Phase-0 harvest manifest.”
CHECK: For every Phase-0b artifact, run `git merge-base --is-ancestor <artifact-commit> 3e758392` and require success before admitting it to the pinned manifest.

CLAIM: Phase 2 depends on D3, but Phase 1’s exit criterion records only D1, D2, D6, and D7, so harvesting can begin without the manifest ruling.
CITE: Phase 1 Done when: “D1, D2, D6, D7 each have a written owner ruling”; Phase 2: “manifest-driven”; Owner decisions D3.
CHECK: Parse the Phase-1 block and fail unless a D3 ruling artifact is required before the first Phase-2 port commit.

CLAIM: Phase 6a is ordered after Phase 4 in the numbered plan even though its exact action requires it to run “before the Gate-0 stamp” produced by Phase 4.
CITE: Phase 6a heading: “after D1 and before the stamp”; Phase 4 Actions: “Stamp”; Phase 6a appears after Phases 4 and 5.
CHECK: Build a dependency graph from phase order and explicit preconditions; flag the edge `Phase 6a -> Phase 4 stamp` because the numbered order supplies the reverse edge.

CLAIM: Phase 3 can depend circularly on D12 because its exit requires serena-first JSONL, its action says a protected hook needs an owner kit, and D12 later decides whether that kit is needed.
CITE: Phase 3 Done when: “serena-first JSONL exists”; Phase 3 Actions: “if the hook file is in the protected bundle…fold this into the next owner kit”; D12: “whether serena-first’s JSONL counter needs a kit.”
CHECK: On the survivor, attempt the JSONL-counter modification through the normal guarded path; if denied, require D12 before Phase 3 in the dependency graph.

CLAIM: D16a is internally sequenced after the ceiling run even though the protocol and D16 text require the threshold ruling hash to predate every revealed label.
CITE: Phase 7a ends with “owner approves the threshold protocol (D16a)” after “Run the ceiling classification”; D16 says “co-signed as a hashed protocol committed BEFORE any label is revealed.”
CHECK: Require the D16a ruling commit to be an ancestor of the first commit containing any ceiling item label.

CLAIM: D18 has no scheduled phase action even though Phase 3 collects cold-start percentiles and Phase 4 executes environment-sensitive Linux fault runs that require its environment declaration.
CITE: D18; Phase 3 cold-start measurement; Phase 4 Linux fault-run action.
CHECK: Run `rg -n "\bD18\b" GIGA_PLAN_2026-08-22.md` and fail if D18 occurs only in the owner-decision list.

CLAIM: Phase 0b’s claim that “no corpus item opened yet” is not machine-checkable because a parent-commit test proves repository history, not what a human or process previously read.
CITE: Phase 0b Done when: “no corpus item opened yet (parent-commit check passes).”
CHECK: NONE

CLAIM: Phase 1’s losing-line criterion is satisfiable at one instant without enforcing the invariant, because a tip tag plus an ordinary-agent denial does not prevent the owner-run amendment token that D2 says remains writable.
CITE: Phase 1 Done when: “losing branch carries a frozen/* tag and zero commits after it”; D2: “the guard fences agents, not owner-run kits.”
CHECK: Attempt a correctly formed amendment-token write while checked out at the frozen losing branch and require deterministic denial before declaring the fence effective.

CLAIM: Phase 2’s exit criterion covers only the 36-or-37 checkpoint rows, allowing the reverse trunk-only manifest to remain unported despite the phase title promising both directions.
CITE: Phase 2 heading: “both directions”; Done when: “every row (36 or 37 as pinned)”; Phase 0 separately defines “the REVERSE manifest.”
CHECK: Compute the union of checkpoint-only and trunk-only manifest row IDs and require every ID to have terminal state `ported` or `drop-with-reason`.

CLAIM: Phase 3’s blocker alternative can pass on a no-op trace because it requires no authenticated schema field proving that the loop started, the guard was observed, or the picker was called.
CITE: Phase 3 Done when alternative “(b) runs/loop/blocker_<sha>.json names the exact blocker…in both cases zero effects before install_process_guard.”
CHECK: Validate every blocker receipt with mandatory positive fields `loop_invocations`, `guard_install_events`, and `picker_calls`, each at least one where applicable.

CLAIM: Phase 4 can report Gate 0 closed without reducing inventory-only exposure because `inventory_only=0-or-owner-accepted-with-record` permits all surviving doors to be relabelled by record.
CITE: Phase 4 Done when: “inventory_only=0-or-owner-accepted-with-record.”
CHECK: Apply the stricter deterministic predicate `inventory_only == 0 && blocked == 0` to the stamped report and compare it with the plan’s reported `closed` value.

CLAIM: Phase 6a’s checker-independence criterion is partly attestation-held, because Git can prove blob order and module separation but cannot prove that an author “never reads checks.py.”
CITE: Phase 6a Actions: “authored…by an author who never reads checks.py.”
CHECK: NONE

CLAIM: Phase 7b can satisfy its corpus exit with no external fixture by writing a dated negative explanation, despite H-NC-cal requiring evidence over at least four external fixtures.
CITE: Phase 7b Done when: “>= 4 external fixtures replayed (or a dated negative result explaining why no backbone can be attested)”; kill criterion: “no reproducible…on >= 4 external fixtures.”
CHECK: Count distinct external fixture IDs in the signed corpus manifest and require at least four before assigning either `confirmed` or `killed`.

CLAIM: Phase 8’s greater-than-50-percent adoption criterion is circular because neither an immutable population of write-touching sessions nor the inclusion rule defining its denominator is specified.
CITE: Phase 8 Done when: “command appears in > 50% of write-touching sessions over the first 2 weeks.”
CHECK: Compute numerator and denominator from an immutable external session ledger using a committed classifier, and fail if any session lacks a deterministic write-touching classification.

CLAIM: D14 is a fake decision because both its owner-decision text and Phase 5 prescribe refusal, with no second admissible outcome.
CITE: D14: “refuse re-minting”; Phase 5: “owner decision D14 recorded as refusal.”
CHECK: Parse every D14 occurrence and count explicit alternative outcomes; the count is one.

CLAIM: The fixture-rule half of D10 is fake because Phase 6’s kill criterion makes any lift of higher_twin_nc checks ineligible to count, leaving only the no-lift outcome.
CITE: D10 asks to “confirm the rebuild-from-plan-text fixture rule”; Phase 6 kill criterion discards a packet produced by importing higher_twin_nc checks or operators.
CHECK: Deliberately construct a packet using the lifted checker and run the Phase-6 gate; it must fail regardless of the D10 ruling.

CLAIM: The tracking-polarity portion of D15 is fake because Phase 4 unconditionally commands the untracking, tracking, and cached removal actions, leaving choice only for the separate critique disposition.
CITE: Phase 4 Actions: “Invert evidence tracking polarity”; D15 repeats the same prescribed operations and asks only whether critiques enter the protocol or archive.
CHECK: Parse D15 into independent clauses and verify that the tracking clause contains no alternative branch.

CLAIM: D18 is not an owner policy choice but a duplicated evidence requirement, because D9 already chooses the Linux host while hardware and environment identity are measurable receipt fields.
CITE: D9: “Linux host/CI”; D18: “Linux/CI host class and hardware declaration.”
CHECK: Require environment identity and hardware fields in every fault and cold-start receipt schema, then verify no remaining execution branch depends on a separate D18 outcome.

CLAIM: D5 is missing the acceptance semantics of its hybrid option, so a future implementation can silently treat the HMAC factor as mandatory, advisory, or ignored while still saying “B as root.”
CITE: D5: “hybrid with B as root”; Phase 4: “retire or demote the loser to a ledgered second factor.”
CHECK: Run a four-case truth table over `{B valid, B invalid} × {HMAC valid, HMAC invalid}` and require a precommitted expected promotion result for every case.

CLAIM: The pre-ruling tree-write exception is a missing owner decision because the plan commits the memo and Phase-0b artifacts before D1 while relegating owner disagreement with that exception to a self-dissent.
CITE: Phase 0 permits two writes; Phase 0b commits multiple artifacts; merged-plan self-dissent: “if the owner rules that exception unacceptable, those files move to the scratchpad.”
CHECK: At D1 time, compare both branch tips with 3e758392 and 93f11adf and fail if either moved without a prior signed exception ruling.

CLAIM: D17 is dead in the executable sequence because Phase 2 forbids shim deletion, says it must follow the Phase-4 census, and no post-Phase-4 action performs the deletion.
CITE: Phase 2 Done when: “no shim deleted yet”; Phase 2 Actions: deletion “after the Phase-4 census”; D17.
CHECK: Parse all phase actions after Phase 4 and fail if none consumes D17 by running the shim-absent suite and then deleting or retaining the modules explicitly.

CLAIM: The first 48 hours should begin in parallel with chain validation and fence tests, exact-head Gate-0 censuses, entrypoint reachability, and bidirectional commit inventories because each directly triggers a stated D1 stop or eligibility condition.
CITE: Phase 0 actions `preruling_chains`, `preruling_fence`, `preruling_gate0`, `preruling_onekernel`, and harvest manifests; Phase-0/1 kill criteria.
CHECK: Require timestamped receipts for those five tracks before generating the D1 memo, and verify every receipt names one of the two pinned SHAs.

CLAIM: Trust-root testing should start only after reachability identifies the live promotion path, because otherwise the seven-case suite may measure an implementation that no canonical entrypoint calls.
CITE: Phase 0 `preruling_onekernel` asks whether promote_candidates reaches approvals.py; `preruling_trustroot` tests both roots; dissent says the checkpoint verifier has “zero production callers.”
CHECK: Require `trust_root_report.json` to cite a reachability receipt and a concrete canonical attempt-path entrypoint before accepting any end-to-end result.

CLAIM: Phase-0b novelty work, corpus protocol work, the loop trace, and Phase-3 watchdog, Serena, loop, and telemetry mutations should be cut from the ruling-critical first 48 hours, while the crashing scanner must be measured at 93f11adf rather than repaired before eligibility is determined.
CITE: Phase-0 kill criterion makes an unrunnable g0 reporter disqualifying as-is; Phase 0b and Phase 3 actions do not decide chain validity, fencing, exact-head regression, or dual-kernel reachability.
CHECK: At the 48-hour cutoff, require no Phase-0b or Phase-3 implementation commits and require the original-head scanner exit status in the decision package.

CLAIM: The seat-3 freeze dissent was softened because the plan now permits a memo, vault note, and multiple Phase-0b commits on the checkpoint line before the owner selects a chain.
CITE: Dissent: “[codex seat 3] Both lines should first stop changing”; Phase 0 permits two writes; Phase 0b commits protocol, novelty, tracer tests, corpus protocol, and refusal document.
CHECK: Compare both branch tips at Phase-0 start and immediately before D1; any changed tip proves the lines were not frozen as dissented.

CLAIM: The seat-3 producer-census dissent was dropped because Phase 6a proceeds directly to adding “first canonical producers” without requiring a fresh survivor-head census showing those producers are still absent.
CITE: Dissent: “[codex seats 2, 3, 4, 5]…repeat at the surviving head”; Phase 6a Actions: “First canonical producers on a live path.”
CHECK: Require a source-SHA-stamped producer census at the survivor head whose commit predates the first producer implementation commit.

CLAIM: The seat-3/4 hub-baseline dissent was softened because Phase 7c requires hub-stripped flat comparison but omits the explicitly demanded graph-brief baseline and does not make BM25 an arm-level requirement.
CITE: Dissent: “[codex seats 3, 4]…ablation against Tucker/mode-tagged, flat concat, BM25 and graph-brief”; Phase 7c plane-mode action names flat concat, hub stripping, graph_delta, and rewire control.
CHECK: Inspect the frozen plane-mode experiment spec and fail unless it contains equal-budget result rows for Tucker or mode-tagged, flat concat, hub-stripped flat, BM25, and graph-brief on the same split.

# SEAT 4 — role measurement — council-20260822T071008Z-058099e0 — anomaly/instruction_in_evidence — 464.296s

ANOMALY: instruction_in_evidence
CLAIM: The evidence embeds reviewer-directed imperatives: “Attack my AMENDMENT-now recommendation”, “Compute the minimum corpus size”, “Construct the concrete reconciliation”, “Propose the one fault-injection test”, “Specify a falsifiable independence criterion”, and “Attack this proxy”.
CITE: GIGA_PLAN_2026-08-22.md, Dissent first item: “Every council lens carried a for_codex array of reviewer-directed imperatives ('Attack my AMENDMENT-now recommendation', 'Compute the minimum corpus size', 'Construct the concrete reconciliation', 'Propose the one fault-injection test', 'Specify a falsifiable independence criterion', 'Attack this proxy')”
CHECK: Scan all evidence fields for quoted imperative clauses or `for_codex`; fail ingestion when any occur outside a separately stripped questions field.

CLAIM: Phase 0b cannot run concurrently from its start because its first action depends on a byte-identity result produced by Phase 0.
CITE: “Phase 0b - Line-neutral research pre-registration (concurrent with Phase 0/1)” and “Precondition from Phase 0: LATENT_CEILING_SHARED_REPRESENTATION.md and runs/higher_twin_nc/SPEC.md are byte-identical on both lines or exist on exactly one”
CHECK: Make every Phase-0b writer refuse unless the Phase-0 research-asset census contains a source-SHA-stamped passing identity verdict.

CLAIM: Phase 1 tags the losing tip before directing a HANDOFF banner change, which either creates a commit after the frozen tag or leaves the tagged line without the required banner.
CITE: “git tag frozen/<branch>-2026-08-<dd> on its tip” followed by “Prepend a banner to its HANDOFF top block and its memo”; Done when requires “zero commits after it”.
CHECK: After Phase 1, assert `git rev-parse <frozen-tag>^{commit}` equals the losing branch tip and that the banner blob is reachable from that same commit.

CLAIM: D3 is not an enforced dependency of Phase 2 even though Phase 2 immediately executes the manifest whose owner ruling D3 is supposed to govern.
CITE: Phase 1 Done when lists “D1, D2, D6, D7”; D3 is “harvest manifest approval”; Phase 2 says “Work the Phase-0 harvest manifest row by row”.
CHECK: Fail the first Phase-2 port commit unless its ancestry contains a signed D3 record naming the exact manifest SHA-256.

CLAIM: Running Phase 3 in parallel with Phase 4 can invalidate Phase 4’s exact-head census because Phase 3 changes the scanner, registry, loop routing, and egress code on which Phase 4’s counters depend.
CITE: “Phase 3 - Trunk quick wins… (parallel with Phase 4)” and Phase 4: “Re-run the exact-head census at the post-harvest head”; Phase 3 includes “Fix the v3 repository-write scanner crash” and “Add SECRETS effect rows”.
CHECK: Require the stamped Gate-0 source revision to contain the final Phase-3 scanner, SECRETS, loop-registration, and egress commits, then rerun every counter at that exact SHA.

CLAIM: D9’s scanner schema decision is scheduled in Phase 4 even though Phase 3’s first action already depends on deciding scanner option A.
CITE: Phase 3: “owner decides option A schema bump”; D9: “Linux host/CI… and the v3 scanner option A schema bump”; Phase 4 contains D9.
CHECK: Assert the signed D9 schema ruling predates the first post-fix v3 report commit and that the report declares the selected schema version.

CLAIM: D16a is sequenced too late because the owner-co-signed threshold protocol must predate all labels, while the protocol is written in Phase 0b and D16 is handled in Phase 7a.
CITE: D16(a): “co-signed as a hashed protocol committed BEFORE any label is revealed”; Phase 0b: “Commit the ceiling protocol BEFORE opening any corpus item”; Phase 7a: “owner approves the threshold protocol”.
CHECK: Verify that the signed D16a record and its protocol hash are ancestors of every commit containing a ceiling label.

CLAIM: Phase 7a cannot satisfy its seven-baseline calibration criterion before Phase 7b supplies baseline (d), the read-and-write footprint tracer.
CITE: Phase 7a Done when: “calibration report lists all seven baselines”; Phase 7a baseline “(d) read+write footprint from the Phase-7b tracer - PRIMARY kill”.
CHECK: Fail the Phase-7a calibration receipt unless the Phase-7b tracer commit is an ancestor and baseline `d` contains measured predictions for every evaluated pair.

CLAIM: Phase 5 moves the entire round2 directory before Phase 8 tries to stamp a file at its old round2 path.
CITE: Phase 5: “Move… docs/research/rounds/round1+round2… to docs/archive/swarm-2026-07-30/”; Phase 8: “Stamp docs/research/rounds/round2/v-embeddings.md”.
CHECK: After the Phase-5 move, run `git ls-files --error-unmatch docs/research/rounds/round2/v-embeddings.md`; the Phase-8 action fails unless it is retargeted to the archived path.

CLAIM: Phase 8 mandates `daedalus brief` through a skill before the comparison that is supposed to determine whether it becomes the crew default.
CITE: “a thin repo skill requiring it before write-touching work” appears before “Before making brief+Serena the crew default: frozen, independently authored task set (>= 20 tasks…)”.
CHECK: Reject any mandatory-skill commit whose parent lacks a passing, source-SHA-stamped ≥20-task comparison receipt.

CLAIM: Phase 0 requests a “freshness-refusal fraction” from only one loop iteration, leaving a denominator of one that cannot characterize a rate.
CITE: “wrap `python -m daedalus.loop` (one iteration…)” and “record the fraction of iterations the picker refuses solely on freshness”.
CHECK: Require the receipt to expose integer numerator and denominator and fail rate claims when `iterations_total <= 1`.

CLAIM: Phase 0b’s claim that no corpus item was opened is not machine-checkable because a parent-commit relation proves commit order, not what an author previously read.
CITE: “Ceiling protocol committed with its sha256 recorded and no corpus item opened yet (parent-commit check passes)”.
CHECK: NONE

CLAIM: Phase 2’s aggregate suite-count criterion can pass while previously passing tests regress if new or duplicated passing tests offset them.
CITE: “survivor full suite count >= Phase-0 baseline with 0 new failures”.
CHECK: Compare baseline and survivor test node IDs; fail if any baseline passing node is absent, skipped, xfailed, or failing, regardless of aggregate totals.

CLAIM: Phase 3 can be declared done with a nonfunctional loop merely by writing a blocker JSON, so its exit criterion is explicitly satisfiable by the broken state.
CITE: “either (a) one `daedalus loop` iteration passes… or (b) runs/loop/blocker_<sha>.json names the exact blocker”.
CHECK: If branch `(b)` is selected, require Phase 3 status `blocked` rather than completed; only a passing branch `(a)` may satisfy functional completion.

CLAIM: “SECRETS rows >= 4” measures registry labels rather than whether credential-bearing execution is contained.
CITE: Phase 3 Done when: “SECRETS rows >= 4”; action: “Add SECRETS effect rows to the registry for the four provider rows”.
CHECK: For each of the four rows, execute a credential-bearing fault case and assert denial occurs before subprocess or socket creation with a signed receipt.

CLAIM: Phase 4’s `closed:true` result is circular because the same phase changes the scanner schema, reporter predicate, accepted inventory categories, and then uses that reporter as the denominator and verdict authority.
CITE: “blocker-ize LOCAL_GUARDS/non-CENTRAL rows in the closed predicate… or amend the plan”; “v3 scanner option A schema bump”; Stamp: “daedalus.gates report… closed:true”.
CHECK: Recompute the Phase-4 evidence with a hash-pinned verifier frozen before Phase-4 implementation changes and fail on any verdict disagreement.

CLAIM: Allowing `inventory_only=0-or-owner-accepted-with-record` permits Gate 0 to close without demonstrating containment for the surviving doors.
CITE: Phase 4 Done when: “inventory_only=0-or-owner-accepted-with-record”.
CHECK: Independently fault-inject every surviving door under exhausted budget and kill switch; require fail-closed behavior and a receipt before counting it toward closure.

CLAIM: The Gate-1 checker’s claimed epistemic independence is not machine-checkable because Git cannot establish that its author “never reads checks.py”.
CITE: “authored… by an author who never reads checks.py”.
CHECK: NONE

CLAIM: The higher_twin_nc confirmation phase has no numeric confirmation predicate, so any result that avoids the “no reproducible… on >= 4 fixtures” kill can be called confirmed.
CITE: Done when: “H-NC-cal adjudicated (confirmed or killed…)”; kill: “no reproducible behavioural non-commutation on >= 4 external fixtures”.
CHECK: Fail `status=confirmed` unless the frozen spec contains and the receipt satisfies an explicit minimum fixture count, nonzero-pair count, effect threshold, and confidence bound.

CLAIM: Phase 7b’s “dated negative result” alternative can finish corpus work without four external fixtures even though the plan separately permits from-scratch features when no backbone can be attested.
CITE: “>= 4 external fixtures replayed (or a dated negative result explaining why no backbone can be attested)” and “otherwise from-scratch features only”.
CHECK: Require ≥4 external fixture receipts for H-NC adjudication regardless of whether pretrained backbones are excluded.

CLAIM: Phase 8’s adoption percentage lacks a machine-defined denominator for “write-touching sessions” and is therefore gameable by session splitting or omission.
CITE: “command appears in > 50% of write-touching sessions over the first 2 weeks”.
CHECK: Require an append-only session census listing every unique session ID, detected write intent, and brief-call count, then recompute `brief_sessions/write_touching_sessions`.

CLAIM: Phase 8’s kill rule has no minimum effect or confidence requirement, so a one-token improvement across 20 tasks satisfies “reduce”.
CITE: “if brief+Serena does not reduce tokens-per-verified-gate-passing-write… over >= 20… tasks”.
CHECK: Fail unless a pre-run protocol specifies a minimum useful paired effect and the resulting confidence interval clears that threshold.

CLAIM: The header’s claim that 93 dissents were carried is not auditable because the dissent list aggregates multiple seats and multiple numbered dissents without a 93-item identity-to-disposition mapping.
CITE: “93 dissents carried verbatim-or-tighter”; examples include “[codex seats 1-5…]” and “[Lens C dissents 0, 1, 2, 3, 4 - carried intact]”.
CHECK: Parse the five source reviews into unique `(review, dissent-id)` records and require exactly 93 one-to-one mappings to a plan action, criterion, refusal, or explicitly unresolved item.

CLAIM: D3 is a fake decision because it specifies manifest ratification but supplies no alternative disposition or measurable choice.
CITE: “D3: harvest manifest approval, explicitly including the BIDIRECTIONAL research port…”
CHECK: Validate the decision schema and fail D3 unless it contains at least two materially different executable options and consequences.

CLAIM: D6 is a fake decision because the plan supplies only the write-intent match rule as admissible and calls the alternative an ongoing defect.
CITE: “D6: guard match rule amendment - enforce protected-artifact protection on write intent, not literal path substrings”.
CHECK: Validate that D6 contains at least two testable match-rule options with separate false-positive and bypass measurements.

CLAIM: D14 is a fake decision because both its title and Phase 5 prescribe refusal rather than presenting a choice.
CITE: “D14: refuse re-minting…” and “Re-minting the eval tasks… is refused”.
CHECK: Parse D14’s options; fail the decision record if every option yields `remint=false`.

CLAIM: D16f is a fake decision because Phase 7a cannot finish unless the owner signs the already-fixed refusal.
CITE: D16(f): “sign the refusal record”; Phase 7a Done when: “refusal doc owner-signed”.
CHECK: Parse D16f and fail if it lacks an admissible unsigned alternative with defined downstream state.

CLAIM: D18 is a declaration rather than a decision and is not scheduled before either measurement whose environment it is meant to qualify.
CITE: “D18: Linux/CI host class and hardware declaration for the cold-start measurement and the fault run”.
CHECK: Require a signed environment manifest hash to predate both the first cold-start sample and every Linux fault receipt.

CLAIM: D5 omits owner-level values for signer authorization, revocation source, approval freshness, and replay-state retention even though its seven tests depend on those policies.
CITE: D5 selects “option B… option A… or hybrid” while requiring “signer authorization, replay prevention, revocation, artifact binding”.
CHECK: Fail the D5 record unless it fixes machine-readable signer allowlist, revocation authority, maximum age, artifact-binding fields, replay key, and replay retention.

CLAIM: D11 is missing from the executable phase schedule because Phase 3 says it is not done there and no later Done-when requires its ruling.
CITE: “the real hook is owner decision D11… and is NOT done here”; D11 is “post-commit map-regeneration hook… vs in-loop regeneration only”.
CHECK: Search all phase prerequisites and Done-when records for D11; fail the plan DAG if no phase consumes a signed D11 result.

CLAIM: D17 is sequenced after evidence that no phase is assigned to produce, because shim deletion is mentioned in Phase 2 but deferred until after the later Phase-4 census, scan, and shim-absent suite.
CITE: “Shim deletion happens only on the survivor (owner decision D17) after the Phase-4 census plus a scan… and a full-suite run”.
CHECK: Require explicit DAG nodes for the scan, clean wheel/import audit, shim-absent suite, D17 record, and deletion in that order.

CLAIM: The first 48 hours should begin with head pinning, ancestry/count checks, chain validation, and both fence probes because these are fast fatal gates that can invalidate the planned ruling path.
CITE: Phase-0 actions beginning “Pin both heads”; kill criteria: “if either chain fails…” and “if both worktrees can produce competing protected revisions… the ruling waits”.
CHECK: Require source-SHA-stamped branch-graph, chain, and two fence receipts before scheduling any tree mutation.

CLAIM: The two exact-head full suites should start immediately in parallel with reachability and trust-root probes because their results directly constrain D1 and D5 while the suites consume wall time.
CITE: D1 uses “exact-head census… one-kernel reachability, trust-root suite with canary”; Phase 0 specifies identical full suites on both heads.
CHECK: Verify job timestamps show both suites, reachability, and trust-root runs started against the pinned SHAs before any of them completed.

CLAIM: The bidirectional harvest manifests should follow the fatal chain and fence checks but still precede D1 so either ruling has a measured stranding cost.
CITE: “Nothing is frozen before both manifests exist” and D1’s package includes “harvest manifests both directions”.
CHECK: Require every pinned checkpoint-only commit and every enumerated reverse research asset to have a nonpending disposition before accepting a D1 record.

CLAIM: Phase-0 loop tracing, all Phase-0b research authoring, and Phase-3 code changes should be cut from the ruling-critical first-48-hour queue because none appears in D1’s enumerated evidence package.
CITE: D1 enumerates “chain validity, fence receipts, exact-head census… one-kernel reachability, trust-root suite… harvest manifests both directions”; Phase 0b is research pre-registration and Phase 3 is “Trunk quick wins”.
CHECK: Until the D1 package is complete, fail the work log if coordinator capacity is charged to novelty-table prose, ceiling labels, tracer implementation, watchdog changes, retrieval telemetry, or Phase-3 mutations.

CLAIM: The plan softens seat 5’s cold-start requirement from 200 samples to 100 in both the Phase-3 action and Phase-8 exit criterion.
CITE: Dissent: “N >= 100 (seat 5: 200)”; Phase 8 Done when: “cold-start receipt with N >= 100”.
CHECK: Count valid cold-start rows and fail the carried-seat-5 claim when `N < 200`.

CLAIM: The plan drops the requirement to trace effects in loop grandchildren because it logs subprocess creation but never requires audit instrumentation inside spawned descendants.
CITE: Dissent: “the Phase-3 tracer must include grandchildren”; Phase 0 tracer uses “sys.addaudithook… /subprocess/socket”; Phase 3 only says “Verify with the Phase-0 filesystem-write tracer”.
CHECK: Run a fixture where a WaveExecutor grandchild writes before installing its guard and require the central trace to identify and fail that child write.

CLAIM: The plan softens the default-change dissent by installing a skill that requires `daedalus brief` before the ≥20-task comparison has passed.
CITE: Dissent: “a default change follows a >= 20-task frozen comparison”; Phase 8 first action: “a thin repo skill requiring it before write-touching work”.
CHECK: Compare commit ancestry and fail if the mandatory skill commit predates the passing comparison receipt.

CLAIM: The plan drops seat 4/5’s exhaustive protected-policy-divergence gate because Phase 0 has no required byte-level diff covering every protected artifact across the two pinned heads.
CITE: Dissent: “trunk eligibility fails on any… unaccounted protected-policy difference” and “no unresolved protected-file divergence before any ruling”; Phase-0 package lists chains, fences, censuses, reachability, trust roots, loop trace, manifests, and research census.
CHECK: Diff every path in the protected-artifact allowlist between both pinned SHAs and fail D1 if any changed blob lacks an explicit package disposition.

CLAIM: The shim-removal plan softens the clean-environment test by omitting the requested wheel build and explicit import auditing.
CITE: Dissent: “the cheapest test is the wheel build in a clean environment plus a full suite with import auditing”; Phase 2 requires only “a full-suite run in a temp worktree with the shims absent” plus scans.
CHECK: Build and install the wheel in a fresh environment, enable import tracing, run the full suite, and fail D17 if any removed shim is imported or packaged.

CLAIM: The plane-mode tensor arm drops graph_brief from the explicitly requested equal-budget baseline set.
CITE: Dissent requires comparison against “Tucker/mode-tagged, flat concat, BM25 and graph-brief”; Phase 7c specifies “Tucker / mode-tagged Node Cards vs flat concat” with hub stripping and rewiring.
CHECK: Fail arm activation unless the frozen spec contains equal-budget result rows for Tucker/mode-tagged, flat concat, BM25, and graph_brief on the same split.

CLAIM: The open dissent about graph_brief truncation on a repository ten times larger is carried only as prose and is not made a gate before shipping the CLI and mandatory skill.
CITE: Dissent: “whether truncation-honesty survives on a repo 10x this size is unmeasured”; Phase 8 immediately adds `daedalus brief` and “a thin repo skill requiring it”.
CHECK: Run a 10× symbol-layer fixture and fail rollout if required symbols are omitted without an explicit truncation receipt or if task accuracy breaches a predeclared bound.

# SEAT 5 — role falsifier — council-20260822T071753Z-9c4a3859 — anomaly/instruction_in_evidence — 411.791s

ANOMALY: instruction_in_evidence
CLAIM: The evidence contains reviewer-directed imperatives: “Attack my AMENDMENT-now recommendation”, “Compute the minimum corpus size”, “Construct the concrete reconciliation”, “Propose the one fault-injection test”, “Specify a falsifiable independence criterion”, and “Attack this proxy”.
CITE: GIGA_PLAN_2026-08-22.md, Dissent: “[codex seats 1-5, process anomaly: instruction_in_evidence] Every council lens carried a for_codex array of reviewer-directed imperatives...”
CHECK: NONE

CLAIM: Phase 0b cannot commit artifacts concurrently while Phase 0 keeps checkpoint pinned at 3e758392 and derives a manifest from that pinned history containing those new artifacts.
CITE: “Pin both heads for the whole phase: checkpoint = 3e758392”; Phase 0b: “concurrent with Phase 0/1” and “all of these appear as rows on the Phase-0 harvest manifest.”
CHECK: For every Phase-0b artifact, run `git merge-base --is-ancestor $(git log -1 --format=%H -- <artifact>) 3e758392`; any nonzero result proves the pinned manifest cannot contain its introducing commit.

CLAIM: The pre-ruling write budget is internally inconsistent because Phase 0 permits exactly the memo and vault note while concurrent Phase 0b commits at least five additional document, test, receipt, and protocol paths on the checkpoint line.
CITE: Phase 0: “Exactly two tree writes are permitted in this phase”; Phase 0b: “Commit the ceiling protocol”, “Write ... TENSOR_PIVOT_NOVELTY_TABLE.md”, “RED tests first”, “Commit the external corpus selection protocol”, and “Write ... LATENT_CANONICAL_STATUS_REFUSAL.md.”
CHECK: Diff the checkpoint tree between Phase-0 start and finish and require the changed-path set to equal only `docs/decisions-pending/FORK_PRERULING_2026-08-22.md` plus the named vault note.

CLAIM: Phase 1 freezes and tags the losing tip before instructing a HANDOFF and memo banner write, so committing those banners necessarily creates commits after the supposedly final frozen tag.
CITE: Phase 1: “git tag frozen/<branch>-2026-08-<dd> on its tip” followed by “Prepend a banner to its HANDOFF top block and its memo”; Done when: “zero commits after it.”
CHECK: Resolve the frozen tag, then run `git log --format=%H <tag>..losing-branch -- HANDOFF.md '*FORK_PRERULING*`; any banner commit violates the criterion.

CLAIM: Phase 6a is positioned after the Phase-4 stamp even though it is explicitly required to run before that stamp, creating a dependency cycle under the document’s phase order.
CITE: Phase 4 action “Stamp”; later Phase 6a title: “after D1 and before the stamp”; Phase 6a preconditions: “before the Gate-0 stamp.”
CHECK: Build a DAG with document-order edges and the explicit edge `Phase-6a -> Phase-4-stamp`; a topological sort must fail.

CLAIM: Phase 7b may start immediately after Phase 2 while the embedding-egress prerequisite is only delivered in Phase 3, allowing external-corpus work involving a backbone before denial-before-connect is proven.
CITE: Phase 7b: “starts right after Phase 2 port”; Phase 3: “Close the embedding egress gap BEFORE any new embedding consumer or experiment”; kill criterion: “if the embeddings backend cannot be made to deny before socket connect, no latent experiment starts.”
CHECK: Require a dependency edge from the passing egress-test commit to every Phase-7b run commit and fail if any Phase-7b commit is not its descendant.

CLAIM: Phase 2 can begin manifest-driven ports without a recorded D3 ruling because Phase 1’s exit gate names D1, D2, D6, and D7 but omits D3.
CITE: Phase 1 Done when: “D1, D2, D6, D7 each have a written owner ruling”; Phase 2: “Work the Phase-0 harvest manifest row by row”; D3: “harvest manifest approval.”
CHECK: Require the signed D3 record hash to be an ancestor of the first Phase-2 port commit.

CLAIM: D18 is required for Phase-3 cold-start and Phase-4 fault evidence but has no phase action, exit criterion, or timing that guarantees it precedes either measurement.
CITE: D18: “Linux/CI host class and hardware declaration for the cold-start measurement and the fault run.”
CHECK: Run `rg -n '\bD18\b' GIGA_PLAN_2026-08-22.md`; fail if no precondition or Done-when reference exists outside the Owner-decisions entry.

CLAIM: Phase 8 installs a skill “requiring” brief before write-touching work before the comparison that is supposed to decide whether brief becomes the default.
CITE: Phase 8: “a thin repo skill requiring it before write-touching work”; later: “Before making brief+Serena the crew default: frozen ... comparison.”
CHECK: Compare commit ancestry and require the comparison receipt to predate any skill or settings commit that mandates `daedalus brief`.

CLAIM: Phase 0b’s “no corpus item opened yet” criterion is not established by a parent-commit check because commit ancestry proves write ordering, not whether an author previously read the corpus.
CITE: Phase 0b Done when: “Ceiling protocol committed ... and no corpus item opened yet (parent-commit check passes).”
CHECK: NONE

CLAIM: Phase 0b can satisfy its threshold exit criterion without measuring any input by writing the literal fallback “CONVENTION 15%, un-derived.”
CITE: Phase 0b Done when: “threshold either derived ... or labelled ‘CONVENTION 15%, un-derived’ verbatim.”
CHECK: Set all three measurement fields absent, retain the fallback literal, and run the proposed Done-when validator; passing demonstrates no-op satisfiability.

CLAIM: The derived threshold is circular because the plan author declares C_exp and selects the experiment budget while using that author-controlled value as the formula’s numerator.
CITE: “p_b* = C_exp / (N_f x V_f) with C_exp = declared budget of one registered latent experiment.”
CHECK: Hold N_f and V_f fixed, vary only the declared budget, and verify that the go threshold can be moved arbitrarily without new observations.

CLAIM: Phase 2’s “63/63 green” criterion conflicts with its required inclusion of newly committed RED read-tracer tests whose implementation does not land until Phase 7b.
CITE: Phase 0b: “read-footprint tracer has RED tests committed”; Phase 2: “the Phase-0b read-tracer RED tests” and “63/63 green”; Phase 7b: “Land the Phase-0b read-footprint tracer (RED tests first, then green).”
CHECK: At the Phase-2 candidate commit, collect targeted test node IDs and require every new RED test to be collected; either one fails or the claimed 63/63 excludes the required tests.

CLAIM: Phase 2’s suite-count criterion can be satisfied after deleting coverage because it compares only aggregate counts rather than requiring preservation of baseline test identities.
CITE: Phase 2 Done when: “survivor full suite count >= Phase-0 baseline with 0 new failures.”
CHECK: Compare collected node-ID sets and fail unless every Phase-0 node ID remains present, independent of the total count.

CLAIM: Phase 4 permits all surviving inventory-only doors to remain unchanged while still declaring closed:true if the owner supplies acceptance records.
CITE: Phase 4 Done when: “inventory_only=0-or-owner-accepted-with-record”; action D4: “accept-with-recorded-justification or wire.”
CHECK: Keep the registry code hash unchanged with 13 inventory-only rows, add acceptance records, and run `assert_gate_report`; a zero exit demonstrates no-op closure.

CLAIM: Phase 6a’s claim that an author “never reads checks.py” is not machine-checkable from separate authorship, blob order, module sharing, or a checker diff.
CITE: Phase 6a: “authored ... by an author who never reads checks.py”; independence criterion lists “separate authorship + blob sha predating operator code + shared-module check + attached diff.”
CHECK: NONE

CLAIM: Phase 7b’s corpus exit criterion is satisfiable without replaying any external fixture by filing a dated explanation that no backbone can be attested.
CITE: Phase 7b Done when: “>= 4 external fixtures replayed (or a dated negative result explaining why no backbone can be attested).”
CHECK: Supply a dated negative-result file with zero manifest fixtures and run the Done-when validator; passing proves the alternative is a no-run exit.

CLAIM: Phase 8’s greater-than-50-percent adoption criterion is circular because neither the raw session denominator nor an independent classifier for “write-touching sessions” is specified.
CITE: Phase 8 Done when: “the command appears in > 50% of write-touching sessions over the first 2 weeks.”
CHECK: Require a raw immutable session census and recompute numerator and denominator with a separately versioned write-touch classifier; absent either input, fail the criterion.

CLAIM: D6 and D7 are fake decisions because both entries prescribe a single amendment outcome rather than presenting two admissible policies.
CITE: D6: “enforce protected-artifact protection on write intent, not literal path substrings”; D7: “lands with D6 to stop the CRLF pin daemon.”
CHECK: Parse each decision entry for an explicit option set and fail unless it contains at least two mutually exclusive outcomes.

CLAIM: D14 is a fake decision because its entry already commands refusal and fixes HANDOFF’s fate.
CITE: “D14: refuse re-minting ... HANDOFF freezes with a top pointer.”
CHECK: Apply an owner-decision schema requiring at least two admissible outcomes; D14 has only the prescribed refusal.

CLAIM: D17 is a fake decision and an unassigned action because it prescribes deletion after specified checks but no later phase actually performs that deletion.
CITE: “D17: shim deletion ... after the ... scan and a shim-absent full-suite run”; Phase 2: “Shim deletion happens only on the survivor ... after the Phase-4 census.”
CHECK: Search phase Actions after Phase 4 for an operation deleting the six shims and require its commit to descend from a D17 record; no matching action proves the gap.

CLAIM: D16f is a fake decision because signing the refusal is mandatory for Phase 7a completion and no non-signing branch is defined.
CITE: D16(f): “sign the refusal record”; Phase 7a Done when: “refusal doc owner-signed.”
CHECK: Remove the signature and run the Phase-7a completion check; if completion necessarily fails with no alternative outcome, D16f is ratification rather than a choice.

CLAIM: D16a is sequenced after the evidence it must precede because Phase 7a orders the ceiling run before the later owner action while D16 says the protocol must be co-signed before any label is revealed.
CITE: Phase 7a first action: “Run the ceiling classification”; final action: “owner approves the threshold protocol”; D16(a): “co-signed as a hashed protocol committed BEFORE any label is revealed.”
CHECK: Require the signed protocol commit to be an ancestor of every label-bearing ceiling commit.

CLAIM: D2 decides where docs and vault live only after Phase 0 and Phase 0b have already written those artifacts to the checkpoint line.
CITE: Phase 0 writes the memo “on the checkpoint line” plus “the vault/Sessions note”; Phase 0b commits documents “on the checkpoint line”; D2 later decides “where docs+vault live.”
CHECK: Compare the first artifact commit timestamps with the signed D2 record and fail if any destination-dependent write predates D2.

CLAIM: The missing pre-ruling owner decision is whether the acknowledged exception for Phase-0b checkpoint commits is permitted at all.
CITE: Merged-plan self-dissent: “if the owner rules that exception unacceptable, those files move to the scratchpad and the vault until Phase 2”; no D1-D18 entry assigns that ruling before the writes.
CHECK: Search D1-D18 for an option governing the pre-ruling-write exception and require its signed record to predate every Phase-0b commit.

CLAIM: The first 48 hours should begin with ancestry and chain validation, fence attempts, exact-head reporter execution, and one-kernel reachability because each can immediately remove a canonicalization option under the stated kill criteria.
CITE: Phase-0/1 kill criteria: chain failure stops reconciliation, fence failure makes the ruling wait, reporter failure removes g0-as-is, and dual-kernel reachability bars Rev 6 without amendment.
CHECK: Require timestamps for `chain_report`, both fence receipts, reporter exit, and reachability report to precede every research-authoring or documentation receipt.

CLAIM: The trust-root canary should run only after reachability determines whether the live promotion path reaches approvals.py, otherwise it measures an unwired candidate implementation rather than the operative authority.
CITE: Phase 0 `preruling_onekernel`: “whether promote_candidates reaches kernel/approvals.py:732/767 at all”; dissent: checkpoint verifier has “zero production callers” and threat depends on reachability plus secret visibility.
CHECK: Enforce a workflow dependency requiring the reachability report hash as an input to `trust_root_report.json`.

CLAIM: Phase-0b novelty writing, OpenAlex queries, corpus protocol authoring, and the Phase-3 cold-start campaign should be cut from the first 48 hours because none appears in D1’s ruling package or its hard kill criteria.
CITE: D1 enumerates “chain validity, fence receipts, exact-head census ... one-kernel reachability, trust-root suite ... harvest manifests”; Phase 0b and Phase 3 list the unrelated novelty, corpus, and cold-start work.
CHECK: Time-box the first 48-hour queue and fail scheduling if any cited research or cold-start task starts before all D1 package receipts exist.

CLAIM: The only Phase-3 mutation worth starting in the first 48 hours is the scanner repair after reproducing the crash and selecting the survivor, because every later Gate-0 counter depends on scanner_error=0.
CITE: Phase 3: “Fix the v3 repository-write scanner crash ... First, because every later counter depends on scanner_error=0.”
CHECK: Require a failing exact-head scanner receipt and signed survivor ruling as parents of the scanner-fix commit.

CLAIM: The plan softened the first-round demand that both lines stop changing before D1 by deliberately committing the memo and Phase-0b artifacts on the checkpoint line.
CITE: Dissent: “[codex seat 3] Both lines should first stop changing”; merged-plan self-dissent: pre-ruling commits are “a deliberate exception to ‘no tree writes before D1’.”
CHECK: Run `git rev-list --count 3e758392..checkpoint/2026-07-20-session` at D1; any positive count is the softened behavior.

CLAIM: The plan softened seat 5’s cold-start requirement from 200 observations to an exit gate of only 100.
CITE: Dissent: “N >= 100 (seat 5: 200)”; Phase 3 Done when: “cold-start run has >= 100 rows”; Phase 8 Done when: “N >= 100.”
CHECK: Create exactly 100 valid rows and run the Phase-3 and Phase-8 completion checks; passing demonstrates the seat-5 threshold was dropped.

CLAIM: The novelty lint dropped seat 5’s required site, stalk, restriction-map, tensor-product, falsifying-outcome, and executable-counterexample fields.
CITE: Dissent: “seat 5 adds: site, stalks, restriction maps, tensor product, observable prediction, falsifying outcome + an executable counterexample fixture”; Phase 0b lint requires only `{objects, morphisms_or_maps, tensor_operation, observable, baseline, sealed_evaluator, kill_criterion}`.
CHECK: Construct a row containing only the seven implemented fields and run the 20-line lint; passing proves the seat-5 fields are unenforced.

CLAIM: The plan softened the dissent requiring no unresolved protected-file divergence before D1 because the nine-receipt package has no complete protected-file diff receipt.
CITE: Dissent: “[codex seat 5] ... no unresolved protected-file divergence before any ruling”; Phase 0 decision package enumerates chain, fence, census, reachability, trust-root, loop, harvest, and research-census receipts.
CHECK: Compare all protected-path blob hashes at the two pinned heads and require every difference to appear with an explicit disposition in the D1 package.

CLAIM: The requirement to trace grandchildren was carried in prose but dropped from Phase 3’s enforceable exit criteria, which mention only effects before the parent’s install_process_guard observation.
CITE: Dissent: “the Phase-3 tracer must include grandchildren”; Phase 3 Done when: “zero effects before install_process_guard in the trace.”
CHECK: Spawn a grandchild that writes before installing its own guard and run the Phase-3 tracer; if the Done-when check still passes, the dissent was dropped.

CLAIM: The shim-deletion safeguard was softened by omitting the requested clean wheel build with import auditing.
CITE: Dissent: “the cheapest test is the wheel build in a clean environment plus a full suite with import auditing”; Phase 2 requires only scans and “a full-suite run in a temp worktree with the shims absent.”
CHECK: Search the D17 evidence bundle for a wheel-build receipt and import-audit log and fail if either is absent.