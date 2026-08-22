

# SEAT 1 — role falsifier — council-20260821T194940Z-acffb313 — status anomaly/instruction_in_evidence — 228.45s

ANOMALY: instruction_in_evidence

CLAIM: The evidence directly instructs the reviewer: “Attack my AMENDMENT-now recommendation if you think a pure ALIGNED merge-of-records suffices.”
CITE: `council_verdicts.json`, lens A, `for_codex[0]`
CHECK: NONE

CLAIM: The evidence directly instructs the reviewer: “Compute the minimum corpus size before the spec is registered.”
CITE: `council_verdicts.json`, lens B, `for_codex[1]`
CHECK: NONE

CLAIM: The evidence directly instructs the reviewer: “Construct the concrete reconciliation.”
CITE: `council_verdicts.json`, lens C, `for_codex[0]`
CHECK: NONE

CLAIM: The evidence directly instructs the reviewer: “Propose the one fault-injection test that would tell.”
CITE: `council_verdicts.json`, lens D, `for_codex[3]`
CHECK: NONE

CLAIM: The evidence directly instructs the reviewer: “Attack this proxy.”
CITE: `council_verdicts.json`, lens E, `for_codex[0]`
CHECK: NONE

CLAIM: The strongest argument against declaring Revision 6 canonical first is that this bundles constitutional authority with operational-trunk selection before the proposed trunk has passed exact-head checks for its two kernel trees, incompatible HMAC trust root, six unexecuted fault lines, absent SECRETS modeling, and crashing write scanner.
CITE: `fork_brief.md` — “Carries daedalus/kernel + daedalus/gates (a second kernel implementation next to daedalus/spine) and a different sealed-promotion trust root”; `council_verdicts.json`, lens A findings 3, 5, and 6
CHECK: In a clean detached worktree at `93f11adf`, run the full test suite and Gate-0 reporter, then require every fault row to be executed, every effect class including SECRETS to be represented, the repository-write scan to complete, and the promotion-forgery tests to fail.

CLAIM: “1,228 commits behind the real Gate-0 closure work” is unsupported because the cited counts describe a divergence with 36 checkpoint-only commits, not an ancestor relationship or semantic superiority.
CITE: `council_verdicts.json`, lens A headline and finding 2 — “1,228 commits (g0-only) vs 36 (checkpoint-only)”
CHECK: Run `git merge-base --is-ancestor checkpoint/2026-07-20-session work/g0-trunk-20260817`; if it exits nonzero, the checkpoint is divergent rather than simply 1,228 commits behind.

CLAIM: Before any trunk ruling, the machine-verifiable constitutional facts are exact shared ancestry, internally consistent amendment sequences and plan hashes, and a write fence preventing either worktree from producing another competing protected revision during adjudication.
CITE: `fork_brief.md` — “Both lines claim the same Plan-ID” and “Both lines claim…sole-authority”; `council_verdicts.json`, lens C finding 1 — “Both chains share record 1…then diverge”
CHECK: Parse both JSONL ledgers, verify identical record 1, monotonic sequence/result revisions and each recorded result hash against its plan file, then attempt a protected-file write in both worktrees and require both attempts to fail.

CLAIM: The claimed “24/24 production-HMAC-signed” matrix cannot establish 24 executed fail-closed results while six rows are declared blocked.
CITE: `fork_brief.md` — “24/24 fault-matrix lines production-signed”; `council_verdicts.json`, lens A finding 5 — “the 6 declared-blocked fault-matrix lines need a Linux host/CI run”
CHECK: Parse the matrix and require all 24 rows to contain an executed status, observable injected fault, expected fail-closed outcome, exact commit identifier, and independently verified signature; fail on any declared-blocked row.

CLAIM: Freezing the checkpoint before producing a tested harvest manifest risks stranding 36 unique commits that include the serena-first amendment, vet-gate hardening, and a promotion verifier.
CITE: `council_verdicts.json`, lens A finding 2 and recommendation 5 — “36 (checkpoint-only)” and “tools/vet gate hardening + its 207 test lines…promotion_approval verifier, amendment-003 hook”
CHECK: Run a patch-ID comparison of checkpoint-only commits against `93f11adf`, apply each nonduplicate candidate to a disposable trunk worktree, and record whether its targeted and full tests pass.

CLAIM: The critical “one-kernel violation” is not proved by `ls` showing three directories because coexistence does not establish that both implementations are reachable from production entrypoints.
CITE: `council_verdicts.json`, lens A finding 2 — “ls agent_env_g0/daedalus shows gates+kernel+spine”
CHECK: Build an AST import graph rooted at every registered executable entrypoint and fail the invariant only if live paths reach both `daedalus.spine` and `daedalus.kernel`/`daedalus.gates`.

CLAIM: Deciding the 13 `INVENTORY_ONLY` rows “now” while scheduling the exact-head trunk census “next” reverses the necessary ordering because the evidence admits the audit ran entirely on the checkpoint and even the line of the 24/24 measurement is unclear.
CITE: `fork_brief.md` — “Tonight’s audit…ran ENTIRELY on the checkpoint line” and “measured on WHICH line is now unclear”; `council_verdicts.json`, lens A recommendations 2 and 5
CHECK: Run the effect-boundary census at `93f11adf` first and compare its row identifiers and justifications byte-for-byte with the alleged set of 13 before presenting any row for disposition.

CLAIM: Porting option B immediately is under-supported because the cited checkpoint verifier has zero production callers and no presented end-to-end evidence for signer authorization, replay prevention, revocation, or binding an approval to the promoted artifact.
CITE: `council_verdicts.json`, lens A finding 3 — “has zero production callers here”
CHECK: Run an adversarial promotion suite that attempts unsigned, wrong-signer, revoked-signer, replayed, artifact-substituted, and stale approvals and require every case to fail before wiring either trust root.

CLAIM: The docs councillor’s critical assertion that reconciliation “requires rewriting one history” is contradicted by its own append-only remedy, because the losing ledger can remain immutable while a new winning-chain record identifies it and reintroduces selected content.
CITE: `council_verdicts.json`, lens C finding 1 — “requires rewriting one history”; lens C recommendation 1 — “losing chain’s content re-enters as new amendments”
CHECK: Snapshot hashes of every existing ledger line, append one reconciliation record only to a disposable copy of the selected chain, and require every preexisting byte and hash to remain unchanged.

CLAIM: The missing `arch_memory` regeneration hook is mis-prioritized as critical because the cited picker already fails closed, making the demonstrated result unavailable ranking rather than wrong ranking.
CITE: `council_verdicts.json`, lens D findings 2 and 3 — “picker already fails closed on the stale map — the loop runs blind, not misled”
CHECK: Supply a deliberately stale `architecture-state.json` to `picker.py` and assert that it emits no ranked candidate and an explicit untrusted-map status.

CLAIM: The Serena timeout finding is not supported at critical severity by one 28.35-second cold-start measurement against a 30-second timeout when the evidence also says no inert-rate counter exists.
CITE: `council_verdicts.json`, lens E finding 2 — “28.35s cold vs 30s timeout” and “no counter anywhere measures deny/pass/inert rates”
CHECK: Run at least 100 clean cold starts under the tracked default configuration, record readiness and hook decisions, and compute the timeout and inert rates before and after prewarm.

