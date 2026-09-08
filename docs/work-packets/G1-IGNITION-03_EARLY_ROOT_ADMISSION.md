# G1-IGNITION-03 - Early root admission for the shipped ignition door

Packet ID: `G1-IGNITION-03`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `bf69e7195eba4d2c161e61aaead6aaa5695ab5bc`
Dependencies: `G1-INTEGRATION-01 main integration and combined acceptance; G1-RENOVATION-02A shipped-door fault matrix; existing primary_tree containment primitive`
Status: local acceptance passed with independent review; source CI and integration pending
Promotion: not requested

Draft review additions before baseline or implementation (2026-09-08):
the build remains dependent on the reviewed main integration. The following
clarifications narrow path admission; they do not change the Master Plan.

- Windows root arguments admit ordinary local drive paths only. Reject UNC
  paths, administrative shares and DOS-device/extended namespace prefixes
  before comparison or writes. Reject components ending in a dot or space,
  apart from the syntactic `.` and `..` components normalized normally. These
  spellings can alias two missing prospective paths even when `resolve()`
  returns different text. Add actual temporary missing-root alias controls;
  do not infer coverage from symlink/reparse checks alone.
- Derived path checks preserve their types: an existing regular
  `M/receipt.json` remains legitimate retained evidence for replay; directory
  rules apply to `M`, `E`, `C`, `objects` and `bundle`. An unexpected link or
  wrong type still refuses before any writer.
- Selecting the default scratch parent must itself remain read-only. An
  uncached `tempfile.gettempdir()` can create/delete probe files, so it cannot
  precede admission. Select an existing configured or platform temp parent
  without probing writes, choose a prospective scratch leaf, validate that
  exact path, and allocate it only after admission. Acceptance trips both temp
  discovery and actual allocation to verify first-write ordering.
- Pre-baseline scope correction (2026-09-08, parent agreement): comparing two
  prospective missing roots needs an additive comparator in the canonical
  `daedalus/primary_tree.py` module and meaningful regressions in
  `tests/test_primary_tree_fence.py`. The existing `planned_overlap_reason`
  contract remains unchanged. The dated revision record below preserves the
  counterexample, the superseded scope restriction and the exact added matrix.

Master Plan Revision 13 SHA-256:
`04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`.
This applies the existing working agreement in `AGENTS.md`, Master Plan
sections 4, 10, 11 and 15, and `G1-WP-INDEX-01` metadata contract.

Task agreement: prepare this reviewable draft while PR 318 integration
acceptance is running. Do not begin production edits or execution baselines
until the parent confirms that the integrated source is on main. If that merge
changes the owning paths, record the new exact build base and review the
differences before running the frozen baseline; do not silently move this base.

## Primary acceptance claim

The shipped `run_gate1_ignition` rejects a dangerous directory topology or a
nonempty supplied workspace before the first reset, mkdir, copy, store
construction, command dispatch, or other write belonging to the run. A refused
invocation leaves source, prior receipts, evidence, source CAS and workspace
sentinels unchanged. The independently callable `prepare_ignition_repo` also
rejects a destination that overlaps its source or installation before copying.

This is entry-time directory admission. It does not claim handle-anchored
filesystem isolation, protection against a concurrent path replacement after
admission, complete hard-link defense for arbitrary old receipt contents,
same-attempt recovery, durable terminal evidence, or closure of Gate 1.

## Scope

Allowed during the later authorized build phase:

- `daedalus/ignition/gate1.py`: one read-only ignition-local layout preflight,
  ordered before the current first writer; direct preparation guard; passing
  the admitted normalized paths to existing writers.
- `daedalus/primary_tree.py`: an additive comparison for two prospective
  directory roots, reusing the canonical resolution, directory identity and
  nearest-existing-ancestor machinery. Keep the existing public predicates,
  including `planned_overlap_reason` and its missing-protected-root refusal,
  unchanged; no general fence refactor or new policy authority.
- `tests/test_primary_tree_fence.py`: paired positive/refusal regressions for
  the additive comparator, real supported alias cases, and explicit protection
  of the existing predicates' contracts, as frozen in P1-P9 below.
- New `tests/ignition/test_gate1_root_admission.py`: topology and effect-order
  sentinels, real directory alias cases, positive layout controls.
