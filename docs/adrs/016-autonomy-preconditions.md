# ADR-016: Preconditions for an Unattended Loop

## Status

Accepted as a **gate**, 2026-07-29. This ADR does not schedule autonomy and
does not approve it. It states what must be true before a loop may run
unattended, and it makes each item **falsifiable** — every precondition below
carries a command or a test that would show it satisfied, and most of them are
RED today.

An ADR that only listed good intentions would be the thing this repo keeps
finding and deleting: a sentence doing a control's job. So the deliverable here
is the checks, not the prose.

## Scope, stated precisely

"Unattended loop" means: **the assistant runs `pick → attempt → gate → record`
repeatedly, invoking a model that writes code, with no human watching the
iteration.** Three weaker things are explicitly *out* of scope and are already
permitted:

- the **advisory** loop (`daedalus improve --once` with no `--live`) — no model
  is invoked;
- an **attended** `--live` attempt — a human is watching and can stop it;
- **promotion**, which stays a human act under every precondition below and is
  not made automatic by satisfying them.

## Provenance

**MEASURED** = a command was run on this box on 2026-07-29 and its output is
quoted. **INHERITED** = taken from `docs/archive/2026-07/HANDOFF.md` (session-3 block) and not
independently re-verified. Line numbers drift — sixteen agents were editing in
parallel while this was written, and the test count moved by 3 during the
session. Symbol names do not drift; prefer them when re-checking.

## Context: what is measured true tonight, and what is not

**True (INHERITED, `docs/archive/2026-07/HANDOFF.md`).** The circle is closed and was run on
this repo, not mocked: `daedalus improve --once` picked from generated
evidence, recorded the intent before the effect, attempted in an isolated
worktree, cleaned up including the ref, and then *chose something else* — rank
1 → rank 7 of 10, still in the queue. Reproduced MEASURED tonight: the ledger
carries `"attempt_memory": {"read": true, "tasks_remembered": 1}` and the queue
note reads `attempt memory: 1 candidate(s) match a prior attempt at the same
instruction (1x no_change); 1 sank to their outcome's ceiling`.

**Not true, and load-bearing.** The runner that produced that demonstration was
**advisory** — no model wrote anything. Promotion is deliberately a human act.
Candidate write-containment landed tonight and is win32-only. And the fitness
signal is not trustworthy.

**There is no unattended loop today.** MEASURED — `daedalus improve` attempts
*exactly one* candidate and offers no interval, repeat, or daemon flag:

```
$ python -m daedalus.spine.picker --help
  --once --dry-run --limit --eval --hotspots --live --repo-root
  --artifact-dir --keep-worktree --forget --stale-inventory --verbose --json
```

That is the ground truth this ADR gates: the loop does not exist yet, so this
is a gate written *before* the thing it gates, which is the only time such a
gate is honest.

---

## The preconditions

Status key: **RED** = measured false today. **AMBER** = partly true, with a
named gap. **GREEN** = measured true today, and the check is the regression
test that keeps it true.

---

### P1 — Write containment must be on the path a candidate actually runs. **RED**

**The claim.** A `--live` attempt must execute model-driven code inside the
measured Low-integrity boundary, and must **refuse to run** rather than
silently run uncontained when the boundary cannot be established.

**Evidence.** `daedalus/spine/containment.py` landed tonight with a strong,
honestly-bounded measurement — eleven write/destroy vectors refused by the
kernel, including the move-in attack the handoff records as *"open by
construction and no reparse check can ever close it"*. It also states its own
limits, including that `ContainmentUnavailable` is *"NEVER downgraded
silently"*.

**And nothing calls it.** MEASURED:

```
$ grep -rn "spine.containment" --include=*.py . | grep -v "^./tests/"
(no output; exit 1)

$ grep -rn "spawn_contained\|label_low_integrity" --include=*.py . | grep -v "^./tests/"
daedalus/spine/containment.py:68:    "label_low_integrity",
daedalus/spine/containment.py:70:    "spawn_contained",
daedalus/spine/containment.py:186:def label_low_integrity(...)
daedalus/spine/containment.py:271:def spawn_contained(...)
```