CLAIM: Making the latent-ceiling classification a gate for every tensor proposal is too timid because that classification measures failure-corpus expressibility while the K experiment targets intervention-order prediction, and the evidence supplies no equivalence between those outcomes.
CITE: `council_verdicts.json`, lens B finding 1 and recommendations 1 and 4 — buckets “covered-by-brief / present-but-not-expressible / absent” versus “predict continuous K_behave”
CHECK: Extract the preregistered input, target, and success fields from both specs and require an explicit dependency mapping from ceiling bucket `(b)` to held-out K-prediction error; absent that mapping, the ceiling result cannot mechanically gate K.

CLAIM: The proposed 15% tensor-go threshold is a new policy choice rather than part of the cited preregistration.
CITE: `council_verdicts.json`, lens B recommendation 1 — “Pre-register the tensor-go threshold before the run (e.g. bucket-(b) >= 15%)”
CHECK: Run `rg -n "15%|tensor-go|operator|K_behave" docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md`; no matching preregistered threshold settles that it was added by the councillor.

CLAIM: The claim that measured noncommutation falsifies flat intervention embeddings is overbroad because only vector-offset composition is structurally forced to commute, and the reported nonzero K values come from author fixtures on which the experiment forbids effect claims.
CITE: `council_verdicts.json`, lens B findings 3 and 5 — “any intervention-as-vector-offset model predicts K identically 0” and “Messkonstruktionsregel forbids effect claims on author fixtures”
CHECK: Reproduce AB/BA on a preregistered external history corpus and compare vector-offset, whole-state/diff embedding with nonlinear readout, and footprint baselines on identical held-out pairs.

CLAIM: Registering a learned operator-embedding experiment now is too generous because roughly 40 pairs across four author fixtures, an all-zero fixture, fixture imbalance, and a backlog-only external corpus cannot support a stable held-out advantage claim.
CITE: `council_verdicts.json`, lens B finding 5 — “roughly 40 pairs over 4 author-written fixtures…chemlab is all-zero…history-replay corpus…backlog only”
CHECK: Run leave-one-fixture-out permutation testing against measured-footprint overlap and require a preregistered lower 95% confidence bound above zero; if that cannot be attained, keep the work at calibration-only corpus construction.

CLAIM: Refusing canonical or promotion-gating status to every latent space is evidence-supported until live probes, anchored freshness, and budget-equal ablations pass because the present latent route is measured at 0/5 production use and its index freshness is unanchored.
CITE: `council_verdicts.json`, lens B findings 6 and recommendation 7 — “0 of 5 live probes,” “freshness unanchored,” and “Refuse…any elevation…to canonical status”
CHECK: Add a policy test that fails whenever an embedding score affects promotion or defines a new canonical plane unless receipts show the ceiling run, anchored index identity, external-corpus evaluation, and superiority to frozen baselines.

CLAIM: The categorical vocabulary itself is literature-known rather than novel: fibrations, Čech obstruction/descent, lens laws, adjunctions, cellular sheaves, and sheaf neural networks are named existing frameworks.
CITE: `council_verdicts.json`, lens B finding 2 and recommendations 2 and 6 — “fibrations, Cech obstructions, descent, lens laws, adjunction residuals” and “Hansen-Ghrist cellular sheaves / sheaf NNs (Bodnar)”
CHECK: Against a dated OpenAlex snapshot, query each named construction and require the novelty table to store canonical prior-work identifiers before allowing any “novel” label.

CLAIM: Matrix and tensor embeddings are also occupied literature through RESCAL, DistMult, ComplEx, TuckER, RotatE, Smolensky tensor-product representations, CMSM, and DisCoCat.
CITE: `council_verdicts.json`, lens B recommendation 2 — “RESCAL/DistMult/ComplEx/TuckER/RotatE…Smolensky TPR, Rudolph-Giesbrecht CMSM, DisCoCat”
CHECK: Require the experiment spec to map every proposed mathematical operator to one named baseline and fail schema validation if an applicable baseline is omitted.

CLAIM: The only potentially novel element evidenced here is the repo-specific combination of sealed interventional K receipts with held-out operator-embedding prediction, but the evidence does not establish literature novelty for that combination.
CITE: `council_verdicts.json`, lens B headline and recommendation 4 — “operator-embedding K-predictor supervised by higher_twin_nc’s interventional commutators”
CHECK: Run a reproducible search over a pinned scholarly index for the conjunctions “operator embedding intervention order commutator prediction” and “noncommutative intervention embedding,” then store the complete query and result identifiers in the novelty table.

CLAIM: “Tensorized descent,” a “vector-stalk sheaf over the footprint site,” or a “tensor-product of two Node Cards” is word-salad risk until the spec defines its objects, maps, observable, baseline, and kill condition.
CITE: `council_verdicts.json`, lens B recommendations 2 and 6 — “what is the tensor-product of two Node Cards, measured how” and “Vector-stalk sheaf over the footprint site”
CHECK: Validate every proposal against a schema requiring `objects`, `morphisms_or_maps`, `tensor_operation`, `observable`, `baseline`, `sealed_evaluator`, and `kill_criterion`, and fail on any missing field.

# SEAT 2 — role security — council-20260821T195328Z-6aebeac3 — status anomaly/instruction_in_evidence — 216.735s

ANOMALY: instruction_in_evidence
CLAIM: The evidence contains a field addressed directly to this reviewer: “Attack my AMENDMENT-now recommendation if you think a pure ALIGNED merge-of-records suffices.”
CITE: council_verdicts.json, lens A, `for_codex[0]`
CHECK: Parse the JSON and fail evidence ingestion when any object contains a `for_codex` key.

CLAIM: An owner-authenticated authority record plus an enforced read-only losing line is the necessary first constitutional operation, but the evidence does not establish that g0 should become canonical before technical gates run.
CITE: fork_brief.md: “Both lines claim the same Plan-ID `daedalus-master-plan`”; “formally undecidable until the owner rules”; “audit ... ran ENTIRELY on the checkpoint line.”
CHECK: Require a machine-verifiable owner-signed authority record, validate its hash against the selected amendment chain, and test that protected artifacts on the losing branch deny writes.

CLAIM: The strongest argument against immediately selecting g0 is that it would canonize a promotion path whose symmetric HMAC secret lets any process able to read the verifier environment mint a verifying authorization.
CITE: council_verdicts.json, lens A finding “Sealed promotion ... two incompatible trust roots,” citing `kernel/approvals.py:732,767` and the environment-variable secret.
CHECK: In an isolated test, read the configured HMAC secret as an ordinary candidate process, mint a receipt for an unauthorized candidate, and require trunk verification to fail.

CLAIM: Before g0 can pass the trunk gate, commit `93f11adf` must show a clean trust-root test, 24 actually executed fault cases, a non-crashing repository-write scan, and a fresh census of executable, egress, and write entrypoints.
CITE: fork_brief.md: “24/24 ... measured on WHICH line is now unclear”; lens A findings citing six declared-blocked lines, `report.py:203-209`, the v3 `ValueError`, and `approvals.py:732/767`.
CHECK: Checkout detached `93f11adf` on Linux, run the fault matrix and write scanner, and fail unless all 24 rows have executed receipts, the scanner exits zero, and no promotion occurs without the selected trust root.

CLAIM: The “24/24 production-HMAC-signed” statement is not evidence that 24 fault cases ran because the same verdict says six cases remain declared-blocked.
CITE: council_verdicts.json, lens A findings “The council is auditing the stale line” and “What actually still blocks Gate-0 exit.”
CHECK: Parse the fault-matrix artifact and separately count statuses `executed` and `declared-blocked`; the executed count must equal 24 before “24/24” is emitted.

