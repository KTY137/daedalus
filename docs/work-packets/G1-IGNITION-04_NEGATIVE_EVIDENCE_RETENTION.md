# G1-IGNITION-04 - Retain negative aggregate evidence across later runs

Packet ID: `G1-IGNITION-04`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `24e229c0f34e5404bc219637b646386529f82035`
Status: local acceptance passed; GitHub source CI and manual main integration pending
Promotion: not requested
Dependencies: `G1-INTEGRATION-01 accepted main; G1-IGNITION-03 accepted early root admission`
Production implementation is held until the frozen red baseline is retained; the activation record below supersedes the earlier draft phase.

## Primary acceptance claim

A negative ignition run retains a truthful canonical EvidencePacket where its
existing identities permit one, plus its measured outputs and exact receipt
bytes in the existing content-addressed store. Later successful runs preserve
those bytes and their resolvable references. Negative evidence never becomes
passed, complete replay, nomination, or promotion merely because a packet now
exists. This packet does not close scientific Gate 1 or implement crash recovery.

## Scope

Production changes are confined to:

- `daedalus/kernel/fourfold_evidence.py`: existing assembler at281 and its local
  validation composition. Keep passed defaults and complete snapshot/candidate/
  locator binding. The promotion-facing verifier at468 and nomination consumer
  remain passed-only; no require_complete/bypass flag or alternate verifier.
- `daedalus/ignition/gate1.py`: store preparation at182/763; candidate compilation
  refusal at1038; existing check persistence at597 and aggregation at1174-1322;
  `_refused_receipt`, `_build_receipt`, and `write_receipt` at2249. Preserve the
  predecessor's early path admission, policy/lease/runtime gates and CLI door.

Reuse without modifying: `storage.py::ArtifactStore` (put_bytes527,
get_bytes593, load_locator601, verify673), `ArtifactLocator`95,
`artifact_manifest`348 and `artifact_locator_uri`343. These locators identify
manifest bytes, distinct from the payload digest. Never fabricate an ArtifactStore
locator with `kernel.artifacts.artifact_locator(packet.digest)`. Candidate
identity remains `kernel/source_trees.py::SourceTreeStore`, not a graph digest.
Reuse `atomic.py::write_bytes_atomic` for latest-file replacement, and existing
canonical contract JSON serialization. No second store, history database,
locator scheme, schema version, policy path, evaluator, or promotion path.

Tests may extend existing fourfold evidence/adversarial/source-review suites,
`tests/test_ignition_gate1.py` and `tests/ignition/test_voltage_ignition_faults.py`.
Run existing ArtifactStore tests unchanged. Root owns metadata/index/evidence.

## Contracts and behavior

1. Derive aggregate status from retained items using the current EvidencePacket
   rules: any unverified assurance or inconclusive/unknown observation makes the
   aggregate inconclusive; otherwise an explicit failed/error item makes failed;
   passed requires every item passed and all existing complete Fourfold bindings.
   Keep actual assurance, verdict, usage and raw output. Never upgrade assurance
   or translate a generic exception into a proven failed scientific check.
   Default assembler callers retain their current passed-only behavior; ignition
   selects explicit negative assembly. Refactor only local validation composition
   as needed so negative assembly still verifies canonical identity and durable
   locators while the public passed verifier refuses negative packets.
2. A complete snapshot can coexist with a failed test; preserve its actual
   structural evidence. Partial/no snapshot must not enter the complete Fourfold
   assembler, be replaced by the base snapshot, or yield fabricated graph/snapshot
   digests. On compilation refusal, persist measured diagnostic/available attempt
   items in a plain existing EvidencePacket only when the actual attempt chain,
   policy and candidate source bindings suffice. Unknown compiler infrastructure
   failure is inconclusive. If these bindings or any required bytes cannot be
   persisted, leave packet absent and retain a named refusal as far as storage
   permits. No invented Attempt, PolicyDecision, subject digest or success item.
