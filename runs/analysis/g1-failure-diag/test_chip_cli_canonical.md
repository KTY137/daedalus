# Diagnosis: tests/test_chip_cli_canonical.py (main @ 74008fab)

Scope: 3 node IDs recorded as failing in a full-suite run at 74008fab
(20 failed, 9565 passed):

- `test_admitted_inspect_publication_is_idempotent_and_restart_recoverable`
- `test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[synth]`
- `test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[impl]`

Interpreter used throughout: `/c/Users/Administrator/daedalus/.venv/Scripts/python.exe`.
Repo confirmed at `74008fabad9c93b582f87e8ecac35f72938fa905` ("Merge G1-HIER-14
fix: close the leaked sqlite connection, not the symptom"), tree clean of
uncommitted changes to this test/product area.

Methodological note: my first solo run accidentally wrote to a shared
`/tmp/run1.txt` and picked up **another concurrent agent's** pytest output
(`tests/test_spend_coverage.py`, 2 failed/27 passed) because this box runs
~85 concurrent agents against one shared temp directory — a live example of
the "load" half of "order/load-dependent". I switched to a dedicated scratch
dir (`/tmp/diag_chip_cli_canonical_g1fa/`) for all subsequent runs; all
output below is from that dedicated dir and is not shared with other agents.

## Common finding for all 3 node IDs: ORDER/LOAD-DEPENDENT

**Evidence — three solo runs of the whole file, dedicated scratch dir:**

```
cd /c/Users/Administrator/daedalus
.venv/Scripts/python.exe -m pytest tests/test_chip_cli_canonical.py -q \
  > /tmp/diag_chip_cli_canonical_g1fa/run1.txt 2>&1
echo "RC=$?" > /tmp/diag_chip_cli_canonical_g1fa/run1_rc.txt
```
Run 1: `RC=0`, `19 passed in 14.91s`
Run 2 (identical command, run2.txt/run2_rc.txt): `RC=0`, `19 passed in 14.02s`
Run 3 (identical command, run3.txt/run3_rc.txt): `RC=0`, `19 passed in 13.42s`

```
.venv/Scripts/python.exe -m pytest tests/test_chip_cli_canonical.py --collect-only -q
```
→ `19 tests collected in 0.40s`, and the collected list includes all three
target node IDs verbatim (confirming they were actually collected and run,
not skipped):
`test_admitted_inspect_publication_is_idempotent_and_restart_recoverable`,
`test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[synth]`,
`test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[impl]`.

So: **19/19 green, 3/3 solo runs**, against a recorded full-suite outcome of
these exact 3 failing. This is an order/load-dependence finding per the task
definition, not a deterministic defect in this file's own logic.

## Per-node-ID sections

### test_admitted_inspect_publication_is_idempotent_and_restart_recoverable

- **Verdict:** order/load-dependent (solo: pass, pass, pass; full suite: fail).
- **Evidence:** see the three solo runs above; this test is one of the 19 that
  passed identically all three times, at `tests/test_chip_cli_canonical.py:696`.
- **First failing commit:** not bisected. Rationale: the test is deterministically
  green at HEAD in isolation, so there is no product-code state change to walk
  backward through with `git log -p` / `git show` that would flip a solo run
  from green to red — the failure only exists as a property of full-suite
  execution, which rule 3 forbids me from reproducing (I may run pytest only
  on this one assigned file). Bisecting a load-only artifact requires
  comparing full-suite runs at multiple revisions, which I did not do.
- **Root cause:** HYPOTHESIS, not confirmed. I checked the specific
  WAL-companion defect class named in the task brief
  (`with sqlite3.connect(p) as conn:` leaking the connection into a reference
  cycle until GC runs) against every `sqlite3.connect` site reachable from
  this test's call graph:
  - `daedalus/kernel/effects.py:568` (`EffectLeaseLedger._connect`, used
    transitively via `daedalus.kernel.effect_replay` /
    `daedalus.kernel.offload_lease`, both imported by `chip_cli`) — **already
    fixed at this exact commit.** `git log --oneline --graph -15 74008fab`
    shows `74008fab` is the merge commit that lands
    `e9254e12 fix(effects): close the lease store's connection, and pin the
    WAL precondition`, and `daedalus/kernel/effects.py:568-585` now closes the
    connection explicitly with a comment describing exactly this bug class.
    Since the task's failing-run snapshot is *at* 74008fab (i.e., after this
    fix), this specific site cannot be the (sole) explanation.
  - `daedalus/kernel/effect_replay.py:366` (`_project_persisted_execution`,
    imported directly by `chip_cli`) — inspected: uses
    `connection: sqlite3.Connection | None = None` + `try/finally:
    connection.close()` (confirmed at line 573-575), not the leaking `with`
    pattern. Not implicated.
  - `daedalus/kernel/offload_lease.py:2204` — uses
    `contextlib.closing(sqlite3.connect(...))`, correctly closed. Not
    implicated.
  - The still-open sites the task brief names as "being swept"
    (`daedalus/kernel/approvals.py:443`, `daedalus/kernel/effect_recovery.py:523`,
    `daedalus/runtimes/provider_observation.py:553`,
    `daedalus/runtimes/provider_observation_store.py:294`,
    `daedalus/runtimes/provider_target_receipt_ledger.py:293`,
    `daedalus/kernel/promotion_execution_reader.py:152`,
    `daedalus/runtimes/trust_store.py:253`) are **not imported** by
    `daedalus/chip_design/cli.py`, `executor.py`, `publication.py`,
    `publication_verifier.py`, `manifest.py`, or `contracts.py` (checked via
    `grep -n "^import\|^from" daedalus/chip_design/cli.py`). I found no direct
    code path from this test into those modules, so I cannot confirm this
    defect class explains these 3 failures, only that I could not rule it out
    through an indirect path I didn't fully trace (e.g. via a shared
    `runs/spine/spine.sqlite3` if `ikarus_os.ask` or a budget guard is
    exercised elsewhere in the same worker process — not exercised by this
    test itself).
  - A second, better-fitting prior-art candidate: `tests/conftest.py` documents
    (lines 1-49, 92-157) **exactly this failure signature** — "solo green,
    full-suite red" — twice already, both root-caused to process-wide state
    that leaks between test files in the same interpreter: (a) `cli.main`
    loading a developer's real `.env` into `os.environ` and never scoping it
    back (fixed by re-clearing `_OPERATOR_DECLARATIONS` in an autouse fixture
    before every test), and (b) `daedalus.budget.ledger()` caching a
    process-wide default `Ledger` singleton so the first spending test pins
    it for everyone after (fixed by `_budget_mod.reset_default_ledger()` in
    the same autouse fixture). `DAEDALUS_KILLSWITCH` — which this test sets
    via `monkeypatch.setenv` — is **not** in the conftest's
    `_OPERATOR_DECLARATIONS` pin list. I could not determine, without running
    the full suite (forbidden), whether some other test leaves a real
    `DAEDALUS_KILLSWITCH` value in `os.environ` via direct `os.environ[...] =`
    (not `monkeypatch`) rather than relying on this test's own
    `monkeypatch.setenv`, which self-restores. I did not find such a direct
    assignment via a targeted grep of `daedalus/` and `tests/` for
    `os.environ["DAEDALUS_KILLSWITCH"]` / `os.environ['DAEDALUS_KILLSWITCH']`
    — only `monkeypatch.setenv` call sites — so this exact vector is
    unconfirmed, not ruled in.
  - `--dist loadfile` (the documented fast full-suite mode in
    `pyproject.toml` lines 55-73) keeps all 19 tests of this file in one
    xdist worker, but that worker also runs *other* test files before/after
    it in the same interpreter process — so cross-file process-global
    pollution (env vars, singletons, GC-deferred finalizers) remains a live
    mechanism even under `loadfile`, consistent with what `tests/conftest.py`
    already had to fix twice for unrelated test areas.