CLAIM: The exact outbound path identified by the evidence is the raw `urllib` POST at `daedalus/memory/embeddings.py:340-347`, which targets a caller-supplied host without `lane_for_host`.
CITE: council_verdicts.json, lens E finding “Wiring an embedding index ... unregistered egress-capable call.”
CHECK: Replace the HTTP transport with a recorder, submit a sensitive embedding request to a disallowed host, and require denial before any socket connection or request-body transmission.

CLAIM: The exact unguarded execution opening is the `loop.py` tail `if __name__ == '__main__': raise SystemExit(main())`, which bypasses the guarded CLI dispatch.
CITE: council_verdicts.json, lens D finding “daedalus.loop is an externally reachable spend/spawn/write entrypoint,” citing the quoted tail and `cli.py:1074`.
CHECK: Trace `python -m daedalus.loop` and fail if any subprocess, network call, spend action, or write occurs before `install_process_guard` is observed.

CLAIM: The recommendation to regenerate the architecture map before every pick opens a new automatic write path from the currently unregistered loop, so loop registration and containment must mechanically precede regeneration.
CITE: council_verdicts.json, lens D recommendations “before each pick, loop.py invokes ... `daedalus map` (`cli.py:1147`)” and “Register daedalus.loop.”
CHECK: Run the loop under a filesystem-write tracer and fail if the map generator opens any file for writing before the centralized guard is active.

CLAIM: The evidence does not identify the exact filesystem-open line that writes the architecture map or watchdog logs, so naming a more precise write sink than `cli.py:1147` or `.claude/watchdog/.../attempt-*.log` would be unsupported.
CITE: council_verdicts.json, lens D map-regeneration and watchdog findings.
CHECK: Instrument `open`, `Path.write_*`, `os.replace`, and `subprocess` during one map generation and one watchdog attempt, then emit source file and line for every write.

CLAIM: Councillor C’s critical claim that reconciliation “requires rewriting one history” is wrong because a new reconciliation record can be appended to the winning chain while retaining the losing chain as historical evidence.
CITE: council_verdicts.json, lens C finding “reconciling a fork ... requires rewriting one history,” versus lens A recommendation “append a reconciliation record ... Rollback-forward only, no history rewrite.”
CHECK: Run the amendment-chain validator after appending a new record referencing the winning tip plus the losing-chain digest; require all existing records to remain byte-identical.

CLAIM: Councillor A’s critical “one kernel is violated” finding is unsupported by its cited directory listing because coexisting `spine`, `kernel`, and `gates` directories do not prove that two kernels are reachable at runtime.
CITE: council_verdicts.json, lens A finding citing only “ls agent_env_g0/daedalus shows gates+kernel+spine.”
CHECK: Build a static-plus-dynamic import graph from every executable entrypoint at `93f11adf` and fail one-kernel discipline only if both implementations reach effectful runtime paths.

CLAIM: Councillor E’s critical Serena race claim is overstated because a measured 28.35-second cold start is below the stated 30-second timeout and no failure-rate or tail-latency distribution is cited.
CITE: council_verdicts.json, lens E finding “28.35s cold vs 30s timeout” and “no counter anywhere measures deny/pass/inert rates.”
CHECK: From a clean process state, run at least 100 cold starts with fixed hardware and fail the timeout gate only from the measured timeout fraction and pre-registered percentile threshold.

CLAIM: Councillor D’s critical “Registration is not routing” finding is unsupported as a security conclusion because registry label counts alone do not demonstrate different containment behavior.
CITE: council_verdicts.json, lens D finding citing one `CENTRAL`, two `UNGUARDED`, and approximately 41 `INVENTORY_ONLY` rows.
CHECK: Fault-inject the same forbidden subprocess, network call, and write through one entrypoint of each wiring class and compare actual deny behavior and receipts.

CLAIM: Councillor D’s critical missing-post-commit-hook finding is mis-prioritized because the cited picker already fails closed on stale maps, making this an availability defect unless a bypass is demonstrated.
CITE: council_verdicts.json, lens D findings citing `picker.py:1014-1036`: “reporting I have no trustworthy map beats ranking work from a tree that is gone.”
CHECK: Feed the picker a stale or dirty map and require it to return no ranked work and perform no downstream execution.

CLAIM: Councillor D’s critical producer-less-contract claim is only established for the checkpoint tree and cannot support trunk work until repeated at `93f11adf`.
CITE: council_verdicts.json, lens D finding citing checkpoint grep results; fork_brief.md: the audit ran entirely on the checkpoint line.
CHECK: At detached `93f11adf`, search imports and runtime construction of `MissionContract` and `EvidencePacket`, then execute the ignition dry run and inspect emitted artifact types.

CLAIM: Councillor D’s “delete the five zero-importer shims now” recommendation is mis-prioritized because static grep cannot exclude string imports, serialized module names, or external callers, and the checkpoint is proposed for read-only harvest.
CITE: council_verdicts.json, lens D shim finding and recommendation; lens A recommendation freezing the checkpoint to read-only harvest.
CHECK: Search tracked text and serialized fixtures for each fully qualified shim name, run the complete suite in a temporary copy with the shims absent, and compare import traces.

CLAIM: Councillor E’s raw embedding-host issue is under-prioritized as “next” because it is the clearest evidenced outbound-data path and must gate every latent experiment that could invoke the backend.
CITE: council_verdicts.json, lens E finding citing `embeddings.py:340-347`, plus recommendation “close the embedding egress gap before any new embedding consumer.”
CHECK: Make the embedding experiment gate depend on an egress test proving host policy enforcement and host-bound index identity.

CLAIM: The research councillor’s core sequence is sound: run the frozen ceiling classification first, keep learned representations experimental, and deny latent spaces canonical authority.
CITE: council_verdicts.json, lens B findings citing `LATENT_CEILING_SHARED_REPRESENTATION.md:40-54,111-119` and recommendation refusing canonical status.
CHECK: Hash the pre-run corpus and classification rubric, classify every item once into exactly one bucket, and permit one latent experiment only if the pre-recorded threshold is met.

CLAIM: The operator-embedding experiment is slightly too generous in timing because approximately 40 author-fixture pairs, an all-zero fixture, and no history-replay corpus cannot support a stable held-out learned comparison.
CITE: council_verdicts.json, lens B finding “Data starvation kills any tensor fit today,” citing `SPEC.md:108-113,227-241,332-338`.
CHECK: Before fitting, count independent external-history pairs and run a fixed power calculation against the measured-footprint baseline; keep the experiment calibration-only unless the pre-recorded minimum sample size is met.

CLAIM: The plausibly novel element is only the repo-specific protocol of predicting receipt-backed interventional `K_behave` with frozen operator representations and kill criteria, not operator matrices or tensor factorization themselves.
CITE: council_verdicts.json, lens B findings citing measured `k=0.1754` and `k=0.1915`, plus the frozen operator-embedding recommendation.
CHECK: Compare the frozen spec’s claimed contribution against its novelty table and fail any novelty claim that does not isolate the receipt supervision, sealed evaluator, and repo-specific baselines.

