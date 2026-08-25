# One owner decision, eighty-nine places that never heard about it

**MEASURED 2026-08-25** over `git ls-files` at `52b30412`. Reproduce with the
command at the end; every count below came from it.

On 2026-08-22 the repository owner retired the mechanical guard. Plan revision
7 records it in one sentence:

> the mechanical guard (`tools/iron_plan_guard.py` (removed 2026-08-22), hooks, commit hooks, CI) is
> retired by owner decision

Commit `79825b57` deleted the script. Three days later, **89 tracked files
still name that ceremony** — 24 of them on surfaces that are current rather
than dated evidence. None of this was negligence. A deletion propagates to the
things that *import* a file automatically and to nothing else, and every
surface below refers to the guard by **name in text**: a workflow step, a
policy list, an agent's standing orders, a corpus document id. Nothing links
them, so nothing broke, so nothing announced itself.

That is the general lesson worth keeping: **a decision propagates along
dependency edges; a decision recorded as prose has no edges.** The blast radius
of retiring something is the set of places that *mention* it, and that set is
not computable from the code.

## The four kinds, and only two of them are defects

| kind | what it means | count |
|---|---:|---|
| **standing order** | tells a human or an agent to run it, now | 3 files (repaired) |
| **enforcement surface** | a policy or gate that lists it | 3 files |
| **authority text** | the plan and the Gesamtplan still mandate it | 2 files |
| **record** | says, correctly, that it was retired | 16 files |
| **frozen data** | a research corpus that indexed it as a document | 6 files |
| **generated** | an artifact regenerated from a stale input | 3 files |
| dated evidence (`docs/archive/`, `inventory/`, `recovery/`, ADRs, handoffs …) | describes the tree as it was; correct by construction | 65 files |

Only the first three kinds are defects. A record of a retirement is the system
working.

## 1. Standing orders — REPAIRED 2026-08-25

The sharpest trace, and the one nobody had looked for. Three crew charters
ordered the deleted command as the **first action** of every dispatched agent:

| file | line | text |
|---|---:|---|
| `.claude/agents/atalanta.md` | 11 | "Run `python tools/iron_plan_guard.py verify` first." |
| `.claude/agents/heracles.md` | 11 | same, "before any edit" |
| `.claude/agents/hephaestus.md` | 11 | same |

Every Heracles, Atalanta and Hephaestus dispatched since 2026-08-22 was told to
begin by running a file that does not exist. Replaced with what the plan
actually requires now — say in one line whether the work is `ALIGNED` /
`EXPERIMENT` / `AMENDMENT`, and note that nothing verifies it for you. No other
duty in those charters changed.

### It fired at least once, and the outcome was good for a reason you cannot rely on

`[MEASURED 2026-08-25, INHERITED from the parallel session `agent-env-8e`, which
dispatched the agent]` Atalanta ran at ~11:15-11:40 under the unrepaired
charter. Her report carries, under the heading "Could not measure":

> `tools/iron_plan_guard.py` does not exist (retired by owner decision, plan
> revision 7)

She caught the impossible order, classified it as *could not measure* —
distinguishable from *measured, found nothing* — and carried on; the ignition
lane ran blocker-free to a green receipt.

That is not the reassuring reading. **It was the agent's quality, not a
property of the system.** The charter sent her into a dead end and her noticing
was not designed for. What the failure actually looks like, measured here:

| how it is invoked | exit | stdout | stderr |
|---|---:|---|---|
| directly, bash | 2 | empty | `can't open file …` |
| directly, `cmd /c` | 2 | empty | same |
| directly, PowerShell | 1 | empty | same |
| through any pipe | **0** | empty | same |

The diagnosis lives *entirely* on stderr and the failure lives *entirely* in
the exit code. A caller that captures stdout and does not check the status gets
an empty string and a zero — a clean-looking nothing. Pipe it through anything
at all and even the exit code is gone, because the status belongs to the last
command in the pipe. So the two plausible bad outcomes were: read the failure
as a blocker and abandon the lane, or log `verify` as passed because nothing
came back. Neither happened, once, by grace.

Heracles and Hephaestus were not dispatched that day; for them there is no
evidence in either direction.

`.claude/watchdog/docs-sweep-prompt.md:11` still lists
`tests/test_iron_plan_guard.py` (removed 2026-08-22) among the paths a sweep must treat as
protected. Left alone: it is a hint, not an order, and it fails closed.

## 2. CI — REPAIRED 2026-08-25

- `.github/workflows/` — **170 step lines across 94 files**, each
  `- run: python tools/iron_plan_guard.py verify`, no `continue-on-error`; in
  26 of the 94 the step sat above `pytest`. Removed; 0 lines added.