3. Reuse the admitted mission `store` across runs; remove its destructive reset.
   Persist packet canonical bytes with their actual digest through ArtifactStore,
   including manifests for all check/diagnostic/snapshot outputs. Before replacing
   an existing latest receipt, store its exact raw bytes (including malformed JSON)
   and verify the locator/blob. Preserve malformed bytes as opaque observation;
   parsing failure never supplies replay authority. Persist the finalized new
   receipt bytes too. Publication order is artifacts, then latest file; failures
   before successful atomic replacement preserve the prior latest and refuse
   success. After replacement, a read-back failure refuses success but may leave
   the new latest visible; both generations were already retained in CAS.
   Orphan CAS bytes after interruption are safe;
   this is not same-attempt recovery or concurrent-writer arbitration.
4. Keep `<receipt_root>/<mission_id>/receipt.json`, its existing schema identifier,
   field meanings and `(path, body)` return. Add only portable references inside
   its existing evidence/replay projections: packet locator and previous receipt
   digest/locator, using the existing ArtifactLocator representation. No separate
   history index. The predecessor link refers to already-persisted bytes, avoiding
   a self-digest cycle. Older receipts without links remain readable history;
   no deleted history can be reconstructed or claimed retained retroactively.
5. Retention never converts failed/inconclusive packet presence into completion:
   previous_run_complete and replay_demonstrated require passed status plus the
   existing full checks. Preserve clock/bundle/fixture comparisons and blockers;
   a negative aggregate is not labelled nominated. Old unknown status refuses
   completion conservatively. Positive latest receipt consumers stay compatible.

## Acceptance matrix

After main and the predecessor are accepted, freeze identical interpreter,
fixture bytes, criterion/evaluator bundle, declared scopes, existing execution
limits, clock input and selectors for each before/after comparison. No provider
or model calls; only existing fixed ignition fixtures and admitted runtime.

- Red then green: complete candidate with actual failing pytest, schema or link
  observation produces a negative packet with exact raw-output locators; a run
  containing unverified evidence produces inconclusive. Mixed negative/unknown
  precedence obeys canonical contract rules; passed defaults remain unchanged.
- Partial/no-snapshot and injected compiler failure: no complete Fourfold item,
  snapshot or graph delta is fabricated; stored diagnostic status/absence agrees
  with available bindings. Missing artifact, corrupt locator, foreign subject,
  wrong revision and unverified inputs cannot yield conclusive passed evidence.
- Run failure -> success -> success against one admitted receipt/CAS root.
  Reopen every prior negative packet/item/receipt by recorded locator, compare
  exact bytes and SHA256s, and validate candidate/source identities. Latest path
  still returns the newest body; no negative predecessor becomes complete replay.
- Existing legacy and malformed latest receipt: exact predecessor bytes survive;
  absent provenance/status does not become replay proof. Re-persisting identical
  packet bytes is idempotent; changed evidence has a distinct actual digest.
- Inject failure at output, packet, predecessor-receipt and new-receipt CAS
  publication, and immediately before atomic latest replacement. Prior bytes and
  locators survive; no unresolved advertised locator or false durable success.
- Passed verifier and nomination reject every failed/inconclusive packet; no
  approval consumption or promotion entrypoint is imported/executed. Run all
  existing positive binding, locator, adversarial and early-root regression tests.

Baseline and corrected focused suites: one run each, same selectors and a
900-second external ceiling per run; no pytest -x or failure-driven retries.
The three-run retention scenario uses the same original per-attempt limits and
counts on both source versions. Timeout is retained incomplete evidence, not a
reason to loosen the gate. Retain stdout/stderr, JUnit, exact source/fixture/bundle
hashes, actual elapsed time and ResourceUsage; perform independent review.

Four bounded mutants in the canonical isolated shadow runner: force status
passed; turn any retained failed/unknown case into no packet; restore destructive
store reset; publish latest before predecessor retention. Freeze the exact
mutant anchors only on the accepted predecessor source. Each mutant and its
control use identical named regression selectors and a 120-second ceiling;
4 mutant runs, one control per distinct selector set, no adaptive extra attempts.
A survivor or timeout is a retained failure/inconclusive result, never a pass.
No mutation touches the shared checkout, evaluator policy, clock or limit values.

## Migration and rollback