CLAIM: Multi-relational tensor factorization and compositional representation are literature-known territory represented here by RESCAL, DistMult, ComplEx, TuckER, RotatE, Smolensky tensor-product representations, Rudolph–Giesbrecht CMSM, and DisCoCat.
CITE: council_verdicts.json, lens B recommendation “Write the novelty-narrowing table.”
CHECK: Require each named mechanism in the pivot document to map to one cited prior-work row and one explicit implementation difference.

CLAIM: Vector-stalk descent and code-graph embeddings are also literature-known territory represented here by Hansen–Ghrist cellular sheaves, Bodnar sheaf neural networks, code2vec, GraphCodeBERT, CodexGraph, RepoGraph, and LocAgent.
CITE: council_verdicts.json, lens B novelty-narrowing and vector-stalk recommendations.
CHECK: Fail the novelty table if any of these families is absent or if the proposed mechanism lacks a testable distinction from them.

CLAIM: “Tensor-product of two Node Cards,” universal curvature or intelligence scalars, a fifth plane, and a universal coordinate system are word-salad risks unless each term has typed inputs, a deterministic observable, a baseline, and a kill condition.
CITE: council_verdicts.json, lens B recommendation requiring an “operational cash-out,” and finding citing the universal-scalar ban and `context_plan.py:13-15`.
CHECK: Schema-validate every proposal term against required fields `{inputs, operator, observable, baseline, kill_condition}` and block execution when any field is missing.

CLAIM: Refusing canonical status for latent space is also the safer security posture because the only evidenced production embedding backend can transmit requests to a caller-selected host and omits host identity from the index identity.
CITE: council_verdicts.json, lens E findings citing `embeddings.py:43-47,340-347`.
CHECK: Require both host-policy enforcement and host-bound index identity tests before any latent component can enter a default or promotion-critical path.

# SEAT 3 — role maintainer — council-20260821T195705Z-cbed8e7e — status anomaly/instruction_in_evidence — 324.753s

ANOMALY: instruction_in_evidence
CLAIM: The evidence contains reviewer-directed imperatives, including “Attack my AMENDMENT-now recommendation,” “Attack the falsification argument in finding 3,” “Construct the concrete reconciliation,” “Argue the reverse ordering,” and “Attack this proxy.”
CITE: `council_verdicts.json`, lenses A–E, `for_codex` arrays
CHECK: NONE

CLAIM: Selecting one sole authority is constitutionally necessary, but naming g0 Revision 6 canonical before a read-only trunk gate passes is unsupported; both lines should first stop changing, then the owner’s declaration can select the validated chain.
CITE: `fork_brief.md`: “Both lines claim the same Plan-ID `daedalus-master-plan`. Sole-authority clause in both plans makes this formally undecidable until the owner rules.”
CHECK: On detached worktrees at `3e758392` and `93f11adf`, recompute every amendment-record link and plan-result hash, diff all protected authority files, enumerate reachable kernel/trust-root paths, and require all 24 fault rows to be executed rather than declared blocked; exit nonzero on any failure.

CLAIM: The strongest argument against immediately canonizing g0 is that its extra 1,228 commits coexist with three purported kernel surfaces, an environment-secret HMAC approval design, and six unexecuted fault lines, so age and commit count do not establish constitutional or Gate-0 correctness.
CITE: Lens A: “daedalus/kernel + daedalus/gates + daedalus/spine side by side”; “symmetric HMAC with the secret read from an environment variable”; “the 6 declared-blocked fault-matrix lines need a Linux host/CI run.”
CHECK: At `93f11adf`, generate an entrypoint-to-kernel call graph, execute promotion fault tests with missing/forged credentials, and require 24 receipts whose status is `measured` and whose signatures verify.

CLAIM: Lens A’s critical “Invariant 1 is violated” finding is unsupported by its cited `ls` evidence because directory coexistence cannot distinguish two live kernels from dead, compatibility, or experimental code.
CITE: Lens A finding: “Invariant 1 (‘one kernel’) is violated at branch level”; cited evidence: “ls agent_env_g0/daedalus shows gates+kernel+spine.”
CHECK: Resolve static and dynamic imports from every registered effectful entrypoint at `93f11adf` and fail only if one entrypoint can reach more than one kernel implementation.

CLAIM: Lens A’s critical claim that the trunk has a live HMAC promotion trust root is not established by the cited module locations, which show implementation but not that `promote_candidates` reaches that implementation.
CITE: Lens A: “kernel/approvals.py uses a symmetric HMAC”; elsewhere: “PromotionReceipt schema exists, nothing constructs it, promote_candidates takes no approval parameter.”
CHECK: Invoke every public promotion entrypoint under coverage with valid, invalid, forged, and absent HMAC material; report whether `kernel/approvals.py` is reached and whether any unauthorized case promotes.

CLAIM: Calling the trunk fault matrix “24/24 production-HMAC-signed” is an overclaim if six rows are merely declared blocked, because a valid signature authenticates a declaration but does not demonstrate fail-closed behavior.
CITE: Lens A: “fault matrix 24/24 production-HMAC-signed”; “the 6 declared-blocked fault-matrix lines need a Linux host/CI run.”
CHECK: Parse all 24 receipts and fail unless each contains an executed outcome, environment identity, expected failure mode, observed failure mode, and a valid signature; `declared-blocked` must not count as executed.

CLAIM: Lens C’s critical assertion that reconciliation “requires rewriting one history” is wrong because a winning chain can append a reconciliation amendment naming the losing tip without altering either historical prefix.
CITE: Lens C: “reconciling a fork it never anticipated requires rewriting one history”; same finding quotes section 15: “rollback is a new amendment, never a history rewrite.”
CHECK: In a temporary copy, hash both original JSONL files, append one record to the selected chain referencing its current tip and the losing-tip hash, then assert all prior bytes are unchanged and the chain validator passes.

CLAIM: Lens D mis-prioritizes the missing `post-commit` regeneration hook as critical because its own correction says the picker fails closed, making this a liveness failure rather than silent stale-map execution.
CITE: Lens D: “arch_memory staleness loop is broken”; correction: “the picker already fails closed on the stale map — the loop runs blind, not misled.”
CHECK: Supply a stale architecture snapshot, replace every write/spawn/provider function with a sentinel that fails if called, run the picker and loop, and assert that no effect occurs.

CLAIM: Lens D’s critical findings about `daedalus.loop`, producer-less canonical contracts, and roughly 41 `INVENTORY_ONLY` rows cannot be “now” trunk blockers because all inventory slices ran on the checkpoint line while the trunk reportedly has only 13 remaining inventory-only doors.
CITE: `fork_brief.md`: “Tonight’s audit … ran ENTIRELY on the checkpoint line”; Lens D critical findings “daedalus.loop … no effect-boundary row,” “Canonical contracts are producer-less,” and “~41 INVENTORY_ONLY”; Lens A: “13 justified inventory_only doors.”
CHECK: At `93f11adf`, rerun the registry census and symbol-producer/import census, then compare exact row and caller sets with the checkpoint report.

CLAIM: Lens D’s “delete the five zero-importer shims” recommendation is internally malformed because it names six modules and its cited importer search does not mention `langgraph_adapter.py`.
CITE: Lens D recommendation: “Delete the five zero-importer shims (daedalus/ikarus.py, decompose.py, drafts.py, mission_control.py, orchestrate.py root wrappers, plus langgraph_adapter.py)”; evidence lists only the first five names.
CHECK: Scan tracked source, configuration, entry-point metadata, pickle fixtures, and importlib string arguments for all six module names, then build/install the wheel in a clean environment and run the full test suite with import auditing.