- `.github/CODEOWNERS` — 6 ownership lines naming the ceremony
  (`iron_plan_guard.py`, `iron_plan_hook_runner.py`,
  `test_iron_plan_guard.py`, `enforce-iron-plan/`, `.githooks/`,
  `workflows/iron-plan.yml` (removed 2026-08-22)). Removed. `/.codex/` is also dead and was **left**
  — it is not part of this ceremony.

`tests/test_workflow_references.py` now keeps both from returning. Note what
this repair is *not*: no Actions job currently starts at all, for a separate
billing reason. See `docs/STATUS.md`.

## 3. Enforcement surfaces — OWNER-SHAPED, not touched

This is the one a lane must not tidy, because the dead names are **test-pinned
in three places**.

- `.agentenv/agentenv.json` — `policy.high_risk_paths` lists
  `tools/iron_plan_guard.py`, `tools/iron_plan_hook_runner.py`,
  `tests/test_iron_plan_guard.py`, plus `.agents/skills/enforce-iron-plan/`,
  `.githooks/` and `.codex/`. Six of its 28 entries point at nothing. Under the
  plan's authority table this file is the **mechanical veto policy** — the one
  artifact here that is not merely descriptive — and `.agentenv/` protects
  itself by being in its own `high_risk_paths`.
- `daedalus/sensitivity.py` ships the same defaults; line 215 also carries the
  name in an explanatory comment.
- `tests/test_sensitivity_default_policy_pins.py` pins
  `tools/iron_plan_guard.py` at lines 17, 70 and 143, including
  `test_the_pinned_paths_also_read_as_high_change_risk`.

So the entries cannot simply be deleted: the pin test is the thing that stops a
future edit from quietly widening the protected set, and it would go red. The
question for the owner is narrow — *should a retired artifact stay in the
protected set?* Keeping it is harmless (nothing can write to a file that does
not exist) but makes the protected set partly fictional, and a reader cannot
tell which entries are live. Either answer needs one commit touching the policy
and its pin test together.

## 4. Authority text — OWNER-SHAPED, not touched

- `docs/IKARUS_ARIADNE_MASTER_PLAN.md:550` (§15, *Before handing off*):
  "2. Run `python tools/iron_plan_guard.py verify`." — **the plan mandates a
  command the plan retires 35 lines later.** The retirement note was appended
  without editing §15.
- §16 step 3 instructs an amending session to export
  `DAEDALUS_IRON_PLAN_AMENDMENT=<current full plan sha256>` — an environment
  variable read by the deleted tool. See `docs/PLAN_DIGEST_EOL_FINDING.md` for
  why that step also does not say which bytes it means.
- `docs/DAEDALUS_GESAMTPLAN.md` — 7 mentions plus 2 of the env var. Program
  authority under the plan, so the same protocol applies.

A lane removing the callers while leaving §15 intact has not completed the
decision; it has chosen which half of the constitution wins. That is why the
94 workflows were repaired and these two files were not.

## 5. Records — correct, leave them

`tests/test_registry_retired_rows.py` (asserts the rows are gone and stay
gone), `daedalus/spine/effect_boundary.py` (registry comments naming commit
`79825b57` as the cause), `daedalus/lanes/checks.py:132`, `WATCHDOG_STATUS.md`,
and `docs/STATUS.md`'s own report of the dead policy entries. A system that
remembers what it retired is working; these are not rot.

## 6. Frozen research data — leave, and know why

`experiments/forest_v2/s07_bm25/` (index, measurement, taskset, tests) and
`s09_eval/taskset*.json` reference `tools/iron_plan_guard.py` as a **corpus
document**, not as a command. Repairing them would silently change a frozen
retrieval corpus and invalidate every measurement taken against it — the plan's
own rule about temporal provenance (§9.1) forbids exactly that. They stay.

`docs/architecture-map.html`, `docs/architecture-state.json` and
`funnels/today/funnel.json` are generated; they carry the name because their
inputs did on the day they ran.

## What this cost, in one line

One sentence of owner decision. Three days. 170 CI steps that could only fail,
6 dead ownership lines, 3 agents told to start by running nothing, 6 fictional
entries in the mechanical veto policy, and a constitution that mandates what it
retires.

## A note for the next automated sweep

This file deliberately carries **no** `(removed YYYY-MM-DD)` stamps. A sweep on
2026-08-25 added twelve of them here, and three landed inside material that is
quoted verbatim: the plan's retirement note, a charter's literal instruction,
and a CI step reproduced as it stood. A stamp inside a quotation does not
annotate the quotation, it falsifies it — the retirement note began reading

