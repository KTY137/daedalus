# Daedalus — Current Claude Handoff (2026-08-22 — READ THIS FIRST)

This section supersedes everything below it, including the session-8 block.
Everything below is history: its branch, test counts, and open items describe a
tree that is no longer where the work happens.

**The one thing to know first: main is now the g0 trunk. The fork ruling settled on Option A (2026-08-22).**

| | path | branch | commit |
| --- | --- | --- | --- |
| truth (code + tests) | `C:/Users/nukei/Desktop/agent_env_g0` | `main` | `1e0f6a3c` |
| archived checkpoint | `C:/Users/nukei/Desktop/agent_env` | `checkpoint/2026-07-20-session` (tag: `archive/checkpoint-2026-07-20-session`) | — |

[MEASURED 2026-08-22, Mnemosyne: `git rev-parse HEAD` → `1e0f6a3c…`, `git branch
--show-current` → `main`.] The iron guard was retired (record 7 in ledger, owner
decision recorded at 2026-08-22). The mission for this session is recorded at
`docs/missions/MISSION_2026-08-22.md` — read it before making significant architectural decisions.

**Mission summary:** 20 hours of implementation; main gained 40+ commits since the pre-ruling checkpoint.
Base 7e7bfa7d; Q1–Q5 porting + delivery; Q4 ignition blocker at scheduler effect-lease boundary.
Ledger: `runs/watchdog/mission-20260822/PROGRESS.md` (13 hours, 39 line items, last row 11:49Z).

**Pending owner actions** (in `docs/decisions-pending/`):
1. `promotion_allowed_signers.proposed` — signed approval root for promotion decisions.
2. `control_root_migration.md` — the control-root migration; **loop refuses to arm until this runs**.
3. `gated_writes_lease_handdown.patch` — sealed source pin bump for promotion seam.