CLAIM: Lens C’s now-recommendation to manufacture `SPEND_AND_EGRESS_COVERAGE.md` from the citing tests would repair a link but not the missing contemporaneous receipt, especially when the same author controls numerator and denominator.
CITE: Lens C: the file “has never existed”; recommendation: “Write docs/SPEND_AND_EGRESS_COVERAGE.md from the two coverage suites’ own docstrings”; finding notes the denominator was “already flagged … as author-owns-numerator-and-denominator.”
CHECK: Run `git log --all --follow -- docs/SPEND_AND_EGRESS_COVERAGE.md`; if no receipt predates the tests, require any replacement to be machine-labeled `reconstruction` and make a doc-reference test fail on unresolved receipt links.

CLAIM: Lens E correctly identifies a silent fail-open degradation, but its now-recommendation of `MCP_TIMEOUT>=60000` is unsupported by one 28.35-second observation and supplies no tail-latency or half-ready-service bound.
CITE: Lens E: “28.35s cold vs 30s timeout”; recommendation: “MCP_TIMEOUT (>=60000)”; finding: “fail-open … silently converts ‘mandatory Serena’ into ‘never Serena’ with zero recorded signal.”
CHECK: Inject Serena states for unavailable, dashboard-only, indexing, and functional symbol-query readiness at delays around 30, 60, and 120 seconds; require prewarm to wait for a successful symbol query and require every fail-open path to emit a receipt.

CLAIM: Lens B’s “latent ceiling has never been run” finding is critical only for latent-expansion work, not globally, because its own evidence says even a high ceiling licenses one experiment rather than infrastructure.
CITE: Lens B: “The pre-registered gate for ANY latent expansion”; cited span: “a high ceiling licenses ONE experiment, not infrastructure.”
CHECK: Make the task scheduler require a ceiling receipt only for tasks tagged `latent` or `embedding`, and verify that removing the receipt changes no Gate-0 test result.

CLAIM: Running the pre-registered ceiling classification first and denying canonical authority to latent spaces is sound, but enabling an executable operator-embedding fit now is too generous until an external history-replay corpus and a frozen power calculation exist.
CITE: Lens B: “roughly 40 pairs over 4 author-written fixtures”; “history-replay corpus = BACKLOG”; recommendation says the K predictor is “Calibration-only until the history-replay corpus exists.”
CHECK: Fail the ExperimentSpec transition from `calibration` to `active` unless it contains ceiling and history-corpus receipts, a frozen minimum-sample calculation, and `observed_n >= required_n`.

CLAIM: The measured non-commutation values falsify intervention-as-vector-offset models specifically, not flat embeddings or nonlinear state models generally.
CITE: Lens B finding: “where any intervention-as-vector-offset model predicts K identically 0.”
CHECK: Symbolically compose translations `T_a(x)=x+a` and `T_b(x)=x+b` in both orders and assert equality, then verify the same test does not impose commutativity on arbitrary nonlinear operators.

CLAIM: The only plausibly novel element identified is the repo-specific experiment coupling operator representations to held-out behavioral `K_behave` receipts and footprint baselines; the evidence establishes no globally novel tensor or categorical construction.
CITE: Lens B recommendation: “fit per-operator matrices (or low-rank tensors) to predict continuous K_behave on held-out pairs, supervised by the existing anchor-verified kmatrix receipts,” with footprint and flat baselines.
CHECK: Run `git log --all -S "K_behave"` and `git log --all -S "operator-embedding"` to establish repo-local novelty; global novelty remains `NONE`.

CLAIM: Multi-relational tensor factorization and compositional or sheaf-based semantics are literature-known territory under RESCAL, DistMult, ComplEx, TuckER, RotatE, Smolensky TPR, Rudolph–Giesbrecht CMSM, DisCoCat by Coecke–Sadrzadeh–Clark, Hansen–Ghrist cellular sheaves, and Bodnar sheaf neural networks.
CITE: Lens B recommendation: “multi-relational factorization = RESCAL/DistMult/ComplEx/TuckER/RotatE; non-commutative compositional embeddings = Smolensky TPR, Rudolph-Giesbrecht CMSM, DisCoCat (Coecke-Sadrzadeh-Clark); vector-stalk descent = Hansen-Ghrist cellular sheaves / sheaf NNs (Bodnar).”
CHECK: Make the pivot document’s bibliography checker fail unless every claimed construction resolves to one of these named prior-art entries and states a concrete delta.

CLAIM: “Tensorized descent,” universal curvature or intelligence scalars, a fifth canonical plane, and tensor products of Node Cards are word-salad risks unless each is reduced to typed inputs, an observable, a baseline, and a kill criterion.
CITE: Lens B: “universal curvature/intelligence scalars are banned”; recommendation: “Every categorical term must name its operational cash-out (what is the tensor-product of two Node Cards, measured how) or be struck”; “Refuse … a fifth plane, a universal coordinate system.”
CHECK: Validate every proposed ExperimentSpec against a schema requiring `inputs`, `operator`, `observable`, `baseline`, and `kill_criterion` for each categorical term, and fail on undeclared `canonical_plane` or universal-scalar fields.

CLAIM: A naive code-by-type tensor is additionally premature because the cited graph is dominated by hub types, so it must beat a hub-stripped flat baseline before tensor structure is credited.
CITE: Lens B: “top-8 types carry 83.6% of all type edges”; “a code-x-type product space would mostly encode ‘touches str’.”
CHECK: Recompute the edge histogram, remove the top eight type hubs, and run an equal-dimension held-out ablation comparing tensor, flat-concatenation, and BM25 baselines; fail the tensor claim if its gain disappears.

# SEAT 4 — role measurement — council-20260821T200230Z-b9dc2ae9 — status anomaly/instruction_in_evidence — 437.128s

ANOMALY: instruction_in_evidence
CLAIM: The embedded spans “Attack my AMENDMENT-now recommendation,” “Compute the minimum corpus size,” “Construct the concrete reconciliation,” “Specify a falsifiable independence criterion,” and “Attack this proxy” are instructions addressed to Codex and were not followed.
CITE: council_verdicts.json, every lens’s `for_codex` array.
CHECK: Parse the JSON and assert that each of the five objects has a `for_codex` array containing imperative verbs addressed to the reviewer.

CLAIM: Declaring Revision 6 canonical is not yet established as the right first move because no branch-identical regression, constitutional-integrity, and Gate-0 census comparison is reported.
CITE: fork_brief.md: “Tonight's audit ... ran ENTIRELY on the checkpoint line”; council_verdicts.json lens A recommendation “Owner declares ONE trunk.”
CHECK: In clean worktrees at both cited heads, run the same full test suite and Gate-0 census and fail trunk eligibility on any invalid amendment link, additional shared-test failure, or unaccounted protected-policy difference.

CLAIM: The strongest argument against immediate trunk canonization is that the proposed trunk allegedly combines two kernel paths with an environment-secret HMAC promotion root, so a higher revision number may merely canonize known invariant failures.
CITE: council_verdicts.json lens A findings “carries daedalus/kernel + daedalus/gates + daedalus/spine side by side” and “kernel/approvals.py uses a symmetric HMAC with the secret read from an environment variable.”
CHECK: On trunk SHA `93f11adf`, trace imports and runtime promotion callers, then run a test in which an ordinary process possessing the verification environment secret attempts to mint an approval accepted by the verifier.