The only hits are the module's own `__all__` and its own `def`s. The single
production runner, `attempt.offload_runner`, calls `daedalus.offload.offload`
directly in-process at the operator's own integrity level — MEASURED, the
function body is four lines and none of them mention containment.

**So the strongest boundary this repo has ever measured currently protects
nothing that runs.** It is a module with tests and no callers — which is
exactly the classification the repo's own picker calls an *island*, and would
rank in its top band if it could see it (see P7).

**Falsifiable check.**

1. `grep -rn "spawn_contained" daedalus/spine/attempt.py` returns ≥ 1 hit.
2. An integration test drives a real `--live`-shaped attempt whose runner
   attempts to write a file in the **primary checkout**, and asserts the write
   fails with a *kernel* refusal (`PermissionError` / winerror 5), not a Python
   path check.
3. The same test, with containment unwired, goes **RED** — verified by
   physically deleting the wiring and re-running, in the style
   `docs/archive/2026-07/HANDOFF.md` already uses for every other guard in this repo.
4. A test asserts that when `platform_supported()` is false, a `--live`
   unattended run **refuses to start** rather than proceeding uncontained.

**Blocks.** Everything. No other precondition is worth satisfying first,
because without this the failure mode is a model with a bad instruction writing
the developer's working tree.

---

### P2 — The boundary must bound egress and reads, not only writes — or the loop stays attended. **RED**

**The claim.** An unattended candidate must not be able to read the checkout
and post it somewhere. Today it can, and the containment module says so itself.

**Evidence.** MEASURED, `daedalus/spine/containment.py` docstring, the module's
own "THE CLAIM, AND ITS EXACT LIMITS" section:

```
  * CONFIDENTIALITY: NONE. MIC is a write-UP barrier. A contained candidate may
    read the whole checkout and the user profile. Nothing here prevents
    exfiltration and no caller may read it that way.
  * NETWORK: unrestricted. A Low process still has a network stack.
  * NAMED PIPES: UNMEASURED.
```

That module is being honest, and its honesty is the finding: **P1's boundary,
once wired, still leaves egress completely open.** Meanwhile the repo's actual
egress fence is process-level Python — `sensitivity.lane_for_host`,
`slice_egress_rule`, `secret_floor_rule` — which binds only code that chooses
to call it. Candidate code does not.

This matters more here than it would elsewhere because of what INHERITED
evidence says about that fence: `lane="trusted"` was chosen from the *provider
name* while the endpoint came from `OLLAMA_HOST`, so a tailnet address kept the
name "ollama", kept the trusted lane, and converted a no-egress lane into a
network one — *"No code change, no flag, no log line. A comment asserting
locality was doing the security work."* That was closed, in two call sites,
tonight. A contained candidate with a full network stack can reproduce the
*effect* of that bug by hand, without touching the fence at all.

**Falsifiable check.** A test that spawns a contained child and asserts **both**:

1. it **cannot** open a TCP connection to a non-loopback address; and
2. it **cannot** read a secret-shaped file outside its worktree.

Today both succeed, so this test is RED by construction — which is the point of
writing it now. Satisfying it requires a different mechanism than MIC
(AppContainer, or a restricted token with its own SID), and `containment.py`
already names that as *"its own ADR with its own threat model"*. **That ADR is
a prerequisite of this precondition, not a substitute for it.**

**Blocks.** Unattended `--live`. Does **not** block attended `--live`, where a
human is the compensating control — which is the honest reason attended live
runs are permitted today and unattended ones are not.

---

### P3 — The fitness signal must be shown to reject known-bad, not merely to pass. **RED**

**The claim.** A gate that has never been demonstrated to fail on a bad change
is decoration, and a loop steered by it optimises for the decoration.

**Evidence.** MEASURED: the gate is `pytest`, assembled by
`attempt.pytest_gate_argv` as `(sys.executable, "-m", "pytest", *paths, "-q",
"-p", "no:cacheprovider")`. MEASURED: every candidate in the live queue carries
`"gate_paths": []`, so `*paths` is empty and the gate is **the whole suite** —
2066 tests collected on this tree tonight.

