# G1-IKARUS-COMPUTER-01 — General tool execution

Packet ID: G1-IKARUS-COMPUTER-01
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: owner-approved amendment 012 and G1-IKARUS-17; existing kernel effect, lease, policy and canonical artifact contracts

Iron Plan: ALIGNED with owner-approved amendment 012.
Retained uncommitted work. Branch: codex/ikarus-computer-assistant-20260905.

## Primary acceptance claim

Primary claim: explicit computer tasks reach a trusted tool adapter only after
canonical policy and persisted effect admission, and report observed results.

## Contracts and behavior

The adapter uses owner-configured roots, tools, application identities and
origins. Defaults grant no computer capability. No candidate executes this
adapter, and its policy lives outside candidate workspaces. For v0.1.6, a
central release fence removes every file tool and path-based vision/skill read
from both effective admission and advertised capabilities. Legacy policy
grants remain readable for migration but cannot override that fence.

## Scope

Scope: kernel computer policy, canonical effect inventory/lease scope, computer
runtime service, Ikarus loop and command routing, optional dependency extra,
focused tests and desktop capability presentation. Dependent CV/desktop/browser
adapters are separately verified before activation. Preserve existing routes
and unrelated changes. No automatic merge/promotion or external submissions.

## Evidence, expected failures and review

Baseline: existing tool projection/effect bridge/supervisor 29 passed; no
OpenCV import, capture or computer adapter in inspected runtime modules.

Independent review must challenge scope escalation, evidence integrity,
duplicate effects and actual versus advertised capability availability.

## Acceptance matrix

Acceptance: disabled path tools cause no effect or lease and are absent from
capability projection; deterministic ancestor swap does not reach an adapter;
observation-backed vision schemas contain no path alternative; setup and
legacy stored grants cannot reactivate path I/O; operation/policy drift is
refused; cancelled or expired work stops; canonical start and terminal
receipts are retained; no hidden remote context; model success cannot
substitute for tool evidence. Historical scratch-file execution is retained as
negative development evidence, not as a v0.1.6 release capability. Run focused
existing kernel and Ikarus suites after integration; retain baseline failures
separately.

## Migration and rollback

Rollback: disable computer policy for new tasks; retain effects and reconcile
interrupted operations. Delete only this packet's changes to reverse code.

## Measured delivery, 2026-09-05

Implemented during development: owner-scoped file adapters; fixed native
application launch and Windows foreground-window observation/input; isolated
static browser navigation/read/fill/click; local OpenCV image inspection,
template matching and changed-region detection; native local Windows OCR;
schema-constrained Ikarus planning; explicit product notes and an inert skill
projection; one-shot schedules through the existing Kairos/File Bridge worker.
After the ancestor-swap finding, every file adapter, path-based vision adapter
and skill-directory reader is release-disabled for v0.1.6. State remains in
canonical leases, SpineLedger and CAS. No candidate process, generic shell,
evaluator access, second event store or automatic promotion was added.

The `computer` extra was installed into both the Python 3.10 test environment
and the project's Python 3.13.14 `.venv`, with Chromium available. Core imports
keep these dependencies optional. The existing desktop distribution was not
rebuilt; the web build reports ThemeStudio.tsx references to missing
`ThemeSpec.scene` at lines 140, 260 and 261. Source startup and configuration
instructions are in [IKARUS_COMPUTER.md](../IKARUS_COMPUTER.md).

| Measurement | Result and retained evidence |
| --- | --- |
| Actual project Python 3.13 computer matrix | 219 passed in 35.43 s; `../evidence/ikarus-computer-project-venv-regression.xml` |
| Policy compatibility after replacing deprecated pathlib API | 69 passed in 4.89 s on Python 3.13; `../evidence/ikarus-computer-policy-compatibility-final.xml`; 33 policy tests passed in 1.27 s on Python 3.10 |
| Combined computer, kernel boundary, Ikarus and LLM regression | 394 passed, 2 failed, 34 subtests passed in 581.34 s; `../evidence/ikarus-computer-regression.xml`. Both failures were stale `_llm` signature doubles introduced by adding optional `response_schema`. Exact doubles were updated, retaining signature checks and asserting ordinary chat has no response schema. |
| Final LLM, loop and watcher regression | 41 passed in 1.98 s; `../evidence/ikarus-computer-llm-regression-final.xml` |
| Affected current registry baselines | 196 passed, 5 failed, 5 subtests passed in 46.09 s; `../evidence/ikarus-computer-registry-regression.xml`. Three failures exposed stale plan-revision pins and were fixed; the two remaining failures are described below. |
| Plan-index migration | 22 passed in 11.02 s; `../evidence/ikarus-computer-plan-index-regression-final.xml`. The first incomplete schema-pin migration remains in `ikarus-computer-plan-index-regression.xml`. |
| Canonical ledger reader compatibility | 22 passed in 198.74 s; `../evidence/ikarus-computer-ledger-reader-regression.xml` |
| Independent scheduler/configuration/ledger regression | 64 passed in 56.13 s, recorded in G1-IKARUS-20; final independent scheduler/watcher review 20 passed in 22.75 s |
| v0.1.6 path-I/O release-fence regression | 229 passed in 24.33 s across policy, service, context, configuration, loop, scheduler, vision, OCR, desktop, browser and watcher suites. This includes deterministic ancestor swap, legacy-grant capability projection and private-seam refusal; no live host action. |
| Final independent v0.1.6 fence re-review | 38 targeted tests passed in 4.08 s; the relevant policy, service, context, configuration, loop, scheduler, vision, OCR, desktop, browser and watcher matrix passed 247 tests in 26.01 s. It verified the exact observation-only schema, static and dynamic prerequisites before lock/lease, `coordinate_space="desktop"`, and zero execution-lock, issuer-key, lease-ledger, evidence or host-adapter state on rejection. No live host action. |
| Historical local planner to kernel to files | Qwen2.5-Coder 7B executed write, read and finish in 248.609 s; independent exact file-byte equality succeeded. Five development trials including failures retained in `../evidence/ikarus-computer-local-2026-09-05.json`. This predates the release fence and is not current file-tool acceptance. |