CLAIM: Before ruling on the trunk, the machine-readable Gate-0 report must disclose executed, blocked, inventory-only, security-boundary, and scanner-error counts rather than the aggregate “24/24 signed.”
CITE: council_verdicts.json lens A: “13 justified inventory_only doors,” “6 declared-blocked fault-matrix lines,” “security_boundary_claimed:false,” and “v3 repository-write scanner crashes.”
CHECK: Run the trunk Gate-0 reporter and require explicit counters for all five categories plus a nonzero exit status whenever executed fault lines are fewer than 24 or the scanner errors.

CLAIM: The constitutional fork itself is supported: two headers claim the same Plan-ID while their chains share record 1 and diverge at sequence 2.
CITE: fork_brief.md: “Both lines claim the same Plan-ID”; council_verdicts.json lens C: “Both chains share record 1 ... then diverge.”
CHECK: Recompute every JSONL record hash, previous-record link, revision transition, and resulting plan SHA on both chains and compare their sequence-2 hashes.

CLAIM: Lens A’s critical finding “Invariant 1 is violated at branch level” is overclaimed because directory coexistence measures files, not whether two kernels are live authorities.
CITE: council_verdicts.json lens A evidence: “ls agent_env_g0/daedalus shows gates+kernel+spine.”
CHECK: Build a static import graph plus instrumented ignition and promotion runs, and count which of `spine`, `kernel`, and `gates` execute authority decisions; the violation requires more than one active decision path.

CLAIM: Lens C’s critical claim that reconciliation “requires rewriting one history” is unsupported because an append-only reconciliation record on the chosen chain can reference the losing tip without altering either prior chain.
CITE: council_verdicts.json lens C critical finding; lens A recommendation “append a reconciliation record ... Rollback-forward only, no history rewrite.”
CHECK: In temporary copies, append one record referencing both tip hashes, recompute the winning chain, and verify that every pre-existing byte and hash remains unchanged.

CLAIM: The “24/24 production-HMAC-signed” description does not demonstrate 24 fail-closed executions when six rows are declared blocked.
CITE: council_verdicts.json lens A: “fault matrix 24/24 production-HMAC-signed” and “the 6 declared-blocked fault-matrix lines need a Linux host/CI run.”
CHECK: Parse all 24 receipts and report `executed`, `blocked`, and `signature_valid` separately; the stated evidence predicts 18 executed and 6 blocked.

CLAIM: Lens D’s critical arch-memory finding is mis-prioritized as a safety failure because its own evidence says the picker fails closed, leaving availability impact—not stale selection—as the unmeasured quantity.
CITE: council_verdicts.json lens D: “picker already fails closed on the stale map — the loop runs blind, not misled.”
CHECK: In a temporary clone, stale the map deliberately, invoke the picker, and assert zero selections while recording the fraction of loop iterations blocked solely by freshness.

CLAIM: Lens D’s critical claim that `daedalus.loop` is a spend/spawn/write entrypoint proves missing registration but not critical runtime exposure because no invocation or effect count is cited.
CITE: council_verdicts.json lens D: `if __name__ == '__main__'` plus zero registry matches.
CHECK: Run `python -m daedalus.loop` under instrumented process, filesystem, network, and spend adapters and count effects occurring before a central guard denies execution.

CLAIM: Lens D’s “Canonical contracts are producer-less” is a valid static gap but mis-prioritized as a Gate-0-now critical until an ignition test proves that canonical artifacts are an enforced exit dependency.
CITE: council_verdicts.json lens D: “grep MissionContract ... exactly one file, daedalus/schemas.py.”
CHECK: Run a dry ignition mission and validate every emitted artifact against `MissionContract`, `AttemptContract`, and `EvidencePacket`, failing if any required type has zero producers.

CLAIM: Lens D’s critical “Registration is not routing” severity is unsupported by row counts alone because the evidence contains no measured behavioral difference between CENTRAL, INVENTORY_ONLY, and UNGUARDED labels.
CITE: council_verdicts.json lens D: “1 CENTRAL row against ~41 INVENTORY_ONLY and 2 UNGUARDED.”
CHECK: Inject the same forbidden spend, write, and kill-switch faults through one row of each wiring class and compare denial and receipt outcomes.

CLAIM: Lens E’s Serena startup race is a real hypothesis but its critical severity and proposed 60-second timeout are unsupported by one 28.35-second cold-start observation and an unknown inert rate.
CITE: council_verdicts.json lens E: “28.35s cold vs 30s timeout” and “no counter anywhere measures deny/pass/inert rates.”
CHECK: Collect at least 100 clean cold starts, report p50/p95/p99 readiness and hook-inert rate, and derive the timeout from a predeclared maximum inert-rate fence.

CLAIM: Lens E’s critical graph-brief finding proves missing crew wiring but not user-impact magnitude because it cites one hallucinated-symbol episode and no comparative task results.
CITE: council_verdicts.json lens E: “three hallucinated symbol names” and consumers limited to ollama/fanout.
CHECK: On at least 20 frozen tasks, compare graph-brief plus Serena against grep/BM25 using verified-symbol error rate, tokens, latency, and gate-passing writes.

CLAIM: Lens C’s now-action to author `SPEND_AND_EGRESS_COVERAGE.md` from the tests would repair a dangling path but would not independently validate the tests’ self-maintained numerator and denominator.
CITE: council_verdicts.json lens C: the file “has never existed” and recommendation to write it “from the two coverage suites' own docstrings.”
CHECK: Add a doc-reference test separately from an independently generated runtime effect census, and require the census denominator and test denominator to match exactly.

CLAIM: Lens D’s now-action to delete zero-importer shims is mis-prioritized before trunk selection and unsafe on static grep alone because string imports and serialized module names remain unmeasured.
CITE: council_verdicts.json lens D recommendation “Delete the five zero-importer shims”; lens A dissent “Delete only on the surviving trunk.”
CHECK: On the surviving trunk, scan `importlib`, entry points, pickle/config strings, and built artifacts for each module name, then run the full suite with the shims absent in a temporary worktree.

CLAIM: Running the latent-ceiling classification now is supported, but the example tensor-go threshold “bucket-(b) >= 15%” has no cited cost, power, or utility derivation.
CITE: council_verdicts.json lens B recommendation: “Pre-register ... e.g. bucket-(b) >= 15%.”
CHECK: Commit a hashed threshold and loss function before labels are revealed, then compute `bucket_b / total` and apply that immutable rule.

CLAIM: The research councillor’s overall boundary is sound only if “admit the operator experiment” means freezing a spec without fitting until external history replay, power, and gauge-identifiability gates pass.
CITE: council_verdicts.json lens B: “history-replay corpus = BACKLOG,” “roughly 40 pairs over 4 author-written fixtures,” and “Calibration-only until the history-replay corpus exists.”
CHECK: Make the experiment runner refuse training unless the corpus manifest meets pre-registered minimum sample, fixture-independence, contamination, and gauge-invariance checks.

CLAIM: The measured non-commutation values `k=0.1754` and `k=0.1915` falsify additive intervention-as-vector-offset models, but they do not show that tensors outperform flat composed-state or footprint baselines.
CITE: council_verdicts.json lens B finding: “where any intervention-as-vector-offset model predicts K identically 0”; operator-experiment recommendation lists flat and footprint baselines.
CHECK: Use held-out fixtures to compare continuous-K error against always-zero, declared-footprint, measured-footprint, co-change, and flat AB-versus-BA baselines with predeclared confidence intervals.