And the whole suite is measurably not an oracle. INHERITED,
`docs/archive/2026-07/HANDOFF.md` and restated in `tools/system_check.py`'s own docstring:

> "The unit suite is at 1732 green and that is not evidence the product works.
> Three times in one day a fully green suite sat over a live escape; the A/B
> produced two implementations that passed their gate and contained no tests at
> all."

Three escapes, three green suites, one day. Measured rejection rate of the
current gate against the day's known-bad changes: **0/3**.

This is not a new opinion — it is already this project's own ruling. INHERITED,
the A/B writeup's conclusion: *"fix the gate first. A repair loop is meaningless
when its oracle accepts wrong implementations… Pre-register behavioural
acceptance tests, prove they reject known-bad fixtures."* P3 is that ruling
written as a precondition with a number attached.

**Falsifiable check.** A **known-bad corpus** — a directory of patches that
reintroduce defects this repo has actually shipped, each with a one-line
provenance note:

- `lane="trusted"` selected from the provider name (the egress breach);
- `agy -p "$(type FILE)"` over ssh (the RCE, which existed in three copies);
- `bInheritHandles=True` in `spawn_contained` (the measured MIC bypass);
- `shutil.rmtree(..., ignore_errors=True)` restored in a `finally:`;
- an inventory `recorded_head` of `"a"` (the prefix check that passes by
  coincidence).

The check: apply each patch to a clone, run the gate, and record the verdict.
**The precondition is satisfied when the gate rejects every patch in the
corpus.** The number is published, not asserted, and it goes in the review
packet next to the gate verdict so no reader ever again sees "GATE: PASS"
without seeing what that gate has been shown to catch.

`tools/system_check.py --self-test` is the existing prior art for this exact
move — it *"break[s] things in the clone and prove[s] the checks go RED"* — and
the corpus is that idea pointed at the candidate gate instead of at the
acceptance harness.

**Blocks.** Any relaxation of P8 (human promotion). Does **not** block an
unattended loop that only *proposes*, because a proposal a human reads is
judged by the human, not by the gate. This distinction is the reason the
ordering below is not a single chain.

---

### P4 — An unattended loop must have a hard spend and iteration bound, enforced by a control. **RED**

**The claim.** A loop that can run all night must have a ceiling that a
crash, a retry storm, or a cheerful model cannot exceed.

**Evidence.** MEASURED — no such control exists:

```
$ grep -rn "budget_usd\|max_usd\|spend_cap\|MAX_SPEND\|daily_budget\|cost_cap" \
    --include=*.py daedalus/
(no output)
```

`daedalus/bookkeeper.py` is documentation rendering, not accounting.
`daedalus/token_policy.py` contains no refusal path — its only function is
`trim_paths`. There is token *accounting* in `benchmark.py` and
`council/vendors.py`, but accounting is a record, not a brake.

Scale, INHERITED from the A/B table: a single feature cost **$1.4335** on one
arm and **$1.8451** on the other, at 358s and 545s wall clock. An unattended
loop is that, per iteration, with no ceiling and no operator awake.

**Falsifiable check.** A test that drives the loop with a stubbed accountant
past a configured cap and asserts that **iteration N+1 does not start**. Plus:
the cap must be *required*, not defaulted — an unattended entry point invoked
without an explicit bound must refuse to start. Plus: the cap must survive a
crash, i.e. spend is read back from the durable ledger rather than from a
counter in memory, so a restart cannot reset the budget to zero. That last
clause is where a naive implementation will fail, and the test must exercise it
by killing and restarting the loop.

**Blocks.** The existence of an unattended entry point. Cheap to satisfy and
independent of P1–P3.

---

### P5 — The loop must be stoppable from outside itself, and the stop must be measured. **RED**

**The claim.** A human must be able to stop a running loop without finding a
process, and the stop must be shown to actually kill the in-flight child — not
just prevent the next iteration.

**Evidence.** The parts exist and are good. `daedalus/spine/cancel.py`
implements a win32 Job Object backend with a fail-closed contract
(`CancellationUnavailable`), and `tests/test_spine_cancel.py` already pins
*"spawn fails closed when containment fails"*. `TaskAttempt` accepts a
`cancel=` predicate. What does not exist is a loop to cancel, or any documented
external switch — a file, a signal, a named event — that a human could use
without a debugger.