- `tests/ignition/test_voltage_ignition_faults.py`: strengthen the existing F5
  and debris assertions while retaining their recorded negative baseline.
- This packet and its bounded evidence directory after execution is authorized.
- `docs/work-packets/index.json` only through the existing deterministic
  generator when the draft is admitted to tracked integration.
- The exact F5 evidence paragraph in `docs/work-packets/G1_ACTIVATION_CHECKLIST.md`
  only after the acceptance evidence passes; no other gate status changes.

Forbidden: Master Plan, amendment chain, AGENTS.md, policy, Effect Registry,
leases, contracts, scheduler, evaluator rules, source CAS implementation,
promotion, provider code, generated architecture baselines, new state stores,
and changes to the historical `ignition.runner` rehearsal. Changes to existing
`primary_tree` predicate contracts and an ignition-local copy of filesystem
overlap geometry are also forbidden. No production file, test, historical
evidence, checklist or registry is edited in this draft phase.

## Contracts and behavior

Let `S` be the existing source fixture, `W` the effective scratch workspace,
`R` the receipt root, `M = R / SESSION_MISSION_ID`, `E = M / "store"`, and
`C` the source CAS root (default `M / "source-trees"`). `C / "objects"`,
`M / "bundle"`, and `M / "receipt.json"` are reserved derived output paths.

Inspect raw roots and their existing ancestor components before normalization.
Refuse symlinks, Windows junctions/reparse points, uninspectable components,
existing non-directory roots, or resolution failures. The existing read-only
`lstat`/`S_ISLNK`/Windows reparse-bit pattern at
`kernel/policy/computer.py:217` is a reference, not a reason to import computer
policy as another authority. Validate derived paths as well as arguments: a
real `R` may contain a linked mission or evidence directory, and a real `C`
may contain linked `objects`.

Use `primary_tree.planned_overlap_reason` for each planned write root against
the existing protected fixture and for `W` against installation `ROOT`. It
already handles both containment directions, aliases, and missing planned
leaf directories without incorrectly refusing fresh siblings. Do not replace
it with a one-direction string-prefix test. For a pair with one existing root,
use the existing predicate with that root as its protected second argument;
preserve the existing path-admission checks before calling it.

For two not-yet-created roots, use the additive canonical comparator. It must
compare the identities of examinable existing ancestors together with the
remaining intended path segments, preserving equality and both ancestry
directions. A shared existing ancestor alone is not an overlap. Unknown ground
or resolution failure remains a refusal, not evidence of disjoint paths.
Expose the relation needed for the permitted directional `C/R` nesting without
making ignition parse diagnostic prose or reimplement path geometry. Keep
ordinary source/installation checks on the existing predicate and keep raw
alias/type admission in ignition. Do not feed a missing protected root to the
existing-root-only predicate, replace intended roots with their ancestors,
create directories to make comparisons possible, or silently relocate a root.

The private `kernel.attempt_workspace._resolve_workspace_parent` is not a
drop-in boundary: it requires a pre-provisioned workspace and source store.
Ignition currently accepts a fresh or empty supplied workspace and provisions
its CAS itself. Reuse the canonical comparison and keep that public behavior,
rather than importing the Attempt coordinator or constructing stores merely
to validate their paths.

Frozen topology rules:

| Pair / path | Admission |
| --- | --- |
| `S` with `W`, `R`, `C`, or derived writable paths | Reject equality and ancestry in either direction, including resolved aliases. |
| `W` with `R` or `C` | Reject equality and ancestry in either direction. |
| `W` with installation `ROOT` | Reject equality and ancestry in either direction, also when `S` is external. |
| Direct prepare destination with `S` or installation `ROOT` | Reject overlap before `copytree`; preserve existing refusal when destination already exists. |
| `E` with `C` | Require disjoint paths in both directions; CAS must never occupy the evidence reset subtree or contain it. |
| `C` with `R` | Allow a disjoint external CAS or a strict descendant of `R`; reject equality or a CAS containing `R`. |
| CAS beneath `R` | Keep it disjoint from reserved receipt file and bundle subtree as well as `E`; default `M/source-trees` is valid. |
| Supplied `W` | Allow absent or existing empty real directory; reject any existing child, including hidden entries, files and links. |