No existing blob or locator is rewritten or garbage-collected. Legacy receipts
are captured on first subsequent admitted write. Rollback must preserve accumulated
CAS/history bytes; do not reinstate deletion as a cleanup step. Current absence of
archived history is reported honestly. Fresh-nonce replay, durable Attempt wiring,
trusted-clock composition, process crash/concurrency proof and runtime/evaluator
isolation remain separate ordered work after this packet.

## Evidence expected failures and review

Current source evidence is read-only: the assembler hardcodes passed and then
uses its passed verifier; failed/unverified aggregation becomes packet=None.
Candidate compile refusal returns before aggregate storage. `_reset_evidence_store`
erases an otherwise recognized mission store, and `write_receipt` overwrites the
one latest file. Existing tests explicitly expect packet absence for these
negative runs; those expectations must change only with retained red/green proof.
No baseline or test was run for this draft. Any discovered need for new authority,
schema, shared storage internals or wider recovery semantics is a scope blocker to
report before editing. Review and final activation freeze follow the predecessor.


Pre-baseline review note (2026-09-08): the new latest receipt cannot serialize
its own ArtifactStore locator, because doing so changes the bytes that locator
addresses. The retained predecessor link is sufficient inside the v1 body.
Store the finalized new bytes without adding a self-locator cycle; expose or
verify its actual returned ArtifactLocator through existing observation seams
only. A later receipt may point to it as predecessor. Tests must distinguish
packet payload SHA, artifact-manifest SHA, receipt payload SHA and source-tree
identity, and reopen bytes through actual returned store locators. This is a
clarification of paragraph4, not a new receipt schema or authority.


## Pre-activation review clarifications - 2026-09-08

This draft is now in an isolated successor worktree at PR319 source2ed5a5d0.
The original draft base5d6c82ad is historical; the original complete draft hash
was d53f5353a5a7648a2906bd01c19ad7f43601880d9bf2147541f1dd2f6aabef48. Accepted main still awaits PR319 review/CI integration. Before
baseline or production changes, replace the header with the actual accepted
main descendant, append the activation record and freeze all test selectors.
The preceding draft's no-build dependency remains in force.

The current canonical EvidenceItem verdict set is passed/failed/error/cancelled.
An unknown compiler/infrastructure observation must use error with unverified
assurance and an inconclusive aggregate; do not invent an unknown/inconclusive
item verdict. Unverified assurance and cancellation conservatively make an
aggregate inconclusive before otherwise conclusive failed/error observations.
Passed defaults retain strict refusal of every nonpassed/unverified item.

Changing gate1.py necessarily changes the evaluator-bundle digest because it
is an explicitly included source. Freeze the external criterion/fixture,
interpreter/plugins, clock input, selectors and limits across red/green arms;
retain both actual source/bundle identities. Require bundle equality within
each arm's three-run sequence. Do not claim cross-version replay equality or
hide a criterion/bundle drift blocker. This clarifies the equal-budget section,
not the evaluator or its rules.

The existing atomic write helper supports atomic replacement and subsequent
read-back. It does not fsync file and parent directory, so this packet claims
retained/readable bytes and atomic latest visibility, not power-loss durability,
process-crash recovery or a transaction across CAS and the latest receipt.
Store and verify the finalized new receipt bytes before atomic replacement;
never add its own locator to that body or to a different returned dictionary.

Keep ArtifactStore and all canonical contracts unchanged. Verify every new
advertised evidence output locator with the actual store, not just snapshot
resolution. Existing per-attempt items retain their own revisions: diagnostic
aggregate observations must bind actual composed source and actual attempt
contracts rather than relabelling old items. Existing source-review tests may
follow private validation factoring only when they still prove the same common
binding checks plus strict public passed-only verification/nomination.

Bounded metadata allowance after measured code changes: the exact new packet ID
and moving index counts, measured module/edge census with all SCC structural
invariants unchanged, and source-corpus normalized pin/write-up only after two
complete retained measurements. No architecture/evaluator baseline loosening.
The early-root predecessor test suite remains a required regression selection.


## Activation and API freeze - 2026-09-08