`docs/adrs/007-root-of-trust.md` already names *"The Emergency Stop /
Kill-Switch"* as a Root-of-Trust component and records its own status as
**"Proposed; not enforced"**, with acceptance requiring *"a kill switch that
the candidate process cannot modify"*. P5 is ADR-007's unmet condition, made
checkable.

**Falsifiable check.** Start the loop; create the stop file; assert **both**
(a) the next iteration does not begin, and (b) the in-flight child process is
gone within a stated number of seconds — verified by pid, not by a log line. A
third assertion closes ADR-007's clause: the stop file lives **outside** any
path a contained candidate can write, and a test proves the candidate cannot
delete or overwrite it. Note that this assertion is only *meaningful* once P1
is satisfied, which is one of the ordering edges below.

**Blocks.** The existence of an unattended entry point, jointly with P4.

---

### P6 — "No candidate" must never be indistinguishable from "a source broke". **GREEN**

**The claim.** A loop whose input source fails must say so, not go quietly
idle.

**Evidence.** This one is satisfied, and recording a GREEN precondition matters:
it is the only way the list is a measurement rather than a complaint. MEASURED
tonight, with the exit code captured directly (not through a pipe — the first
attempt at this measurement piped stdout through `tail` and read `tail`'s exit
code, which is exactly the class of mistake this repo keeps cataloguing):

```
$ python -m daedalus.spine.picker --dry-run --json --limit 4 > q.json
$ echo $?
3
$ python -c "...; print(d['degraded_sources'])"
['inventory']
```

Exit **3** = `EXIT_SOURCE_UNAVAILABLE`, distinct from 0 (work is waiting), 1
(anything else) and 2 (ran and changed nothing). The picker states the
reasoning in source: *"0 still means, and only ever means, that work is
waiting."*

**Falsifiable check.** `tools/system_check.py --only
picker.exit_code_distinguishes_degraded` → PASS. That check already exists and
already asserts the exit code matches the degraded state. **This precondition's
maintenance job is to keep it green, and any unattended runner must branch on
exit 3 explicitly** — a wrapper that treats 3 as "nothing to do" throws the
whole guarantee away at the last mile.

---

### P7 — The loop's evidence sources must be demonstrably about the tree it will act on. **AMBER, with a new finding**

**The claim.** The picker chooses work from files on disk. Those files must be
provably about the current tree, or the loop is reasoning about a repo that no
longer exists.

**Evidence — the good half.** The inventory source is gated on freshness
against HEAD and is currently, correctly, **suppressed**. MEASURED:

```
"inventory": { "suppressed": true,
  "freshness": { "fresh": false,
    "reason": "the inventory was written against f40529c but HEAD is 9edf6db" } }
```

12 candidates withheld. That gate works and fails in the right direction.

**Evidence — the finding, and it is new.** The *map* source — now the loop's
only live source — has **no freshness gate at all, and cannot have one**.
MEASURED, `docs/architecture-state.json` top-level keys:

```
['schema', 'note', 'counts', 'ignore', 'modules', 'islands', 'unknown',
 'shims', 'test_only', 'dark_switches', 'doc_drift', 'unparsable',
 'index_extra_edges', 'acceptances', 'digest']
```

**There is no `head` and no `generated_at`.** The snapshot does not record the
revision it was generated against, so `picker.map_state_trustworthy` checks the
*digest* — "has anyone hand-edited this" — and nothing else. That is a real
protection against a different attack and it verifies today
(`"trust": {"trusted": true, "reason": "snapshot digest verifies"}`). It is not
a freshness check, and a digest-valid snapshot generated forty commits ago
would be trusted identically.

**The asymmetry is already biting.** MEASURED: the map lists 122 modules and 7
islands. `daedalus/spine/containment.py` is **in none of them** — it is not in
the module list at all. The repo's own measurement engine cannot see the safety
module that landed tonight, so the picker **cannot rank the work that P1
describes**, even though that work is the exact shape (`island`,
`imported_only_by_tests=True`) that the picker's highest band exists for.

**Falsifiable check.** Two parts:

1. `python -m daedalus.spine.picker --dry-run --json` reports
   `"degraded_sources": []` — every source consulted and fresh.
2. The map snapshot records the revision it was generated against, and
   `map_state_trustworthy` refuses a snapshot whose recorded head is not a
   prefix of actual HEAD — the same contract `inventory_freshness` already
   implements, including its deliberate boundaries (dirtiness alone does not
   suppress; fail **open** when git cannot answer; the recorded head must match
   `[0-9a-f]{7,64}` so a one-character value cannot match ~1 HEAD in 16 and
   report fresh by coincidence). A test must go red when the check is removed.

**Blocks.** Nothing structurally — a loop can run on a stale map. It **caps the
value** of everything else: an unattended loop pointed at a stale map does real
work on a tree that has moved. Fixing part 2 is what would let the loop see P1
as its own top-ranked task, which is a pleasing property and not an argument
for doing it first.

---

### P8 — Promotion stays human until P1, P2 and P4 are green and P3 has a published number. **GREEN, and to be kept green**

**The claim.** Nothing lands without a person.

**Evidence.** MEASURED, three independent structural facts, not one promise:

1. `daedalus improve --help` offers no `--apply`, `--promote`, `--merge`,
   `--commit` or `--push` (full flag list quoted in the Context section above).
2. `tools/system_check.py`'s `safety.picker_cannot_apply` check inspects the
   **argparse parser**, not the help text — and its comment records why: *"The
   first version grepped --help output and matched the epilog sentence 'There
   is no --apply flag', i.e. it read the denial of the flag as evidence the
   flag existed."*
3. `daedalus/spine/attempt.py` documents that the deliverable is inert bytes and
   that `READ_ONLY_REPO_VERBS` makes adding an apply path *"fail loudly rather
   than quietly work"*.

Corroboration from outside this repo (see ADR-017): NousResearch's own
`hermes-agent-self-evolution` — a project whose entire purpose is automated
self-improvement — states its promotion rule as *"All changes go through human
review, never direct commit."*

**Falsifiable check.** `python tools/system_check.py --only
safety.picker_cannot_apply` → PASS. Run it in CI, not by hand.

**This is the precondition that must be satisfied last, and it is the reason
the others can be worked on safely.** Every red item above is survivable
precisely because nothing lands without a person.

---

### P9 — The acceptance run must be green on this box, and its checks proven able to go red. **UNMEASURED HERE**

**The claim.** "The unit suite is green" is not the claim; "the spine runs, on
this machine, right now" is.

**Evidence.** `tools/system_check.py` exists for exactly this and already
encodes the right contract — three outcomes where **UNAVAILABLE is not
success**, and *"on a CORE check it is not even neutral"*, with exit 2 meaning
INCOMPLETE. It ships `--self-test`, which *"break[s] things in the clone and
prove[s] the checks go RED"*.

**I did not run it.** It builds a disposable clone of the working tree and
executes the full spine end to end; with sixteen agents editing this tree, a
run tonight would measure a moving target and its result would be
uninterpretable. **Recorded as UNMEASURED rather than assumed** — that is the
same distinction the harness itself insists on.

**Falsifiable check.** `python tools/system_check.py` → exit **0** (not 2), on
a quiesced tree, and `python tools/system_check.py --self-test` → every check
demonstrated able to fail. This is the standing regression for every other
precondition, and an unattended loop must not start if it exits non-zero.

---

## The honest ordering

Not a single chain. Three independent tracks that converge, plus one that must
stay green throughout.

```
                    P8 human promotion (GREEN — hold it green the whole way)
                                      |
   track A (boundary)     track B (oracle)      track C (bounds)
        P1 wire                P3 known-bad          P4 spend/iteration cap
         |                     corpus                 P5 external kill switch
        P2 egress-bounding          |                      |
        boundary (needs its         |                      |
        own ADR)                    |                      |
         \__________________________|______________________/
                                    |
                    unattended --live loop may run
                                    |
                    P9 acceptance run green, standing
                    P7 sources fresh (caps the value of all of it)
```

**The dependency edges that are real, and why:**