Default receipts under installation `ROOT/runs/ignition` remain valid. Do not
apply the workspace-versus-installation prohibition to that established
operator output namespace. `E = M/store` and `C = M/source-trees` are valid
siblings inside one mission receipt directory; requiring all four top-level
roots to be pairwise disjoint would incorrectly prohibit every default run.
Replay may reuse `R` and `C` with a fresh workspace, preserving current receipt
and source-CAS behavior after admission succeeds.

Complete the read-only checks before `_reset_evidence_store`, `SourceTreeStore`
construction, `scratch.mkdir`, or `tempfile.mkdtemp`. Default workspace
selection must yield a prospective uncreated leaf for admission; its allocation
cannot be the operation used to discover that other supplied roots were unsafe.
Freeze the resolved paths used by the run and keep the existing cleanup rule:
only an automatically allocated scratch workspace is eligible for automatic
cleanup. No failed layout is retried, reset, silently relocated, or repaired.

Requiring an empty supplied workspace covers all current debris targets:
`target`, `candidate`, `candidate.tar`, `patch-N.diff`, `spine.sqlite3` and SQLite
sidecars, `controls`, and `coverage`. This deliberately refuses an arbitrary
nonempty workspace too; the existing API has no supported resume-over-debris
contract. It preserves pre-created empty directories used by callers/tests.

## Acceptance matrix

All generated source/receipt/CAS content and destructive mutations are confined
to pytest-owned temporary roots. No provider/model/vendor command or network
request is part of the packet. Budget: ten minutes per focused invocation and
twenty minutes for the affected real shipped-door suites; retain timeouts and
missing-platform evidence as failures or unmeasured cells, never green results.

| Cell | Frozen discriminator and expected behavior |
| --- | --- |
| A1 | Parameterize equality and both ancestor directions for each forbidden pair, including both roots missing as well as one or both existing. Reject before any writer; use the canonical comparator cases P1-P9. |
| A2 | Relative `.`/`..`, Windows case aliases and real directory symlink/junction cases resolve to the same forbidden relation and refuse. Raw reparse components also refuse before `resolve` erases their spelling. |
| A3 | A safe-looking receipt root with redirected `M`, `E`, bundle or receipt path, and a safe-looking CAS with redirected `objects`, refuse before reset or constructor. |
| A4 | Seed eligible `E/blobs` and `E/locators`, a prior `receipt.json`, prior CAS object, source bytes and workspace files. On every invalid layout, compare path sets, contents and retained file identities; old evidence must survive unchanged. |
| A5 | Put each reserved debris name into `W` independently, including archive, patch and SQLite sidecars and hidden files. Refuse before touching preexisting `R/E/C`; unrelated nonempty `W` also refuses. |
| A6 | A direct `prepare_ignition_repo(S, destination)` with equal/ancestor/descendant or aliased destination refuses before `copytree`, Git or test seeding; safe missing sibling destination still prepares successfully. |
| A7 | Positive controls: absent and empty explicit `W`; fresh default `W`; existing replay receipts/CAS; default sibling `E/C`; safe separate external CAS; safe strict child CAS under receipts. Include all of `W/R/C` absent and default `E/C` absent beneath an absent mission directory, with no preparatory mkdir. |
| A8 | Negative custom CAS controls: `C=R`, `C` contains `R`, `C` equals/contains/is inside `E`, and CAS overlaps reserved receipt/bundle paths. Retain all preexisting evidence. |
| A9 | First-effect tripwires around reset, store construction, scratch allocation and direct copy prove ordering. On the unmodified base, deliberately stop at the first writer so the red probe does not damage a source checkout. |
| A10 | Real shipped-door F5 row becomes early-and-clean refusal; fresh-workspace replay retains existing candidate/graph identity evidence. This does not claim same-attempt resume. |
| A11 | Mutation: move preflight below evidence reset, remove the contains-direction check, remove derived-path checking, and bypass the direct prepare guard one at a time. Each targeted regression must turn red; restore exact bytes in `finally`. |
| A12 | Existing canonical planned-root tests, ignition legacy suites, packet metadata/index and scoped diff checks pass; supported Windows and Linux alias coverage is stated separately. |
| A13 | The additive prospective-pair comparator passes P1-P9 below while existing `planned_overlap_reason` behavior remains unchanged, including refusal for a missing protected root. |