PR319 was manually merged under the owner's existing goal authorization at
09:27:15Z, after independent review and all 12 source CI checks succeeded (four
conditional skips). Its four actual Linux ignition lanes each passed329 tests
with10 platform skips. Main24e229c0f34e5404bc219637b646386529f82035 has exactly the
accepted source2ed5a5d0 tree2511549b11cc2266f058ec137783461d62250e6c. Original main
and this isolated successor were fast-forwarded; the user's local Session bytes
were unchanged. Pre-activation draft SHA256: 58966a4ad1c37db173386faa550d2f3ac7b85a4bfe8d2ca3292a03420bad8472. Earlier no-build text
records the completed draft phase. The current release permits writing/fixing
regression tests and capturing one complete frozen red baseline, not production
edits. Root releases implementation only after that baseline is retained.

Frozen kernel API: append only the keyword-only
`status_mode: Literal["passed_only", "from_items"] = "passed_only"` to the
existing `assemble_fourfold_evidence_packet`. Validate closed mode values
before any storage operation. The default retains strict passed behavior;
from_items derives inconclusive for any unverified assurance/cancelled item,
otherwise failed for any failed/error item, otherwise passed. The structural
Fourfold item remains deterministic/passed and still requires a complete actual
snapshot bound to the independently supplied candidate. All old non-status
binding checks factor through one private helper; public verification and both
nomination paths unconditionally require passed. No alternate verifier or
partial-snapshot switch. In from_items, read back every item through actual
ArtifactStore load_locator/verify and require its actual payload SHA to match
output_sha256; never interpret the candidate SourceTreeStore locator using that
other store. Missing/corrupt/foreign outputs refuse assembly instead of being
labelled inconclusive. Packet-byte persistence remains the ignition caller's
responsibility. The independent detailed proposal SHA256 is
fdb9f83b568e7f0a3a0e040ded223e8b5673844872d726bfcbb70d6896a3e0ae.

Frozen real three-run discriminator: after the existing compose_candidate has
returned, and before gate1 computes/captures candidate identity, the test's
first invocation changes the unique data/events.csv value1,125.0 to
1,not-a-number, keeping the renamed header. The candidate is captured and all
checks run normally. This must preserve a complete structural Fourfold while
actual pytest/schema observations fail. The next two invocations use the
unmodified producer, fresh workspaces and shared admitted receipt/source stores.
All three calls happen before the new retention assertions, so an expected
missing negative packet on old source cannot shorten the baseline to one run.
Run2's passing execution cannot claim replay of the negative predecessor; run3
may replay run2. Actual output, packet and exact prior receipt bytes must remain
retrievable after run3. Within each arm freeze fixture, clock, criterion,
interpreter, limits and evaluator bundle; preserve the distinct actual bundle
identities across changed source versions.

The existing negative expectations are updated before the red baseline, with
their original accepted-predecessor assertions/results retained as historical
evidence. All final regression test bytes must then be identical for red/green
unless a named test defect is recorded and both affected arms are remeasured.
No changed test may silently substitute for the frozen baseline.

Frozen focused selection (all paths verified to exist before execution):
`tests/kernel/test_fourfold_evidence.py`,
`tests/kernel/test_fourfold_evidence_adversarial.py`,
`tests/kernel/test_fourfold_evidence_source_review.py`,
`tests/kernel/test_fourfold_evidence_owner_binding.py`,
`tests/kernel/test_fourfold_evidence_outer_ports.py`,
`tests/test_fourfold_snapshot_locator.py`, `tests/test_artifact_store.py`,
`tests/test_ignition_gate1.py`, `tests/ignition/test_voltage_ignition.py`,
`tests/ignition/test_voltage_ignition_faults.py`,
`tests/ignition/test_gate1_root_admission.py`, `tests/test_primary_tree_fence.py`,
`tests/test_ignition_bundle.py`, `tests/test_ignition_bundle_gitattributes.py`.
One complete invocation for red and one for corrected source, identical
selectors, `-q -p no:cacheprovider --color=no` and JUnit, using the original
repository .venv/Scripts/python.exe. The external driver enforces a 900-second
whole process-tree ceiling and records actual elapsed time/exit/timeout/source
hashes. No pytest -x, provider/model calls or relaxed per-attempt limit.