- **P1 → P2.** You cannot bound the egress of a mechanism nothing calls. P2's
  test is meaningless until a candidate actually runs inside something.
- **P1 → P5(c).** "The candidate cannot delete the stop file" is a claim about
  a boundary. Without P1 there is no boundary and the clause is untestable.
- **P1 + P2 → unattended `--live`.** Together they are the whole difference
  between "a human is the containment" and "the machine is".
- **P3 → relaxing P8.** Only the oracle gates promotion. Nothing else does.
- **P4 + P5 → an unattended entry point existing at all.** These two are
  cheap, independent of the boundary work, and are the minimum a daemon needs
  to be shut off and to stop spending.
- **P7 caps value, blocks nothing.** Listed last deliberately, to resist the
  pull of doing the tidy thing first.

**The edges that are NOT real, and saying so is the point:**

- P3 does **not** block an unattended loop that only proposes. A proposal a
  human reads is judged by the human. Conflating these would make the whole
  list one impossible chain and guarantee nothing gets done.
- P7 does **not** block P1. It is tempting to argue "the picker should see
  containment.py before we work on containment.py", and that is backwards: the
  picker is a convenience for choosing work, not a prerequisite for doing it.

---

## The smallest first step

**Wire `spawn_contained` into `TaskAttempt`'s runner path, behind an explicit
opt-in, preserving the `ContainmentUnavailable` → refuse contract; and add the
integration test that goes RED when the wiring is removed.**

That is P1, and only P1. One module touched, one new argument, one test.

Why this and not something else:

- **It is the only item everything else rests on.** P2 is untestable without
  it. P5's strongest clause is untestable without it. P4 without it is a budget
  on an uncontained process, which is a spending limit on a fire.
- **It converts the repo's best-measured artifact from an island into a
  boundary.** Eleven refused write vectors, including one the handoff records
  as unclosable by any Python check, are currently protecting nothing. That is
  the highest ratio of measured value to realised value anywhere in the tree
  tonight.
- **It is verifiable in the way this repo already trusts** — physically delete
  the wiring, re-run, count the red tests, restore. The same sweep
  `docs/archive/2026-07/HANDOFF.md` records for eleven other guards, one of which found two
  guards with *no* red at all and exposed two real test defects. Expect that to
  happen here too.
- **It changes no behaviour anyone depends on.** Advisory runs are unaffected;
  attended `--live` gains a boundary it did not have; promotion is untouched.

**What must NOT be done in the same commit**, because each is a separate
decision with a separate review:

- adding a loop driver, an interval, or a daemon (P4/P5 gate that);
- making containment the default before its refusal path has been exercised on
  a machine where `platform_supported()` is false;
- anything named "sandbox" — `containment.py` argues at length for why it is
  not one, and the name would re-import the confidentiality and network
  assumptions the module explicitly disclaims.

**The second step, once P1 is green**, is P4 + P5 together — a cap and a
switch, both cheap, both independent of the boundary work — and *then* the
ADR that P2 requires for an egress-bounding mechanism. P3's known-bad corpus
can be built in parallel by anyone, at any time, and is the highest-value item
for a second person.

## Consequences

- **No unattended `--live` loop may be started until P1, P2, P4 and P5 are
  green.** Attended `--live` and the advisory loop are unaffected.
- **P8 stays green throughout.** No precondition in this list, satisfied or
  not, is an argument for adding `--apply`. Relaxing P8 requires its own ADR
  and P3's published number.
- **A precondition without a runnable check does not belong in this list.** If
  a future item cannot be falsified, it is a value, not a gate, and it goes
  somewhere else.
- **Two findings here belong to other owners** and are recorded, not fixed:
  the map snapshot records no revision (P7), and `daedalus/web_api.py` binds a
  server with a settable `--host` (default `127.0.0.1`, so `0.0.0.0` is one
  flag away) and zero authentication — MEASURED, no `Authorization`, bearer,
  or token check anywhere in the file. That second one is the ADR-002 shape —
  *"an independent, unauthenticated WebSocket server"* — alive in this repo
  today, and an unattended assistant reachable over it would be strictly worse
  than the thing ADR-002 deleted. It is out of this ADR's scope and should not
  stay out of someone's.
