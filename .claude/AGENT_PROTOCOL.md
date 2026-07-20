# Crew protocol — Daedalus

How the Claude crew that *builds* Daedalus is organised. Synthesised from two working
crews and from what actually failed in this repo.

> Not to be confused with the **Ikarus runtime**, whose agents are Ollama/CLI personas
> defined in `agents/*.json` and dispatched by the harness. This file is about Claude Code
> subagents in `.claude/agents/`.

## Where this came from

**Odin (NorthStar)** contributes the *gate structure*: three cost tiers, an always-on cheap
tier, and adversarial review as a structural requirement rather than a courtesy — design
critique on paper, an attack on the running result, a security veto that blocks, and a
testability owner. "Momus tells you why the idea is tired; Nemesis proves the break with a
real exploit and a failing test."

**Adam (project_tct)** contributes the *ownership model*: one router, no agent-to-agent
chat, named owners per area, and Aristaeus's rule that **every proposal carries a named
test-thermometer** — a specific runnable measurement with a before reading and an expected
after.

**This repo** contributes three rules neither crew has, each earned by a real failure
(see "Why these rules exist").

---

## The router

The main thread is the only router. It takes the request, briefs specialists, integrates
what comes back, and answers in one voice.

- **No agent-to-agent chat.** Subagents report to the router. The router summarises; it
  does not relay raw agent output to the user.
- **Brief with context, not pointers.** A subagent cannot ask a sibling what you meant.
- **The router owns the verdict.** If a specialist's work fails a gate, that is the
  router's problem to resolve, not the specialist's to argue.

## Tiers

Cheap work is delegated *by default*, so the expensive crew is reserved for judgment.

### Tier 0 — the always-on delegates (haiku)

Dispatched by default for their beat rather than done inline. They are cheap; using them
is the point.

| agent | beat |
|---|---|
| **argus** | scout — "where is X?", sweeps, find-usages, verification reads. Use instead of an inline grep sweep. |
| **hermes** | scribe — mechanical, precisely-specified writes: boilerplate, repeated edits, renames, fixtures. |
| **mnemosyne** | chronicler — updates HANDOFF/docs/status in the *same beat* as a structural change, and stamps provenance on every number. |
| **metron** | sentinel — pre-runs the full gate suite before any review or commit and reports raw output. Refuses to time anything under load. |

### Tier 1 — implementation (sonnet)

`core-dev` (Daedalus, harness core) · `extension-dev` (Icarus, VS Code surface) ·
`test-dev` (Talos, the suite) · `docs-dev` (Clio) · `provider-researcher` (Pythia)

### Tier 2 — judgment (opus)

`safety-dev` (Minos — **owns** the fail-closed core) · `cerberus` (**reviews** it; CRITICAL
blocks) · `momus` (design critique on paper) · `qa-critic` (Nemesis — attacks the
running result) · `aristaeus` (read-only structure distiller) · `orchestration-dev` (Theseus) ·
`iris` (UI/UX)

Minos writes the fence and Cerberus vetoes breaches of it. That separation is deliberate:
an owner reviewing their own work is the anti-pattern this crew exists to avoid.

---

## The gates

**Every consequential change** — anything touching correctness, safety, egress, money, or
the shape of a published output — passes these. Order matters: two are cheap and happen
before code exists.

1. **Momus — on paper, before implementation.** Why is this idea tired? What is the failure
   mode nobody costed? A blocking objection stops the work until answered.
2. **Týr (`test-dev`) — testability.** How will we know it worked? Named thermometer.
3. **Nemesis (`qa-critic`) — attacks the running result.** Not a read-through: *run it*.
4. **Cerberus — security and egress.** A **CRITICAL blocks. No override.**
5. **Metron — the gate suite**, with raw output, before any commit.

**Dissent is documented, never averaged away.** If Momus objected and was overruled, the
objection goes in the commit message, not into a consensus mush.

### The test-thermometer rule (from Adam's crew)

A proposal without a **named, runnable** measurement — with a BEFORE reading and an
EXPECTED AFTER — is not a proposal. "Run the tests" is not a thermometer; `1/21 shapes
named → 21/21` is.

This is not ceremony. It is the reason the C/C++ naming work produced a real before/after
table instead of a claim.

---

## Why these rules exist

Each of the three below cost real time in this repo. They are not general best practice;
they are scar tissue.

### 1. Measurement validity is a gate, not a habit

**Never report a performance number measured under load.** Before timing anything, check
the box is quiet. State warm-vs-cold cache. Compare like for like.

In one session this rule was broken three times and produced three wrong numbers that were
reported as fact:

| claimed | actual | cause |
|---|---|---|
| 1.47× speedup | **0.99×** | baseline measured while 23 agent processes ran |
| 171.0s full scan | **86.5s** | same, contended |
| 499 files corrupted | **66** | measured a code path Python does not take |

A benchmark whose validity was not checked is not evidence. `metron` re-runs any number that
is going to be reported.

### 2. Provenance: MEASURED / INHERITED / ASSUMED

Every number in a handoff, doc, or commit message carries where it came from.

The failure this prevents: a handoff written by a *previous session of the same model* was
later cited as independent evidence, with its own hedge ("re-check this before spending")
silently dropped. Inherited context stops looking like a claim and starts looking like a
fact — and your own prior output is the most invisible kind of inherited context there is.

`mnemosyne` stamps these. If a number cannot be attributed, it is ASSUMED, and it may not
carry an argument on its own.

### 3. Parallel writers get isolation

Two agents writing the same checkout will collide. So will an agent and a `git stash`.

**Never `git stash`, checkout, or rebase a shared working tree while any agent may be
writing.** Use `git worktree add` (or the Agent tool's `isolation: "worktree"`).

The failure: a stash of `clones.py` during an active round left the tree transiently
un-importable — `clones.py` reverted while `index.py` still imported its symbols — and a
Nemesis agent independently reported it as a defect. It cost a reconstruction and a
confusing verification run.

---

## Standing orders

- **Under-report rather than guess.** In this product a fabricated clone cluster — telling
  a user that unrelated code is duplicated — is worse than a missed one. When a judgement
  call is genuinely ambiguous, return `<anonymous>`, drop the edge, exclude the language.
- **Never silently exclude or truncate.** If something was withheld, say so in the output:
  counts, the rule that did it, and a bounded sample. A report that quietly shrank is
  indistinguishable from a codebase that got cleaner.
- **Determinism is load-bearing.** The index must be byte-identical across
  `PYTHONHASHSEED`. Iterate `sorted(...)` anywhere set or dict order can reach output.
- **Verify the claim, don't inherit it.** If a brief hands you a number, check it. Briefs in
  this repo have been wrong (a stale 415-test baseline; a stale 79.0% eval figure) and the
  agents that checked were right to correct the router.
- **A test that passes because the fixture is inert is worse than no test.** Assert that the
  thing you are guarding against could actually have happened.
- **Additive endpoints only.** `/api/dashboard` shape is frozen by `tests/test_ui_contract.py`.
- **BYOK.** The platform never holds a paid API key.

## Delegation budget

A Tier-1 or Tier-2 agent may run **up to two Tier-0 delegates at once**. Beyond that, the
router fans out, so results land in one place and nothing writes the same file twice.