- **Fix sketch:** Cannot be written responsibly without first reproducing the
  full-suite failure and capturing its actual traceback (which differs from
  "assertion fails" — it could be a stale-state assertion, a PermissionError
  on Windows cleanup, or an unrelated exception bubbling from a leaked
  resource). The two candidate owners are: (1) whichever module still has an
  unclosed `sqlite3.connect(...)` reachable in the full-suite worker's import
  graph before this file runs — continue the sweep named in the task brief;
  or (2) `tests/conftest.py`'s `_OPERATOR_DECLARATIONS` / autouse fixture, if
  the actual leak turns out to be an environment variable or process-global
  singleton rather than a WAL file.
- **Owner:** `daedalus/kernel/*` (sqlite ledger sweep) or `tests/conftest.py`
  (isolation fixture), pending the actual full-suite traceback.

### test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[synth]

- **Verdict:** order/load-dependent (solo: pass, pass, pass; full suite: fail).
- **Evidence:** identical to above — this parametrization is one of the 19
  tests green in all 3 solo runs; confirmed collected as
  `tests/test_chip_cli_canonical.py::test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[synth]`
  in the `--collect-only` output.
- **First failing commit:** not bisected — same rationale as above (no
  reproducible red state at HEAD to walk backward from without running the
  full suite, which is out of scope for this diagnosis).