Published JUnit documents normalize the machine-local hostname and any
absolute temporary/workspace path to explicit neutral tokens. Assertions,
failure text apart from those identifiers, counts and timing remain intact.

These rows overlap and must not be summed into a distinct test total. Tests
measure fixture behavior, not general application support. The live trials
used different development revisions and 25/180/300-second bounds; they are
not a budget-equal model comparison. Token usage was not supplied by the
existing text transport and is explicitly unknown. The general report leaves
`task_success_verified` false; independent fixture byte equality is separate
evidence. OCR was exercised on synthetic image text and returns real word
rectangles without inventing confidence values.

The computer-assistant rows changed the effect registry digest from
`88dab18d92d47af19952a50cd37a5ea32013c1816df59dbb738e0680689a1ac4` to
`94de423f95f2da49554702adffe1ac71e6dd98b742a9a9c37c3335a1b92d8085`.
The six new rows are `python.ikarus_computer`,
`python.ikarus_computer_setup`, `python.ikarus_computer_configure`,
`python.computer_context`, `python.computer_schedule` and
`python.computer_dispatch_due`. The v0.1.6 desktop-sidecar audit subsequently
added its real `PROCESS_SPAWN` effect, producing the current digest
`a22bf29764c289e6ec15642f513844a2197bc6986edfab207f55d81bc9aac6cd`.
Exactly 25 current test constants were migrated to that inventory; historical
packet/evidence hashes remain unchanged.
The approved plan revision 12 and its exact digest were propagated to the
index checker, schema and current index authority only. The tracked-only
packet index does not include the new unstaged packets; each is validated
individually before future staging/index regeneration.

The broad dirty-tree check still has two failures outside this packet's
implementation scope: HTTP effect-handler literal census (442 versus frozen
479 literals) and desktop settings save-failure behavior (expected
DesktopEffectUnavailable was not raised). This delivery does not claim the
entire repository or frontend build is green. Their source files were already
modified outside this packet and were preserved.

Independent reviewers challenged context authority, policy drift, replay,
effect receipts, browser script escape, scheduler crash claims, secret
retention and excessive historical tick reads. Findings were fixed and their
negative cases retained. For still-enabled operations, the canonical lease
binds the exact admitted operation. File-path lease/write evidence is
historical: v0.1.6 refuses those operations before the execution lock, lease,
evidence or adapter.
Imports bind adapter source identity once, including frozen executable
fallback. Receipt persistence failure before host entry refuses the effect;
uncertainty after entry remains reconciliation-required.

## Retained negative finding and v0.1.6 release decision

A deterministic pre-fix fixture validated `workspace/sub/escaped.txt`, then
replaced the already-checked `sub` ancestor with a directory symlink before the
adapter's pathname operation. The write created `outside/escaped.txt`
(`outside_file_created=True`). Only the later readback validation noticed the
linked path and raised `ComputerRefused`. This proves that lexical resolution,
link checks and postcondition readback did not form an atomic write-root
boundary. On Windows the equivalent risk includes junctions and other reparse
points; no live host action was used for this finding.

The bounded v0.1.6 response is fail-closed disablement, not a repaired-path
security claim. `file.list`, `file.read`, `file.write`, `file.mkdir`,
`file.move`, `vision.match` and `vision.changes` are never admitted or
advertised. `vision.inspect` and `vision.ocr` are projected and admitted only
with `observation_id`; their path form is refused. New skill selection never
opens its local directory, while retained skill metadata projects as
unavailable and remains clearable. Fresh setup stores no grants; legacy stored
path grants remain inert. Private file/read seams repeat the same refusal as
defence in depth.

Re-enabling these operations requires a separately reviewed implementation
whose complete traversal and final open/rename are anchored to trusted handles:
for example `openat`/directory-FD semantics with no-follow constraints on
POSIX, and verified handle-relative traversal that rejects reparse points on
Windows. The current fence makes no claim that the dormant pathname helpers
meet that contract.

Remaining limitations: native foreground capture/input was initialized and
tested with deterministic host fixtures but not exercised on a live user
application. Browser JavaScript, form submission and downloads are disabled.
All file tools, path-based image operations and new local skill selection are
disabled by the v0.1.6 release fence; only observation-token vision remains.
Schedules need the existing watcher or an explicit tick; no autonomous daemon
was installed. There is no unrestricted terminal, arbitrary app support or
claim of complete Hermes parity. Computer setup defaults to a separate
workspace and local model context; adding apps/origins is an explicit owner
configuration command. No personal computer policy, scheduled job or host
window was changed by verification. No commit, merge or promotion was made.