Baseline commands, to run only after the parent releases the build phase from
the frozen worktree using the existing repository virtual environment:

```powershell
$ignitionPython = 'C:/Users/Administrator/Desktop/projects/daedalus/.venv/Scripts/python.exe'
& $ignitionPython -m pytest tests/test_primary_tree_fence.py tests/test_ignition_gate1.py::test_work_items_come_from_the_four_plane_manifest tests/test_ignition_gate1.py::test_plan_refuses_a_manifest_whose_code_plane_lost_the_symbol -q -p no:cacheprovider --color=no
& $ignitionPython -m pytest tests/ignition/test_voltage_ignition_faults.py::test_a_workspace_nested_inside_the_source_is_refused tests/ignition/test_voltage_ignition_faults.py::test_restart_over_debris_refuses_and_a_fresh_root_replays_identically -q -p no:cacheprovider --color=no
```

Freeze the new A1-A9 and P1-P9 regression tests next and run them on the unchanged
production base with first-effect tripwires before implementing the checks.
The new file must exist before invoking its test command. Final command adds
`tests/ignition/test_gate1_root_admission.py`, both full shipped-door suites
`tests/ignition/test_voltage_ignition.py` and
`tests/ignition/test_voltage_ignition_faults.py`, and
`tests/test_ignition_gate1.py` to the canonical fence tests. Capture raw stdout,
stderr, exit status, exact revision and JUnit; no `-x` and no accepted red
baseline substitution. Unavailable real symlink/junction creation is an
explicit unmeasured platform cell, not replaced by a mocked alias claim.

## Migration and rollback

No ledger, CAS format, receipt schema, evaluator or policy migration. Valid
fresh-workspace calls retain the current API and default storage layout.
Invalid layouts receive an earlier `IgnitionError` identifying the conflicting
roles, instead of later fixture-digest failure or destination-exists failure
after evidence was already reset. Preserve the original negative evidence and
name the intentional tightening to empty supplied workspaces in the handoff.

Rollback is a scoped revert of the implementation/tests/checklist evidence
commit. It does not delete generated evidence or restore old store bytes.
This draft alone is reversible by removing this untracked packet; it has not
changed code or registry authority.

## Evidence expected failures and review

Read-only audit at the pinned base; no baseline execution is claimed here:

- `gate1.py:182-196,763` resets eligible evidence before workspace admission.
- `gate1.py:764-767` resolves away the custom CAS spelling and constructs the
  store; `kernel/source_trees.py:274-283` calls mkdir in that constructor.
- `gate1.py:370-388` direct preparation checks existence but not source overlap.
- `gate1.py:550-580` creates the candidate and writes/unlinks archive and patch
  names; `gate1.py:915` uses the workspace ledger; controls at `1487-1502` and
  coverage controls at `1594-1597` include recursive cleanup of reserved paths.
- `tests/ignition/test_voltage_ignition_faults.py:104-146` explicitly retains
  the F5 late pollution baseline. The debris row at `58-91` checks fixture and
  debris preservation but does not seed prior evidence to catch premature reset.
- Independent reviewer `runtime_branch_review` reproduced `workspace=ROOT`
  reaching the first reset through a no-write tripwire and confirmed the derived
  path/reparse and debris findings. This report is advisory source evidence;
  the frozen acceptance commands must produce independently retained test data.
- Reviewer found no shipped path requiring nonempty supplied `W` or permitting
  a preparation destination inside installation `ROOT`; existing test callers
  use absent/empty temporary workspaces and default sibling CAS/evidence.

Review questions: Are all effective and derived roots checked before the first
writer? Is the canonical planned-root comparison actually reused? Does every
invalid invocation preserve eligible old evidence, not just source files?
Are raw alias checks performed before normalization? Are missing planned roots
handled without requiring provisioning? Do default receipts/CAS and real
replay still work? Are entry-time checks described honestly without a TOCTOU,
hard-link, sandbox, atomic-Project-Twin or Gate-close claim?

Blocked chain step: baseline/build awaits completion of the parent main source
integration and its explicit continuation signal. This is the current task
agreement, not a request for another user approval or a new policy boundary.