```text
the mechanical guard (`tools/iron_plan_guard.py (removed 2026-08-22)`, hooks, …
```

which the plan has never said. Removed. Every path in this document is already
stated to be gone; that is the subject.

The same sweep put stamps *inside runnable command lines* in
`docs/DAEDALUS_GESAMTPLAN.md` — program authority under the plan's §0 table.
Repaired by the session that had committed two of them, in `479fbf52`, under a
title worth keeping: *a removal stamp inside a code fence is a forgery, not an
annotation*.

**And three of its stamps are simply false.** [MEASURED 2026-08-25, generic
pattern `\(removed \d{4}-\d{2}-\d{2}\)` over every tracked `.md`, 42 stamped
path mentions:]

| file | line | claims removed | actually |
|---|---:|---|---|
| `docs/GATE0_EFFECT_BOUNDARY_INVENTORY.md` | 85 | `tools/audit_triage.py` | present at HEAD, tracked |
| `docs/GATE0_EFFECT_BOUNDARY_INVENTORY.md` | 86 | `tools/agent_findings.py` | present at HEAD, tracked |
| `docs/HANDOFF_2026-07-30_NIGHT.md` | 386 | `tools/agent_findings.py` | present at HEAD, tracked |

Neither file was ever deleted: `git log --diff-filter=D` returns nothing for
either, and both resolve at HEAD. The stamps were not stale, they were **wrong
when written**. So the sweep's failure direction is not over-annotation — it is
asserting a falsehood about live tooling.

**Withdrawn in `131b83b6`** — "withdraw three removal stamps that were false
when they were written" — by the session that had introduced them. Verified
here afterwards: 33 stamped path mentions remain tree-wide and all 33 name a
path that is genuinely gone; zero false stamps survive. `tools/audit_triage.py`
(321 lines) and `tools/agent_findings.py` (309 lines) are both present at HEAD.

That withdrawal is *not* an answer to the doctrine question, and it is worth
being clear why, because the distinction is the useful part:

> Dated evidence preserves what was measured at its date. It does not preserve
> an untruth a later sweep wrote into it. **A statement that was never true has
> no date to be faithful to.** — `agent-env-8e`, 2026-08-25

So removing a false stamp from evidence is not repairing evidence; it is
removing something that was never evidence. Whether *correct* annotations
belong on frozen pages at all is still open, still a live disagreement between
lanes, and still the owner's. What this episode adds is one measurement in its
favour: an annotation pass over frozen evidence has no reviewer, because the
page is not supposed to change — and the first such pass put three false
sentences into it. The bitterest landing was
`docs/GATE0_EFFECT_BOUNDARY_INVENTORY.md`, whose entire purpose is to enumerate
which effectful doors exist: the stamp denied the existence of two living doors,
on the list of doors.

### The pattern is an instrument too

A scan for this must use the generic form, and that is the smaller half of the
lesson. The larger half:

> A search pattern is itself an instrument, and it belongs calibrated against
> known positive cases before its null result means anything.

Measured, twice, on this afternoon. Both sessions first searched for the
literal `(removed 2026-08-22)` and each was blind to the other's `-08-23`
stamps. The second attempt still caught only one of the three false stamps,
because in `` `tools/audit_triage.py:248` `` the closing backtick sits after the
line number and the path-extracting regex stopped early. It found all three
only once it was calibrated — assert 3/3 against the cases already reported —
before its output was believed. Without those three reports the sweep would
have concluded "1 false stamp" and stopped, satisfied.

That is the same shape as the morning's 146-versus-3 pinned files: two agents
searching the same way confirm each other's error, and only two *different*
methods disagreeing raise an alarm. Every instrument failure recorded in this
repository today — four faces of the CRLF daemon, a docs checker reporting
clean over zero reads, a byte-pin control sample eaten by its own subject, two
scan patterns — failed in the same direction: **less coverage, reported as a
result.**

## How to reproduce

```powershell
python - <<'EOF'
import subprocess
TERMS = ["iron_plan_guard", "iron_plan_hook_runner", "enforce-iron-plan",
         "iron-plan.yml", "DAEDALUS_IRON_PLAN_AMENDMENT"]
files = [f for f in subprocess.run(["git","ls-files"],capture_output=True,text=True).stdout.split("\n") if f]
for f in files:
    try: text = open(f,"rb").read().decode("utf-8","replace")
    except OSError: continue
    hits = [(t, text.count(t)) for t in TERMS if t in text]
    if hits: print(f, hits)
EOF
```

Credit: the parallel session `agent-env-8e` asked for this list and had already
found the BM25 and corpus traces independently; `agent-env-30` established that
no Actions job starts at all, which is why §2 is careful about what it claims.