Pre-test-freeze owner seam clarification (2026-09-08): receipt publication
faults and opaque predecessor-byte tests live in the new focused
`tests/test_ignition_receipt_retention.py`, alongside the existing real-door
three-run scenario in `tests/test_ignition_gate1.py`. This keeps independent
writers on disjoint test files; it adds no production owner or subsystem.
Add that new file to the complete red/green selector list above, under the same
900-second ceiling; it must exist before execution. Kernel test owner freezes
private common helper `_fourfold_evidence_binding_mismatches` as the one shared
set of complete source/snapshot/candidate/provenance mismatch checks.

Frozen additive v1 projections: a retained aggregate uses
`evidence_packet.packet_locator = ArtifactLocator.portable_summary()` alongside
its existing packet_sha256/status/items. A latest receipt observing a predecessor
uses `replay.previous_receipt = {"sha256": <exact raw payload SHA>,
"locator": ArtifactLocator.portable_summary()}`. The previous body need not
parse; its exact bytes are the observed artifact. A first run has no such
predecessor reference. No current-receipt self-locator field is added; real
store returns/readback prove storage of final bytes before latest publication.
These fields are references within existing projections, not a new schema or
history index. No unresolved locator is advertised.


## Retained red and pre-production correction - 2026-09-08

The first full frozen selection completed in244.125s: 63 failed,340 passed,
12 platform skips and6 setup errors; no watched source/test bytes changed.
All three actual candidate runs completed under one bundle; the first produced
real pytest/schema failures and a complete snapshot but no packet. Its exact
outputs, candidates, receipts and measurements are retained in red/.

The six compiler-case setup errors are a test defect, not product evidence:
the sentinel omitted required canonical ArtifactStore provenance fields.
Correct only that fixture, retain old/new hashes, and rerun its whole file
on unchanged source before implementation. Add the two promised output/packet
CAS-publication fault cases in tests/ignition/test_gate1_evidence_publication_faults.py.
This supplementary selection gets one red and matching green, same900s external
ceiling and unchanged per-door limits. The original14 unaffected test files
stay byte-identical; the affected compiler file compares with its explicitly
retained supplementary red. The first result and driver bytes are not replaced.

Actual output or packet persistence/verification failures propagate a named
refusal without publishing a new latest receipt; old latest bytes remain exact.
Structural or missing-contract refusal may publish an honest absent-packet
receipt when material storage succeeds. This resolves publication ordering
within the original acceptance claim; it grants no recovery authority.


Implementation release: initial and supplementary red artifacts are retained.
The supplementary selection completed in67.438s with5 expected failures and
9 passes, no setup errors or skips. Only gate1.py and fourfold_evidence.py
changed in production. Root reviewed the kernel status/helper diff; independent
runtime and receipt reviewers found no blocking defect. The corrected-source
comparison uses the frozen original14 test files, the corrected fault file
against supplementary red, and the unchanged supplementary publication cases.
Exact source hashes and byte-preserving output logs are retained before running.
A readable ReferenceCompileError is recorded as a refusal under the compiler's
declared input contract; generic exceptions remain unverified/inconclusive.
Receipt bytes use opaque observation media type, including malformed history.

The first corrected-source invocation is retained as NONPASSING:407 passed,
2 failed,12 skipped in255.235s. The complete real three-run retention case
passed. Both remaining compiler-diagnostic cases return no packet. Static
source/contract inspection identifies a construction error: ResourceUsage
requires integer wall_time_ms, while measured compiler time was passed as float.
Full stdout/JUnit/source and three-run raw artifacts are retained; individual
compiler temporary receipts were already absent at follow-up lookup and are
not claimed archived. A new source revision rounds measured milliseconds once
at the exception boundary. Contracts, tests, criteria and budgets are unchanged.
This revision receives one full frozen15-file invocation under the same900s
ceiling in green-ms-correction/. This is a recorded code correction, not an
identical-source retry, selective failing-test rerun or budget change.

The final full source comparison passed409 tests with12 platform skips in
277.531s, without watched source or test drift. The additional material-fault
comparison remains a separately retained equal-budget selection.

CI coverage wiring is included in this packet: .github/workflows/gate1-ignition.yml
adds the new receipt tests plus existing adversarial/source-review/owner/outer-port
Fourfold and storage/locator regressions to its existing Python3.10/3.12, seed0/123456
Linux matrix and matching path triggers. Existing tests/ignition/ already selects
the new material-publication cases. This changes test selection only; no evaluator
criterion, policy, workflow permission, platform, seed, or limit is relaxed.