- **Root cause:** HYPOTHESIS, same candidate mechanisms as above — this test
  (defined at `tests/test_chip_cli_canonical.py:1042`) shares its entire
  fixture/import surface with the `restart_recoverable` test (same
  `ArtifactStore`, `write_evidence_root`, `chip_cli._recover_phase`,
  `chip_cli.verify_chip_eda_publication_graph`/`_retain_chip_eda_terminal_artifact`
  call graph — see `daedalus/chip_design/cli.py:117` and `:303`). No
  synth-specific code path was found that would distinguish its failure mode
  from the other two; I found no evidence it fails for a *different* reason
  than the shared one above.
- **Fix sketch / Owner:** same as above — this is not a distinct defect, it
  is the same mechanism hitting a second test in the same file.

### test_kernel_recomputes_cas_semantics_and_rejects_forged_build_receipts[impl]

- **Verdict:** order/load-dependent (solo: pass, pass, pass; full suite: fail).
- **Evidence:** identical to the `[synth]` case; confirmed collected as a
  separate parametrized node ID in `--collect-only` output.
- **First failing commit:** not bisected — same rationale.
- **Root cause:** HYPOTHESIS — same shared mechanism as `[synth]`; the `phase`
  parametrization (`synth` vs `impl`) only changes which `--phase` value is
  passed to `chip_cli.main`, not the shared artifact/ledger/recovery
  machinery under suspicion.
- **Fix sketch / Owner:** same as above.

## Cluster

All 3 node IDs share **one** root-cause class, not three independent ones:
they are the only tests in this 19-test file that (a) go through
`write_evidence_root` / `ArtifactStore` / `chip_cli._recover_phase` /
`verify_chip_eda_publication_graph` restart-recovery machinery, and (b) are
green in every solo run while red in the recorded full-suite run. The other
16 tests in the file (plan/inspect effect-free paths, admission refusals,
kill-switch/policy refusals) do not touch that recovery path and are not in
the failing set. This is consistent with a single shared contamination
vector (process-global state — sqlite WAL/connection lifetime, an
un-pinned env var, or a cached singleton — accumulated earlier in the same
full-suite worker process) rather than three unrelated bugs. I could not
identify the exact vector without violating rule 3 (no full-suite runs), and
I say so explicitly rather than guessing a specific line to patch.

## What I did NOT do (explicit UNVERIFIED boundary)

- Did not run the full suite, `-n auto`, or any multi-file pytest invocation
  (forbidden by rule 3).
- Did not capture the actual full-suite traceback for these 3 tests (it was
  not provided to me and I could not reproduce it under the rules given).
  Everything above about "root cause" is HYPOTHESIS ranked by how well it
  fits the observed pattern (solo-green/full-red, prior art in
  `tests/conftest.py` for exactly this signature), not a confirmed defect.
- Did not modify any file other than this report.

---

# COORDINATOR ADDENDUM (Odysseus) — verdict SUPERSEDED

The worker section above concludes "ORDER/LOAD-DEPENDENT" with root cause
unconfirmed. That conclusion is now **superseded**. The worker's evidence is
correct and retained (the file IS green 3/3 solo); its *interpretation* was
wrong, and the reason is instructive: a solo run gets a SHORT `tmp_path` and
therefore can never see this defect.

## VERDICT: DETERMINISTIC IN PATH LENGTH. Not order-dependent, not load-dependent.

### Controlled experiment (MEASURED, at 851ff43c, no xdist)

    .venv/Scripts/python.exe -m pytest tests/test_chip_cli_canonical.py -q \
        --basetemp="C:/t/o1"                      # 8 chars
    -> 19 passed in 11.40s                          RC=0

    .venv/Scripts/python.exe -m pytest tests/test_chip_cli_canonical.py -q \
        --basetemp="C:/t/odysseus_basetemp_padding_aaaaaaaaaabbbbbbbbbbccccccccccdddddddddd/eeeeeeeeeeffffffffff"   # 92 chars
    -> 3 failed, 16 passed in 3.14s                 RC=1