CLAIM: Registering a fitted tensor predictor before power analysis would be too generous because approximately 40 non-independent author-fixture pairs cannot establish generalization.
CITE: council_verdicts.json lens B: “roughly 40 pairs over 4 author-written fixtures” and “effect claims” forbidden on author fixtures.
CHECK: Compute minimum sample size from pre-registered alpha, power, smallest useful baseline improvement, and leave-one-fixture-out variance; block fitting until independent history replay reaches that number.

CLAIM: The genuinely new item evidenced here is the repo-specific experimental linkage between operator embeddings and anchor-verified continuous `K_behave` receipts, not a demonstrated new tensor or category-theory method.
CITE: council_verdicts.json lens B recommendation “fit per-operator matrices ... to predict continuous K_behave ... supervised by existing anchor-verified kmatrix receipts.”
CHECK: Search full repository history for the exact experiment definition and require its novelty table to distinguish “new combination in Daedalus” from “new in literature.”

CLAIM: Multi-relational tensor factorization and non-commutative compositional embeddings are literature-known territory represented here by RESCAL, DistMult, ComplEx, TuckER, RotatE, Smolensky TPR, Rudolph–Giesbrecht CMSM, and DisCoCat.
CITE: council_verdicts.json lens B novelty-narrowing recommendation naming those methods and Coecke–Sadrzadeh–Clark.
CHECK: Require the frozen experiment spec to map every claimed tensor mechanism to one cited baseline family and fail lint on an uncited mechanism name.

CLAIM: Vector-stalk descent and sheaf neural methods are also literature-known territory represented here by Hansen–Ghrist cellular sheaves and Bodnar’s sheaf neural networks.
CITE: council_verdicts.json lens B novelty-narrowing and vector-stalk recommendations.
CHECK: Fail the novelty-table lint unless every sheaf/descent claim cites the occupied method and states a falsifiable delta specific to sealed evaluator calls.

CLAIM: The existing categorical work is not a novel pivot proposal because fibrations, Čech obstructions, descent, lens laws, and adjunction residuals already have deterministic assays and kill criteria in `higher_twin_nc`.
CITE: council_verdicts.json lens B finding: “already exists as the repo's most disciplined experiment” with `H-CERT/H-ANOM/H-DESC/H-HOL` criteria.
CHECK: Execute all registered categorical assays and require each result to resolve to a pre-registered pass or kill condition with no embedding dependency.

CLAIM: The principal word-salad risks are universal curvature or intelligence scalars, a canonical latent coordinate system, and undefined phrases such as “tensor-product of two Node Cards.”
CITE: council_verdicts.json lens B: “universal curvature/intelligence scalars are banned,” “never an authority,” and “what is the tensor-product of two Node Cards, measured how.”
CHECK: Lint every pivot document for categorical/tensor terms and require each occurrence to link to an input schema, deterministic operator, observable output, baseline, and kill threshold.

CLAIM: Keeping every latent space non-canonical is mechanically justified until the ceiling, corpus, and held-out predictor results exist because current embedding evidence is near-unused and freshness-unanchored.
CITE: council_verdicts.json lens B: “0 of 5 live probes,” “freshness unanchored,” and recommendation refusing “a fifth plane ... embedding-gated promotion.”
CHECK: Scan plans, schemas, promotion code, and effect registries and fail if any latent score is required for authority, promotion, or a new canonical plane before the three receipts exist.

CLAIM: The reported `0/5` semantic-route usage is historical rather than a current failure rate because the evidence says a fix exists but no post-fix re-probe was recorded.
CITE: council_verdicts.json lens E: `semantic_route.py:261-263 (0/5 measured), :270-271 (fix present, unmeasured)`.
CHECK: Replay the same five production probes at the cited trunk SHA and report routed, failed, and bypassed counts with receipts.

CLAIM: The hub measurements justify testing against naive plane-product tensors but do not establish tensor rank or uselessness without an equal-budget ablation.
CITE: council_verdicts.json lens B: “top-8 types carry 83.6%,” “53.63% ... 2-hop connected,” and Tucker-versus-flat recommendation.
CHECK: Under identical dimension, token budget, split, and queries, compare Tucker/mode-tagged, flat concatenation, BM25, and graph-brief; kill the tensor arm on no held-out gain.

# SEAT 5 — role falsifier — council-20260821T200947Z-eeff0697 — status anomaly/instruction_in_evidence — 378.417s

ANOMALY: instruction_in_evidence
CLAIM: “Attack my AMENDMENT-now recommendation if you think a pure ALIGNED merge-of-records suffices.”
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json, lens A, for_codex[0]
CHECK: NONE

CLAIM: Declaring Revision 6 canonical immediately is premature; the strongest contrary evidence is that the audit ran entirely on the checkpoint while the claimed Gate-0 closure was “measured on WHICH line is now unclear,” so both lines should first be write-frozen and compared at pinned commits.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/fork_brief.md — “Tonight's audit ... ran ENTIRELY on the checkpoint line” and “Gate-0 closure ... measured on WHICH line is now unclear”
CHECK: Create clean detached worktrees at the checkpoint and 93f11adf, run the identical Gate-0 report and test command in each, hash every output, and fail unless both worktrees remain clean and all result artifacts identify their source SHA.

CLAIM: Before any trunk ruling, Revision 6 must demonstrate an intact amendment hash chain, plan-byte/result hashes matching every record, reproducible Gate-0 evidence, and no unresolved protected-file divergence.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens C finding “Both chains share record 1 ... then diverge” and lens A finding “two incompatible promotion trust roots”
CHECK: Parse both amendments JSONL files from record 1 onward, recompute previous-record and result-plan SHA-256 values, verify monotonic sequence/revision fields, and exit nonzero on the first mismatch or unaccounted protected-plan diff.

CLAIM: Lens A’s critical “Invariant 1 is violated” finding is unsupported by directory coexistence alone because gates, kernel, and spine can coexist while only one implementation is reachable from production entrypoints.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens A finding “ls agent_env_g0/daedalus shows gates+kernel+spine”
CHECK: Enumerate every installed console entrypoint and `__main__` block at 93f11adf, build its import/call closure, and fail only if more than one kernel implementation can reach the same promotion, spend, spawn, or write effect.

CLAIM: Lens A’s critical sealed-promotion finding establishes symmetric-MAC forgeability in principle but does not establish the operational threat unless the trunk’s actual promoter uses that path and an untrusted candidate can read the verification secret.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens A finding “kernel/approvals.py uses a symmetric HMAC with the secret read from an environment variable” and “promote_candidates takes no approval parameter”
CHECK: Run promotion under process-level environment tracing with a unique canary secret and fail if any candidate or worker process receives the canary, or if promotion succeeds without exercising a verified approval receipt.

CLAIM: Lens C’s critical assertion that reconciliation “requires rewriting one history” is wrong because a chosen chain can remain byte-for-byte intact while a new record names the abandoned chain and reintroduces selected content as later amendments.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens C finding “reconciling a fork ... requires rewriting one history” versus lens A recommendation “append a reconciliation record ... Rollback-forward only, no history rewrite”
CHECK: On copies of both JSONL chains, append one correctly hash-linked reconciliation record to the selected chain and byte-compare every pre-existing record before and after; the check passes only if all old bytes are unchanged and the new chain verifies.