Iron Plan: ALIGNED. Iron Gate: 1. Evidence: read-only audit and frozen draft.

## Draft revision record - 2026-09-08: two prospective roots

This is an explicit parent-agreed scope correction before baseline or build,
not a Master Plan amendment. The earlier draft required `primary_tree.py` to
remain untouched and proposed an unspecified local relation over resolved
prospective paths. Those two instructions did not provide the required
single-source comparison for valid layouts whose two roots are both missing.
The narrow allowed-path additions and replacement behavior above supersede
those draft instructions; the original reason is retained here.

Source-derived counterexample at the unchanged base
`b605586b2778659a119b25fa7d05938a986356e3`: let `P = C:/scratch` be an
existing examinable directory, with both `P/new-work` and `P/new-receipts`
absent. These intended sibling directories are disjoint and must be an A7
positive. Nevertheless, `planned_overlap_reason(P/new-work, P/new-receipts)`
calls `_inside(target, root, probe=True)` at `primary_tree.py:401`.
The lexical equal/inside cases do not match; `_identity(root)` at lines
207-209 cannot inspect the missing protected root and returns
`_OUTER_UNEXAMINABLE`. The public result is a refusal rather than `None`.
Reversing the arguments or resolving them first produces the same obstruction.
The valid initially absent siblings `E = M/store` and `C = M/source-trees`
have the same problem. No function call or test was executed to establish this
record; it is a trace through the read source, not measured runtime evidence.

Existing `tests/test_primary_tree_fence.py:233-287` exercises a missing planned
root against a protected repository that the fixture/test already created.
It does not prove the two-missing-root positive. The existing predicate's
missing-protected-root refusal remains correct for its current contract and
must not be weakened globally to accommodate ignition.

The new comparator stays in `primary_tree.py`, with no filesystem writes and
no separate store, policy, state or geometry owner. The exact added matrix is:

| Cell | Inputs and discriminator | Required result |
| --- | --- | --- |
| P1 | An existing temporary `P` with absent siblings `P/new-work` and `P/new-receipts`, then absent siblings under a shared missing intermediate directory. Compare in both orders; also use names where one is only a string prefix of the other. | Disjoint; no directory created. A common existing ancestor or string prefix must not cause refusal. |
| P2 | The same absent intended root twice, including equivalent normalized `.`/`..` spellings and supported Windows case spellings. | Equality/overlap, in both argument orders; no writer reached. Raw spellings disallowed by ignition still refuse at its earlier admission boundary. |
| P3 | Absent `P/new-root` and absent `P/new-root/child`, compared in both orders. | Correct contains/inside relation in the corresponding order; reject either ordering for a forbidden pair. No missing-path inspection error may replace the relation needed by the caller. |
| P4 | Absent `W` and `R` siblings, absent `M = R/SESSION_MISSION_ID`, and absent default `E = M/store`, `C = M/source-trees`; separately an allowed strict descendant CAS and a disjoint external CAS. | Preserve the valid A7 layouts, including allowed directional CAS nesting, without provisioning any root during comparison. |
| P5 | One root existing and one missing, then both existing; pair disjoint controls with equality/ancestry refusals. Separately call the old predicate with a missing protected sibling. | Reuse existing semantics when the protected root exists. The old `planned_overlap_reason` still refuses a missing protected root; only the additive comparator supports the new two-prospective contract. |
| P6 | Two real supported alias spellings of existing ground, extended with equal, ancestor/child and distinct prospective tails. Keep canonical alias tests separate from ignition's stricter raw reparse/namespace refusals. | Equal/ancestral intended destinations overlap; distinct sibling tails remain disjoint. State unavailable real platform alias coverage explicitly; do not replace it with a mocked claim. |
| P7 | Uninspectable existing ground, failed resolution or an existing non-directory component, paired with lexically disjoint prospective names. | Named refusal before any write; inability to establish the ground must not become a disjoint result. Preserve invocation-owned file/path sentinels. |
| P8 | Invoke canonical comparison and shipped ignition layout preflight with first-effect tripwires around temp probing/allocation, reset, store construction and direct preparation; cover P1 positive and P2/P3/P7 refusals. | Comparison/preflight itself performs no write. Invalid layouts cannot reach a writer; valid layouts reach allocation only after all effective and derived roots have been admitted. |
| P9 | Independently mutate away prospective tails, remove one ancestry direction, and admit an uninspectable ground, using temporary source copies and exact-byte restoration. | P1/P6 positives or P2/P3/P7 refusals turn red for the corresponding defect. Retain the negative result; do not weaken a positive control to accept overrefusal. |