**Branch consolidation 2026-08-23:** [MEASURED 2026-08-23] `origin/main` was 1,525 commits behind the local trunk (last push 2026-07-13) and is now fast-forwarded. Forest-v2 slices s02/s07/s09 landed from their lanes (`6f3aae70`). 148 `archive/*` tags on origin freeze every other line, 27 of them `-wip` salvage commits of uncommitted lane work; 31 lane worktrees and 50 local branches removed. **Pending owner action 4:** delete the 125 archived remote branches — kit and verified list in `docs/recovery/cleanup_2026-08-23/README.md` (the agent's mass deletion was refused by the harness).

**Status update 2026-08-23:** [MEASURED 2026-08-23, Mnemosyne: commit `0f7f8187`] `tests/test_spine_attempt.py` green again (17 red → 0 green); was red since `57a2e7cb` due to `nearest_existing` climbing to ancestor. Fixed by `daedalus/primary_tree.planned_overlap_reason()` with forward-direction probing and shared renderer, both callers (`spine/attempt.py`, `kernel/offload_lease.py`) switched. Control-root migration and sealed lease hand-down patch remain pending owner actions in `docs/decisions-pending/`.

---

# HISTORY: Pre-ruling documents below (checkpoint/2026-07-20-session archived)

The following sections record the state before the fork ruling (2026-08-22).
They describe a split between a checkpoint branch and a trunk branch that no
longer exists. Read them as evidence of what was measured at that time, not as
current status. The active work is now on main.

## Amendment 005 — landed

- Commit `900665e` on `work/g0-trunk-20260817`: sealed-promotion guard checks
  follow the strangler into the retained source.
- Chain record: `sequence: 4`, `base_revision: 3` → `result_revision: 4`,
  `result_plan_sha256: 9329de665ba9…aa00`, `approval_ref:
  conversation-2026-08-17-owner-ran-amendment-005-kit`, accepted
  `2026-08-17T14:47:32+02:00`.
- Naming caution: the kit file is `docs/recovery/amendment_005_kit.py` ("005"),
  but the amendment-chain entry is **sequence 4** and produces **revision 4**.
  The "005" and the 4 are the same event; do not reconcile them by inventing a
  fifth amendment.

[MEASURED 2026-08-17, Penelope: tail of
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` at trunk; `git log --oneline`.]

## The landing: one precursor + four waves

The sources say "four waves" but list five commits. The commit messages settle
it — `05eb06f` is not labelled a wave:

| commit | role |
| --- | --- |
| `05eb06f` | precursor: fixtures stop writing CRLF into byte-exact files |
| `0f2fb00` | wave 1 — six review-cleared test-only lanes |
| `e98758d` | wave 2 — five review-cleared production lanes |
| `2a25d95` | wave 3 — a verified fault-matrix run can become gate evidence |
| `7c88f72` | wave 4 — the true effect-boundary inventory |

[MEASURED 2026-08-17, Penelope: `git log --oneline -12` at trunk.] Reconciles
`vault/Sessions/2026-08-17.md:29` (five commits called four waves) with
`vault/Gates/Gate-Status.md:37`.

## Where the suite stands

**35 failed / 6428 passed / 51 skipped**, run time 19:57, on committed trunk
`7c88f72`.

[INHERITED — Athena's run, recorded at `vault/Gates/Gate-Status.md:39`. Penelope
did **not** re-run this suite; it is not hers to stamp MEASURED.] Day arc
265 → 199 → 35, same source. The 265 baseline is corroborated by
`docs/GATE0_TRUNK_FAILURE_TAXONOMY.md` (measured at `60b2bfe`, pre-amendment:
265 failed / 6186 passed / 51 skipped in 30:20) — that document is **superseded
for counts** but still the best map of failure *shape*.

Flag on the provenance, not the number: the Gate-Status entry is labelled
"17:31", but the wall clock here reads 16:40+02:00 on the same day
[MEASURED, Penelope]. A 19:57-minute run cannot have finished at a future time.
The label is unreliable; the balance is Athena's and stands until re-run.

### Failure clusters

| cluster | count | disposition |
| --- | --- | --- |
| v3-report family | — | **owner decision**: scanner identity |
| blob-pin integration review | 13 tests | **owner decision**: re-pin |
| `claude_runtime_broker` | 4 | undiagnosed at the time of writing |
| release-cli subprocess | 3 | dispatched |
| kernel/runtime/gates review tail | ~24 | 27 modules, mostly 1 failure each |

[INHERITED: `vault/Gates/Gate-Status.md:39` for the clusters and the "27 modules,
mostly one failure" shape; `vault/Sessions/2026-08-17.md:45` for the blob-pin 13.]
[ASSUMED: the "~24" tail figure. No source states it; it is the residual after
broker (4) and release-cli (3) come off 35. Treat as an estimate, not a count.]

## The eight grind lanes

Eight `grind/*` lanes are checked out as siblings on the Desktop
(`C:/Users/nukei/Desktop/gw_*`). **All eight sit at `7c88f72` with no
lane-local commits** — every lane's work, where it exists, is uncommitted.

| lane | dir | working tree |
| --- | --- | --- |
| `grind/claude-broker` | `gw_claude-broker` | clean |
| `grind/v3-scanner-owner-prep` | `gw_v3-scanner-owner-prep` | clean |
| `grind/release-cli` | `gw_release-cli` | dirty |
| `grind/adoption-baseline` | `gw_adoption-baseline` | dirty |
| `grind/ledger-writes` | `gw_ledger-writes` | dirty |
| `grind/receipt-binding` | `gw_receipt-binding` | dirty |
| `grind/secrets-modeling` | `gw_secrets-modeling` | dirty |
| `grind/tools-registration` | `gw_tools-registration` | dirty |

[MEASURED 2026-08-17 16:40+02:00, Penelope: `git status --porcelain` and
`git log --oneline -3` per lane. Snapshot only — crew agents were live in these
lanes as this was written, so re-check before acting.]

**Correction to the dispatch brief.** The brief said broker *and* release-cli
carry inherited uncommitted work. Measured: `gw_claude-broker` is **clean**;
`gw_release-cli` is dirty (`tests/gates/test_gate0_release_cli.py` modified,
`scripts/gate0_release.py` and `tests/gates/_headcheck_release_cli.py`
untracked). Four further lanes carry uncommitted work nobody flagged —
`adoption-baseline`, `ledger-writes`, `receipt-binding`, `secrets-modeling`,
`tools-registration` all have modified or added files, several under
`daedalus/spine/` and `daedalus/gates/`. That work is unreviewed and uncommitted.

## Open owner decisions

From `vault/Sessions/2026-08-17.md:43-46` [INHERITED]:

- [ ] Blob-pin fixtures (13 tests) — re-pin.
- [ ] v3-scanner identity.
- [ ] CENTRAL predicate.
- [ ] K1–K13 rebase against the revision-4 text.
- [ ] Run the `SETUP` steps (install Obsidian, open the vault).
- [ ] Copy `docs/recovery/settings_beast.json` over user settings, restart the
      session (enables statusline, serena-first (replaced by daedalus/hooks/, 2026-08-23), PreCompact audit, toasts).
- [ ] Athena: remove the `wt_*` worktrees. (Full-suite balance: now recorded.)


## Gate 0 remains open

Exit still requires a fault-injection matrix demonstrating fail-closed protected
effects and fail-open read-only inspection. Remaining work per
`vault/Gates/Gate-Status.md:38` [INHERITED]: the migration grind (165 targets /
114 unregistered, MEASURED floor) plus a Linux fault run.

---

Everything from here down is history. Retained for evidence, not for status.

## SESSION 8 — FEATURE HARVEST (Mnemosyne, 2026-07-29)

Documentation sync pass: captured 39 session features in docs/FEATURE_INVENTORY.json.

**Changed:** 27 annotations created (24 module + 3 env), 63 narrative features (55 original + 8 cross-cutting), 0 unmatched. Inventory digest consistency check passed; `unmatched: 0` validated.

**Features captured (39 total):**

*Safety/Fences (9):*

- `daedalus/sensitivity.py` — split `is_loopback_host` (physics, undeclarable) from `declared_trusted_hosts` via `DAEDALUS_TRUSTED_HOSTS` (policy, narrows-on-typo).
- `daedalus/web_api.py` — auth bind via `is_loopback_host`, never the widenable predicate (fixed CRITICAL: unauthenticated control-plane to tailnet).
- `daedalus/budget.py` — `DAEDALUS_SUBSCRIPTION_VENDORS` (free-tier policy); loopback-only `free_local` vs declared `trusted_remote`.
- `daedalus/dotenv.py` NEW — fail-closed .env loader, loaded BEFORE process guard.
- `daedalus/primary_tree.py` NEW — clone-invariant fence (numeric st_dev/st_ino identity).
- `daedalus/spine/attempt.py` — `_persist` fences `artifact_dir` (candidate bytes cannot land in primary).
- `daedalus/spine/containment.py` — Job-Object 96-process/4-GiB caps with kernel READ-BACK verification.
- `tests/conftest.py` — operator declarations cleared before every test (14 tests went red in full, green alone).
- Spend guard installed in 5 more entry points + `tests/test_spend_coverage.py`.

*Self-Improvement Loop (5):*

- `daedalus/loop.py` NEW — pick→attempt→gate→promote→re-pick; four bounds; LoopLedger admission; stop-marker fail-closed.
- KillSwitch threaded through promote chain (asked-to-stop != candidate-failed).
- `daedalus/kairos/gated_writes.py` Phase 3 — `run_write_wave` with three policies (never/low_risk/always).
- `daedalus/config.py` — `resolve_write_wave_policy` (fails closed).
- `daedalus/build_exec.py` NEW — `WaveExecutor` for wave planning; gated outcomes never coarse.

*Docref/Verifier Lane (4):*

- `daedalus/spine/docrefs.py` — `overrides` + `check_denominator` structurally first.
- `daedalus/spine/docref_gate.py` NEW — gate IS the re-scan (exit 0/1/2); replaced pytest-on-markdown.
- `daedalus/spine/picker.py` — band 500, one per document, worst-first; per-document denominator.
- `daedalus/verifier.py` + `daedalus/offload.py` — prose-preservation from rollback backups (git-show-HEAD on dirty tree).

*Evolution/Ariadne (3):*

- `daedalus/kairos/evolution.py` — bare pytest wrong-tree fix: sys.executable -m pytest + 600s timeout.
- `daedalus/kairos/archive.py` NEW — inspiration archive from OpenEvolve (Apache-2.0, digest-only).
- `daedalus/mapping/spectral.py` NEW — leak_rate conductance, Newman modularity; picker enrichment opt-in.

*Ikarus (2):*

- `daedalus/conversation.py` NEW — ConversationStore with bounded resumable history.
- `daedalus/progress.py` + `daedalus/progress_sources.py` NEW — fact-based progress with stall detection.

*Bench/RTX (2):*

- `daedalus/providers/ollama.py` — schema-constrained decoding: MEASURED 0→100% structured calls on 4.5GB model.
- `daedalus/health.py` — new probes: `disk.free`, `bench.residency`, `bench.scheduled_task`, `bench.engine_crashes`.
- `daedalus/accelerators.py` — RTX SSH lanes with compute-capability floors (tensor 7.0 / RT 7.5).

*Infra/Misc (9):*

- `pyproject.toml` — `daedalus.mapping` packaged; verified by real wheel build.
- `daedalus/cli.py` — 77 CLI commands; loads .env BEFORE process guard.
- `tools/bootstrap_receipt.py` — artifact deposit moved from fenced attempt to tool itself.
- `daedalus/spine/envelope.py` NEW — trace_id contract threading (contextvars + DAEDALUS_TRACE_ID).
- `references/openevolve/` NEW — dissection plate with 5 core .py.txt files + LICENSE + PROVENANCE.md.
- README rewritten with live-measured numbers and provenance section.
- ~250 new tests across 12 new test files (test_prose_gate, test_loop, test_primary_tree_fence, test_gate_containment_job_caps, test_mapping_spectral, test_picker_spectral_enrichment, test_kairos_archive, test_envelope_join, test_envelope_coverage, test_dotenv, test_bootstrap_receipt, test_host_predicate additions).
- IN FLIGHT (agent running): eval hardening — F1 measurement, coverage-guided mutant selection.
- IN FLIGHT (agent running): three-shell Ikarus architecture with Momus corrections.

**Narrative features:** 8 cross-cutting stories added (two-predicates disease, wrong-tree fix, clone invariant, self-improvement loop, bench swarm, docref lane, envelope+trace threading, eval hardening). All carry IN FLIGHT markers where appropriate.

**Inventory state:** 159 modules (148 wired, 6 island, 3 shim, 1 unknown, 1 stale), 77 CLI, 35 API, 5 bus, 47 env (19 dark), 0 packaging gaps. Created no new commits; only updated docs/FEATURE_INVENTORY.json.

## SESSION 7 — THREE MORE COMMITS, TOGETHER THEY CLOSE THE SESSION-6 HEDGE

Provenance/doc-sync pass only (Mnemosyne), not a re-audit of the mechanism.
Numbers below are stamped by source; none were re-run this pass. This entry
was corrected mid-pass — see the CORRECTION note at the end before trusting
the "not yet reviewed" language anywhere else in this file.

**`390f75e` IS NOW CLOSED — CORRECTED FROM AN EARLIER DRAFT OF THIS ENTRY.**
An earlier version of this section, written before `3c74716` existed in this
tree, carried the session-6 hedge forward as still-open: "`390f75e`'s own
commit message says NOT YET REVIEWED BY CERBERUS ... do not read `e282dab` as
closing that flag." That was correct *at the time it was written* — no commit
recorded a review, and the discipline here is to flag rather than assume. It
is now stale: `3c74716` (`harden(egress): a trust declaration must name one
machine, not a wildcard`, on top of `b22b7a8`) records, in its own commit
message, that the review happened. **Verified by reading `3c74716` directly**
(`git show -s 3c74716`), not taken on the coordinator's word alone:

- **One CRITICAL, blocking, fixed in `e282dab`** — the shared-predicate bind
  hole documented below. This is the half already correctly attributed to
  Cerberus in the original version of this entry.
- **Cleared**: the `DAEDALUS_TRUSTED_HOSTS` mechanics themselves —
  numeric-only, exact-match, empty-default preserving the prior fail-closed
  behaviour, `urlsplit`+`ipaddress` normalisation strips scheme/port
  correctly, unparseable entries drop rather than guess.
- **Cleared, reasoning worth keeping**: the content-egress relaxation via
  `slice_egress_rule` for trusted lanes is pre-existing, deliberate behaviour,
  not a new widening introduced by `390f75e`.
- **Cleared**: the budget dollar/call axis — traced to every route that can
  reach `usd == 0` and found safe.
- **One non-blocking hardening, closed in `3c74716` itself**:
  `declared_trusted_hosts()` accepted the bind wildcards `0.0.0.0` and `::`,
  not addresses of any specific machine — one declared entry could have meant
  every host. Rejected now, along with multicast and reserved ranges.
  Verified per the commit: `0.0.0.0`, `::`, `224.0.0.1` all drop out; a mixed
  declaration keeps only the valid unicast entry (a bad entry narrows the
  list rather than poisoning the good one beside it); `lane_for_host
  ('0.0.0.0')` stays untrusted even when declared; 274 tests green.

All of the above (this bulleted verdict) is **INHERITED from `3c74716`'s
commit message and the coordinator's relay of it — not independently re-run
by this pass.** What this pass DID independently verify: that `3c74716`
exists, is a real commit on this branch (`git log --oneline -- daedalus/
sensitivity.py`), sits after `b22b7a8`, and its message says what is quoted
above. The mechanism itself (does the wildcard rejection actually work) was
not re-tested here.

**THE FINDING WORTH RECORDING ON ITS OWN, per the coordinator:** the review
existed only inside an agent transcript for some period between `390f75e`
landing and `3c74716` landing. Nothing in the tree recorded that it had
happened. That is why the first draft of this entry was right to refuse to
assume it and to flag it as unverified rather than close it — and it is the
same shape as a stale doc one layer up: a real event with no durable
artifact. It will recur every time a review or a gate runs outside the repo
(an agent transcript, a chat, a verbal sign-off) instead of landing as a
commit message, a test, or a receipt file. Treat "reviewed" as unproven until
something in `git log` says so, the same rule this file applies to every
other claim.

**`e282dab` — `fix(egress): CRITICAL -- split the loopback predicate from the
trust predicate`.** `daedalus/sensitivity.py` now exports two predicates where
the docs and the module's own prior docstring described one — Cerberus found
this reviewing `390f75e`, live at the time (the tailnet address was already
declared in `.env`):

- `lane_for_host(host) -> "trusted"/"untrusted"` — **consent**: may repo bytes
  go to this host? Widenable by `DAEDALUS_TRUSTED_HOSTS`. Unchanged in shape.
- `is_loopback_host(host) -> bool`, **new** — **physics**: is this the same
  machine? No environment variable reaches it; numeric-literal-only; nothing
  widens it.

The reason it is a CRITICAL and not a refactor: `web_api._resolve_bind` was
asking the consent question (`lane_for_host`) to decide whether the
control-plane HTTP server may bind **without authentication**. Declaring a
bench trusted (for inference, via `DAEDALUS_TRUSTED_HOSTS`) would therefore
have published the spine ledger, the role-rewriting PUTs and the
model-invoking POSTs unauthenticated to that tailnet. Fixed by pointing
`_resolve_bind` at `is_loopback_host` instead. See
`docs/ENV_SWITCHES.md`'s `DAEDALUS_TRUSTED_HOSTS` row for the corrected
consequence statement — it previously did not distinguish these two
questions and needed the same fix.

Any doc claiming `lane_for_host` is "the only implementation" of the host
question (the module's own docstring still says this, of itself correctly —
it IS the only implementation of the *consent* question) now needs the
one-sentence addition: there are two questions, `web_api` asks the physics
one, everything egress-related asks the consent one.

Same commit added two health probes to `daedalus/health.py` (was 14 probes,
now 16 — **INHERITED from the commit message, not independently counted this
pass**):

- `disk.free` — none of the previous 14 probes read free disk space. MEASURED
  by the committing session: the bench reached 0.2 GB free of 921 GB and
  every existing probe stayed green, because Ollama's `/api/tags` answers
  200 regardless of disk headroom.
- `bench.residency` — compares `size` against `size_vram` from `/api/ps`, the
  diagnostic for silent CPU offload. A model that exceeds VRAM is not
  refused; it keeps running, ~20x slower, and reads as a model-quality
  problem rather than a placement one if nothing surfaces it.

**`b22b7a8` — `feat(picker): a candidate source the write policy actually
permits`.** `daedalus/spine/picker.py` gained a fifth candidate source,
`docref`, at band 500 (between `map_shim` 700 and `inventory_island` 400).
This is the fix for the empty-intersection problem session 5 recorded below
(picker §3, "the picker's queue and the write permission do not intersect")
and that session 6 did not touch:

- MEASURED before (session 5, carried forward, not re-run this pass):
  `build_queue` returned 17 candidates, every one surgery under `daedalus/`,
  while the installed self-policy (`docs/`, `tests/`, `README.md`) permitted
  none of them — the intersection was empty.
- MEASURED after, cited in the `b22b7a8` commit message (**INHERITED, not
  independently re-run this pass**): `docrefs.scan` reads 52 docs, 537
  resolving references, 4 broken; the picker turns that into 3 `docref`
  candidates; `path_write_blocked` permits 3 of 3.

Docs that currently say the self-write loop is blocked by the
write-policy/candidate-source intersection (session 5's finding, still
accurate as *history*) need the follow-on sentence: as of `b22b7a8` it is no
longer blocked on the free lane — a `docref` candidate is real,
policy-permitted work, not yet a run of it. **Not verified this pass:**
whether a live `daedalus improve` has actually picked and attempted a
`docref` candidate; the 3/3 permits number above is a policy-function result,
not an executed write.

Same commit also fixed a hole in the subscription axis (`daedalus/budget.py`
per `DAEDALUS_SUBSCRIPTION_VENDORS`, landed `390f75e`): the host check ran
first but only reassigned an *untrusted* host's vendor to `remote_inference`;
the subscription lookup then priced that reassigned vendor at $0.00.
`remote_inference` is the catch-all for "we cannot tell whose GPU this is",
so the bug declared every unrecognised remote endpoint free. Not
independently re-measured this pass — carried from the commit message.

**`daedalus/spine/docrefs.py`** was untracked with zero importers as of the
session-6 entry below (`daedalus.mapping` gap list); `b22b7a8` commits and
wires it (the picker's `docref_candidates()` imports it directly, `daedalus/
spine/picker.py:2186`). Any doc still calling it new-and-unwired is stale as
of this commit.

**Files owned by this pass:** `docs/ENV_SWITCHES.md` (`DAEDALUS_TRUSTED_HOSTS`
row corrected), this file (including a mid-pass self-correction once `3c74716`
was found — see above). `docs/architecture-narrative.md` and `README.md`
were checked by grep for `lane_for_host`, `docref`, and picker-candidate
claims — no contradicted claim found in either; `architecture-narrative.md`
is an explicitly dated 2026-07-28 snapshot ("MOVED, not written... kept
unedited") and was left as history rather than rewritten to the current
tense. `docs/architecture-state.json` was deliberately NOT re-baselined — a
reviewed act, and other agents were committing concurrently with this pass.

**RESOLVED, was flagged as unverified earlier in this same pass:** whether
Cerberus (or anyone) had independently reviewed the *egress-widening* half of
`390f75e`. Answer: yes — see `3c74716` above, which records the verdict and
was found by exactly the check this note originally recommended
(`git log --oneline -- daedalus/sensitivity.py` after `e282dab`/`b22b7a8`).
Left in place, corrected rather than deleted, as the record of how the
question was actually closed.

## SESSION 6 — THREE COMMITS TODAY THAT CHANGE INTERFACES AND NUMBERS THIS DOC QUOTES

Not yet reviewed for correctness by this pass — Mnemosyne's job here is
provenance and doc sync, not re-auditing the mechanism. Read as: what changed,
what is MEASURED vs INHERITED vs ASSUMED, and one open flag that has not been
closed.

**NOT CLOSED, CARRY THIS FORWARD:** `390f75e` (`DAEDALUS_TRUSTED_HOSTS`,
subscription vendors, 5 unmetered spawn sites) touches the egress fence and its
own commit message says so: **"NOT YET REVIEWED BY CERBERUS. This touches the
egress fence and per the crew doctrine wants an independent look before it is
relied on."** That hedge travels with this entry; do not cite the trust-boundary
widening as settled until that review lands. See `docs/ENV_SWITCHES.md` for the
full consequence statement on `DAEDALUS_TRUSTED_HOSTS`.

**What landed (`git log`, all three same day):**

- `7612c99` — tool-call decisions now go through grammar-constrained `format`
  (a JSON schema), not just the content. MEASURED 2026-07-29 on the bench, 3
  trials × 2 tasks per model, native `tools` array vs schema-constrained
  `format`: qwen2.5-coder 1.5b/7b/14b and devstral:latest went 0% → 100%;
  qwen3.6:latest was 100% → 100% (unaffected, was already correct). SCOPE,
  stated in the commit: this only affects the EXPLORATORY (`_run_agentic`) path;
  at ≤3 declared paths `run()` takes `_run_rewrite`, which never used tool calls
  at all and is unaffected.
- `390f75e` — declared trust boundary (`DAEDALUS_TRUSTED_HOSTS`), a subscription
  dollar-axis (`DAEDALUS_SUBSCRIPTION_VENDORS`), and closed 5 spend-guard-free
  process entry points (`claude_bridge`, room, room server, `run_arm`,
  `summarize` each had their own `__main__` and never installed the budget
  guard). MEASURED 2026-07-29, cited in the commit: an uncapped `claude -p` arm
  ran $1.43–$1.85; `codex --version` was refused at estimate=$0.0000 against a
  fictional spent=$24.00 (worst-case reservations a flat-rate plan had already
  paid for) before the `estimate.usd > 0` fix.
- `68921f0` — `.env` is now actually read at CLI start (`daedalus/dotenv.py`);
  accelerator reporting now probes the bench over ssh for compute-unit ground
  truth instead of reporting the local machine's (CC 6.1, no tensor/RT cores)
  as if it were the only card that mattered; `daedalus.mapping` added to
  `pyproject.toml`'s explicit package list, closing the non-editable-install gap
  the OPEN list below used to name.

**Numbers MEASURED 2026-07-29 on the bench (RTX 5080, 16303 MiB, CC 12.0),
reported to this doc by the launching session and not independently re-run
here — stamped MEASURED because they carry a workload and a warm/cold state,
not because this pass reproduced them:**

- Concurrency, qwen2.5-coder:7b, warm: N=1 137 tok/s, N=2 232, N=4 367, N=8 394,
  N=16 409 — knee at N=4, matching server-side `OLLAMA_NUM_PARALLEL=4`, zero
  errors through N=16. CAVEAT the reporting session itself raised and this doc
  preserves: the two **cold-load** figures quoted alongside this run (14b
  52.1 s, 32b 109.7 s) may be contaminated by a silent crash-retry and should
  not be quoted as clean until re-measured.
- qwen2.5-coder:32b: 6.08 tok/s, 109.7 s load — **exceeds VRAM on this bench and
  is unusable, not merely slow.** Do not route to it expecting degraded-but-
  working performance.
- Served weights: 7b 4,466 MiB, 14b 8,572 MiB, devstral 13,670 MiB. KV per slot
  at ctx=6144: 7b 336 MiB, 14b 1,152 MiB.

**`daedalus map --check` drift, current count is 2 `doc_drift` entries** —
`FROZEN_GATE_PATHS` (long-standing, see `docs/ENV_SWITCHES.md`'s closing note)
and `OLLAMA_NUM_PARALLEL`. The second is now documented in
`docs/ENV_SWITCHES.md` with the reason it will likely stay flagged: the
variable is read by the `ollama serve` Go binary on the bench, not by this
Python client, so the drift gate is correctly reporting "documented, nothing in
THIS tree reads it" — that is not a doc error to fix by deleting the entry.

**`README.md` (rewritten in `68921f0`, same commit as the `.env` change):
still holds.** It does not mention `.env` sourcing, the tool-call mechanism, or
the trust-boundary switch, so none of today's changes leave it stating a
removed mechanism. Checked by grep, not by a full re-read against every claim.

**Not verified this pass, flagged rather than assumed:** whether Cerberus's
independent review of `390f75e` has since landed — check `git log` for a
commit touching `daedalus/sensitivity.py` or `daedalus/budget.py` dated after
this entry before treating the egress widening as reviewed.

## SESSION 5 — THE SELF-POLICY IS INSTALLED, AND WHAT IT TAUGHT

Kaya authorised self-modification on 2026-07-29. Four things were measured
before anything was installed, and all four changed the outcome.

**1. The drafted policy confined nothing.** `docs/PROPOSED_SELF_POLICY.md`
claimed its `allow` list was "the whole permission". Measured against
`path_write_blocked` — the function the write lane actually calls — **8 of 12
paths it claimed to deny were writable**, including `daedalus/config.py`, which
*loads the policy*. `allow`/`default_deny` are the EGRESS axis and are read by
`classify_data` and by nothing on the write axis. The ninth instance of this
repo's recurring defect, and the first where the author of the document and of
the code was the same. Fixed with an opt-in, prefix-anchored `write_allow`;
see ADR-019 and `tests/test_self_policy_confinement.py`.

**2. The policy only counts if it is COMMITTED.** `offload_runner` pins
`repo_root` to the worktree, and a worktree is checked out from HEAD. An
uncommitted `.agentenv/agentenv.json` grants exactly nothing. This is a good
property — permission travels with the revision — and it is not written down
anywhere else.

**3. The picker's queue and the write permission do not intersect.** Measured:
17 candidates (7 map_island, 7 inventory_island, 3 map_shim), every one of them
source surgery under `daedalus/`. The permission is `docs/`, `tests/`,
`README.md`. The top candidate does not even reach the write guard — its
instruction contains "delete", a HIGH risk term, so it routes `risk=high ->
claude_cli -> senior`. **The loop correctly selects work it is not allowed to
do.** Do not fix this by widening the fence; that is the day-one failure mode
the policy itself warns about.

**4. The one permitted lane has no gate.** A live 7B write against
`docs/LOCAL_MODELS.md` succeeded mechanically (`action=offloaded`, file changed
2235 -> 2207 bytes) and was **not promotable**: against an instruction that said
"keep every fact", the model deleted "OpenAI-compatible endpoint" and the
cross-reference to `docs/IMPROVEMENTS_RESEARCH.md`, dropped backticks around
`daedalus`, and re-cased two headings. **No gate could have caught this.**
`test_command` proves tests pass; there is no red test for a deleted true
sentence in Markdown. The policy chose `docs/` because a wrong patch there
"costs a review rather than an incident" — that is now measured to be exactly
right, and it means the review is a HUMAN one. `docs/` is simultaneously the
safest place to write and the least verifiable. Those are the same property.

**Also fixed:** `daedalus doctor` died on a traceback whenever the spend ceiling
fired — `BudgetRefused` is neither `OSError` nor `SubprocessError`, so it
escaped both handlers in `codex_status`. A firing guard must not kill the
diagnostic that reports it. `refused` is now its own state, deliberately not
folded into `present=False`: "codex is not installed" and "I was not allowed to
ask" are different facts.

**Standing constraint at the time of writing:** the spend ceiling is exhausted
(`$5.00/$5.00`), so codex is unreachable and none of the above has had an
adversarial cross-vendor review. Raising `DAEDALUS_BUDGET_USD` is a deliberate
act and was not taken unilaterally.

## THE TWO SENTENCES

The self-improvement circle runs end to end on a clean clone and is fail-closed
at every step; an operability drill trips all seven controls and holds; and the
gate has now been **shown to discriminate — 83%, with all four critical defect
classes killed.** It may still promote nothing, because that receipt was
measured at `b3bcee7` and commits landed faster than the run, so the staleness
rule correctly refuses it at the current tip.

## THE MEASUREMENT THE SESSION WAS BLOCKED ON

    planted 12, killed 10 -> 83%   (floor 80%)
    scope: 7 covering-test files, 306 tests, frozen BEFORE the run

    deletes-outside-the-worktree   CAUGHT, CAUGHT
    spends-money-without-a-gate    CAUGHT, CAUGHT
    sends-bytes-off-the-machine    CAUGHT, CAUGHT
    reports-failure-as-success     CAUGHT, CAUGHT

Two survivors, both non-critical and both explained by scope:
`read_inlined_context_inverted_skip` was **predicted to survive before the run**
(and has since been closed by `tests/test_inlined_context_enforcement.py`, which
was not in this scope), and `picker_abbrev_sha_guard_disabled`'s covering tests
are not in the scoped set — evidence the scoped gate cannot see it, not evidence
the suite cannot.

**This measured a SCOPED gate, not the whole suite**, and the receipt says so.
The whole-suite number is unmeasured; its one finished attempt came back
baseline-red at an earlier revision and the cause was never established.

RE-MEASURED AT THE SESSION'S FINAL REVISION `ee8bff8`, complete:

    planted 12, killed 10 (83%)   all 8 CRITICAL mutants killed
    gate_discrimination() -> proven=True, "no critical class survived"

    ok  worktree_moved_checkout_unguarded       deletes-outside-the-worktree
    ok  worktree_drain_skips_reachability       deletes-outside-the-worktree
    ok  offload_escalation_gate_disabled        spends-money-without-a-gate
    ok  free_lanes_includes_claude              spends-money-without-a-gate
    ok  room_ssh_rce_reintroduced               sends-bytes-off-the-machine
    ok  lane_for_host_accepts_localhost         sends-bytes-off-the-machine
    ok  room_verify_always_passes               reports-failure-as-success
    ok  attempt_capture_patch_drops_no_textconv reports-failure-as-success
    MISS read_inlined_context_inverted_skip     logic      (predicted; scope)
    MISS picker_abbrev_sha_guard_disabled       boundary   (covering tests
                                                            outside the scope)

AND THEN THE WHOLE SUITE, COMPLETE, at the same revision:

    gate measured: THE WHOLE SUITE
    planted 12, killed 12 -> 100%

Every mutant caught, including BOTH that survived the scoped gate. That settles
what the two survivors were: `read_inlined_context_inverted_skip` dies to
`tests/test_inlined_context_enforcement.py` and `picker_abbrev_sha_guard_disabled`
to `tests/test_spine_picker.py` / `test_spine_map_source.py` -- neither is in
`SCOPED_GATE_PATHS`. They were scope artefacts, exactly as predicted, and not
holes in the suite.

Written to `runs/spine/gate_discrimination.whole_suite.json` via `--out`, so the
scoped receipt the reader consults was left untouched. `gate_discrimination()`
therefore still reports the CONSERVATIVE 83% -- the number a scheduled run would
be judged against is the one measured against the gate a candidate actually
gets, not the best number available.

WITH THAT RECEIPT IN PLACE THE DRILL READS:

    promotion.a_gated_candidate_is_still_refused
      effect   : promotion is PERMITTED, and the receipt says why
      telemetry: a candidate patch is waiting and the gate has demonstrated
                 discrimination at this revision; promotion is still a human act

    7 pass / 0 FAIL / 0 incomplete

**The receipt is now ONE COMMIT BEHIND**, because committing this document moved
the tip. That is the property, not a defect: re-prove with
`python tools/gate_discrimination.py --scoped --head-only` (~20 min), and read
the drill afterwards.

## WHAT NEEDS A HUMAN DECISION, AND IT IS NOT MEASUREMENT

The reviewer's closing correction, and it is a correction to my own framing:

> The scoped gate is solid evidence; the whole suite stays unproven. I disagree
> with "everything after this is just measurement" — after a fresh receipt, the
> self-policy and a write-shadow remain their own APPROVAL step. I cannot judge
> the policy without the diff and file:line; Kaya should decide exactly that
> diff before any self-write run starts.

So the remaining sequence is not three measurements, it is two measurements and
one decision:

1. re-measure discrimination at the tip (mechanical, ~20 min)
2. **decide the self-policy diff** — `docs/PROPOSED_SELF_POLICY.md`, one JSON
   block, undone by deleting one file. This is the approval step.
3. one write-shadow against a `docs/` candidate, read by hand

Nothing in step 2 is implied by step 1 going green.

## THE PATTERN, NINE TIMES

Every major finding was one defect in different clothes: **code that exists was
reported as capability that works.**

| claimed | true |
|---|---|
| `semantic_route`, a listed feature | unwired **and** broken if wired |
| `latent_weight: 0.35` in every context receipt | described a source that had never spoken |
| `spine/containment.py`, 11 vectors measured, committed | **zero production callers** |
| `kairos/evolution.py`, ADR-009's baseline | no pipeline; would score the **primary checkout**, not the candidate |
| `FEATURE_INVENTORY.json`, 136 features | hand-written, 30 commits stale, driving the two highest bands |
| `budget.py`, a spend ceiling | nothing called `install_process_guard()` |
| `council` / `canary` | launched **paid binaries from an invocation with no flags** |
| five host predicates | three different answers for `[::1]` |
| **my own commit `efd0ed6`** | **shipped one of my own mutations** — see below |

## THE THREE STRUCTURAL FINDINGS

**1. The loop invalidates its own inputs every time it succeeds.** Both picker
sources are derived artefacts stamped with the revision they describe. Every
commit makes them stale. Demonstrated three times: a clean clone produced ZERO
candidates; after eleven commits the live picker went 13 → 0; and the acceptance
harness reported "the queue is EMPTY" while the live picker had ten. Regeneration
is now **step zero** in `spine/bootstrap.py::refresh_sources` AND in
`tools/system_check.py`. "The generator exited 0" is explicitly NOT the success
criterion — the criterion is that the artefact stamps a revision its consumer
can check.

**2. Quality and damage are different questions, answered by different
mechanisms.** The correctness evaluator covers none of the four CRITICAL defect
classes: a patch that fixes the bug and also deletes a repository outside the
worktree scores `fixed`. That is the design, not a hole — promotion must fail on
**independent containment** anyway. Measured in the drill: a contained child
**exits 0**, a success code, and still cannot delete the canary outside its
worktree. The bound does not depend on the verdict.

**3. A guard verified through its own function is not verified.** `efd0ed6` — my
own commit — replaced `self._admin_dir = _read_gitdir_pointer(worktree)` with
`= None`, leaving the six-line comment explaining why the pointer must be
captured sitting above it. Thirteen of fourteen tests stayed green because they
call `_git` directly. Only the end-to-end test through `TaskAttempt.run` was red,
and I did not re-run it after committing. The vector was committed and open.
Found by the drill on its first run.

## WHAT NOW EXISTS

* **`tools/operability_drill.py`** — seven controls, each deliberately tripped,
  passing only when EFFECT and TELEMETRY are both visible. Promotion refused on
  a gated candidate; 6 vendor spawns under a 1-call ceiling with 0 reaching the
  binary; child **and grandchild** dead 0.36 s after cancel against a 3 s SLO,
  pids checked individually; the git-filter vector refused; damage bounded
  independently of the verdict; the primary checkout untouched; and every proof
  tied to the current revision. `INCOMPLETE` is never a pass.
* **`daedalus/eval/correctness.py`** — FAIL_TO_PASS / PASS_TO_PASS. It
  discriminates where the existing gate does not:

  | candidate | correctness evaluator | the repo's `pytest_gate` |
  |---|---|---|
  | plausible **wrong** fix | `not_fixed`, 1/2 green | **exit 0 — "19 passed"** |
  | correct fix + sabotage | `regressed`, 3 P2P broken | — |

  3 of 4 real fix commits admitted, 22 of 41 nodes. One of the four shipped **no
  test at all** — a real fix nothing can witness, refused rather than invented
  around.
* **Containment wired into the gate**, one bounded handle via
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. `APPEND|SYNCHRONIZE` alone **blinds the
  gate**: `os.fstat(1)` needs `FILE_READ_ATTRIBUTES`, and without it pytest sends
  every byte to devnull — exit 0, zero bytes, `passed=True`. An empty green, in
  the gate. Mask is now `APPEND|READ_ATTRIBUTES|SYNCHRONIZE` plus a
  no-empty-green guard. **On non-win32 the default gate hard-refuses.**
* **A spend cap installed at the CLI entry point.** There is no chokepoint —
  four subsystems, 17 sites, three invisible to any text scan — so one is
  manufactured at the syscall boundary.
* **A kill switch**: permit-not-stop-file, latching, measured 186–260 ms to
  latch and 514–643 ms to a dead process tree.
* **A health surface with five states that cannot collapse into green**, served
  at `/api/health`, and three spaces in the web UI that render them on four
  distinguishable axes.
* **Browser acceptance**: 18 Playwright specs, every red demonstrated, a missing
  browser is `INCOMPLETE`.
* **A GUI component catalogue** where `use_mode` is derived from the licence in
  code and never read from the entry.

## TRAPS PAID FOR — DO NOT RE-LEARN THESE

* A guard test that matches its own prose stays green after the guard is
  deleted. Assert on the **AST**, not on source text.
* A guard reached only through its own function is untested wiring.
* A refusal test with no control proves nothing.
* `assert <set> == []` is vacuously true on a clean tree.
* A **collection error is not a red test** — an `IndentationError` from a
  botched mutation looks like a failure and proves nothing.
* Hardening git removed `core.autocrlf`; on Windows every text file then looks
  modified and an idle runner reports `clean` instead of `no_change`.
* A mutation harness that rewrites whole files while other work is in flight
  will eventually commit one of its own mutations. It did.
* `git add <path>` then `git commit` without reading the **staged set** sweeps up
  other work. Twice tonight; two commits carry `git notes` corrections, one of
  them for 41 files under a message about one endpoint. Use
  `git diff --cached --name-only` before every commit.
* The island metric is gameable: deleting a test moves a module to `unknown` and
  the count falls with the dead code untouched. Read `unreached` instead.

## THE LAST BOOTSTRAP BLOCKER IS A POLICY DECISION, NOT CODE

A shadow run in a clean clone picks real work, routes it to a FREE LOCAL LANE in
WRITE mode, and stops on one line:

    routed to : ollama  mode=write  action=escalate_to_claude
    note      : refusing live write: no project policy loaded (guards off)

Correct: without a loaded policy the write guards run under `DEFAULT_POLICY`,
whose deny-list is empty, so the safety core itself would be writable.
`resolve_project("agent_env")` returns `None` and there is no `.agentenv/` --
Daedalus can improve other projects and not itself.

`docs/PROPOSED_SELF_POLICY.md` drafts the file and deliberately does NOT install
it. `allow` is `docs/`, `tests/`, `README` and nothing else; the safety core is
named separately in `high_risk_paths` so a future widening has to delete a line
reading "the egress fence". Installing is copying one JSON block; undoing is
deleting one file.

Related and worth knowing: `availability` does NOT fully gate the router's
choice. With `claude_cli: False` some objectives still resolve to `claude_cli`
(the island instruction does) while others correctly move to ollama. The
`--local-only` flag on the shadow runner therefore DECLARES a lane rather than
forcing one, and its help now says so.

## VERIFICATION AS OF THE SESSION END

    tools/system_check.py     17 pass / 0 FAIL / 1 unavailable   exit 2
                              (the one unavailable: the eval's focus file is
                               withheld by the secret floor, so that task cannot
                               be scored -- not a pass, not a failure)
    tools/operability_drill.py  7 pass / 0 FAIL / 0 incomplete   exit 0
    pytest tests/            2838 passed, 1 failed, 2 xfailed
                              (the one failure was a load-dependent socket
                               timeout, since fixed with a readiness loop)

Four commands reach the new capabilities, and `daedalus status` propagates its
verdict for the first time -- it previously exited 0 even while reporting a
degraded subsystem:

    daedalus drill            0    every control tripped and held
    daedalus health           1    subsystems degraded (correct)
    daedalus status           1    correct now; was silently 0
    daedalus project-memory   0    dry run

## OPEN, WITH OWNERS

* **No discrimination receipt.** `runs/spine/gate_discrimination.json` does not
  exist; a scoped run (306 tests, ~95 s per gate invocation) was in flight at the
  session end. Until it lands, promotion is correctly `unproven`.
* **The whole-suite gate was red at `c5dfb52`** on a clean committed checkout.
* `daedalus.compaction` is the one remaining capability module with zero
  production callers.
* **Two room implementations**: the skill's (`~/.claude/skills/room/room.py`,
  703 lines, no chaining) writes the transcript actually used; the project's
  (`runs/council/room.py`, 1271 lines, 44 chain-related lines) writes a
  different, older one. Choosing which is canonical is a decision.
* A bridge task from 2026-07-20 sits queued with a dead watcher: *"how is
  daedalus currently build and how does it function?"*, targeting `project_tct`,
  lane `local_only`.
* `daedalus/web_api.py:1040` — `AUTH_TOKEN_ENV = "DAEDALUS_WEB_TOKEN"` trips the
  secret floor's credential-assignment pattern. A false positive in the safe
  direction; the floor stays, and the eval reports the withholding rather than
  scoring the task.
* `daedalus.mapping` is missing from `pyproject.toml`'s explicit package list.
* `runs/spine/` is gitignored, so drill and discrimination receipts do **not**
  travel with the repo — every machine must measure for itself, which is
  defensible given containment is win32-only, but it is a choice worth knowing.
* The import graph and the reachability snapshot disagree ~8×; the UI reports
  the disagreement rather than painting ~70 false islands.

---

# Daedalus — Handoff (2026-07-28, session 3 — SUPERSEDED, kept as history)

This section supersedes everything below it, including the session-2 block.
The rest of the file is history; do not treat its arc claims, test counts or
open items as current.

## A LIVE EGRESS BREACH, CLOSED — and the Momus CRITICALs re-audited

**The breach.** `lane="trusted"` switches OFF the default-deny allow-list in
`slice_egress_rule`, leaving only the secret floor. It was chosen from the
PROVIDER NAME — *"ollama is local and trusted with IP, so lane='trusted'"* —
while the client resolves its endpoint from an environment variable:

```python
# providers/ollama.py
self.host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
```

So `OLLAMA_HOST=http://100.119.126.9:11434` — the RTX bench, **off-machine over
a tailnet** — kept the name "ollama", kept the lane "trusted", and converted a
no-egress lane into a network one. Distilled source that the allow-list
withholds from every external provider would have gone over the wire with only
the secret floor applied. No code change, no flag, no log line. **A comment
asserting locality was doing the security work.**

**Closed by `sensitivity.lane_for_host(host)`**, which answers "where do the
bytes actually go" and never "which provider is this". Loopback literals plus
all of `127.0.0.0/8`; everything else untrusted; empty/unparseable/unknown fail
CLOSED. `0.0.0.0` is deliberately not loopback — it is a bind address and
promises nothing about who answers a connect.

```
OLLAMA_HOST=http://127.0.0.1:11434      -> trusted
OLLAMA_HOST=http://100.119.126.9:11434  -> untrusted     (both were "trusted")
```

**TWO live call sites, not one.** The offload slice wire, and — found by
grepping the class rather than stopping at the reported instance —
`ikarus_os`'s LOCAL chat branches, which hardcoded the trusted lane next to an
`OLLAMA_MODEL` lookup. The chat path is user-facing, so that one shipped
distilled project context off-machine on every turn once the env var pointed
away.

The wire REFUSES rather than downgrades to `untrusted`: default-deny would still
ship whatever survives the allow-list to a host somebody pointed an env var at,
and this wire exists *because the destination was believed local*. A human
decides what a remote bench may read.

Guards, verified by disabling each: revert the wire → 2 red; make
`lane_for_host` trust everything → 16 red. One ordering test exists because the
bug was nearly re-shipped — the refusal must be evaluated BEFORE the budget
check, or an operator with the wire enabled and a remote host gets the egress
path while the refusal test still passes for the wrong reason (`budget=0` →
nothing built → "no slice" looks like success).

**Two safety predicates now disagree, and this is a finding, not a fix.**
The council already derives its lane from the host (`session._is_local_http`,
`vendors._LOCAL_HOSTS`), so this class was closed THERE and not in offload.
Measured divergence against the new one:

```
http://[::1]:11434       sensitivity=trusted   council=untrusted
http://127.5.5.5:11434   sensitivity=trusted   council=untrusted
```

Both cases have the council STRICTER, so it is imprecise rather than unsafe.
Three implementations of "is this host local" is still one too many.
**Deliberately NOT consolidated tonight:** collapsing them touches three council
security call sites and would widen a boundary as a side effect of a refactor.
It wants its own review.

**The Momus CRITICALs, re-audited — and I got this wrong first, which is the
point worth keeping.** I checked `daedalus/council/` and reported two of the
three as already closed. They are — *in that module*. An independent review
then pointed at `runs/council/room.py`, a SECOND implementation of the same
council that never inherited the fixes. Verified in the source:

| CRITICAL | `daedalus/council/` | `runs/council/room.py` |
|---|---|---|
| reviewers must not be write-capable | closed (`--sandbox read-only`, FORBIDDEN-flag list, pinned by a test) | flags are read-only, but they still start at `cwd=REPO_ROOT` (`:846`) |
| agy-over-ssh must not put a prompt on a remote command line | closed (`agy -p -`, stdin, pinned by a test) | **LIVE RCE** (`:948`) |
| `lane="trusted"` from the provider name | closed tonight (2 call sites) | **LIVE** (`:397`) — neighbourhoods built trusted, then sent to EXTERNAL speakers |

The RCE, verbatim:

```python
cmd = f'agy -p "$(type {remote.replace("/", chr(92))})"'
proc = subprocess.run(["ssh", BENCH_SSH, cmd], ...)
```

`$(...)` is command substitution performed by the REMOTE shell. The file it
expands is the room prompt, which carries diffs. A patch containing backticks or
`$(...)` — an ordinary shell script, a test log, a Python f-string — executes on
the bench as Administrator, with no adversarial model required. This is the
exact hazard `daedalus/council/vendors.py` documents at length and fixed by
sending the prompt on stdin; `room.py` reimplements it.

**The generalisable lesson, and it is about auditing, not about ssh: I searched
the module I expected the bug to be in, found it fixed, and reported the class
closed.** A fix that lives in one of two implementations is not a closed class.
`runs/council/` is a parallel council that did not inherit any of the hardening,
and nothing in the repo made that visible.

**All three are now closed in `runs/council/room.py` too, and the RCE was in a
THIRD copy as well.** `~/.claude/skills/room/room.py` — the portable skill, the
one this session has been driving all night — carried the same
`agy -p "$(type FILE)"`. I nearly reported it clean because my first grep used
the project copy's variable name. Both now build a fixed argv and pass the
prompt on **stdin**; the only remaining `$(type ...)` occurrences in either file
are the comments explaining why.

Room attachments now take the lane from the SPEAKER
(`_speaker_lane(who, host)`), and ollama is judged by the endpoint it will
actually dispatch to — `BENCH` by default, which is another machine. My first
version of that predicate read `OLLAMA_HOST` and would have called bench traffic
"trusted": the exact bug being fixed, reintroduced one module over, caught only
because the predicate was exercised against the room's real default.

**And the verification caught a hole in my own tests.** Reverting the
`build_prompt` wiring changed nothing — 47 passed either way — because every
test exercised `_attach(lane=...)` and `_speaker_lane()` *separately*. Both
halves were perfect while the connection between them was untested. Fixed by a
test that drives `build_prompt` end to end for an external speaker; the revert
now goes red (2 tests). Same shape as a guard whose absence nothing detects.

## THE CIRCLE IS CLOSED, AND IT WAS RUN ON THIS REPO

Not "the modules exist". Measured end to end on `agent_env` itself, in this
order, with nothing mocked:

```
$ daedalus improve --once
  picked   map-island-daedalus-compaction-py-269cb9   830.00  [map_island]
  evidence classification=island, imported_only_by_tests=True,
           measurement=docs/architecture-state.json (generated, digest-covered)
  attempt  worktree created, intent #1 recorded BEFORE the effect
  state    no_change (advisory runner -- no model was invoked)
  cleanup  worktree removed: True
  reaped   branch deleted; leaked attempt branches after: 0

$ daedalus improve --dry-run          # the SAME command, immediately after
  1. 830.00  map-island-daedalus-council-publish-py-ed442f     <-- moved on
  ...
  7. 800.00  map-island-daedalus-compaction-py-269cb9
     "...; already attempted 1x with this exact instruction (last: no_change)"
     prior_attempts=1, last_attempt_outcome=no_change, offset 30.00 -> 0.00
  note: attempt memory: 1 candidate(s) sank to their band floor
```

**Rank 1 → rank 7 of 10, and still in the queue.** The loop picked work from
generated evidence, recorded the attempt durably, cleaned up after itself
including the ref, and then *chose something else*. That is "measurement picks
the next work" actually happening rather than being asserted, and before this
session the same command returned the same five candidates forever.

What is still NOT true, and must not be claimed: the runner above was
**advisory**, so no model wrote anything. The circle is proven for
pick → attempt → record → reap → re-pick. It is not yet proven for a landed,
promoted change, because promotion remains a human act by design.

## THE A/B RAN. Arm B did not earn its cost on this task.

Full writeup: `docs/EXPERIMENT_A_B_RESULT.md`. Pre-registration §7's second
falsification condition is MET — *"the gate outcome is the same for both, and
the extra machinery bought only process."*

```
                    Arm A (self-directed)   Arm B (DSS + gate feedback)
gate                pass, first try         pass, first try
hidden conformance  21/23                   21/23        (same two failures)
billable tokens     99,971                  122,592      +22.6%
USD                 $1.4335                 $1.8451      +28.7%
wall clock          358s                    545s         +52.2%
turns / rework      1 / 0                   1 / 0
human interventions 0                       0
tests written       none                    none
```

**Read these four before quoting that table.**

1. **It was NOT "full Daedalus".** Codex made this correction in design review
   and it stands. Pre-registered Arm B is distilled context + TaskAttempt +
   gates + council + human promotion. What ran was **DSS + enforced gate
   feedback versus self-directed Claude**. TaskAttempt, council and promotion
   were never in the loop. A plan-only `daedalus offload` returned
   `action: "senior"` — for a high-risk greenfield write the router escalates
   rather than executing — so "Arm B = offload --live" would have measured a
   system declining to run. Silver lining: both arms then ran the SAME model,
   so this measures process, not model.
2. **Arm B's central mechanism never fired.** Both arms passed the gate on the
   first pass, so the repair loop had nothing to repair. This run measures Arm
   B's overhead in full and its benefit not at all. It is evidence about a task
   that goes RIGHT, not about the case the machinery exists for.
3. **Blind judging split, and the only uncontaminated verdict preferred Arm A.**
   Mapping was X=B, Y=A. I preferred Y and guessed X=A — **my guess was wrong**,
   and the direction matters: I preferred what I believed was Arm B, and it was
   Arm A. Codex preferred X (Arm B) but **disqualified its own guess** because
   it had contaminated the blind while locating files. That contamination taints
   its qualitative verdict too, not just the guess. Opus 4.6 and Kaya did not
   judge — two voices missing, named rather than papered over.
4. **N = 1. An anecdote, recorded as one.**

**The finding I did not expect: neither arm wrote a single test.** Both were
told the gate was `tsc --noEmit && vite build` and both optimised precisely for
it. That is a fact about MY BRIEF, not about the models — I specified a gate
that cannot fail for a wrong-but-compiling implementation and got two
wrong-but-compiling implementations. Same lesson this repo learned three times
in one day on its own safety code, arriving from the opposite direction.

**Codex's ruling on what comes next, and I agree: fix the gate first.** A repair
loop is meaningless when its oracle accepts wrong implementations, and choosing
a feature "to fail" would game the experiment. Pre-register behavioural
acceptance tests, **prove they reject known-bad fixtures**, then run a naturally
difficult second feature. That is the project's own guard doctrine — a test that
does not die when the thing it checks is broken is decoration — applied to the
experiment's own oracle.

Blind review also found five defects **23 mechanical tests could not see**
(stable-ID corruption in one arm's deep links, a forbidden `@revision` in the
other's canonical form, both violating "export exactly", an unrecognised query
key promoted to an object, two divergent slug grammars). That is an argument for
cross-vendor review existing at all — not for Arm B's machinery, and it must not
be read as one.

## Also shipped this session, each verified by deleting the guard

- **`6476cdf` — the picker has work again.** The queue was EMPTY because its
  only source was hand-written and thirty commits stale. It now also ranks from
  `docs/architecture-state.json` (generated, digest-covered, drift-gated), with
  islands and shims as SEPARATE sources carrying opposite remedies. Trust is
  verified via `digest_ok()` before any list is inherited, so a hand-edit the
  drift gate would have caught cannot become the thing the loop works from.
  Guards: digest check off → 2 red; suppression off → 1 red.
- **`selftest.py`** — the last `shutil.rmtree(repo, ignore_errors=True)` in a
  `finally:` on a directory a live model just wrote into. Now routes through
  `remove_tree_no_follow` and REPORTS what it could not delete. `import shutil`
  is gone, so re-introducing it costs a visible line. The discriminating test is
  the REPORTING one on purpose: a static junction fixture would not reliably go
  red on a revert, since `rmtree` is safe against a junction already in place
  and only unsafe against one renamed mid-walk. Revert → 2 red.
- **`reap_branches()` is wired** — the leak of one ref per attempt into the
  SHARED `.git`, forever. Called from `TaskAttempt.run()` strictly AFTER intent
  resolution and never in cleanup's `finally:`, because the branch IS the effect
  key and deleting it there would leave an OPEN intent with no findable effect.
  `reap=False` opts out; `keep_worktree=True` reaps nothing by construction.
  The old test asserting the branch survives a completed run was REPLACED, not
  deleted: the crash-window property is now tested where it actually exists —
  from inside the runner, while the intent is still open. Unwiring the call →
  1 red.

## THE SPRUNG WAS MIS-SPECIFIED. Here is the measured map.

Session 2 recorded: *"All four exist; none is wired to the next."* **That is
wrong, and wrong in the direction that would have produced a bug.** Measured
before building, not inferred:

| arc | status | evidence (MEASURED 2026-07-28) |
| --- | --- | --- |
| picker → attempt | **wired** | `picker.py` `_default_attempt` → `run_attempt(candidate.to_task_spec(), …)` |
| attempt → mint | **dark AND INVALID** | `offload_runner` pins offload's `repo_root` to the candidate WORKTREE (`attempt.py:707`) |
| mint → eval | **wired** | `harness.all_tasks()` = `TASKS + load_minted_tasks()` |
| eval → picker | **wired, starved** | ran it: `eval_baseline: {"candidates": 0}` |
| ledger → picker | **DEAD** | picker never opened a ledger, and no query could enumerate a resolved attempt |

Three of five arcs were already wired. The circle was broken on the **return**
path — the half where measurement comes back and changes the next pick.

**"Wire attempt → mint", read correctly, was an instruction to build a bug.**
With `DAEDALUS_AUTO_MINT=1` an attempt mints a task whose `repo` is an absolute
path into the throwaway worktree. `TaskAttempt._cleanup` then deletes that
directory in a `finally:`. At eval time `resolve_task_repo` takes the
absolute-path branch, finds nothing, and raises `cannot resolve task repo
label` — **permanently, once per attempt, in an append-only store nothing
prunes.** Quarantine tier is what kept this survivable: `_is_primary_tier`
trusts only the exact string `"primary"`, so these rows never entered a go/no-go
number. Containment worked; the path still had to go.

The honest seam for minting already existed and needed no building:
`daedalus eval --mint-commit` → `mint_from_commit`, on landed history.

## What shipped

**A. `_is_linked_worktree` (mint.py)**, checked at the top of `_mint_from_diffs`
so it covers BOTH public entry points, not the one known-bad call site.
Detection is STRUCTURAL, and the structure was measured on real git artifacts
rather than taken from documentation — two earlier versions of this check were
wrong:

    linked worktree  .git/worktrees/<id>/  HEAD ORIG_HEAD commondir gitdir index logs
    submodule        .git/modules/<name>/  HEAD config description hooks index info
                                           logs objects packed-refs refs

A `gitdir:` pointer alone is not enough (a **submodule** has one too, and is
permanent). A `worktrees` path component is not enough either (it fires on any
repo living under a directory somebody named `worktrees`). `commondir` AND
`gitdir` together appear only in the linked-worktree layout. Verified: real
submodule `False`, real linked worktree `True`, primary `False`. An unreadable
or unexpected target fails toward "not ephemeral" — the correct direction, since
the alternative is refusing to mint from ordinary repositories.

**B. `SpineLedger.recent_intents()` and `.intents_matching_payload()`** — the
reads that did not exist. `open_intents` is a crash-recovery worklist and
excludes everything terminal, so a COMPLETED attempt was reachable only by an id
or effect_key the caller already had to know.

**C. `SpineLedger(..., read_only=True)`.** The normal constructor `mkdir`s the
parent, sets `journal_mode=WAL` (a file write) and runs migrations inside
`BEGIN IMMEDIATE` — so **opening a ledger to look at it created and mutated
it**, inside `--dry-run`, whose whole contract is that it changes nothing.
Read-only mode uses a `file:…?mode=ro` URI plus `PRAGMA query_only=ON`; SQLite
refuses writes at the engine, so a future edit that adds one cannot pass tests.
*Honest limit, stated rather than hidden:* opening a WAL database read-only
still creates the `-wal`/`-shm` sidecars — the shared-memory index is how WAL
reads work. The ledger's CONTENTS are untouched (a test pins its sha256).

**D. `attempt_history` + `apply_attempt_memory` (picker.py).** A **penalty, not
a filter** — measured: 12 candidates before, 12 after; the attempted pair moved
from ranks 1,2 → 6,7. Dropping attempted work would let one transient runner
failure delete a real task forever.

The join is **lineage plus definition**: `task_id` identifies the lineage, and
`instruction_fingerprint` (sha256 of the instruction) identifies the work. Same
id + same instruction → sink to the band floor. Same id, *different*
instruction → **not penalised**, lineage recorded in evidence and reported in a
note. An inventory id hashes `area|name|status` only, so the instruction can be
rewritten while the id stays byte-identical; penalising that would be evidence
about work nobody is proposing any more.

Lookups are **targeted, not windowed**: a row limit is a window, and old
attempts falling out of it would make their tasks selectable again — the exact
defect the memory exists to prevent. Verified: an attempt buried under 600
newer unrelated ones is still remembered.

**E. Inventory freshness, fail-closed.** See below.

**F. `rank()` tie-breaks on `prior_attempts`.** Found by its own test: the
penalty drives a candidate to its band FLOOR, which is exactly where every
candidate with no measured evidence already sits — so tried and untried collide
on score precisely when the distinction matters most. A tie-break, not a bigger
penalty: a penalty large enough to separate them would have to leave the band,
and **the stated priority is not memory's to overrule.**

**G. `EXIT_SOURCE_UNAVAILABLE = 3` and `PickedQueue.degraded_sources`.** Codex's
condition for calling this shippable, and it was right: *"source unavailable"
must not collapse into "valid source, zero candidates"*. Before it, a dry run
exited **0** whether the queue was healthy-with-work or its only source had been
withheld, and `--once` exited **1** for both "no candidate" and "the source
failed". Automation that cannot tell those apart eventually reads a broken
adapter as "nothing to do" and goes quiet — which is exactly the risk a
fail-closed source gate would otherwise introduce. `--once` on a withheld source
now prints `! inventory could not be consulted -- this is NOT evidence that
there is nothing to do` and exits 3. **0 still means, and only ever means, that
work is waiting.**

All of the above is committed as **`ebdfbfd`**.

## The finding that outranks the wiring

`docs/FEATURE_INVENTORY.json` is the picker's only effective source. It is
**hand-written** — `grep -rn FEATURE_INVENTORY --include=*.py` returns only
`picker.py` READING it, nothing generates it — and records `"head": "f40529c"`.
HEAD is `983f031`. **`git rev-list --count f40529c..HEAD` → 30.**

So the thing that chose what Daedalus works on next was reading a
hand-maintained description of a tree thirty commits gone, in a repo that
shipped `daedalus map` the day before *specifically* because "generated cannot
go stale; hand-written can, and did".

**Live consequence, and the next session hits it immediately:**

    INVENTORY SUPPRESSED (12 candidate(s) withheld): the inventory was written
    against f40529c but HEAD is 983f031

**and `daedalus improve` prints an EMPTY queue.** That is the truthful answer,
not a regression. Regenerate the inventory, or pass `--stale-inventory`.

Deliberate boundaries on that gate: dirtiness alone does NOT suppress (this repo
is dirty almost all session, and refusing to rank work whenever an editor has
unsaved changes would make the loop unusable for the one person using it); it
fails OPEN when git cannot be read at all (a tarball checkout is not evidence of
staleness); and the recorded head must be a real abbreviated sha,
`[0-9a-f]{7,64}` — without that, a recorded `"a"` matches ~1 HEAD in 16 and the
gate reports fresh **by coincidence**, which is worse than no gate because it is
believed.

## Guards, verified by DELETING them one at a time

Not asserted. Each guard was physically disabled and the suite re-run.

    BASELINE                                  114 passed
    mint ephemeral refusal        DISABLED      3 failed
    detector precision            DISABLED      1 failed
    inventory freshness           DISABLED      4 failed
    attempt memory                DISABLED     12 failed
    rank tie-break                DISABLED      2 failed
    instruction fingerprint       DISABLED      1 failed
    read-only ledger open         DISABLED      1 failed
    recorded-head shape check     DISABLED      1 failed
    targeted (no-window) lookup   DISABLED      1 failed
    one-directional prefix        DISABLED      1 failed
    degraded-source exit code     DISABLED      2 failed
    RESTORED                                  114 passed

Full suite after the sweep: **1672 passed, 35 subtests, 0 failed** (1617 at the
session-2 cut).

**The first run of this sweep found two guards with NO red at all**, and both
were real test defects, not code defects:

- The read-only test asserted the ledger's sha256. Against an already-valid
  ledger every migration is a no-op and WAL writes land in the sidecar, so the
  bytes never move and the test could not tell the two open modes apart. It now
  also points the picker at a file that is NOT a ledger: a writing constructor
  would `CREATE TABLE` and turn it into one, so a 0-byte file staying 0 bytes is
  unmissable.
- The one-directional prefix case cannot be built from a real `.git` fixture,
  because `_head_sha` only ever returns a 40-char name. **A test that cannot
  construct the input it claims to check is not a check.** It now stubs
  `_head_sha`.

## Corrections this session earned

1. **Codex was right that the arc was not dead.** It is dark and invalid, which
   is worse. Verified in source rather than taken, and following it one step
   further than Codex did produced the *permanence* of the damage.
2. **My "task ids churn" claim was backwards.** `ident = f"{area}|{name}|{status}"`
   — tests, entrypoints and notes are OUTSIDE the hash, so the id is stable
   while the evidence moves. This is what forced lineage-plus-fingerprint.
3. **"Measurement is 3.6% of the score" is meaningless** and was retracted: the
   score has an arbitrary additive offset. The real evidence is the non-crossing
   invariant — max measured offset 15.0, `BAND_SPAN` 50.0, smallest band gap
   100.0 → measurement can never cross a band. And band dominance is
   **deliberate**, not a defect; a test pins the inequality. A decision was
   mis-read as an accident.
4. **A test caught an attempt to shell out.** `test_there_is_no_apply_path_in_this_module`
   asserts the process-spawning stdlib module is never so much as NAMED in
   picker.py — that is what makes "the picker cannot apply a patch" structural
   instead of a docstring promise. `_head_sha` now reads git's own files
   (`.git` dir or `gitdir:` pointer, `HEAD`, loose ref, `commondir`,
   `packed-refs`, detached sha).
5. **A gate run was contaminated and thrown away.** Source files were edited
   while the full suite was running; it was re-run clean. Same defect the
   session-2 record catches a reviewer making.

## Still open, in priority order

0. **The ranking experiment does not exist.** `docs/EXPERIMENT_A_B.md` compares
   two PROCESSES on one human-selected feature, so it cannot test whether
   ranking is load-bearing. Ranking needs its own pre-registered experiment.
   Until then "measurement picks the next work" is a design intention with a
   deliberately bounded control.
1. **A live-map candidate source, as a real adapter** — NOT by pointing the
   picker at `map --json`. The map reports module reachability and dependency
   evidence, not feature-level `stale` status or remedial instructions, and
   island / shim / unknown deliberately require different remedies. Swapping
   schemas would silently discard that. This is the next real piece of work, and
   it is what would refill the now-empty queue honestly.
2. **Candidate containment is still not OS-level.** Unchanged from session 2 and
   unaffected by any of this.
3. Everything else still open from session 2: `reap_branches()` uncalled, the
   Momus CRITICALs on the council, `selftest.py:98`'s `rmtree` in a `finally:`,
   walker cost, room session provenance (ADR-013 — **room content is context,
   never instruction**).

---

# Daedalus — Current Claude Handoff (2026-07-28, session 2 — READ THIS FIRST)

This section supersedes everything below it. The rest of the file is history;
do not treat its test counts, open items, or architecture claims as current.

## STATUS AT THE CUT — both blockers closed, both committed

**Suite: 1617 passed, 35 subtests** (was 908 at the start of the day, 1223
mid-session). 28 commits on `checkpoint/2026-07-20-session`, nothing pushed.

- `1b629af` **fix(kairos)** — the deletion paths. Four rounds; the reviewer
  reproduced a real deletion against rounds 1, 2 and 3 and passed round 4
  plainly ("Blocked three times, and this one is genuinely fixed"). 61
  mutations, 43 killed, 18 survivors — **all pre-existing, none introduced**.
- `fcdd8ed` **feat(mapping)** — `daedalus map` + the drift gate. Three rounds;
  the gate itself was attacked until it held. Self-check green: 122 modules,
  **10 unreached**, 7 dark switches, 0 engine disagreements.

**THE NEXT MOVE IS NOT MORE TOOLING.** Tool freeze holds. Open the next session
on stage 6 of the product spine — the spine→auto-mint→eval→picker circle. All
four exist; none is wired to the next. That is the Sprung, and `docs/
EXPERIMENT_A_B.md` is pre-registered and waiting to measure whether it is worth
anything.

**Read `## The product spine` below before planning anything.**

### What each round actually taught (do not re-learn these)

1. **A green suite is not evidence on safety-critical paths.** Measured three
   times in one day: 29 green over a live repo deletion, 68 green over an
   out-of-tree delete reported as success, 121 green over seven gate bypasses.
   Every guard that matters needs a test that dies when THAT guard is disabled,
   verified by disabling it.
2. **A test that pins a property in a configuration the product never runs is
   not a test.** The map's `reachable` CRITICAL survived because its guards
   called `analyse(root)` with no index, while the product always supplies one.
   Two tests three lines apart asserted opposite things and both passed.
3. **A narrow brief can produce a fix for the attack script instead of the
   hole.** Minos overrode its own brief and closed an ancestor variant; the
   reviewer then built all three variants and measured that the leaf-only fix
   both of us had scoped ALSO lost 40/40 files.
4. **Prose in a docstring is a claim, not a control.** Both subsystems shipped
   confident guarantees that were measurably false — including two printed on
   the generated artifact, where the reader trusts them precisely because they
   are generated.

## The two things that mattered most (RESOLVED — kept as the record)

**1. ~~A CRITICAL is OPEN~~ — CLOSED in `1b629af`.** A cross-vendor review found that
`cleanup_worktree` could delete the primary repository (candidate code plants a
Windows junction; cleanup resolves it, git refuses, `rmtree` runs). A fix was
written, self-verified, and shipped with 29 green tests — and an independent
security review then **reproduced the same deletion against the patched code**,
through the public API, with all six containment checks passing honestly, while
`cleanup_worktree` returned normally and reported `worktree_removed=True`.

The mechanism is a stale classification: `_remove_tree_no_follow` lstats a
subdirectory, pushes it on a LIFO queue, and later `os.scandir`s it with no
re-check. The window is the whole remaining walk (measured: 1.067 s of a
1.122 s traversal). Plain `shutil.rmtree` survived the same race 3/3; the
bespoke walker failed 3/3 — the replacement is worse than what it replaced.
A second CRITICAL: `reap_branches` globs an allocation directory candidate code
can write, and deleted two branches of real work in the reproduction.

Worse than either: **three guards survive their own deletion** — the suite stays
fully green with `_refuse_if_repo_adjacent`, `_remove_tree_no_follow`, and the
reap sha-proof each disabled. A guard whose absence no test detects is
decoration. Round 2 is running under one hard rule: every guard kept must have a
test that goes red when that specific guard is disabled, verified by actually
disabling it.

**2. The "generalisation failed" claim was WRONG — I read the wrong dict key.**
Retracted the same day it was written. `build_index` on the sibling repo
`PnP_App` returns **25 files** across javascript/typescript/css/python, 99,569
tokens. The earlier "0 files" came from reading a key named `files`, which the
index does not have; the real keys are `n_files` and `modules`. An empty lookup
was mistaken for an empty index and written into this handoff, the memory and
the architecture artifact before anyone checked it.

What IS true and much smaller: `daedalus context` on that repo selected 0 files
for a given objective. Likely cause is the project config — `projects/pnp_app.json`
declares `center: ["app", "src", "design/visual-lab/src"]` and the first two do
not exist yet by design, so scope resolution has almost nothing to offer the
planner. That is a config question, not a broken engine. Still worth diagnosing
before the A/B experiment, since Arm B's advantage is context.

**Take the lesson, not just the correction:** this is the same failure class the
rest of this document catalogues — an unverified reading asserted with
confidence and propagated into three places within the hour.

## Where things stand

**Measured, not inherited:** `python -m pytest -q` → **1223 passed, 35 subtests**
(was 908 at the start of this session). `compileall` clean. 26 commits on
`checkpoint/2026-07-20-session`, nothing pushed. 33 files dirty — see §Uncommitted.

**What was built:** a self-improvement spine and a cross-vendor council.

- `daedalus/spine/` — `ledger.py` (SQLite WAL intent-before-effect ledger; no
  UPDATE anywhere, state lives in an append-only event table; refuses to run if
  WAL did not actually engage), `cancel.py` (Windows Job Object process-tree
  kill; `signal.SIGINT` does not work on win32 and leaked grandchildren),
  `attempt.py` (TaskAttempt: worktree → runner → gates → PatchArtifact),
  `picker.py` (measurement-sorted work queue).
- `daedalus/council/` — `bus.py` (hash-chained transcript), `vendors.py`
  (uniform adapter over four vendors, secret floor before every egress),
  `session.py`, `publish.py` (GitHub PR bridge), `canary.py` (vendor heartbeat).
- `runs/council/` — "Der Raum": a shared append-only chatroom where agents from
  different vendors take turns, plus a local web GUI at
  `python runs/council/room_server.py` → <http://127.0.0.1:8765>.
- Skills: `council` (project) and `room` (portable, `~/.claude/skills/room/`).
- ADR-011 (event spine), ADR-012 (council), ADR-010 (naming namespaces).
- `daedalus/metron/` was renamed `daedalus/kairos/` (product scheduler); the
  crew's own gate-runner keeps the name Metron. Both old aliases still import.

## The three corrections this session earned

1. **The "HALVING LAW" was a misdiagnosis.** Session 4 recorded that Ollama's
   usable input window is `num_ctx/2`. It is not. Measured on the bench with
   fresh unique prompts: `num_ctx=16384` evaluated **3971** and **14375** prompt
   tokens with full first-word recall. Only an OVER-BUDGET prompt collapses to
   `num_ctx/2` (8194@16384, 4098@8192) and loses its head — it is a truncation
   penalty, not a window. It persists with `OLLAMA_NUM_PARALLEL=1`. Code now uses
   full `num_ctx` minus a named `OUTPUT_RESERVE_TOKENS=1024`: usable input went
   3072 → 5120 locally, 15360 on the bench.
2. **"Structurally impossible" was false.** `attempt.py` was claimed to make it
   impossible for a candidate to write the primary checkout. Codex refuted it:
   the runner is an in-process Python callable, and passing it `ctx.worktree` is
   an argument, not a jail. The honest claim is narrower — the HARNESS never
   applies a patch to the primary checkout and there is no promotion path that
   does. Candidate containment needs an OS sandbox, which does not exist yet.
3. **A cleanup path could delete the repository.** `cleanup_worktree` resolved
   its path first (following a symlink or a Windows junction), git then refused
   to remove a main working tree, that refusal was caught, and `shutil.rmtree`
   ran on the resolved target — in a `finally:` block, in code meant to run
   unattended. Reproduced (`AssertionError: the primary repository was DELETED`)
   and closed by containment-by-identity: no-follow checks BEFORE resolving,
   allocation record written at creation, reparse-point detection (`os.path.islink`
   misses `mklink /J` junctions — measured: `islink=False`, reparse tag `0xa0000003`).

## The 922-line lesson: stop hardening the walker (2026-07-28, measured)

`git diff --stat HEAD -- daedalus/kairos/worktree.py` → **+922 / -28**. The tree
walker at the centre of both later CRITICALs — `_remove_tree_no_follow`,
`_force_rmdir` — appears **zero times in HEAD**. It is entirely new code,
written to fix the original deletion bug.

Sequence, all measured, none of it inferred:

- Round 1: fix ships, 29 green tests. Cerberus reproduces a repository deletion
  against it, 3/3.
- Round 2: fix ships, 68 green tests. Cerberus reproduces an out-of-tree delete
  against it, 3/3, through the public API, reported as success (drain loop,
  `worktree.py:377-380`; blast radius bounded to empty directories).
- Round 3: running.

**Two consecutive failures inside code that exists only to fix the first failure
is a signal about the APPROACH, not the implementation.** We are hand-writing a
Windows reparse-point-aware traversal that must out-reason the OS about what a
path means, using the same ambiguous primitives that caused the bug, and every
hardening pass enlarges the surface. Cerberus has now named the real answer
twice: **OS-level isolation** — let the operating system enforce the boundary
instead of parsing our way to it. `worktree.py:45-47` already admits this floor;
the move-in attack (`os.rename(primary_checkout, worktree/moved_in)`, no reparse
point involved, whole checkout destroyed, cleanup returns normally) cannot be
closed by any reparse check, ever.

**UPDATE after round 3 was reviewed — the trend reversed, so round 4 WAS
opened, deliberately and narrowly.** Round 3 is the first round that got
better rather than merely different, and it is measured: the drain hole and a
second hole the fixer found itself (the entry loop — `os.unlink` through a
swapped parent destroys FILE CONTENT, 196/200 victim files with the guard
removed) are both closed 3/3; the residual race window fell from **1.067 s to
4.3 µs median** with a blast radius of exactly one object; the guard round 3
deleted really is dominated (0 counterexamples in 216,225 enumerated shapes)
and its replacement closes a hole nobody had reported (`DAEDALUS_WORKTREE_ROOT`
reached through a junction was placing candidate worktrees INSIDE the
developer's checkout). Round 4 is one CRITICAL and two `high`s, no redesign.

**The round-3 CRITICAL, and it is the sharpest irony in this file:**
`_path_identity` (`worktree.py:185-199`) used `os.stat`, which FOLLOWS reparse
points, inside the module whose entire thesis is never following them. So the
move-in mitigation read the identity THROUGH a junction, matched, and did not
fire: `rename(checkout, wt/moved_in)` + `mklink /J checkout wt/moved_in` →
40/40 tracked files, `.git` and the sentinel destroyed. `os.lstat` is the fix.
Two prose claims (`:668-671` "cannot do this", `:55-57` "knows the identity of
exactly ONE directory") were measured false and go with it.

**ROUND 4 CLEARED — committed as `1b629af`.** The reviewer passed it plainly
after blocking three times, and verified the ancestor variant in BOTH
directions by building three code variants and running one attack against
each: round 3 lost 40/40 files, **the leaf-only fix the brief and the reviewer
had both scoped ALSO lost 40/40**, and only the shipped version refuses. That
is the whole argument for letting a fixer override a narrow brief.

Final state: 61 mutations, 43 killed, **18 survivors, every one pre-existing**
(load-bearing: `_is_within` separator anchoring, the `_read_allocation`
forgery cluster). No false positives on legitimate layouts — verified against
real junction ancestors, `subst` drives, and a 658-directory OneDrive tree.
The one hole the fixer disclosed as un-closable (in-place
`FSCTL_SET_REPARSE_POINT` retarget) turns out to fail with
`ERROR_DIR_NOT_EMPTY` on any recorded ancestor: the disclosure was honest and
slightly over-cautious.

Two process notes worth keeping, because they cut both ways. The fixer caught
that the REVIEWER's working copy was stale — a verdict from it would have been
about code that does not ship. The reviewer then caught that the fixer's byte
count for "shipped" was also wrong (71,722, not 58,324), and caught its own
mid-review contamination (probing a tree while its mutation runner rewrote it),
rebuilt an isolated copy and re-ran. Each side found something the other had
wrong. Neither would have found it alone.

**If a round 5 is ever needed, do NOT open it as more hardening.** The next
move is containment at the OS boundary (job object + restricted token /
sandbox / separate volume), not another guard. The move-in attack against a
DIFFERENT checkout than `manager.repo_path` remains open by construction and no
reparse check can ever close it.

**Logged separately, same defect class, NOT in this file:**
`daedalus/selftest.py:98` runs `shutil.rmtree(repo, ignore_errors=True)` in a
`finally:` on a directory a model just wrote into. Round 3 spent itself removing
exactly this pattern from `attempt.py`. Real, out of that round's scope, unfixed.

**Cost is real and depth-dependent — do not quote "2x".** Measured, 400 files
per shape: depth 2 = 2.2x, depth 6 = 3.0x, depth 12 = 4.3x, depth 20 = 5.9x.
A worktree carrying `node_modules` or a `.venv` (30k-200k files at depth 8-15)
puts cleanup into tens of seconds inside a `finally:`. The fix is known
(hoist `_chain_between` out of the per-child loop; the chain is pure text, the
fresh lstat per component stays) and was deliberately deferred — a round that
closes live deletion bugs is the wrong round to add caching. It is now the top
follow-up: a slow cleanup in a `finally:` block is its own hazard.

**The generalisable finding is about the SUITE, not the file:** of 61 mutants
(final count), **18 guards survive their own deletion**. Three times in one day
a fully green suite sat over a live escape. That is now a measured property of
this repo's tests, and it is the reason `tests pass` cannot be the fitness
signal for the self-improvement loop.

## `daedalus map` — the generated artifact (committed, `fcdd8ed`)

The answer to "can an architecture artifact always exist and grow organically."
Generated cannot go stale; hand-written can, and did — 136 features on the
morning's inventory against 827 from the afternoon's deep read, same tree.

    daedalus map              regenerate docs/architecture-map.html + snapshot
    daedalus map --check      GATE: exit non-zero on unaccepted drift (15-20s)
    daedalus map --json       machine-readable, writes nothing
    daedalus map --accept ID  explicit, dated, EXPIRING acceptance

Mechanical half regenerated every run (`daedalus/mapping/`): `reach.py` derives
entry points rather than listing them — from one seed in `[project.scripts]` it
parses the CLI's if/elif dispatch, so the lazy import in each branch is a real
edge; `switches.py` finds every env/default gate; `drift.py` compares against
the COMMITTED snapshot; `render.py` draws it. Narrative half stays hand-written
in `docs/architecture-narrative.md` and the ADRs.

Current numbers: 212 modules, 131 entry points, **10 unreached** (7 islands,
3 shims: `decompose.py`, `drafts.py`, `mission_control.py`), 7 dark switches,
6 doc drifts, 0 engine disagreements.

**`--check` belongs in CI, NOT in a pre-commit hook.** 15-20s; a slow hook gets
bypassed, which is the exact failure this subsystem exists to prevent.

**The snapshot MUST stay committed.** Untracked, there is no diff — and the
diff is the entire control. That was a blocking review condition.

Known soft spots, disclosed rather than hidden: `_IGNORE_DIRS` is a second
ignore configuration the snapshot does not record; a module named `test_*.py`
is classified `test` and `test` counts as reached, so naming product code as a
test hides it (visible in review, but real).

## Uncommitted, and why

- `daedalus/council/canary.py` — vendor heartbeat, still under adversarial review.
- `runs/council/room*.py` — the room is being wired to use `semantic_slice`,
  the hash-chained bus, and an unread cursor instead of raw whole-file attach.
- `LICENSE` — Apache-2.0 body with NO copyright holder and no license metadata
  in `pyproject.toml`. Deliberately left for the owner to decide.
- ~17 EOL-only files whose canonical diff is empty. Do not commit them.

## Open, in priority order

0. **THE SPRUNG — close ONE circle, then measure it.** stage 6 of the product
   spine: `spine` (attempt recorded) → auto-mint (attempt becomes an eval task)
   → `eval` (task measures) → `picker` (measurement chooses the next attempt).
   All four modules exist; none is wired to the next. This is the only place in
   the system where wiring produces amplification rather than surface area, and
   it is what "Daedalus schreibt Daedalus" actually requires. Then run
   `docs/EXPERIMENT_A_B.md` — if Arm B loses, that is the most valuable thing
   this project can learn, for the price of one feature.
   **Fitness signal warning, now MEASURED and not an opinion:** `tests pass` is
   worthless as a promotion criterion here (three green suites over three live
   escapes in one day). The loop must gate on the deterministic gates plus the
   decontaminated eval, and that eval is still marked ADVISORY.
1. ~~Commit the security fix~~ — done, `1b629af`.
2. **Wire `reap_branches()`** — `git worktree add -b` leaks a branch ref into the
   shared `.git` on every successful attempt, forever. The reaper exists and is
   tested; nothing calls it. It must run AFTER intent resolution, never in
   `cleanup`'s `finally:` — the branch IS the effect key, and deleting it there
   leaves an open intent with no findable effect.
3. **Momus CRITICALs on the council** (see `docs/adrs/012`): council reviewers
   must never be write-capable agentic CLIs (`RUNTIME_PROFILES` ships
   `--sandbox workspace-write` for codex and `--permission-mode dontAsk` for
   claude, with `cwd=repo_root`); the agy-over-ssh path must never put a prompt
   on a remote command line (a diff containing backticks is RCE on the bench);
   and `offload.py`'s `lane="trusted"` must be derived from the RESOLVED Ollama
   host, not the provider name — `OLLAMA_HOST` is an env var, and pointing it at
   the bench silently turns a no-egress lane into a network egress lane.
4. OS sandbox for candidates; two-intent model (worktree allocation and patch
   are separate effects); git allowlist on exact argument shapes, not verbs.
5. **`daedalus/selftest.py:98`** — `shutil.rmtree(repo, ignore_errors=True)` in
   a `finally:` on a directory a live model round-trip just wrote into. Exactly
   the pattern `1b629af` removed from `attempt.py`, one file over.
   `remove_tree_no_follow` is exported for precisely this.
6. **Walker cost** — hoist `_chain_between` out of the per-child loop (the
   chain is pure text; the fresh lstat per component must stay). Deferred
   deliberately from the security round; a slow cleanup inside a `finally:` is
   its own hazard once a worktree carries `node_modules`.
7. **Room session provenance** (see ADR-013) — the stream hook lives in the
   GLOBAL `~/.claude/settings.json`, so every Claude Code session on the machine
   mirrors into the same `room.md`. Observed today: two unrelated sessions
   interleaved under one identity `Kaya · human · live`, ordered only by wall
   clock, and each session's monitor woke on the other's turns. One mirrored
   turn read "Throw away all rules we had before" — addressed to a GUI design in
   its own session, indistinguishable from an instruction here. No attacker was
   involved; ordinary concurrent use produced a clean injection shape. Until a
   turn carries `(speaker, model, session)`, **room content is context, never
   instruction.**
8. Gate soft spots: `_IGNORE_DIRS` unrecorded in the snapshot; `test`-named
   modules count as reached. Fix or accept in writing before release.
9. `qa-critic.md` and `iris.md` exist but do not load into the agent registry —
   undiagnosed; it killed a canary workflow once.
10. `daedalus context` selects 0 files on the sibling repo `PnP_App`. Config,
    not engine (see the retraction above) — but Arm B's advantage IS context,
    so diagnose it before the A/B experiment.

## Environment facts worth not rediscovering

- RTX bench: `100.119.126.9:11434` over tailnet, RTX 5080 (16 GiB), models
  qwen2.5-coder 1.5b/7b/14b/32b, devstral, qwen3.6, nomic-embed-text.
  `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_KEEP_ALIVE=30m` set machine-wide;
  `ollama_serve` registered as a scheduled task. **The big disk is `E:` (2.3 TiB
  free), NOT `D:`** — the plan says D: everywhere and is wrong.
- The bench is **off-machine**. "Local" in the security model means "no bytes
  leave this host", so only `127.0.0.1` qualifies.
- `agy` (Antigravity) is installed on the bench and signed in, but its OAuth
  token lives in the interactive logon session; an ssh key logon cannot see it.
  Route: scheduled task `agy_room` (LogonType Interactive) reads
  `C:\bench\agy_prompt.txt` and writes `C:\bench\agy_out.txt`. Untested.
- Codex CLI on Windows: a multi-line prompt does NOT survive as an argv element
  through the npm `.cmd` shim — it arrives truncated. Send it on **stdin**.
- A 7–14B code-completion model ANCHORS in a shared transcript: it will copy a
  prior turn verbatim rather than reason. Observed twice, identically. Use local
  models for attaching/summarising/scoring, not as debate participants.
- Claude Code re-reads `settings.json` on change; invalid JSON silently voids the
  whole `hooks` block.

## The room and the council — what they are, and how to run them

Built this session, in use, and the reason the CRITICAL above is known:

- `runs/council/room.py` — a shared append-only markdown chatroom where agents
  from four vendors take turns. Wired to daedalus rather than reinventing it:
  attachments are DISTILLED via `structcore.semantic_slice` (measured 71.6%
  smaller on a real file), every turn is mirrored into the hash-chained
  `daedalus.council.bus` (`room.py verify` names the failing position), and a
  per-speaker unread cursor replaced re-sending the whole room (88.4% smaller).
- `runs/council/room_server.py` → <http://127.0.0.1:8765>, a local GUI. The
  human is a participant, not an audience.
- `runs/council/stream_hook.py` — a Claude Code hook mirroring this session into
  the room, abridged to a lede plus a pointer to a full sidecar (84.2%).
- `runs/council/summarize.py` — an ASYNC second stage: `claude-haiku-4-5` turns
  a mirrored turn into DECIDED / CHANGED / ASKS / CONSTRAINT lines (87%). Async
  by design: an external service must never sit in an operational write path.
- Skills: `council` (project) and `room` (portable, `~/.claude/skills/room/`).

Hard-won operational facts, all measured, do not relearn them:

- **A completion-tuned local model ANCHORS in a transcript.** qwen2.5-coder
  returned the same 21 characters three times, once with the full source of the
  file it was asked about in front of it. Fix: `solo` mode — task and material,
  no transcript. Same model, same file, then produced a correct 269-char answer
  naming the exception class. Local models are for summarising/scoring, not
  debate. `--with-room` opts back in.
- **The cursor is keyed by (speaker, model), not speaker.** A model swap in the
  same slot inherited the previous model's cursor and was sent ZERO turns while
  the caller had asked for the transcript — it answered from nothing, silently.
- **A vendor failure must never become a turn.** An agy OAuth timeout landed in
  the room as a turn whose body was the full authorization redirect with scopes
  and state. Failures now raise `VendorError`, print to stderr, exit 5.
- **Two feedback loops were observed and closed.** Monitor notification →
  mirrored as a turn → monitor fires again; and `claude -p` inside the
  summariser starting a session that fires the same hook. Both were closed;
  expect a third through some other door.
- Codex on Windows: a multi-line prompt does not survive as an argv element
  through the npm `.cmd` shim. Send it on **stdin**.
- agy's token lives in the interactive logon session; ssh cannot see it. Route:
  scheduled task `agy_room` (LogonType Interactive) reads `C:\bench\agy_prompt.txt`,
  writes `C:\bench\agy_out.txt`. **Still untested** — run `schtasks /run /tn agy_room`.

## The A/B experiment

`docs/EXPERIMENT_A_B.md` is pre-registered and NOT yet run: one large feature
built twice, crew-only vs full Daedalus, blind-judged. Read it before running
anything that resembles a benchmark. Two points from it that matter generally:
the headline metric is **tokens per accepted outcome**, not tokens; and the
session that built the system cannot be its unblinded judge. §6 lists what must
be true before it can run — all three blockers are the open items above.

## The product spine — six stages, one workflow (agreed with the owner, 2026-07-28)

The owner asked for "all features combined into one big workflow for the user."
The answer is the ordering principle for everything that follows, GUI included.
The one workflow is: **you say what you want → you get it back, improved by the
fact that the system has done things before.** Six stages, one thread:

1. **Intent** — plain language to chat-Ikarus. No flags, no config.
2. **Plan** — the Architect compiles a mission: project, kitchen, crew, cost.
   The user sees ONE card (understanding + price) and one go/no-go.
3. **Build** — the kitchen works; the room livestream is the glass the user may
   watch through, never a console they must operate.
4. **Gates** — Momus before, eval during, Cerberus after. The ONLY moments the
   workflow stops for the human: veto, approval, price change. Green flows past
   silently.
5. **Delivery** — result plus provenance receipt (measured / assumed / refused),
   not logs.
6. **Digestion** — the attempt feeds the spine, mints an eval task, sharpens the
   picker. The next order is cheaper because this one happened.

Three consequences, so nobody re-litigates them:

- **Nobody ever sees 827 features.** Every feature lives inside one stage;
  a feature that needs its own button usually marks an orchestration failure.
  The GUI epic is *rendering these six stages on one screen*, nothing more.
- **Stage 6 is the Sprung.** spine → auto-mint → eval → picker all exist and
  none is wired to the next. Closing that ONE circle is the next session's
  opening move — before any further tooling (tool freeze declared 2026-07-28
  after `daedalus map`; the map was the last infrastructure that gets built
  before the loop runs).
- **The GUI comes after the loop has an A/B number.** Its acceptance metric is
  already fixed: a surface is done the day the owner stops using the terminal
  for that task.

And so stage 6 is not under-read: **CodeEvolution (Ariadne + the Grove) IS
stage 6 grown up.** The owner's frame (2026-07-28): Daedalus as THE AGENT OS —
Jarvis shell, dynamic agent workforce (knowledge management, codebase editing,
code evolution, general-purpose work via Hermes/ADR-002), local models as the
grey matter. Ariadne looks parked only because evolution without a trustworthy
fitness signal is the AlphaEvolve-clone failure mode (candidates passing their
own tests); the spine→mint→eval→picker circle is Ariadne's ignition, not a
detour from it. Lane A2 stays closed on measurement (ceiling 2.3%, reopen =
eval/ceiling.py). The latent layer (LATENT_PROJECTION_INDEX, memory/embeddings,
semantic_route) is the binding fabric for all of it — note the dead-latent-route
bug in the validation status before trusting any of its routes.

## Method note

The council found all three corrections above, and Opus 4.6 found two things
both Codex and Claude missed. A fresh Claude instance, reading cold, then
predicted that the session lead would not request a review of its own fix
because it was in flow — and was right until the human asked. Cerberus then
reproduced a repository deletion against that fix. **No test found any of it.**
Agents disagreed with the session lead five times and were right five times.

The standing lesson, and the thing to wire next: none of this should depend on
someone remembering to ask. A patch to safety-critical code should not be able
to reach a commit without an independent adversarial pass, and that rule belongs
in the gate, not in a person's discipline.

---

# Daedalus — Handoff (2026-07-28, session 1)

This section is superseded by the one above but retained as evidence.

## 0. Executive state

The session converted the Antigravity synthesis into an evidence-backed
foundation and wrote the long-horizon plan for:

- **Ikarus** — the user-facing, JARVIS-like assistant;
- **Ariadne — the Daedalus Forest Evolution Engine** — the evolutionary search
  subsystem;
- **The Grove** — Ariadne's append-only Quality-Diversity archive;
- **Kairos** — mission compilation and scheduling;
- **Forge / Talos / Nemesis / Cerberus** — execution transactions, evaluator
  packs, independent verification, and policy.

`ForestEvolve` remains a useful descriptive CLI/protocol name. It is not a
second product identity.

Read these first:

1. `docs/IKARUS_ARIADNE_MASTER_PLAN.md` — version 0.2, the dependency-gated
   masterplan and definitions of done.
2. `docs/FOUNDATION_AUDIT.md` — what survived the Antigravity audit and what was
   removed as unsupported.
3. `docs/LATENT_PROJECTION_INDEX.md` — exact Latent Index v2 contract and
   migration behavior.
4. `docs/adrs/009-ariadne-forest-evolution-engine.md` — naming and role
   decision.
5. `docs/bypasses.md` — known security gaps; proposed components are not
   guarantees.

Branch/working state:

```text
branch: checkpoint/2026-07-20-session
HEAD:   f40529c
state:  large, intentionally dirty, uncommitted working tree
```

Do not reset, checkout, bulk-format, or discard this tree. It contains the
user's prior work plus the audited foundation. Split commits only after
reviewing provenance and coherent scope.

## 1. What is implemented now

### 1.1 Knowledge Forest and DSS v0

Relevant files:

```text
daedalus/structcore/forest.py
daedalus/structcore/dss.py
daedalus/context_plan.py
tests/test_forest.py
tests/test_dss.py
tests/test_context_plan.py
```

The implemented object is a versioned multiplex forest/hypergraph, not a claim
that software is literally an acyclic tree.

DSS v0 provides:

- deterministic repo/directory/file hierarchy;
- restriction and branch-bounded prolongation;
- independent import, co-change, exact-clone, near-clone, and rename channels;
- clone hyperedges retained as hyperedges;
- temporal carry only through stable IDs or explicit rename confidence;
- measured file-token costs;
- greedy token-budget packing;
- content-addressed receipts.

The hybrid planner adds path/symbol BM25 seeds plus optional, path-grounded
latent memory seeds:

```powershell
python -m daedalus.cli context "<objective>" `
  --repo-root <repo> --max-tokens 8000 --json

GET /api/context/plan?project=<name>&q=<objective>&max_tokens=8000
```

The smoke run succeeded and produced a deterministic receipt. Known UX issue:
the full JSON includes exhaustive relation-channel traces and can exceed
30 kB. Add a concise default projection plus an explicit debug/evidence mode
before feeding this directly into the UI.

### 1.2 Lossless Agent Shell transport

Relevant files:

```text
daedalus/adapters/events.py
daedalus/adapters/transport.py
daedalus/adapters/subprocess_adapter.py
tests/test_adapters.py
docs/adrs/008-universal-agent-adapter.md
```

Agent shells are translators/interfaces:

```text
native runtime input/output/tool event
  -> lossless TransportRecord
  -> optional text projection
  -> optional versioned embedding projection
```

Claude and Codex one-shot profiles are tested. Generic runtimes are
configurable. This is not hidden-state communication. Closed CLI text output
must never be described as model latent state.

### 1.3 Latent Projection Index v2

Relevant files:

```text
daedalus/memory/embeddings.py
daedalus/memory/__init__.py
tests/test_embeddings.py
docs/LATENT_PROJECTION_INDEX.md
```

Implemented:

- current Ollama `POST /api/embed` batch contract;
- injectable embedding backend;
- immutable `EmbeddingSpec` identity over provider, model, optional
  revision/digest, dimension, normalization, and projector version;
- append-only projection tables;
- v1 vectors quarantined instead of guessed/mixed;
- strict finite/dimension/zero-vector validation;
- exact project/trust/source filtering before scoring;
- explicit `ready`, `partial`, `embedder_unavailable`,
  `index_unavailable`, and invalid-response states;
- memory bridge now preserves project, repo root, trust, source, task, status,
  and explicit paths; path evidence is present in metadata and projection text;
- optional `OLLAMA_EMBED_MODEL_REVISION` pins movable Ollama tags.

Remaining P0: `append_event()` still performs embedding synchronously when
`DAEDALUS_VECTOR_INDEX=1`. Build the journal-offset/content-hash Projection
Worker from PR 2.5 in the masterplan; never make Ollama availability part of
the operational append path.

### 1.4 Accelerator capability contract

Relevant files:

```text
daedalus/accelerators.py
tests/test_accelerators.py
```

Surfaces:

```powershell
python -m daedalus.cli accelerators --json
GET /api/accelerators/status
```

The local machine exposes an MX330 (compute capability 6.1, 2 GiB). A shallow
probe does not claim CUDA readiness merely because a Python package imports.
Remote RTX Ollama remains unconfigured:

```text
DAEDALUS_RTX_OLLAMA_HOST
DAEDALUS_RTX_OLLAMA_TOKEN   # optional; always redact
```

Lane semantics are explicit:

- CUDA tensor inference: unverified until an active kernel smoke passes;
- cuVS/cuGraph/Warp/Newton: missing locally;
- Optical Flow: image/UI temporal tasks only;
- DLSS: unsupported as a general code/tensor backend;
- Newton/PhysX: domain evaluators, never general code semantics.

The user's large `D:` HDD is on the remote RTX machine, not this host. Design
that worker as compute + content-addressed artifact storage:

- RTX SSD/NVMe, if present: active scratch/workcells/index hot set;
- RTX `D:` HDD: Grove artifacts, datasets, model cache, completed workcells,
  and cold/warm archive;
- local kernel: digests, metadata, small receipts;
- missing remote volume must return `storage_unavailable`, never silently spill
  to local `C:`.

The next session needs the RTX worker's reachable endpoint, authentication
method, and actual D:-capacity/free-space probe before wiring mutations or
model downloads.

### 1.5 Safety corrections made this session

Two mathematically/security-false execution claims were closed:

1. `core._codex_report` previously granted a direct forced-Codex
   workspace-write while bypassing offload snapshot, verifier, rollback, and
   worktree execution. Forced `--lane codex` is now advisory-only until Forge.
2. Kairos previously called parallel writes “safe” when declared path strings
   were disjoint, although a writer could touch undeclared files while
   `isolate_paths` observed only declared paths. Writable attempts now run
   sequentially with whole-repo attribution. Only advisory work may overlap.

Do not overstate this fix. The system still has split execution worlds:

- legacy offload/provider paths can mutate the primary checkout;
- `_ask_claude_report` is not unified with adapters/worktrees;
- auto-routed Codex/Ollama writes are not Forge transactions;
- worktrees are not a host-security sandbox;
- no durable Mission state machine exists.

The next write-capable architecture must go through one `TaskAttempt` /
`ExecutionTransaction` service. Do not re-enable forced Codex or parallel
workspace writes as an interim shortcut.

### 1.6 Evolution status

`daedalus/kairos/evolution.py` remains a Best-of-N baseline:

- launch N candidates;
- run a fixed `pytest`;
- reject failed candidates;
- choose a green candidate.

It is not evolution at AlphaEvolve level. There is no persistent candidate
archive, lineage, parent/inspiration sampling, Quality-Diversity, frozen
external evaluator bundle, repeated benchmark statistics, or promotion root of
trust.

Ariadne is specified, not implemented. “Better than AlphaEvolve” remains a
falsifiable hypothesis requiring equal-budget, multi-seed held-out comparison.

## 2. Removed or quarantined claims

Do not restore these without an independent benchmark:

- radial projection of Euclidean embeddings called Poincaré semantics;
- weighted embedding averages called a code gradient;
- spectral partitions called conflict-free schedules;
- latent-vector interpolation treated as a decoder for discrete code patches;
- DLSS treated as an arbitrary tensor/code interpolator;
- PhysX collisions treated as merge conflicts;
- graph-layout distance used as semantic ground truth;
- candidate-authored tests used as sole correctness proof.

Sparse spectral analysis remains read-only/scoped visualization with explicit
limits. Hyperbolic geometry is allowed only as a separately trained,
hierarchy-aware experiment with Euclidean/BM25/graph baselines.

## 3. Validation evidence

Final validation on 2026-07-28:

```text
python -m pytest -q
  882 passed, 30 subtests passed in 143.34s

focused new foundation set
  67 passed in 11.43s

python -m compileall -q daedalus
  pass

npm.cmd run build  (apps/web)
  TypeScript pass
  Vite production build pass
  1,784 modules transformed in 4.58s

python -m pip wheel . --no-deps --wheel-dir runs/validation_wheels
  daedalus-0.1.0-py3-none-any.whl
  365,780 bytes
  SHA256 EE2EC874046DF7EBF3396741B1B0ED5CC24F8758D7A58D9B780807AF229200B6

git diff --check
  pass; only expected LF/CRLF warnings
```

Re-measured after the commit-hygiene pass that landed this foundation
(2026-07-28, later the same day). The `882` above is kept as recorded: it was
true when measured, before the native-Ollama layer added its tests.

```text
python -m pytest -q
  908 passed, 30 subtests passed in 114.43s

python -m compileall -q daedalus
  pass
```

Provenance: [M] measured on this box against the post-hygiene HEAD. Not
re-run in this pass: the npm build and the pip wheel — both regenerate
artifacts (`apps/web/dist`, `runs/validation_wheels/`) that are now
gitignored and deliberately kept out of history, so their numbers above are
[INHERITED] from the run that produced them.

The first full test attempt had three temporary-Git failures while C: had only
0.57 GiB free. After the user cleared Downloads, C: reached ~14.36 GiB; the
failed fixture passed 4/4 and the clean full run above passed. Treat this as
evidence for the planned storage watermark, not a flaky test.

The wheel is in `runs/validation_wheels/`. Frontend output is in
`apps/web/dist/`. The optional `python -m build` package is not installed;
`pip wheel` was used without changing the environment.

## 4. Exact next sequence

Do not add UI spectacle or new math names next. Follow the dependency gates:

### A. Commit hygiene first

1. Inspect the full dirty tree.
2. Separate pre-existing/session work from the audited foundation.
3. Run targeted tests per commit group.
4. Never squash unrelated user work into a mystery “Ariadne” commit.

### B. Movement 1 — Mission Spine

Implement:

```text
daedalus/missions/spec.py
daedalus/missions/state.py
daedalus/missions/store.py
daedalus/missions/events.py
daedalus/missions/recovery.py
```

Start with canonical `MissionSpec`, validated budgets/scope/policy digest, a
durable state machine, idempotency keys, leases/heartbeats, cancel/resume, and
crash-replay tests.

### C. Movement 2/4 — one mutation transaction

Unify adapters, legacy providers, worktrees, and offload behind:

```text
Mission -> TaskAttempt -> ExecutionTransaction
        -> TransportRecords + PatchArtifact
        -> Talos/Nemesis receipts
        -> explicit PromotionPacket
```

No provider may write the primary checkout before promotion. Compare actual
patches for integration; declared path overlap is only a scheduling hint.

### D. Projection Worker in parallel

Consume the append-only journal by file identity, byte offset, and record hash.
Retry independently, pin the Ollama model digest, retain full provenance, and
make re-projection idempotent.

### E. Then Grove + Ariadne Alpha

Only after transactions and frozen evaluators:

1. append-only `Experiment`, `Candidate`, `LineageEdge`, `InspirationEdge`,
   `EvaluationRun`, and `SelectionDecision` schemas;
2. record the current Best-of-N runner as an explicit baseline;
3. external evaluator cascade with timeouts and protected tests;
4. Parent/Novelty/Failure sampling;
5. Pareto + MAP-Elites/island baselines;
6. equal-budget, multi-seed ablations.

### F. Remote RTX worker

Register it through authenticated health/capability/storage receipts. First
jobs should be Ollama embedding batches and reranking. Later candidates:
cuVS ANN, cuGraph layout, Warp semantic kernels, and a custom TensorRT DSS
residual. DLSS remains inspiration, not a backend.

## 5. Stop conditions

Pause and report instead of improvising when:

- Forge/storage volume is unavailable;
- a model revision/dimension does not match its projection index;
- an evaluator/policy digest changes mid-experiment;
- disk drops below the configured watermark;
- a candidate requests evaluator, policy, hidden-test, or promotion writes;
- remote GPU capability is import-only and lacks an active kernel smoke;
- a “latent” feature has no named representation, adapter, baseline, and
  fallback.

---

# Historical handoff (2026-07-20 onward; retained for provenance)

# Daedalus — Session Handoff (2026-07-20, session 2)

> Provenance tags: **[M]** measured this session, uncontended · **[I]** inherited from a
> prior doc, not re-verified · **[A]** assumed/projected, no run behind it. The whole reason
> this section exists is that last session cited its own earlier numbers as fact — so every
> number below says where it came from.

## 0. Session 4 addendum (2026-07-26) — slice→offload WIRED (dark) + the context-window repair — READ FIRST

**STATE: ALL OF THIS IS UNCOMMITTED.** Working tree on `checkpoint/2026-07-20-session`
(tip still `f40529c`): modified `daedalus/offload.py`, `daedalus/providers/ollama.py`,
`daedalus/structcore/slice.py`, `tests/test_rewrite.py`, `tests/test_era1_robustness.py`;
new `daedalus/providers/_ollama_native.py`, `tests/test_ollama_native.py`,
`tests/test_offload_slice_context.py`, `tests/test_slice_include_focus.py`. The session was
STOPPED BY KAYA mid-verification — see "gate status" below before touching anything.

**The lever executed:** handoff item "(3) wire slice→offload (static-only)". It shipped —
but the scoping measurement found something bigger first:

**THE DISCOVERY THAT RESHAPED THE TASK [M, probe-verified twice with fresh unique
prompts]: the local bench head-truncated an over-budget prompt at ~2050 tokens.** Ollama
0.32.1's `/v1` OpenAI-compat shim ignores an `options` block entirely (measured:
`usage.prompt_tokens` stays 2050 with its 4096 default ctx); truncation eats the HEAD, i.e.
the system prompt with the report format and write rules dies first (proven by failed
first-word recall). Every rewrite or fat agentic tool-read that overflowed that default has
therefore been silently degraded since the bench was built — it plausibly explains part of
the historic rewrite-truncation/elision skips. Momus forced the probe matrix BEFORE build
(the A2 lesson, correctly applied): native `/api/chat` honors `options.num_ctx`, so the
native switch was REQUIRED, not gold-plating.

**CORRECTION [M, 2026-07-28]: the old “HALVING LAW” is refuted by measurement.** On the RTX
bench at `num_ctx=16384`, fresh unique ~4k- and ~14k-token prompts produced
`prompt_eval_count=3971` and `14375`, respectively, with first-word recall in both cases.
Only an over-budget prompt fell to `8194` (`num_ctx/2`) and lost first-word recall; an
over-budget prompt at `num_ctx=8192` likewise fell to `4098` and lost recall. The halving
persisted after a fresh server with machine-wide `OLLAMA_NUM_PARALLEL=1`, so parallelism is
not the cause. The usable input budget is the FULL `num_ctx` minus an explicit generation
reserve. The ~`num_ctx/2` result is an over-budget truncation penalty that eats the head, not
the normal request window. **Memory sizing remains measured and unchanged: num_ctx=16384
needs a ~3.9GB runner buffer → loads on an idle box, OOMs mid-session; 8192 OOMs at 4.3GB
free; 6144 loads under the same pressure (~20s cold). `DEFAULT_NUM_CTX=6144`**, with
`OLLAMA_NUM_CTX` available to opt up on an idle box.

**What shipped (Part A — context-window honesty, ollama lane only):**
`providers/_ollama_native.py` (stdlib native `/api/chat` client; OpenAI-shaped message
adapter — tool-call `arguments` re-serialized to JSON string, ids synthesized; a
`_native_messages` normalizer converts our adapted history BACK to native shape for
multi-round loops, or round 2 would 400). All FOUR ollama call sites switched (agentic loop
+ forced-final, rewrite, and the fallback-advisory 4th site Momus caught). Fail-loud window
rules: agentic pre-flight refusal; mid-loop EVICTION to [system, first user, last tool
result, report-now] before the forced final; rewrite reserves OUTPUT tokens
(est(original)+margin) so generation can't overflow either. `warm_model` pins with the same
num_ctx (one stable value — changing num_ctx reloads the model, ~15-45s).

**What shipped (Part B — the wire, trusted lane only, DARK by default):**
`offload._slice_context` builds gated `semantic_slice`s of the declared paths (≤3) ONLY
inside the `decision.provider == "ollama"` branch — codex/deepseek can never receive slice
text (the bootstrap's Cerberus invariant, kept). `lane="trusted"` (floor ON, default-deny
OFF). `semantic_slice` gained additive `include_focus: bool = True`; rewrite-bound tasks get
NEIGHBORHOOD-ONLY context (the prompt already carries the file body; the focus gate still
runs FIRST on the full text and fail-closes identically — invariant proven by test #3 of
`test_slice_include_focus.py`). Provenance never silent: every ollama live result carries
`result["slice_context"]` (injected/reason/per-target status/withheld/trimmed/dropped).
Fail-OPEN on build, fail-CLOSED on content. **Default `OFFLOAD_SLICE_TOKENS=0` = the wire
ships dark** — the Momus landing-gate rule.

**Live verification [M, this box, session lead ran these]:**
- WINDOW: 2.6k-token prompt (above the old 2050 cap) through the new path → full recall of
  the first word. The truncation regime is gone at the default window.
- A/B (n=1, trivial task — directional only): both arms produced the correct
  caller-compatible edit (`step=None` appended); arm B injected a 64-token neighborhood at
  zero time cost. **No lift measurable → default stays OFF.** Flip condition: an op-test A/B
  on tasks hard enough to differentiate (where neighborhood knowledge changes the edit).
- BIG-FILE HONESTY [M at the time; threshold superseded 2026-07-28]: 12k-char rewrite
  target → **0.4s loud skip** "file needs ~6426 tok but the local context window is ~3072
  tok", escalated with reason, file untouched. The fail-loud behavior was correct, but the
  ~3072 threshold came from the now-refuted halving diagnosis; current arithmetic uses the
  full `num_ctx` minus a named generation reserve.

**Gate status — READ BEFORE COMMITTING:** Momus design gate PASSED (GO-WITH-CHANGES, all
adopted). Focused suites green [M]: 21 (`test_ollama_native`) + 8 (`test_offload_slice_context`)
+ 6 (`test_slice_include_focus`) + the 389-test ollama-touching set + the 80-test slice/eval
set (incl. `test_eval`/`test_dctx` byte-identity through the default path). Two legacy test
files were retargeted to the new seam (`test_rewrite.py`, `test_era1_robustness.py` — diffs
reviewed by the session lead, intent preserved, the routing distinction now asserted from the
request shape). **BUT the session was stopped mid-verification: the post-change FULL suite
(Metron), the Nemesis live attack (esp. the native multi-round tool loop — the one thing the
fake-server tests cannot prove, flagged by the build lane itself), and the Cerberus egress
review were all KILLED before returning verdicts. This change is NOT gate-cleared. Do not
commit until all three have run clean.** Also pending: the 2 `test_churn.py` fails from the
baseline (git "not enough memory" while the 5GB model was RAM-resident — re-run with the
model unloaded: `ollama stop qwen2.5-coder:7b` first), and the post-change eval numbers
(pre-change baseline was byte-identical to session 3: 100%/79.3% primary, 86.2%/98.5%
quarantine, gate PASS, ceiling 2.3%/14.0% no reopen).

**Next steps, in order:** (1) rerun the three interrupted verdicts (Metron full gates with
model unloaded; Nemesis per its brief — multi-round native tool loop live, warm/pin
consistency, OOM honesty under env-16384, eviction live, `_slice_context` edge inputs;
Cerberus per its brief), repair findings, THEN commit with provenance-tagged message.
(2) Op-test A/B on a harder corpus → flip `OFFLOAD_SLICE_TOKENS` default only on measured
lift. (3) Chat lane: `ikarus_os`'s ollama branch still rides `/v1` → still truncation-exposed
AND causes reload thrash against the offload lane's 6144 runner (two window sizes, one
server) — switch it to the native client (needs an NDJSON streaming variant for
`chat_stream`). (4) The auto-mint seam (offload → `mint_task_from_landed_edit`) stays the
next flywheel item, unchanged.

**New gotchas (corrected [M] 2026-07-28):** `ollama ps` CONTEXT is the full request budget
for an under-budget prompt; ~`num_ctx/2` is the head-eating penalty only after the prompt
exceeds `num_ctx`, and `OLLAMA_NUM_PARALLEL` is not its cause. `prompt_eval_count` is
polluted by KV-prefix caching — probe with fresh unique content or you measure the cache,
not the window. Changing num_ctx reloads the model — pick ONE value per server. A
RAM-resident 5GB model makes UNRELATED `git init` subprocesses fail
("not enough memory") — unload before memory-sensitive test runs. cl100k over-counts qwen
tokens (~4x on gibberish, direction safe for over-escalation); the code treats estimates as
qwen-tokens with margin and documents the direction.

## 0b. Session 3 addendum (2026-07-21) — the Code Evolution foundation sprint

Phase 0/1 of the code-evolution thesis landed as ONE sprint, currently **uncommitted** on
`checkpoint/2026-07-20-session`. Six workstreams: honest token denominator (tokenizer-exact,
cache-keyed by tokenizer identity), Safety-Class Reachability Router (the fence now asks the
import graph; three fail-open holes closed during build), UI/chat wires (BYOK badge, gated
picker, codex/deepseek brains on the untrusted lane, review-before-apply), `.dctx` certified
context receipts (deterministic SHA, offline verify, anti-tautology `label_provenance`),
the decontaminated eval oracle (per-provenance recall, A/B/C arms incl. BM25, per-task
ratchet `--gate`), and independent label minting + git temporal coupling.

Adversarial pass over the sprint: 18 raw findings → **14 confirmed** by 3-skeptic panels
(3 CRITICAL, 5 HIGH) → **all repaired and regression-tested same-sprint**; 4 refuted.
Cerberus egress review: **zero CRITICALs**. Fence-defect detail + the one known residual
(empty-paths codex sandbox) in §4c.

**Verified by the session author, not inherited from agents [M]:** pytest **700 passed / 0
failed**; `python -m daedalus.eval` prints the per-provenance breakdown and reports
**100% recall / 79.2% compression on the `hand_reachable` primary tier, explicitly labelled
PARTIALLY SELF-GRADED** (that labelling is the sprint's real deliverable — the old headline
quoted the same 100% as if independent); `--gate` ratchet **PASS** (exit 0);
`whole_repo_tokens` for agent_env is now a measured **381,265** (tiktoken/cl100k_base, tree
grown by the sprint's own ~2.5k new lines), no longer `total_chars//4`. The standing rule in
§4d (eval gate stays ADVISORY) is unchanged and load-bearing.

**THE FIRST INDEPENDENT NUMBER (same day, after the flywheel hardening below): quarantine
tier recall = 61.7% [M]** over 18 tasks minted from 20 real commits (2 skipped, reasons
stated). Suite **718/0 [M]**, primary tier unchanged, gate PASS. The first seeding also
CAUGHT ITS OWN POISONING — out-of-scope dist targets, same-file-label tautology, and one
unindexable task that crashed the whole oracle — all fixed same-day (`df0daee`): labels are
now scope-gated + cross-file-only, and a bad task becomes an ERRORED row (errored primary
fails the gate; errored quarantine is reported-only). **Miss triage [M, author-scripted
against import_edges]: of 129 missed labels — 57% = secret-floor fail-closed focus files
(four security-test files whose planted credential fixtures trip the unconditional floor;
the fence working as designed, colliding with the eval), 19% = genuine co-change coupling
with NO static import edge (the temporal class), 25% = cross-language labels (TS symbols
co-committed with .py targets) + parser junk (`if`, `<anonymous>`), and 0% =
edge-but-dropped.** Read that last one again: **the slicer dropped NOTHING it could
structurally see.** Excluding the fence-artifact tasks, structural recall ≈ 79% [M-derived],
and the entire remaining gap is coupling the import graph cannot express. Follow-ups this
implies, in order: (1) minter filters junk/cross-language label names and classifies
floor-tripping targets as `focus_withheld` instead of scoring them as misses; (2) the
temporal co-change tier becomes a slice ENRICHMENT experiment (add co-change neighbours,
measure recall gain vs compression cost on both axes); (3) only then wire slice→offload.

### Campaign Build Day 1 (2026-07-21) — Lane A1 label hygiene + Lane B1 memory ledger

**Item (1) is now shipped.** The first follow-up action landed with two parallel workstreams: minter label filters (Lane A1) that implement the planned junk/cross-language exclusion + floor-withheld classification, and an append-only memory ledger (Lane B1) for task persistence.

**Lane A1: Label hygiene in `_mint_from_diffs` [M].** Three filters now live in `daedalus/eval/mint.py` (~93–121, `_is_junk_label` new):

- **Junk filter:** non-identifier or keyword-shaped names (`if`, `<anonymous>`) never become `must_include`; excluded into `labels_filtered_junk` (sorted, counted).
- **Cross-language filter:** label's source file language must match anchor/target language; mismatches land in `labels_filtered_cross_language` (sorted, counted).
- **Secret floor anchor exclusion:** `secret_floor_rule` applied per-anchor; floor-tripping files drop from anchor pool (stay eligible as sources); if all candidates trip, honest `reason` in `skipped_secret_floor` (sorted, counted).

Wired into `daedalus/eval/harness.py` via `_is_focus_withheld()` / `_focus_withheld_row()`: these rows split from `by_provenance`/means, never fail the gate, never snapshot recall. `daedalus/eval/report.py` renders them one honest sentence: "the secret floor fail-closed on the focus file itself — not a recall miss, not a pass". **Tests: 14 new [M]** in `tests/test_mint_label_hygiene.py`.

**Lane B1: Append-only memory ledger (dmem/1) [M].** `daedalus/memstore.py (removed 2026-08-22)` (390 lines) + `tests/test_memstore.py` (15 tests). Hash-chained ledger at `memory/ledger.local.jsonl`:

- `append_entry`: forces `trust.minted_tier="quarantine"` at write (earned via fold, never asserted), runs secret floor BEFORE writing over text/detail/paths; refused entries store redacted `gate_outcome` only. Dedupe by `body_sha` returns existing id. Hash boundary: `body_sha` = SHA256(canonical_body, sort_keys, separators, ensure_ascii, excluding ts/prev/entry_sha/id/body_sha); `entry_sha` = SHA256(prev+"\0"+body_sha+"\0"+ts); genesis prev→"".
- `append_confirm`/`append_flag`: control records on chain; `MEM_CONFIRM_THRESHOLD = 3` (cited to `MINT_CONFIRM_THRESHOLD`, not import-coupled).
- `load_ledger` (skip-corrupt), `verify_ledger` (chain walk, three per-line checks naming exact 1-indexed line on failure), `fold_state` (quarantine→primary at 3 confirms; flag→terminal; deterministic `state.local.json`).

**Verification [M]:** `pytest tests/test_memstore.py -q` → **15 passed in 24.35s** (roundtrip/dedupe/trust-forced, determinism byte-identical, tamper tests: flipped-byte and deleted-line break chain, planted AKIA/PEM/`.env` paths all refused with secret absent from raw bytes, 3-confirm-promote / 2-stay / flag-terminal, 1000-entry scale verifies <1s + catches flip at line 501). Adjacent suites: `pytest tests/test_dctx.py tests/test_eval.py -q` → **20 passed in 5.46s** [M]; no breakage.

**Measured result [M, re-verified by the session author against the raw eval printout — an
agent-reported "16 minted / 17 focus_withheld" did NOT survive that check and is corrected
here]:** pytest **779 passed / 0 failed**; independent_diff quarantine tier recall **86.2%
over 17 minted tasks** (up from 61.7% at the foundation-sprint seeding), compression 98.4%;
**17 tasks minted from 20 real commits** (3 skipped with reasons: 0360964, d714128, e2c77ad —
no unit-level change or filters drained all cross-file labels); **zero focus_withheld rows in
the final eval** — the hygienic minter excludes floor-tripping anchors at mint time, so none
reach scoring (the focus_withheld classification remains live for any future store); primary
tier unchanged **100% / 79.3%**; gate **PASS**. The lift 61.7%→86.2% is HONEST ACCOUNTING,
not a slicer improvement: junk + cross-language labels no longer count as misses and
fence-artifact targets are no longer minted. The 7 remaining miss tasks are almost entirely
the temporal class (co-committed symbols with no static import edge) — Lane A2's target.
**Adversarial review: 13 confirmed findings repaired (incl. 2 CRITICALs in the new ledger:
secret floor skipped provenance/refs fields; the refusal receipt re-embedded unscanned
provenance), 1 refuted [M].** Tail-truncation of the ledger is now detectable via a
head/count anchor persisted in state.local.json. `.gitignore` gained `memory/*.local.json`
+ `memory/receipts/`.

### Campaign Build Day 2 (2026-07-21 pm) — Lane A2 CLOSED ON MEASUREMENT, nothing built

**Follow-up (2) is resolved — by refutation, not by construction.** The planned "temporal
co-change slice enrichment" experiment was designed in full (opt-in `temporal_pairs` on
`semantic_slice`, backtest-clean per-task pairs, k-grid both-axes measurement), then
NO-GO'd by Momus at the design gate, which ran the cheap measurement the design had
deferred to its own risk list: a pairs-only reachability CEILING over the 7 miss tasks /
43 missed labels. **Backtest-clean (pairs from `git log <minted_at_sha>^`, min_count=2),
zero missed labels were reachable — 0/43.** I reproduced that independently in a fresh
process before accepting it, then extended it [M]: min_count=1 (any single prior
co-commit) = 1/43; full-history (leaky) = 6/43 at min_count=2 and **42/43 at min_count=1**
— i.e. the handoff's own "19% temporal class" triage number was predominantly **the minted
commit predicting itself** (the mint commit IS a co-change event; count it and almost
every miss looks temporally reachable).

**Nemesis then refuted one sub-claim of MY close, and the instrument was corrected:** my
"rename-aware matching does not change it" had only been measured at min_count=1. The true
rename-aware clean ceiling at min_count=2 is **1/43 = 2.3%** — one genuine
`verifier.py<->providers/ollama.py` coupling crossing the agent_env→daedalus rebrand
boundary (93-file rename; numstat spellings differ per commit, so exact-rel matching
starves real pairs below min_count). Verdict CLOSE-STANDS on materiality: **41/43 missed
labels sit on focus files BORN at their mint commit** (zero pre-mint history — structural
temporal immunity under ANY enrichment), 1/43 is a stale label (`_py_maps`, deleted by the
mint commit itself → NO_INSCOPE_DEF).

**What shipped instead of the tier (small, read-only, the reopen gate):**
`daedalus/eval/ceiling.py` — rename-aware (alias-unified counts via `git log --follow`,
summed across spellings BEFORE min_count), clean + leaky arms, per-label classification
(REACHABLE / UNREACHABLE / STATIC_EDGE / NO_INSCOPE_DEF), machine-printed reopen signal
with a **materiality floor** (>=10% of scored labels or >=3 tasks — a lone label must
read "stay closed"), audit list naming every clean-REACHABLE label, alias-probe failures
surfaced. Run: `python -m daedalus.eval.ceiling`. Plus an additive `rev` param on
`churn.co_change_pairs` (the backtest cut). `semantic_slice` was NOT touched — zero new
core-API surface. **Tests: 16 new** (`tests/test_temporal_ceiling.py`) incl. a positive
control (an always-zero checker fails), the leak-artifact control (clean UNREACHABLE /
leaky REACHABLE on the same fixture), the Nemesis rename-boundary case, and the
materiality-floor case. **[M, current corpus]: clean 2.3% / leaky 14.0%, reopen: none.**

**Standing decision this encodes:** slice-side temporal enrichment is CLOSED unless a
grown corpus trips the rename-aware materiality floor (`ceiling.py` docstring is the
canonical statement). Re-run the ceiling when the corpus grows — today's zero generalizes
weakly (born-at-mint focus files can never show pre-mint coupling). The 7 miss tasks stay
open as honest misses; the next lever on the list is **(3) wire slice→offload
(static-only)** — Horizon Phase 2, unchanged.

## TL;DR

A correctness + product-scope session. **14 commits on `checkpoint/2026-07-20-session`**
(`ff59963`..`95f00d2`; including the secret-floor CRITICAL fix, this doc update, and the
completed bootstrap), `main` untouched. Suite **549 passing [M, session 2]**, eval **100% recall /
78.7% compression [M, session 2 — under the chars/4 denominator then in use; re-measured 79.2% in
session 3 under the tokenizer-exact denominator, see §0]**.
The through-line: the structural engine was shipping *confidently wrong* answers on a real
repo, and most of this session was making it honest. The **bootstrap is now SHIPPED and
Cerberus-CLEARED** (egress review complete on the slice gate after six bypass classes were
closed; Ikarus chat brains now answer with gated project knowledge).

The single most important thing to understand before continuing: **the crew is now
gate-structured** (`.claude/AGENT_PROTOCOL.md`), and the gates repeatedly caught defects the
happy path missed — including two of *my own* introductions. Trust the gates; when you skip
one, say so in the commit.

---

## 1. Git state (READ FIRST)

- Branch `checkpoint/2026-07-20-session`, tip **`95f00d2`** (bootstrap: project-aware chat brains via gated slice). `main` untouched.
- Working tree is clean except regenerated `apps/web/dist/assets/*` (build output; harmless).
- Nothing stashed. Scratch worktrees removed. **Do not `git stash` a shared checkout while
  any agent runs** — it left the tree un-importable earlier this session. Use `git worktree`.

## 2. What shipped this session (11 commits, each verified by me not the agents)

**Project scope — the biggest single win.** `center` + `.daedalusignore` + `@tests` preset
(`daedalus/structcore/ignore.py`, `projects/*.json`, docs/PROJECT_SCOPE.md). A project
declares which subtree IS the code; the rest is *shell* — still parsed and resolvable as an
import target, but withheld from metrics and not expanded through by the slicer.

- project_tct `center=["TCT_app"]`, `ignore=["@tests"]`: **6,798 → 187 core files [M]**,
  wall **171s → ~22s [M]**, and hotspots stopped ranking vendored Printrun/Cython/wxPython
  and started ranking the actual app. **93% of the old duplication report was noise. [M]**
- Surfaced in the Structure panel (banner) so the shrink is never silent.

**Code map was 87% disconnected — fixed.** `_py_dotted` named Python modules from the repo
root, but a center IS the package root, so `from controller.x import ...` never matched and
nearly every internal edge was dropped. Now per-importer naming views (`index.py`).

- **42 → 478 edges, 162 → 50 isolated nodes (of 187) [M]**, `truncated` now honest.
- Momus (design gate) blocked the naive "just strip the prefix" fix — it would have widened
  a global table and *manufactured false edges*. The views approach avoids that.

**C/C++ + slice coverage (the "Odin/Adam" round).** S1: `_ts_name` now names C/C++ functions
(1/21 → 21/21 shapes [M]); Type-3 deliberately **held off for C/C++** because the generic
abstraction collapses their types to `ID` and *fabricates* clusters (Momus caught this on
paper; measured 5 unrelated C fns chaining at sim 0.853). S2: the distilled slice now expands
for non-Python targets via `import_edges` (0 → 28/32 files get a neighborhood [M]).

**Fabricated-clone fix.** `_strip_comments_generic` was string-literal-blind: `send("V //
500")` and `send("V // 50")` hashed identically, and `/*` in a string deleted whole function
bodies. Now a per-language string-aware scanner. Exposure was **66 of 6,798 files [M]** (not
the 499 a first bad measurement claimed, nor Fenrir's 889).

**Clone-pass memo.** Shared exact/abstract fingerprints across the three passes. **1.08× on
the full repo [M]** — NOT the ~2.4× projected [A]. Kept because it's free and removes a real
double-normalize, but "Python was never optimized" does not carry the weight it was given.

**Chat: streaming + persistence.** Wired `/api/ikarus/stream` (was dead) with a live bubble;
`es.close()` on final is load-bearing (EventSource reconnect re-spends). Transcript now
survives tab switches via sessionStorage. Chat cwd fix: `_claude()`/`_claude_stream()` run
from a neutral dir so they don't reload the repo's CLAUDE.md every message (~30% latency [M],
big token saving [I]).

**Slice egress gate — the bootstrap blocker, now CLEARED.** Commit `d714128` was NOT gate-cleared
in round 1 (Cerberus re-review found plaintext-secret CRITICAL still leaking: value-shape rule
used `\b...\b` + bare quotes, missing underscore-glued names like `DB_PASSWORD`, string prefixes,
triple quotes, short values, annotated assignment, quoted-key dict forms). Minos rewrote the
rule closing six bypass classes; Cerberus cleared it round 2 (`0360964`). See §4 for residual
limits + product backlog item.

**Crew redesign.** See §3.

## 3. The crew (`.claude/AGENT_PROTOCOL.md`, `.claude/agents/`)

Redesigned on Odin (NorthStar) + Adam (project_tct). Three tiers; **four adversarial gates**:
**Momus** (design critique on paper, pre-code) → **Týr**/`test-dev` (testability) →
**Nemesis**/`qa-critic` (attacks the RUNNING result; a break you didn't run doesn't count) →
**Cerberus** (security/egress; **CRITICAL blocks, no override**) → **Metron**/`vigil` (gate
suite). Minos owns the fence, Cerberus reviews it. Always-on haiku: **argus, hermes,
mnemosyne** (chronicler + provenance), **metron**.

Names are one coherent Cretan/Greek cycle now. `qa-critic` moved **fable → opus** because all
three Nemesis agents in one round died on a Fable quota limit — a gate that can't run is
worse than none.

**Two things the gates caught that I'd otherwise have shipped:** the code-map false-edge risk
(Momus), and the plaintext-secret leak in my own gate (Cerberus). **Two things a gate agent
got WRONG:** Metron reported "fix not applied" by querying the cached server instead of a
fresh process; and Metron called the leaky gate "tight and correct". **Always re-verify a
gate agent's measurement yourself, in a fresh process.**

## 4. COMPLETED: Ikarus bootstrap (wire slice → context)

**The bootstrap is SHIPPED and Cerberus-CLEARED** (commit `95f00d2`). Ikarus's chat brains
now answer with gated project knowledge.

**What it does:** `_claude()` now runs from a neutral cwd AND receives an on-demand distilled
slice of files the user names (via the freshly-gated slice layer). Both Claude (egress to
BYOK provider, gated) and local Ollama (no network egress, floor-gated) run with
`lane="trusted"` (secret floor ON, default-deny OFF → recall preserved). The slice REPLACES
the old 25,666-tok in-repo context baseline, never re-pays that cost. The bootstrap blocked
on two things: (1) the slice egress gate had to PASS Cerberus (done via commit `0360964`,
six plaintext-secret bypass classes closed), and (2) `_project_context` had to be wired
safely into `ikarus_os.py`.

**Verification [M]:** pytest **549 passed** (+23 new: `test_ikarus_context.py`, slice degrade
tests); eval **100% recall / 78.7% compression [M, session 2 — chars/4 denominator; the session-3
sprint replaced that denominator with a tokenizer-exact one, under which the same corpus measures
79.2%]** (slice refactor byte-identical, no symbol lost); no-file chat and deterministic intents
(status/distill/design/enqueue) are behaviorally identical; planted secrets
(glued/annotated/dict-key) never in the assembled prompt across module/focus/symbol paths.
Cerberus CLEARED the egress path.

**Residual limits, non-blocking (Cerberus ledger, for general-product hardening):**
- Keep `_project_context` OFF any untrusted lane. Metadata-disclosure safety (withheld
  breadcrumb tells the model "secret of kind X at path Y", path + rule-kind only, never
  value) rests on hardcoded `lane="trusted"`. Invariant to guard.
- R2-residual floor gaps are now a LIVE wire-reachable path: a focus `.py` file whose only
  secret is in an R2-residual shape (subscript `cfg["k"]="..."`, split-across-lines,
  >60-char-annotation) egresses its body when the user names it. Narrow (code `.py` only;
  config `.yaml`/`.env` not indexed), value-shape classes still caught; adjudicated
  ACCEPTABLE for the Daedalus-on-Daedalus case, but keep on the ledger for third-party
  distillation hardening.

---

## 4b. NEXT TASK: the "Code Evolution" foundation sprint

**Full plan (written, approved direction):**
`C:\Users\nukei\.claude\plans\remember-what-we-want-humble-lightning.md`.

**Direction (agreed with Kaya 2026-07-20):** Daedalus becomes an **evolutionary engine for
code** — a *genome* (certified context artifact), a *trustworthy fitness function*
(decontaminated eval), and *safe selection* (a graph-gated edit loop). Two READ-ONLY audits
this session — a 22-agent subsystem map + an 18-agent novelty tournament — independently
converged on the same reframe, each finding cross-checked against the code by me:

**Three verified findings that set the priority:**

1. **The moat is unwired from the mutate path [M].** `daedalus/offload.py` imports *zero*
   `structcore`; `semantic_slice` feeds chat (the bootstrap) but never the edit loop.
2. **The eval headline is partly self-graded [M].** `daedalus/eval/tasks.py` docstring: labels
   were "verified reachable by running `semantic_slice`" — so "100% recall" is partly a
   tautology. Fix = independent-oracle labels (git co-change + gate-verified diff-touched symbols).
3. **VERIFIED LIVE SAFETY GAP [M].** `sensitivity.change_risk()` (sensitivity.py:350) and
   `path_write_blocked()` (:366) substring-match only the LITERAL edited path against the fence —
   neither asks the import graph. A leaf `utils/clamp.py` transitively imported by
   `controller/hv_interlock.py` gets risk=`low` → the free Ollama lane may write it. *The graph
   knows; the fence doesn't ask.*

**The sprint = Phase 0/1 of the plan — prove + connect the foundation BEFORE building the loop on it:**

1. **`.dctx` certified context artifact** (new `daedalus/dctx.py`): content-addressed receipt
   `{commit, manifest, per-symbol hashes, egress verdict, recall, label_provenance}`, deterministic
   SHA, offline verify predicate. Additive/fail-closed. **NON-NEGOTIABLE:** `label_provenance` must
   distinguish independent-oracle labels from the assembly walk, else recall is tautological.
2. **Honest decontaminated eval oracle + flywheel:** `eval/harness.py` A/B/C (distilled vs concat
   with a *real* tokenizer vs BM25/embedding-RAG) on a held-out set; new `eval/mint.py` minting
   labels from landed diffs (`offload.py:196` disk_changed seam) + git co-change into a QUARANTINE
   tier; a counterfactual-regression ratchet. Start the decontaminated-label long pole day one.
   **GUARDRAIL:** an unvalidated metric NEVER gates autonomy — advisory first.
3. **Safety-Class Reachability Router (~1 day):** BFS `import_edges_reverse` ∩
   `high_risk_path_substrings` in `structcore/graph.py`; pre-check in
   `provider_router.select_provider` BEFORE `change_risk`; graded, over-escalate-never-under,
   dominance fallback. Closes finding #3.
4. **Cheap footgun wires:** BYOK badge (`getEnvStatus`), provider-status picker gating +
   `codex_cli`/`deepseek` branches in `ikarus_os._llm` (:360) (kill the silent brain degrade),
   `getDraft(id)` review-before-apply panel.

**Horizon (Phase 2–4, only after the foundation holds):** wire `semantic_slice → offload`
(Movement III MVP, now correctly sequenced AFTER the oracle proves the slice); **Panel of Rivals**
(cross-vendor candidates, the *gate* judges not a model); **Repo Physician** (hotspot → gated draft);
**Clone-Propagated-Fix**; **Context-as-a-Service MCP** (Cursor/Claude-Code/Copilot become *consumers*
of verifiable context); **Cockpit-as-Proof-Surface** (distillation x-ray + collapse + health morph).

*The old "two paths" are absorbed: the js-tokens over-block + a distillation consent surface stay in
the backlog (§5); Movement III becomes Phase 2, resequenced after the eval oracle.*

## 4c. What this sprint did NOT do (Horizon, still pending)

The foundation sprint completed Phase 0/1 as designed. These remain open:

- **Wire `semantic_slice` into `offload.py`** — the distilled slice now feeds chat (Ikarus) but
  not yet the edit loop. The loop remains routed on raw change-risk path-matching.
- **The closed edit loop** (Movement III MVP) — minting, persistence, and reload all exist
  (`eval/mint.py` store + `--mint-commit`/`--confirm-mint` CLI + `harness.all_tasks()`), but the
  flywheel's live seam is still open: `offload.py` never calls `mint_task_from_landed_edit` after
  a landed write, so minted tasks only enter the corpus by hand today.
- **Panel of Rivals** — cross-vendor candidate selection where the gate (not a model) judges which
  provider answered best, remains phase 2.
- **Repo Physician** — hotspot-to-draft automation remains phase 2.
- **Context-as-a-Service MCP** — third-party tools (Cursor, Claude-Code, Copilot) becoming
  consumers of verifiable distilled context remains phase 3.

Fence-defect status, stated precisely: the adversarial review panel (not Cerberus — Cerberus's
egress review returned **zero CRITICALs**) confirmed three CRITICALs against the new reachability
fence, and **all three were fixed and regression-tested in the same sprint**: (1) the dominance
stand-down could hand an itself-fenced top-level file to the local write lane — closed at the
source by root-anchoring the path-fence match (`sensitivity._fence_norm`; `tests/test_fence_anchoring.py`);
(2) the agentic ollama write tool could write outside the declared paths with no fence consult —
closed by a post-write blast-radius fence over the verified `disk_changed` diff in `offload.py`
(`tests/test_repair_blast_radius_write.py`); (3) the forced codex bridge lane granted writable
without ever calling the fence — closed in `core.py` by consulting the reachability pre-check
before granting write. One residual is genuinely open and known: an **empty-paths codex task**
runs in a repo-wide `workspace-write` sandbox whose individual writes cannot be intercepted
per-file; keep codex off empty-paths write work until that lane gets its own post-write gate.

## 4d. Advisory guardrail on the eval gate

The new `run_gate` (eval/harness.py:635) and any health-delta metric MUST remain **ADVISORY only**
and NEVER gate autonomous action until independently validated to predict task success on real work.
The underlying data (hand_reachable labels) is partly self-graded; the machinery is honest but the
labels themselves are not independent. Do not upgrade the gate to a blocking gate without:
1. An independent label source (minted diffs, temporal churn, or a human-reviewed held-out set)
2. A live validation round showing gate decisions correlate with task success/rollback rates
3. Explicit sign-off from the risk/security review that the policy applies to your actual deployment

## 5. Backlog (recommended order)

1. ✅ **Bootstrap: wire slice → Ikarus context.** SHIPPED + Cerberus-CLEARED (commit
   `95f00d2`). Chat brains now project-aware via gated slice, both lanes trusted, 549 pass /
   eval 100%·78.7% [M, session 2]. See §4 for residual ledger and hardening priorities.

2. **Scan out of the server process.** STILL OPEN. The scan is CPU-bound in a
   `ThreadingHTTPServer` thread and freezes the cockpit; measured 97% of one core, 20s
   request latency during the clone passes [M, session 1]. The per-file phase is already in a
   process pool; it's the *clone passes* that block. Honest budget ~1 week [A], not the ~1 day
   first claimed — the naive version silently loses Move-4 resolution (no exception, no failing
   test).

3. **`file_key` cache staleness (Fenrir, confirmed).** The disk-cache key hashes only
   `parse.py`; edits to `metrics.py`/`imports.py`/`clones.py` serve stale analysis. Fold a
   digest of all analysis modules into the key.

4. **General-product egress-consent surface + hardening** (Path A from §4b). Three items:
   - Value-entropy or whole-keyword anchoring to fix `js-tokens`/`jsonwebtoken` over-block
   - Disclosure wording for R2-residual limits when distilling third-party source
   - One-time "Claude will see your distilled project source" consent surface before Ikarus
     first file-named turn. Keep the Cerberus invariants (§4) visible to future gate rounds.
   Honest budget ~3–5 days [A].

5. **Movement III (orchestration loop, Path B from §4b).** Newly unblocked (import graph
   honest, gate cleared). Wire the loop that reads import-dependency frontier and suggests
   next steps. NOT before #4 — the plan's own rule. Honest budget ~1 week [A].

6. QML `qmldir` implicit imports (map still sparser than it could be); `resolve_internal`
   prefers lexicographically-first candidate (often wrong); Rust parity (see §7).

## 6. Gotchas (hard-won, do not relearn)

- **Measure uncontended, or the number is wrong not slow.** This session: 1.47× was really
  0.99× (23 agent procs running); 171s was really 86.5s; 499 files was really 66. Check the
  python process count before any timing.
- **Any script calling `build_index` needs `if __name__ == "__main__":` AND must be a real
  file, not `python - <<`.** Windows spawns pool workers that re-import `__main__`; via stdin
  that path is `<stdin>` → `OSError 22`. Hit this three ways in one session.
- **A gate/measurement against the running server reads a CACHED index.** Measure in a fresh
  process. Bump `ignore.SCOPE_ALGO_SALT` when the index *contents* change under an unchanged
  center, or warm caches serve the old graph.
- **PowerShell 5.1: no `2>&1` on a native exe** (wraps stderr as a terminating error);
  workflow script files must have **no `\r`** (permission dialog rejects them as control chars).
- **`sensitivity._compile` silently drops any regex >200 chars.** A safety pattern that's too
  long vanishes with no error. `_compile_labeled` now asserts against it for the floor; other
  callers are still exposed.
- BYOK, additive endpoints, `/api/dashboard` frozen by `test_ui_contract` — all still hold.
  `test_ui_contract` is load-flaky (starts its own server); re-run quiet before believing a fail.

## 7. Rust engine — the claim that needs correcting in memory

`memory/daedalus-agentos-moonshot.md` records the pivot rationale as "10–100× faster [I]".
**Measured this session: Rust ~2.1× [I, handoff] / ~1.3× like-for-like [M] / SLOWER on the
full repo (216s vs 171s) [M]** doing less work. The **Tauri/bundling** rationale stands and
is the honest reason to finish it; the speed claim does not. Also: `structcore-rs` has no
safety gate, no scope awareness, is 13 languages behind, has its own copy of the S1 naming bug
(`parse.rs`), and is invoked by zero Python code paths. **This memory should be corrected** —
it's still steering decisions on a false number. (User asked twice about "backend in Rust";
the audit's answer was "right destination, wrong next step — the measured defect is a
concurrency failure the GIL causes, which is a process boundary, language-neutral").

## 8. Pointers

- Plan: `C:\Users\nukei\.claude\plans\ast-driven-distillation-harness-modular-sprout.md`
- Memory: `daedalus-agentos-moonshot.md`, `crew-delegates-protocol.md` (updated),
  `daedalus-validation-status.md`
- Scope: docs/PROJECT_SCOPE.md · Engine parity gap: docs/ENGINE_PARITY.md
