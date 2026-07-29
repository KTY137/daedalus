# Handoff to Antigravity — Daedalus, 2026-07-29

You are picking up a system you have not seen. This file is written to be
sufficient on its own. Read §0–§3 before touching anything; §4 is the work.

Written by the Claude session that produced commits `4e74358..8e48783`. Every
number here is labelled **MEASURED** (a command was run on this box today and
its output is quoted), **INHERITED** (another agent measured it and I did not
re-derive it) or **ASSUMED**. Do not promote an INHERITED number to MEASURED by
repeating it.

---

## 0. What Daedalus is, in five sentences

It is a local-first harness that routes coding work to the cheapest lane that
can safely do it: a free local model (Ollama), a paid CLI vendor, or a human.
It has a self-improvement loop — pick a task from its own defect inventory,
attempt it in a disposable git worktree, gate the result, record it — and the
loop is deliberately unable to apply anything: **promotion is a human act and
there is no `--apply` flag.**

Its safety story rests on three things: a write confinement (which paths a
candidate patch may touch), an egress fence (which bytes may leave the machine),
and Windows MIC containment (what a gate's child process can reach at all).
Everything else is measurement infrastructure whose purpose is to make the
system unable to lie about itself.

That last clause is not decoration. It is the entire project.

---

## 1. Orient yourself — commands that work

```bash
cd C:/Users/nukei/Desktop/agent_env

python -m daedalus.cli doctor            # can we offload real work?
python -m daedalus.cli health            # 5-state health surface
python -m pytest tests -q                # ~2860 tests, ~19 MINUTES. Budget for it.
python -m pytest tests/test_x.py -q      # prefer targeted runs
python tools/operability_drill.py        # 7 controls, each deliberately tripped
git log --oneline -12
```

Read in this order:
1. `docs/HANDOFF.md` — the session-4 block at the top supersedes the rest of
   that file. Everything below its first heading is history.
2. `docs/adrs/019-one-decision-point.md` — the structural finding that explains
   most of the open work.
3. `daedalus/spine/attempt.py` module docstring — why the loop cannot write your
   checkout.

**Free and available:** Ollama at `http://127.0.0.1:11434` with
`qwen2.5-coder:7b` and `nomic-embed-text`. Use it freely.

**Not available:** the paid spend ceiling (`DAEDALUS_BUDGET_USD`, default $5/day)
was exhausted on 2026-07-29. Daedalus-internal paid-vendor subprocesses raise
`BudgetRefused`. It resets daily. Do not raise it without saying so loudly.

---

## 2. The house defect — the one thing to internalise

**Twelve times in one week, the same bug in different clothes: code that exists
was reported as a capability that works.** Not one of them was an agent
escaping its sandbox. Every single one was the system's behaviour drifting from
its own account of itself.

| claimed | true |
|---|---|
| `semantic_route`, wired + tested + documented | had **never once run** — reported `host_unreachable` while the host was up |
| `write_allow` confines writes to `docs/`, `tests/`, `README` | 8 of 12 named paths were writable, incl. the policy loader |
| a file entry in `write_allow` names one file | it matched every **descendant** — `README.md/payload.py` passed |
| `gate_discrimination` "measured against THE CURRENT REVISION" | skipped the check entirely when HEAD was unreadable → forged promotion |
| the verify gate runs the test suite | a worker could dodge it by reporting `files_changed: []` |
| the installed self-policy confines writes | naming `--project agent_env` dropped the confinement completely |
| `spine/containment.py`, 11 vectors measured | zero production callers (since fixed) |
| `budget.py`, a spend ceiling | nothing called `install_process_guard()` (since fixed) |
| `mcp_read` / `mcp_write` capability gates | **gates for a capability that does not exist** — still open, see T5 |

Four of those were authored by the Claude session writing this file. There is no
privileged outer layer that is automatically correct. Assume you will add one
too, and build so it gets caught.

---

## 3. Doctrine — non-negotiable

1. **Every guard needs a test that goes RED when the guard is disabled, verified
   by actually disabling it.** Paste the failure output. A green test never seen
   red is not verification. Back the file up to a scratchpad first so an
   interruption cannot leave the guard off.
2. **Every refusal test needs a control.** Proving the function can say "no"
   proves nothing unless it can also say "yes".
3. **Assert on the AST, not on source text.** A guard test that greps its own
   docstring stays green after the guard is deleted.
4. **A guard reached only through its own function is untested wiring.** Reach it
   the way production reaches it.
5. **"skipped" is never "pass". INCOMPLETE is never a pass.**
6. **Never round a partial result up.** The correct sentence about the last
   bootstrap run is *"rollback, worktree cleanup and ledger resolution held
   during an unintended tenfold stress run"* — **not** "the bootstrap held".
7. **Measure, do not inherit.** If this document gives you a number, re-derive it
   before you build on it. Two agents were right and I was wrong, twice today.
8. **Commit hygiene.** Never `git add -A` or `git add .`. Stage named paths.
   Always read `git diff --cached --name-only` before committing — twice this
   week that read was skipped and other agents' work was swept into an unrelated
   commit. Both commits carry `git notes` corrections.
9. **If more than one agent can write this repo, do not use the index.**
   `git add <paths>` then `git commit` is **not atomic**, and the git index is a
   shared mutable global. MEASURED 2026-07-29: one agent staged three files,
   read `git diff --cached --name-only`, ran `git commit`, and got *"no changes
   added to commit"* — another had committed its staged set in the interval,
   under a different message. Nothing was corrupted, but only because the
   staged set happened to be complete; the same race against a HALF-staged
   index ships a partial change under someone else's authorship, and against a
   session holding one of the four protected artefacts (§T9) it commits exactly
   what everyone was told not to.

   Use `git commit -- <paths>` instead. It commits the working-tree content of
   the named paths only, ignores whatever else is in the index, and leaves the
   index otherwise untouched — so it is immune to the race in both directions.
   Reading the staged set is still worth doing; it just stops being the thing
   that protects you.
10. **An agreed sequence needs an agreed EXECUTOR.** Two agents negotiated the
    correct commit ORDER and both then acted on it. Settling *what* happens is
    not settling *who does it*.

---

## 4. THE WORK

### T0 — Four tests are RED right now. Start here.

MEASURED 2026-07-29 09:55:

```
FAILED tests/test_egress_coverage.py::test_the_floor_catches_the_probe_body_by_path_and_by_content
FAILED tests/test_egress_coverage.py::test_the_repo_room_refuses_to_attach_a_secret
FAILED tests/test_egress_coverage.py::test_no_new_unfloored_body_inlining_path_has_appeared
FAILED tests/test_operability_drill.py::test_a_control_that_raises_is_INCOMPLETE_and_says_so
4 failed, 12 passed
```

These are the unfinished work of agents killed by a power loss mid-session.
`tests/test_egress_coverage.py` is **untracked** — it was never committed.
Decide per test whether it describes a real defect (fix the code) or an
unfinished intent (finish or delete the test). Do not leave a red suite while
claiming anything else in this document is verified.

---

### T1 — `control_promotion` in the operability drill is decorative — **P0**

`tools/operability_drill.py:123-155`. This is the control that certifies
"scheduling is defensible". INHERITED from an adversarial audit, and the shape
is unambiguous — verify it yourself:

```
A subject INTACT   (stale receipt, promotion refused)   status=pass
B subject DISABLED (forged receipt -> promotion ON)     status=pass
C git unreadable + stale receipt                        status=pass
```

It passes on **every** branch. Its name asserts
`a_gated_candidate_is_still_refused`; its body only fails if the refusal string
omits the substring `"NOT evidence"`. It cannot distinguish a held refusal from
a granted promotion. `staleness()` reads the same `measured_head` field and had
the same hole.

**Done means:** the control fails when promotion is actually granted, proven by
granting it. Note case C is now partly closed by `97bf3b1` (unreadable HEAD
refuses) — re-derive which branches still pass.

The other four controls DO discriminate (`control_spend` fails at >1 spawn
reaching the binary; `control_damage_is_bounded` fails if the canary dies), so
this is a targeted fix, not a rewrite.

---

### T2 — `_norm` does not collapse `..` — **P0, latent**

MEASURED at the predicate level in `daedalus/sensitivity.py`:

| path | raw predicate | after `_resolve` |
|---|---|---|
| `docs/../daedalus/core.py` | **WRITABLE** | blocked |
| `docs/./../daedalus/core.py` | **WRITABLE** | blocked |
| `docs/adrs./ADR-999.md` (trailing dot) | **WRITABLE** | blocked |

Not currently exploitable: `daedalus/providers/ollama.py::_resolve` calls
`Path.resolve()` and re-derives the relative path *before* the guard, and it is
the only production caller. **So the confinement's safety currently rests on
normalisation in a different module, and no test asserts that.**
`grep '\.\./' tests/test_self_policy_confinement.py` returns nothing.

A second caller added without `_resolve` makes this live. **Done means** either
`_norm` collapses traversal, or the "callers must pass a resolved path"
invariant is asserted by a test that fails when a caller stops doing it.

Everything else in that surface held: case folding, backslashes, absolute paths,
`\\?\`, UNC, alternate data streams, trailing space, and the fixed
file-entry-descendant case were all blocked or refused at the resolve step.

---

### T3 — The discrimination receipt has no integrity protection — **P0, design**

`runs/spine/gate_discrimination.json` is the artefact that authorises promotion.
`daedalus/spine/bootstrap.py::gate_discrimination` now refuses it when it is
missing, unparseable, not an object, from another revision, internally
inconsistent (`killed > planted`), records no head, or when HEAD itself cannot
be read (all six fixed in `97bf3b1`, red-verified).

**It cannot detect a forgery.** Anything able to write `runs/spine/` can author
a receipt naming the current HEAD and the function will believe it. `runs/spine/`
is gitignored, so the receipt does not travel with the repo either.

This is a key-management decision, not a patch. Options worth costing: sign the
receipt with a key outside the candidate's reach; derive it from something the
candidate cannot fabricate; or accept it and state the trust boundary in
`docs/adrs/`. **Do not close this by adding a checksum the same writer can
recompute** — that is theatre.

---

### T4 — The spend ceiling covers exactly one process — **P0**

`install_process_guard()` has **one** production call site: `daedalus/cli.py`.
It monkeypatches three Python functions *in the installing process*. It is not,
despite earlier claims in this repo's own history, "at the syscall boundary".

INHERITED, confirmed bypasses (verify each):
- `~/.claude/skills/room/room.py` — pure stdlib, spawns `codex`/`claude`
  directly. MEASURED: imports no daedalus module at all.
- `daedalus/claude_bridge.py:169-181`
- `runs/ab/run_arm.py:147-221`
- `runs/council/summarize.py:1011-1076`
- `room_server.py:235-240,540-567`
- `runs/council/room.py` — imports daedalus lazily but installs no guard.

**The system already documents its own gap and nobody read it:**
`daedalus/budget.py:1111-1167` — `BILLABLE_SITES` names every known site, and
each one with `"explicit": False` is covered **only after process installation**.
`tests/test_budget.py` even has a real non-vacuity control.

**Done means** either every executable entry point installs the guard (with a
test that fails when a new entry point does not), or the architecture moves to an
external broker. A per-process patch cannot be a global ceiling; say which you
chose and why.

---

### T5 — Capability gates exist for a capability that does not — **P1**

`daedalus/control_plane.py:25-26`:

```python
{"id": "mcp_read",  "label": "Read via MCP",  "default": "semi_auto"},
{"id": "mcp_write", "label": "Write via MCP", "default": "manual", "critical": True},
```

There is no MCP client, server or transport in this repo, by deliberate decision
— see `docs/ABSORPTION.md` §F4 and ADR-017 Bar 5: the tool *descriptor format*
is adopted, the runtime is refused, because *"everything this repo has built in
the safety direction is about what leaves. There is no fence here for what
enters."* `daedalus/council/vendors.py:490` pins council runs to an empty
`--mcp-config`.

So these two entries are the house defect pre-installed: they look like
protection and have nothing behind them. **Done means** they are labelled as
inactive-by-design, or removed. This is cheap and worth doing regardless.

---

### T6 — The bootstrap has NEVER reached the gate — **P1, the headline**

The self-improvement loop's own end-to-end proof does not exist. MEASURED on the
one live run (2026-07-29 08:20):

```
model wrote      "did_work: verified on disk: docs/LOCAL_MODELS.md"
verify tests     FAIL — timed out after 120 s (the suite needs ~19 min)
rolled_back      [".../docs/LOCAL_MODELS.md"]
action           escalated_after_verify_fail
state            no_change
diff_sha256      e3b0c44298fc...b855   = SHA-256 of the EMPTY input
```

`daedalus/spine/attempt.py:1259-1271` explicitly **skips the gate** on an empty
artefact — so an empty artefact is not a gate failure, it is a gate that never
ran. The timeout cause is fixed (`8e48783` adds `test_timeout_s`, this repo
declares 2700 s), so this should now be reachable.

**Done means** one attempt goes: write → verify PASSES → gate runs → non-empty
artefact → ledger entry, with the receipt quoted. Then read the patch by hand
and say plainly whether it is promotable. The honest answer last time was no —
against an instruction that said *"keep every fact"*, the 7B model deleted a
load-bearing technical fact and a cross-reference.

**Trap:** any script you write that calls into daedalus MUST have
`if __name__ == "__main__":`. `daedalus/structcore/index.py:439` uses a
spawn-based `ProcessPoolExecutor`; on Windows a missing guard re-imports your
script in every worker. That happened, and produced **ten parallel attempts**
that starved each other into `TimeoutError`.

---

### T7 — Re-measure the discrimination receipt at HEAD — **P1**

`runs/spine/gate_discrimination.json` was measured at `a5fc7ce`. HEAD is now
`8e48783` or later. Promotion is therefore correctly refused for staleness, and
**the "83% scoped / 100% whole suite, all 8 critical mutants killed" figures in
`docs/HANDOFF.md` are INHERITED and stale.**

Run `tools/gate_discrimination.py` (~20 min). Then prove BOTH directions:
`promotion_allowed` is False with the stale receipt and True only with a
matching one. Note that committing anything invalidates the receipt again — this
is the loop's structural property, not a bug, and the honest move is to freeze
the tree before the measuring run.

---

### T8 — The picker selects work it is forbidden to do — **P1, composition**

MEASURED: `build_queue(limit=20)` returns 17 candidates — 7 `map_island`,
7 `inventory_island`, 3 `map_shim` — every one of them source surgery under
`daedalus/`. The installed policy permits writes to `docs/`, `tests/`,
`README.md`. **The intersection is empty.** The top candidate does not even
reach the write guard: its instruction contains "delete", a HIGH risk term, so
it routes `risk=high → claude_cli → action=senior`.

The diagnosis, INHERITED from cross-vendor review and worth verifying:
`Candidate` carries **no target paths** — only an instruction and `gate_paths`
(`daedalus/spine/picker.py:214-228`) — so the picker *structurally cannot*
pre-filter by writability.

The recommendation, which I endorse: **no instruction heuristics.** Add explicit
`proposed_paths` to the task protocol so a candidate declares what it intends to
touch, then report **"no admissible candidate"** honestly when nothing qualifies.

**Do NOT resolve this by widening `write_allow`.** That is the day-one failure
mode the policy file itself warns about. An honestly empty queue is a legitimate
deliverable. Note also that anything a candidate declares is candidate-controlled
data: filtering on it is fine for *selection*, but it must never become the thing
that authorises a write. The write guard stays the authority.

---

### T9 — Triage the uncommitted work of six crashed agents — **P1, housekeeping**

A power loss killed six agents mid-flight on 2026-07-29. Their work is in the
tree, uncommitted. MEASURED `git status` at handoff time:

**Modified, tracked:** `daedalus/budget.py`, `daedalus/cli.py`,
`daedalus/compaction.py` (a *deletion*), `daedalus/council/publish.py`,
`daedalus/file_bridge.py`, `daedalus/health.py`, `runs/council/room.py`,
`tests/test_bridge_restart.py`, `tests/test_bridge_signals.py`,
`tests/test_cascade.py`, `tests/test_hardening.py`,
`tests/test_health_surface.py`.

**Untracked:** `daedalus/spine/docrefs.py`, `tools/bootstrap_receipt.py`,
`tests/test_bootstrap_receipt.py`, `tests/test_bridge_enqueue_guard.py`,
`tests/test_council_publish_cli.py`, `tests/test_egress_coverage.py`,
`tests/test_spend_coverage.py`.

**Deliberately dirty, DO NOT COMMIT:** `docs/FEATURE_INVENTORY.json`,
`docs/architecture-map.html`, `docs/architecture-state.json`,
`runs/council/room.md`. These are regenerated artefacts left dirty on purpose so
the picker's freshness checks pass while the receipt still matches HEAD.
Understand that before touching anything near them.

**`daedalus/compaction.py` is deliberately deleted**, with callers updated — see
the explanatory note at `daedalus/health.py:1075` and
`tests/test_health_surface.py:426`. That deletion is intentional and evidenced.

**`daedalus/cli.py` is contested** between two agents' uncommitted work: a
`council --publish-pr` wiring inside `_council` plus a new `_council_pr` helper,
and a `governance` subcommand (usage text, a `_governance(argv)` helper before
`main()`, and an `elif cmd == "governance":` branch at the end of the dispatch
chain). They were reported to apply cleanly together. **Land them as one commit.**

---

### T10 — Two deletion proposals, evidenced but not executed — **P2**

INHERITED, verify before acting. A module was once deleted in this project on
stale evidence and had to be restored, so the bar is: show that nothing needs it.

- **`daedalus/kairos/evolution.py` + `kairos/shadow_shell.py`** (192 lines).
  Zero production callers; only each other and two test files. Superseded by
  `spine/attempt.py`. The sharp argument: `grep -c "ledger\|spine"` returns
  **0** for both — they create branches and worktrees with **no ledger intent
  record**, which is exactly the crash-safety property `spine/attempt.py` exists
  to guarantee. They would be a safety *regression* if anyone ever wired them.
  Deleting `shadow_shell.py` also orphans `worktree.commit_candidate` /
  `has_changes`.
- **`daedalus/memstore.py`** (615 lines). Its `DEFAULT_LEDGER_PATH` and
  `state.local.json` **do not exist on disk**; it has never been written to.
  Superseded three times, one explicitly: `council/bus.py:13` says it
  *"deliberately REIMPLEMENTS memstore.py"*.

---

### T11 — Two modules are islands with no consumer — **P2**

`daedalus/gui_catalogue.py` (real corpus at `catalogue/gui/*.json`, 44 KB
committed, real parser, no consumer) and `daedalus/skills.py` (1040 lines, zero
references outside its own test). Both are format readers built ahead of their
consumers.

**Do not bolt on a `python -m` entry point to make the island count fall.** The
island metric is gameable — deleting a test moves a module to `unknown` and the
headline number drops with the dead code untouched. Read `unreached`, and state
which metric you used.

---

### T12 — ADR-019: six predicates, four normalisers — **P3, the big one**

`docs/adrs/019-one-decision-point.md` records it in full. Six predicates decide
over the same nouns; each reads a **different subset** of the same `Policy`;
three fields are read by exactly one of the six. Four path normalisers exist
(`_norm` in `sensitivity.py` **and** `router.py`; `_fence_norm` in
`sensitivity.py` **and** `structcore/graph.py`).

The target shape: one `verdict(path, action, lane, policy) -> Verdict` (the
PDP/PEP split), one normaliser applied at the boundary, and the string-predicate
layer demoted to defence-in-depth behind the capability layer — the MIC
containment, which has **never leaked**.

**This is deliberately NOT authorised.** It touches the safety core, every
predicate has callers depending on its exact current answer, and a rushed
rewrite there is worse than the defect. Cross-vendor advice was explicit: close
the leaks first, then do this as its own mutation-measured migration.

---

### T13 — A useful thing nobody has built: the docs lane has no gate — **P2**

`write_allow` permits `docs/`, and MEASURED, a 7B rewrite deleted two true
statements against an instruction that forbade exactly that. `daedalus/verifier.py`
has **no markdown branch at all**. A preservation tripwire was committed in
`01a341d` — check what it covers and whether it is wired into `verify()`.

Framing matters here: such a check is worth having **only as an asymmetric
tripwire** (code spans, paths, links and numbers must not vanish). It proves
nothing about semantic completeness. Human review remains the gate, and any
surface that suggests otherwise is worse than none.

---

## 5. Traps already paid for — do not re-learn these

- `verifier.verify()` defaulted to `timeout_s=120`; a `test_command` slower than
  that could never pass. Fixed, but check what a repo declares before blaming a
  gate.
- Windows `ProcessPoolExecutor` is spawn-based → `if __name__ == "__main__":`.
- `assert <set> == []` is vacuously true on a clean tree.
- A collection error (`IndentationError`) is not a red test.
- Hardening git once removed `core.autocrlf`; every text file then looks
  modified and an idle runner reports `clean` instead of `no_change`.
- **A full disk looks exactly like broken code.** 60 tests in
  `tests/test_worktree.py` went red at 0.59 GB free (`StorageUnavailable`,
  a worktree needs 2 GiB) and 58/58 green at 83 GB. Check the disk first.
- **`git grep` searches the INDEX for unstaged changes.** It reported a constant
  as missing that was present in the working tree, and nearly produced a false
  "this bundle is inconsistent" claim. Use a working-tree search.
- A mutation harness that rewrites whole files while other work is in flight
  will eventually commit one of its own mutations. It did.

---

## 6. Things that are TRUE and must not be "fixed"

- **Promotion refuses.** That is the design. `promotion_allowed` is a single
  unconditional return with no parameter and no override.
- **There is no `--apply`.** Do not add one.
- **The four regenerated artefacts are dirty on purpose** (T9).
- **`daedalus/compaction.py` is deleted on purpose** (T9).
- **`runs/spine/` is gitignored**, so receipts do not travel with the repo. Every
  machine measures for itself. Defensible given containment is win32-only, but
  know that you are choosing it.
- **The council pins MCP to an empty config** and refuses the MCP runtime by
  decision, not by omission (T5).
- **The local lane's write path is advisory unless the provider implements
  `rollback()`.** Only the Ollama provider does. That downgrade is explicit and
  rides the result — do not "simplify" it away.

---

## 7. How to report

For every claim: **CONFIRMED / REFUTED / UNVERIFIED**, the exact command and its
output, and for refutations the smallest reproduction. Rank findings most severe
first. If you cannot verify something, write UNVERIFIED and why — do not fill the
gap with a plausible sentence. A short report full of real evidence beats a long
one full of reasoning.

And if something in this document turns out to be wrong, say so plainly with
evidence. Several things in it were wrong when first written, and the only
reason they are right now is that somebody checked.