P1-P9 supplement A1-A13 and retain the same packet budgets and evidence rules.
Only this untracked draft was edited for this revision. Production source,
tests, registry and historical evidence remain untouched. Baseline execution
and implementation still await parent confirmation that the reviewed
integration is on main; this record does not release that dependency or claim
any acceptance cell has run.


Pre-baseline integration metadata clarification (2026-09-08): root may update
only the measured moving censuses required by this source/document change:
`tests/contracts/test_work_packet_index.py` with the rendered index totals and
exact new packet ID; `tests/contracts/test_import_scc_hierarchy.py` module/edge
counts after an actual complete graph measurement; and the s02 normalized
source corpus pin/write-up after two complete retained measurements. The
existing SCC count, maximum, component membership and component digest remain
fixed; no new cycle or architecture regression is waived. The new canonical
import from ignition can add an acyclic edge, so a moving edge count must not
be mistaken for a fixed architectural boundary. These are bounded accounting
followups, not permission to regenerate or loosen architectural/evaluator
baselines. Include existing metadata/SCC/corpus checks in final acceptance.


Pre-baseline known output-file clarification (2026-09-08): the existing regular
`M/receipt.json` is legitimate only with a single filesystem link. Refuse a
hard-linked receipt file before the first writer: the current latest-receipt
writer can truncate that file before the later retention packet switches to
atomic replacement. Directory-root comparison cannot detect a file hard link
into the protected source. Add an actual temporary `os.link` case binding the
receipt to a fixture file and verify both names, link counts and bytes survive
refusal; retain the ordinary single-link receipt positive. An unavailable real
hard-link facility is an explicit unmeasured platform case. This bounded check
for the known output file does not claim complete hard-link defense for arbitrary
old store contents, nor does it pull receipt-publication redesign into this packet.


Activation record (2026-09-08, after main merge; before this packet baseline):
PR318 was manually merged under the repository owner's instruction at08:39:34Z.
Accepted integration head9867c7020e7cabbcc1c6c9f83b2051b153720d62 had22 successful
CI jobs and4 expected conditional skips, including257/257 unskipped real Windows
GUI cases and both real Linux OCI/procfs/54-case Genesis proofs. The complete
local suite on its source5d6c82ad passed13,491 tests plus2,237 subtests, with419
skips and23 expected failures, and no changed source files during the run.
Main mergebf69e7195eba4d2c161e61aaead6aaa5695ab5bc has exactly that accepted tree;
original main was fast-forwarded with the user's dirty Session file unchanged.
The isolated packet branch was then fast-forwarded to this exact main commit.
The original draft baseb605586b2778659a119b25fa7d05938a986356e3 is retained here;
its owning ignition/primary-tree code was not changed by the integration's
WAL/Podman corrections. Header base now names the actual activation source.
Earlier draft-phase no-build statements describe the completed planning phase.
Root now releases only this frozen packet's baseline, build, review and bounded
acceptance. No later dependent packet or Gate transition is released by this
record. The complete pre-activation draft SHA256 was
c88a9f29ddedae058928aed4f749c28aadcb944fb82ad634cdf50af7405c2eb1.

Pre-regression API and case freeze (2026-09-08, production still at main):
`primary_tree.PlannedRootRelation` is a string enum with `DISJOINT`, `EQUAL`,
`INSIDE`, `CONTAINS`, and `UNKNOWN` values (`disjoint`, `equal`, `inside`,
`contains`, `unknown`). `compare_planned_roots(left, right, *,
right_is_file=False)` returns the left root's relation to the right root.
The optional file mode admits only a regular or absent right-hand file leaf;
its parents remain directories. Ignition uses this bounded mode for the known
receipt output so a legitimate ordinary replay receipt is not overrefused.
Unknown or invalid ground never establishes disjointness.

