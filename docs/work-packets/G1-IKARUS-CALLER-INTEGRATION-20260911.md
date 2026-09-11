# Ikarus: integrate real callers and execution evidence

Classification: ALIGNED. Gate 1 remains active. This is a development candidate,
not a main promotion, release, live-provider certificate or gate-closure decision.

## Frozen inputs and reconciliation

Canonical work parent: 70ec314cd55603653c1a23fd888d6995cac3aada.
Initial main input: 217d5edc2b5e59441051b9cb0df60a5fbca93fe2.
Updated non-overlapping main input: df761b7e0e463f1d056f6f5ff3deecc7f3cee5e3.
The latter contains newer Tensor work; those source, test and CI changes are
retained, not overwritten. Work remains solely on the existing Ikarus branch.

The Git bundle from run 34596448537 supplied complete history and exact sources.
The former 25-conflict merge diagnosis was reviewed by module/function and
consumer, rather than resolving every conflict with one side. Modern package
paths are kept. Existing authenticated-handoff, runner-context isolation,
role snapshots and effect admission already exist in main's corresponding
packages and are retained with its newer execution-limit support. The old
flat modules are not resurrected. Both input histories remain available through
commit ancestry; the legacy archive branch is neither read as a source nor changed.

## Changes and acceptance claims

1. The persisted Claude broker's public result now supplies runtime_id and
   attempt_id from admitted authority, and phase/terminal_receipt_sha256 only
   when an actual terminal receipt exists. Both Ikarus consumer paths required
   those fields and previously rejected a real completed broker result. Replay
   retains identity without inventing a fresh terminal or second provider call.
2. Previous runtime-replay and literal-input repairs are selectively ported to
   the canonical package names. Main's newer German/English imperative support
   remains intact. The existing 12 event tests stay unchanged; the additional
   91 replay regressions are in a separate file.
3. Literal-dispatch tests now import the real shell, not AST-extracted copies.
   Existing shell tests use the real LLM client with an explicit readiness
   observation and vendor transport doubles, rather than relying on an installed
   Claude CLI. Readiness and effect policy are not weakened in production.
4. The active WorkRail consumes existing bridge execution fields: provider,
   runtime, WorkItem, Attempt, phase, replay and terminal digest. Receipt-only
   updates no longer disappear under report-name deduplication. Missing or
   nonexact project attribution cannot enter a bound project's report list.
   Field completeness is explicitly not independent verification of task success.
5. The terminal-fence test has bounded startup synchronization and unconditional
   release/join cleanup. Its ordering assertion remains: quarantine cannot finish
   while completed-receipt persistence is deliberately withheld. A Windows 3.12
   five-second startup failure is retained as the baseline; native validation of
   this change is still required, not inferred from the larger timeout.

In scope: the named provider/Ikarus/UI source paths, focused tests, derived docs
and read-only CI. No new executor, provider rights, runtime policy, evaluator,
secret access, budget authority, scheduler, auto-merge or release mechanism.
The master plan and amendment chain are taken unchanged from the owner-approved
main input. This packet does not edit them or change their meaning.

## Builder evidence (not the hosted verdict)

Linux, CPython 3.13.5, full checkout/imports and repository conftest:
- Combined event, literal, shell, supervisor, authenticated handoff, composition
  and real persisted-broker identity checks: 402 passed, 9 subtests passed.
- Terminal-fence/release plus broker identity checks: 26 passed (overlap with
  the preceding selection, not an additive total).
- Actual pure mission/outcome TypeScript specifications: 84 passed through the
  installed TypeScript transpiler. This is not a React build/browser proof.
- Broader computer matrix: 733 passed, 19 failed, 33 skipped, 14 xfailed,
  12 subtests passed. Failures include Windows-only file-tool release guards,
  missing candidate-runtime prerequisites, stale expectations and environment
  interference. The selection is explicitly NOT green and does not close the
  corresponding product stages.

The container overlay fails SQLite WAL/FULL with disk I/O errors even in a
standalone stdlib probe. Tests used /dev/shm as their temporary root without
changing SQLite synchronization policy. That permits contract tests, not a
power-loss durability claim. Vendor processes remain controlled doubles; no
paid provider or owner's desktop has been used. Main's later Tensor changes
were inspected for overlap but were not included in the preceding local counts.

The new CI runs the exact development commit on Linux/Windows and Python
3.10/3.12, builds the actual web app and retains XML/source identity. The existing
unified-runtime workflow separately performs native browser and broker checks.
Hosted results are pending at authoring time. No allow-failure test step turns a
red test green. The built web artifact is a candidate, not a published release.

## Outstanding work and rollback

The 30-stage plan is not complete merely because existing main features are
present. Terminal/build tool admission, Ikarus-to-Genesis conversational wiring,
live configured provider/desktop execution, complete recovery, independent
review, platform-wide acceptance and owner release approval still require
specific evidence. Source-level presence is not marked as a passed stage.

Rollback is a normal revert of this integration on the development line, not a
force/reset or a mutation of main/archive. Source identities and receipts change
with source revision; previously issued authority is not silently rewritten.