The initial supplementary green is retained as12 passed/2 failed in76.125s.
Both new material-fault cases reached the intended fault and preserved all prior
bytes, but then compared pre-check revision to the mutable post-check workspace.
The actual archived candidate has8 captured source files unchanged and exactly
3 added Python bytecode caches. The recorded8/11-file digests reproduce both
failures. Fix only test observation timing: compare actual capture/compile-entry
measurements and the retained source manifest. Keep every material/CAS check.
Remeasure that exact corrected two-case file once on an isolated original24e
worktree (all485 production hashes match originalred) and once on finalsource,
with the sameclock/criterion/300s per-door/900s external limits. The prior
supplement and originaltestbytes remain retained; no15-file test or product
change is needed for this correction.

All102 additional existing Genesis/approval/facade consumer cases passed without
source/test/fixture drift. The frozen four mutations were all caught by their
named tests, three matching controls passed, all loaded source paths/hashes
matched actual canonical sandboxes, and no timeout occurred. Their captured
Python source artifacts are losslessly gzipped to avoid becoming new producers
under the tested checkout's runs directory.

## Local acceptance outcome - 2026-09-08

Final production SHA256s: gate1.py
5f2e95487c34890fbef9aad2d62d3dce09e2b179ec2d4fc3514879e19c7518be;
fourfold_evidence.py
1367e64484514968eb8b710da25d15bbcd021b3ed80a24a39309916105860d19.

The corrected publication pair is complete: original source2 expected failures
in21.609s, corrected source2 passes in21.203s, with identical final test bytes,
fixture, criterion, interpreter, clock and bounds. The original source restores
all485 production hashes from the full red; no test or source drift occurred.
Together with the15-file final suite, local focused acceptance is411 passes
and12 platform skips. Additional unchanged consumers give102 passes without
skips. The three matching mutation controls pass and all4 named mutants are
caught; all7 actual loaded module path/hash proofs and307 retained artifacts
were independently checked. No mutant, timeout or negative observation is omitted.

The observed failure/success/success sequence retains exact prior item, packet
and receipt bytes in the existing mission ArtifactStore. Only the third run
replays a complete passed predecessor. Known compiler refusal is failed; unknown
compiler failure is error/unverified/inconclusive; absent contract binding yields
a named absent-packet refusal. Public passed verification/nomination stays strict.

This is local source acceptance for negative-evidence retention. GitHub source
CI and reviewed manual main integration are still required before the source
handoff. It does not close Gate1, establish same-ID
process recovery, or promote a candidate. Gates2/3 remain subsequent work.

## Final source review and measured metadata - 2026-09-08

Final review makes paragraph3's failure boundary explicit: failures before
successful atomic latest replacement preserve the prior latest bytes. Once
replacement succeeds, a failed read-back refuses success but may leave the new
latest visible. Its exact bytes and the predecessor bytes were already retained
and verified in CAS. This clarifies the earlier broad publication wording;
it adds no rollback, recovery, concurrent-writer or power-loss guarantee and
changes none of the frozen pre-replacement fault assertions or production bytes.

Two complete existing s02 probes agree after removing only their wall_seconds
fields: non-timing SHA256
e15c50747fb071f4973faa294059dcb2dd85ac03f4580ce6b86af5867bad6307.
All six corpora remain declared; four are present in the current interpreter.
Missing fastapi/anyio and bs4/click groups are explicitly retained as unavailable.
Kernel census:485 files,6778 functions,45190 type sites; source pin
d6b652d970c1a5a63a3b8d3960da54befd6eaa440b2ee3122e466a1ee6a8358e.
The import census remains485 modules, with1932 edges: the sole new edge is
gate1 -> daedalus.atomic. All14 nontrivial components, maximum19 members and
exact component digest841a5a979ea07aa45acdf7ab8ed7f2a3841c2e81c80d6b2974e1ba53c2140a78
are unchanged. Only measured moving values and this packet's registry entry
are updated. All production and16 frozen functional test hashes remain exact.
Metadata/index/workflow regression results are recorded in acceptance.json.