Reviewer cases frozen before writing the new regression suite: raw Windows
drive-relative paths, DOS reserved component names and ADS/colon components
refuse; inspect existing raw components even before a following `..` could
erase their spelling. Explicit empty workspace/CAS arguments refuse instead
of choosing defaults. Check known `E/blobs` and `E/locators` directory heads
alongside the already listed derived paths; this is not a recursive audit of
old store contents. The configured default temporary parent is authoritative
for that invocation: unsafe or uninspectable configuration refuses instead
of falling through to another parent. Allocate exactly the admitted prospective
leaf, without another name choice or write-probe discovery. Freeze these
negative cases with valid single-link receipt/default and nested CAS controls.
The legacy shipped-door baseline completed with 4 passed in 46.22 seconds;
the unchanged canonical fence baseline completed with 26 passed and 1 explicit
platform skip. New A/P regression baselines must still run against unchanged
production before either owner starts implementation.


## Implementation and local acceptance record - 2026-09-08

Production remains within the frozen two owners: additive typed prospective
root comparison in `primary_tree.py`, and read-only raw path/layout admission
plus direct preparation guard in `ignition/gate1.py`. All old canonical public
predicate implementations remain unchanged. Effective paths are resolved once
for the invocation and passed to existing writers. The default scratch name is
chosen before admission and that exact leaf is created afterwards; only an
owned automatic scratch remains eligible for cleanup.

The new A baseline on unchanged main had 73 failures, 11 positive passes and
8 actual Windows symlink privilege skips. The P baseline had 39 new-API
failures, 26 old passes and 2 symlink privilege skips. Baseline source and test
hashes, earlier baseline versions and the original F5 late-pollution result are
retained. First-writer tripwires prevented unsafe baseline writes.

Final affected Windows selection: 235 passed, 10 platform skips in 138.35s,
with all five production/test source hashes unchanged during execution.
The first affected run retained one obsolete crash-restart message assertion;
the intended early empty-workspace assertion then passed both the complete
real crash/replay row and this complete affected rerun. Packet index and
actual evaluator-bundle suites passed 62 tests. Moving metadata checks passed
11 tests: 485 modules/1,931 edges, unchanged 14 SCCs/maximum19/membership/digest;
two complete source-corpus measurements agreed outside timing fields. The
normalized corpus pin is
`af8997cf93e2ff07e6440498667bbed657f72f40b34d5fdf9e6859f4b77ab41e`.
These measurements are census maintenance, not a research improvement claim.

Independent first-writer harness: 17 passed, one unavailable Windows symlink
case. A separate allocation observation verified the actual selected leaf,
mode and exclusive creation. Three canonical P9 and five ignition A11/A9
mutants were all caught from green controls, with the same complete selection
and 120-second limit within each track. Every loaded mutant path and source
hash was verified in the isolated canonical Sandbox. Two rejected path-proof
controls are retained: the observed module was inside the sandbox, but its
resolved `Administrator` spelling differed from the expected `ADMINI~1`
spelling. Resolving the expected path corrected the proof; the initial import
hypothesis is explicitly superseded. No shared source was mutated.

Final actual Linux matrix: 146 passed, 12 Windows-only skips, including actual
symlink/hardlink execution. Source image, fixture bytes and all 5,090 snapshot
file hashes were fixed and unchanged. Execution used an unprivileged UID,
read-only source, no network and a 4-GiB temporary filesystem. The first small
filesystem violated the existing store free-space prerequisite; that negative
was retained. An old contains-message assertion failed identically on exact
main `bf69`; only its expected set of the existing platform-specific contains
messages was clarified. The 17 prospective tests/helpers were AST-identical
across that clarification, preserving the P9 test binding. Production was
unchanged. Independent review verified these platform and mutation records.

The exact F5 checklist paragraph now records this bounded early-admission
closure. Historical surrounding Gate-1 gaps remain outside this packet. The
manifest and deterministic compressed raw evidence are in
`docs/evidence/G1-IGNITION-03/acceptance.json`. Parent integration's final CI
and reviewed main merge proofs are also retained under `G1-INTEGRATION-01`;
that evidence handoff changes no production behavior. Source CI and the
reviewed source merge remain pending at this record; no Gate transition or
later packet build is implied by local acceptance.