CLAIM: The “24/24 production-HMAC-signed” fault-matrix claim is misleading while six lines are merely declared blocked, so those six executable outcomes must be measured on the trunk before Gate-0 closure evidence is treated as complete.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens A findings “24/24 production-HMAC-signed” and “the 6 declared-blocked fault-matrix lines need a Linux host/CI run”
CHECK: Run all 24 matrix cases in pinned Linux CI and fail unless every row contains an executed command, exit status, expected fail-closed assertion, artifact hash, and no `blocked`, `skip`, or `xfail` state.

CLAIM: Lens D’s critical missing-post-commit-hook finding is mis-prioritized as an integrity failure because its own evidence says the picker refuses stale maps, making the demonstrated consequence loss of availability rather than incorrect ranking.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens D findings “the promised post-commit hook does not exist” and “the picker already fails closed on the stale map”
CHECK: Feed picker.py a snapshot with a deliberately wrong head and digest, instrument every returned work item and side effect, and fail if it returns or executes any ranked work rather than the documented untrusted-map result.

CLAIM: Lens D’s critical “canonical contracts are producer-less” finding is a Gate-1 readiness gap, not a demonstrated current Gate-0 blocker.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens D headline “an ignition run today could not emit a MissionContract” and recommendation “do it before the ignition run”
CHECK: Trace every input to the Gate-0 closed predicate and fail this claim only if MissionContract, AttemptContract, or EvidencePacket production is a necessary dependency of that predicate.

CLAIM: Lens D’s critical “Registration is not routing” finding proves label counts but not materially different enforcement, so its severity is unsupported until CENTRAL and INVENTORY_ONLY paths exhibit different fail-closed behavior.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens D finding “1 CENTRAL row against ~41 INVENTORY_ONLY and 2 UNGUARDED”
CHECK: Invoke one representative entrypoint from each wiring class under an exhausted budget and asserted kill switch, then fail unless every CENTRAL path is blocked before its effect while at least one non-CENTRAL path behaves differently.

CLAIM: Lens E’s critical Serena timeout finding is under-supported by one 28.35-second cold-start observation against a 30-second timeout, and neither that datum nor a static 60-second replacement establishes tail reliability.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens E finding “28.35s cold vs 30s timeout” and recommendation “MCP_TIMEOUT (>=60000)”
CHECK: In 200 fresh, cache-cleared launches on the supported host class, record time to a successful symbol query rather than dashboard-listen time and fail any proposed timeout whose pre-registered exceedance allowance is breached.

CLAIM: Lens E’s critical claim that graph_brief needs a crew-facing surface identifies missing wiring but does not show that making it a default now improves verified work over Serena, grep, or BM25.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens E finding “three hallucinated symbol names” and recommendation requiring a budget-equal comparison
CHECK: Run a frozen, independently authored task set across graph_brief, Serena, grep/BM25, and combinations with equal context budgets, then compare exact symbol-location and gate-passing outcomes before changing the default.

CLAIM: Lens C’s now-remedy for the missing SPEND_AND_EGRESS_COVERAGE receipt is evidentially circular if the receipt is reconstructed only from the same test docstrings whose claims it is supposed to substantiate.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens C finding “the file has never existed” and recommendation “Write ... from the two coverage suites' own docstrings”
CHECK: Fail the documentation gate unless every numerical coverage claim resolves to an immutable raw run artifact or commit-pinned deletion experiment independent of the citing test source.

CLAIM: Running the latent-ceiling classification before creating latent infrastructure is sound, but calling an example bucket-(b) threshold of 15% “pre-registered” is false unless that threshold predates inspection of the corpus.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B recommendation “Pre-register ... (e.g. bucket-(b) >= 15%)” and evidence “Not yet run”
CHECK: Inspect the parent commit immediately preceding the classification run and fail if the exact threshold, denominator, tie rules, exclusions, and sequencing rule are absent from the committed protocol.

CLAIM: Treating the ceiling classification as a gate for “EVERY latent proposal” is overbroad because failure-corpus expressibility and held-out interventional-K prediction are distinct endpoints.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B recommendation “This is the gate for EVERY latent proposal” versus the K experiment’s endpoint “predict continuous K_behave on held-out pairs”
CHECK: Require each ExperimentSpec to name its primary endpoint and gate dependency, then fail a ceiling dependency when the ceiling bucket labels cannot alter or compute the experiment’s held-out K endpoint.

CLAIM: Refusing canonical authority for any tensor or latent space is sound because the evidence shows no production use, unanchored freshness, and no completed ceiling or history-replay result.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B findings “0 of 5 live probes,” “freshness unanchored,” and recommendation refusing “a fifth plane ... embedding-gated promotion”
CHECK: Scan the plan, gate predicates, promotion code, and effect registry and fail if any embedding similarity, latent coordinate, or tensor output can authorize promotion or override a deterministic receipt.

CLAIM: The proposed operator-embedding experiment is too generous at present because roughly 40 author-fixture pairs, one all-zero fixture, a missing history corpus, and unresolved gauge identifiability cannot support a learned held-out claim.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B findings “roughly 40 pairs over 4 author-written fixtures,” “chemlab ... all-zero,” and “history-replay corpus = BACKLOG”
CHECK: Before fitting, run a seeded fixture-grouped power simulation against measured-footprint overlap and fail unless the planned independent corpus yields at least 0.8 power at the predeclared minimum useful improvement with gauge-invariant predictions.

CLAIM: The measured non-commutation falsifies intervention-as-vector-offset models, not flat representations generally, so it does not by itself establish a need for matrices or tensors.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B finding “where any intervention-as-vector-offset model predicts K identically 0” and proposed baseline “embed the composed diff texts AB vs BA directly”
CHECK: On independently held-out operator pairs, compare the frozen operator model with the composed-diff flat baseline under identical features and nested fixture-grouped validation, and kill the operator hypothesis if it has no predeclared advantage.

CLAIM: Most named tensor/category components are literature-known: RESCAL, DistMult, ComplEx, TuckER, RotatE, Smolensky TPR, Rudolph–Giesbrecht CMSM, DisCoCat, Hansen–Ghrist cellular sheaves, Bodnar sheaf networks, code2vec, and GraphCodeBERT.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B recommendation “Write the novelty-narrowing table”
CHECK: Parse the novelty table and fail if any listed family is marked novel or lacks a primary-paper identifier, year, and explicit delta from the proposed experiment.

CLAIM: The only plausible repo-specific synthesis is predicting interventional K from frozen operator representations under sealed assays, but the supplied evidence does not establish that synthesis as genuinely novel beyond this repository.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B recommendation “fit per-operator matrices ... supervised by the existing anchor-verified kmatrix receipts”
CHECK: NONE

CLAIM: “Tensorized descent” and a “vector-stalk sheaf over the footprint site” remain word-salad risks until the site, stalks, restriction maps, tensor product, observable prediction, and falsifying outcome are defined mechanically.
CITE: C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/de817b68-faa5-4439-85cd-c3967f4542c0/scratchpad/council_verdicts.json — lens B recommendation “Vector-stalk sheaf over the footprint site (the 'tensorized descent' idea)” and requirement that “Every categorical term must name its operational cash-out”
CHECK: Lint the ExperimentSpec against a schema requiring those six definitions and an executable counterexample fixture, failing on any missing field or prediction that cannot be evaluated through the sealed assay interface.