The three failures are EXACTLY the three subject node IDs. The only variable
changed is the length of `--basetemp`. Under `-n auto` xdist appends a
`popen-gwN` component to `tmp_path`, which is what supplies the extra length in
a full-suite run.

Validity: HEAD moved 851ff43c -> b3cc415b during the experiment;
`git diff --stat 851ff43c..b3cc415b -- daedalus/chip_design/ daedalus/kernel/contracts/canonical.py tests/test_chip_cli_canonical.py`
is EMPTY, so both arms saw identical content and the comparison stands.

### Failure mode (quoted from the run)

    "error": "ValueError: reasons[1] must be no longer than 1000 characters",
    "status": "error"

then `assert result == 0` gets 1, and `KeyError: 'steps'` because the error
payload carries no refusal structure. **A refusal becomes an unstructured
crash.**

### Producer PINNED (MEASURED)

A pytest plugin loaded from `/tmp` (no repo file modified) wrapped
`canonical._non_empty` in memory to dump the offending value:

    reasons[1] len=1046
    value = 'containment.attempt: primary_tree.planned_overlap_reason(
             C:\t\...\test_admitted_inspect_publicat0\isolated-workspace,
             C:\t\...\test_...'

The chain, each link read in source:

1. `daedalus/kernel/offload_lease.py` ~1760/1773 — `derive_wave_containment`
   calls `planned_overlap_reason(Path(planned), root)` and builds
   `derived_evidence`, interpolating TWO absolute paths, unbounded.
2. `daedalus/kernel/offload_lease.py:2683-2688` — the `containment.attempt`
   `GuardDecision` takes it as evidence:
   `f"{derived_evidence}; caller mechanism: {declared_mechanism}"`.
3. `daedalus/spine/receipts.py:378` — renders each guard row as
   `f"{row.contract}: {row.evidence}"` into `PolicyDecision.reasons`.
4. `daedalus/kernel/contracts/canonical.py:159` — `_non_empty(..., max_length=1000)`
   inside `_sorted_strings` refuses it at 1046 chars.
5. `chip_cli` catches the ValueError and emits `status: error`.

Note `_sorted_strings` SORTS, so the index in `reasons[1]` is post-sort and does
NOT identify the producer. Reasoning from that index would have been wrong.
`daedalus/build_exec.py:590` is excluded: it passes `reasons=(reason,)`, length
1, so it cannot yield an index 1.

`daedalus/chip_design/cli.py:602 _manifest_refusal_reasons()` is NOT involved —
it emits only short `f"{label}={len(values)}"` strings. An earlier attribution
of mine to that function was wrong and is withdrawn.

## Product code or test expectation? PRODUCT.

Two absolute paths are interpolated into a guard evidence string with no bound,
and that string is contractually capped at 1000 characters. Workspace path depth
is user-controlled. A real project nested deep enough turns a legitimate
containment REFUSAL into `status: error` — the refusal contract fails exactly
when containment is being asserted.

## Fix sketch

Bound the evidence at the MINT site: relativise or elide the two paths in
`derive_wave_containment`'s evidence, or carry them as structured fields and keep
the rendered string short.
- Do NOT raise the 1000-char limit; `canonical.py` is the contract and is correct.
- Do NOT truncate in `receipts.py`; that is the renderer, and truncating there
  would hide the same class for every other guard row.
- Treat it as a small family: `daedalus/kernel/attempt_execution.py:2647` carries
  a near-identical `planned_overlap_reason(...)` evidence template on the
  `containment.worktree` row — same latent shape, different row.

## Owner

`daedalus/kernel/offload_lease.py` (containment evidence minting), with
`daedalus/kernel/attempt_execution.py` as the sibling site.

## Pre-existing vs introduced

PRE-EXISTING latent defect. `0810d39e` ("the suite spent 50 minutes using one of
sixteen threads") only EXPOSED it by adding `popen-gwN` to `tmp_path`; its own
commit message predicted this exactly and flagged the 1000-char limit as "a
production contract". Reverting parallelism would merely re-hide it.
