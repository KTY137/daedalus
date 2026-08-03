# ADR-017: The Assistant Layer — Upstream Reconsidered

## Status

Accepted, 2026-07-29, with a split decision:

- **Hermes Agent (NousResearch): REJECTED for adoption.** Not rejected as a
  project — it is real, healthy, and better than what this repo has in five
  named places. Rejected because what it would cost here is a second
  everything, on a machine where its stated security boundary does not exist.
- **Agent Skills (`SKILL.md`) open standard: ACCEPTED as a FORMAT, narrowly.**
  Data in, no process, no socket, no dependency, no bundled-script execution.

This ADR is written against the six bars ADR-002 set for reopening the
question: *exact project, version, license, threat model, integration seam,
replacement cost.* All six are answered below for both candidates, and for the
two serious alternatives that were checked and set aside.

## Provenance of every claim in this document

This repo has been burned by confident prose with no control behind it, so
every fact below is tagged:

- **MEASURED** — a command was run on this box on 2026-07-29 and its output is
  quoted.
- **FETCHED** — read off a named URL on 2026-07-29. Upstream facts age; a
  FETCHED version string is a snapshot, not a guarantee, and must be re-pinned
  before anyone acts on this ADR.
- **INHERITED** — taken from `docs/archive/2026-07/HANDOFF.md` or another in-repo document and
  not independently re-verified here.

Line numbers in this file were MEASURED on 2026-07-29 while sixteen agents were
editing in parallel. They drift. The symbol names do not.

## Context

ADR-002 recorded that the code labeled "Hermes" was never an integration:
*"an independent, unauthenticated WebSocket server that bypassed the scheduler
and duplicated event types."* ADR-010 §1 then reserved the name for the real
upstream. The question left open was whether the real upstream is worth having.

The honest starting point is that this repo's assistant layer is mostly absent,
and the absence is measurable. MEASURED:

| capability | state in this repo | evidence |
| --- | --- | --- |
| multi-turn agent loop | **does not exist** | `daedalus/ikarus_os.py` `_chat()` calls `_llm(provider, message, model, effort, project)` — the signature carries no history. Every path is single-shot. |
| chat sessions | **do not exist** | no server-side transcript in `daedalus/web_api.py`; `memstore.py` / `spine/ledger.py` / `council/bus.py` are decision and intent ledgers, not conversation |
| long-term memory / FTS5 | **does not exist** | no FTS5 anywhere in code; the only mention in the tree is `docs/adrs/002-hermes-upstream.md:7` describing what Hermes *would* provide. `daedalus/compaction.py` implements rolling summarisation and is imported only by `tests/test_cascade.py` |
| skills | **planned, unbuilt** | `daedalus/control_plane.py` — `"skills_plugins": {"status": "planned"}` |
| plugins / MCP client | **config-reading only** | `control_plane.py` reads `.mcp.json` and lists `mcpServers`; `council/vendors.py` passes `--strict-mcp-config` to *deny* MCP for council seats. Nothing in the repo speaks the protocol |

So the case for adopting an upstream is genuinely strong, and this ADR must not
pretend otherwise. Hermes would not duplicate five things — it would **fill**
them. The argument below is therefore not "we already have it". It is about
cost, and about a boundary that is absent on this specific machine.

---

## Candidate 1 — Hermes Agent (NousResearch). REJECTED.

### Bar 1: exact project

`https://github.com/NousResearch/hermes-agent` — "The agent that grows with
you". FETCHED. This is the project ADR-010 §1 reserved the name for. The thing
this repo deleted was never a fork, a vendored copy, or a client of it.

Sibling project, relevant to Thread 2 and discussed separately below:
`https://github.com/NousResearch/hermes-agent-self-evolution` (DSPy + GEPA).

### Bar 2: version

**v0.19.0 (2026.7.20), "The Quicksilver Release", released 2026-07-20.**
FETCHED from the releases page. Preceding: v0.18.2 (2026-07-08), v0.18.1
(2026-07-08), v0.18.0 (2026-07-01, "The Judgment Release"), v0.17.0
(2026-06-19). Python core with Node components. FETCHED.

Release cadence is roughly monthly with point releases inside a week. That is a
fact with a cost attached — see Bar 6.

### Bar 3: license

**MIT.** FETCHED (`LICENSE` at repo root; corroborated by the release listing).
No copyleft obligation, no field-of-use restriction. **The license is not the
problem and was never going to be.**

### Bar 4: what it would replace here

Nothing. It would **add**, against the five gaps in the Context table:

- agent loop with tool calling → replaces the absent loop at `ikarus_os._chat`
- session store + "FTS5 session search with LLM summarization for cross-session
  recall" (FETCHED) → replaces nothing; fills a hole
- "agent-curated memory with periodic nudges" (FETCHED) → fills a hole
- 166 tracked skills, agentskills.io-compatible (FETCHED) → fills
  `control_plane.py`'s `"planned"`
- MCP client + 40+ tools (FETCHED) → fills the absent client

**And it would add four things this repo already has, in a second copy:**

| Hermes provides | this repo already has | consequence |
| --- | --- | --- |
| gateway daemon + cron scheduler (FETCHED, `windows-native.md` feature list) | `daedalus/kairos/scheduler.py` | two schedulers |
| "durable delivery ledger … finished responses survive a gateway crash" (FETCHED, v0.19.0 notes) | `daedalus/spine/ledger.py`, intent-recorded-before-effect | two ledgers, two crash-recovery models |
| dangerous-command approval + deny rules | `daedalus/sensitivity.py` `slice_egress_rule` / `secret_floor_rule` / `path_write_blocked` | two safety predicates |
| session/transcript persistence | `council/bus.py` hash-chained transcript, `memstore.py` hash-chained ledger | two transcript formats, one tamper-evident |

**This is the exact shape ADR-002 rejected — "bypassed the scheduler and
duplicated event types" — at a larger scale and with an upstream nobody here
controls.** And it is the shape that already cost this repo real money twice in
the last twenty-four hours. INHERITED from `docs/archive/2026-07/HANDOFF.md`: the three Momus
CRITICALs were closed in `daedalus/council/` and **live** in
`runs/council/room.py`, a second implementation of the same council that never
inherited the fixes — including a live RCE. The same RCE was then found in a
**third** copy. The handoff's own stated lesson is *"a fix that lives in one of
two implementations is not a closed class."* Adopting a second scheduler, a
second ledger, and a second safety predicate is that lesson declined in writing.

### Bar 5: threat model

**This bar decides the ADR, and Hermes states its own model clearly enough that
I can state it too — which is the standard I am held to and I am glad to meet.**

Hermes's documented boundary, quoted verbatim (FETCHED,
`website/docs/user-guide/security.md`):

> "Deny rules are a guardrail against an honest-but-wrong agent, the same
> threat model as the dangerous-pattern detector. They are not a sandbox
> against a deliberately adversarial process."

> "The denylist reduces accidental damage and gives models a clear stop signal;
> it does not sandbox a hostile or compromised agent."

The real boundary is therefore the container:

> Container backends "skip dangerous command checks entirely because the
> container itself is the security boundary."

And the local backend, explicitly:

> the local backend "runs on host", suitable only for "development, trusted
> users".

**Now apply that to this box.** MEASURED, `daedalus/spine/containment.py`
docstring, the module's own stated limits:

```
  * CONFIDENTIALITY: NONE. MIC is a write-UP barrier. A contained candidate may
    read the whole checkout and the user profile.
  * NETWORK: unrestricted. A Low process still has a network stack.
  * NAMED PIPES: UNMEASURED.
```

This machine is win32. Hermes's native-Windows guide (FETCHED,
`website/docs/user-guide/windows-native.md`) enumerates what runs natively —
CLI, TUI, gateway, messaging platforms, cron scheduler, browser tool, MCP
stdio+HTTP, local models, web dashboard — and **does not list a container
backend**. The installer's supported targets are Linux, macOS, WSL2, Android
(Termux) (FETCHED).

So on this specific machine, adopting Hermes means adopting an agent loop whose
documented security boundary — the container — is not the thing that would be
running, and whose fallback guard its own docs describe as "not a sandbox".
Meanwhile this repo's only *measured* containment provides no confidentiality
and no network bound, and is not wired to anything (see ADR-016 P1).
**Two boundaries, and their intersection on win32 is approximately the
approval prompt.** That is not a threat model I would sign.

**A second, additive hazard: the gateway is a new UNTRUSTED INPUT channel.**
Hermes's gateway takes instructions from Telegram, Discord, Slack, WhatsApp,
Signal and email (FETCHED). Upstream's own open issue is the cleanest statement
of the risk — `NousResearch/hermes-agent` issue **#4281**, *"Enforce sandboxed
execution for messaging platform sessions"*, filed 2026-03-31, **open,
unassigned, P2** (FETCHED):

> "Once a user is authorized, the agent executes LLM-generated commands with
> the host user's full privileges."

Everything this repo has built in the safety direction is about what **leaves**
— `lane_for_host`, `slice_egress_rule`, the secret floor. There is no fence
here for what **enters**, because until now nothing entered except a human at a
terminal. A messaging gateway inverts that, and it would land on a repo whose
egress fence was itself bypassed for a day by an environment variable
(INHERITED, `docs/archive/2026-07/HANDOFF.md`: `OLLAMA_HOST` + a lane chosen from the provider
name). Adding an inbound channel before the outbound one has been stable for a
week is the wrong order.

**Third: the install seam is trust-on-first-use remote code execution.**
FETCHED: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`,
or on Windows `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`.
That is a script fetched over the network and executed unreviewed, at the
privilege of the user who owns this checkout and its provider credentials.
`docs/adrs/007-root-of-trust.md` names "signed policy/evaluator identities" as
an acceptance condition and records its own status as **"Proposed; not
enforced"** — so this repo currently has no mechanism that would even notice.
This is a solvable objection (pin a release, verify a hash, vendor it) and it
is listed as third because it is the weakest of the three. It is not the reason
for the rejection; it is a cost.

### Bar 6: replacement cost

Two costs, and the second is the decisive one.

**(a) Integration and maintenance.** MEASURED: 2066 tests collected on this
tree at the time of writing (`python -m pytest --collect-only -q`; a parallel
survey twenty minutes earlier read 2063 — the tree is moving under us, which is
itself worth recording). Hermes ships ~monthly. Every adopted seam is a seam to
re-verify at each bump, and the seams that matter are the four duplicated ones
in Bar 4, each of which is a *safety* seam. This is real but ordinary cost.

**(b) The decisive one: Hermes does not touch this repo's actual bottleneck.**
The three things measured tonight as blocking unattended autonomy are, per
ADR-016:

1. write containment exists and is wired to **nothing** — MEASURED,
   `grep -rn "spine.containment" --include=*.py . | grep -v "^./tests/"` returns
   no output;
2. the fitness signal is `pytest`, and INHERITED from `docs/archive/2026-07/HANDOFF.md`: *"Three
   times in one day a fully green suite sat over a live escape"*;
3. there is no spend or iteration bound — MEASURED,
   `grep -rn "budget_usd\|max_usd\|spend_cap\|MAX_SPEND\|daily_budget\|cost_cap"
   --include=*.py daedalus/` returns no output.

**Hermes fixes none of those three.** It supplies conversation, memory and
skills — the layer a user *sees* — while the layer that decides whether an
unattended loop may run at all is untouched. Paying an integration cost for
capability that does not move the blocking constraint is the wrong purchase
this week, however good the capability is.

### Decision on Candidate 1

**Rejected for adoption. Not rejected as a source of design.** Specifically
worth stealing, and free to steal:

- Hermes separates *runtime state* from *cross-session knowledge memory*. This
  repo currently has neither and would otherwise conflate them.
- `hermes-agent-self-evolution` (MIT, FETCHED) evolves skills and prompts with
  DSPy + GEPA and states its promotion rule as **"All changes go through human
  review, never direct commit"**, with variants landing as a PR against
  hermes-agent. That is independent, external corroboration of this repo's own
  rule — `daedalus improve` has no `--apply` (MEASURED: `--help` offers
  `--once --dry-run --limit --eval --hotspots --live --repo-root
  --artifact-dir --keep-worktree --forget --stale-inventory --verbose --json`
  and nothing else). A second self-improving agent project, built by people
  with every incentive to automate promotion, kept the human in the loop. Cite
  it; do not import it.
- Its skill format is the agentskills.io standard, which is Candidate 2.

**Reopening condition.** This rejection is about this machine and this week,
and it should be cheap to revisit. Reopen when *both* hold: (i) ADR-016 P1 and
P2 are green — a candidate process runs inside a boundary that bounds writes
**and** egress, so a foreign agent loop would be running inside something; and
(ii) a container backend is available and measured on this box. At that point
the Bar 5 objection evaporates and only the duplication cost remains, which is
an ordinary engineering trade rather than a safety one.

---

## Candidate 2 — Agent Skills (`SKILL.md`). ACCEPTED, narrowly, as a format.

### Bar 1: exact project

The Agent Skills specification, `https://github.com/agentskills/agentskills`,
published at agentskills.io. Originated at Anthropic (Claude Code, late 2025)
and released as an open standard; a spec copy also lives at
`anthropics/skills/spec/agent-skills-spec.md`. FETCHED.

### Bar 2: version

**NOT PINNED, and this is an open item, not a rounding error.** FETCHED sources
describe the standard as published in December 2025 and actively maintained,
but I could not read a semantic version string off a primary source on
2026-07-29. **Adoption is conditional on pinning an exact spec revision (a tag
or a commit sha) in the implementing commit.** An unpinned "standard" is a
moving target wearing a stable name, and this repo already has a whole ADR
about names that mean two things.

### Bar 3: license

**Code Apache-2.0; documentation CC-BY-4.0.** FETCHED. Both compatible with
this repo. Only the *format* is being adopted, so the practical obligation is
attribution in the parser's docstring.

### Bar 4: what it would replace here

`daedalus/control_plane.py` — `"skills_plugins": {"status": "planned", "note":
"Will be linked to agent profiles after plugin discovery is wired."}`
(MEASURED). It replaces an unmade decision, not code. And the format is already
physically present in this tree: `.claude/skills/council/SKILL.md` and
`.claude/skills/room/` exist because Claude Code loads them. Adopting the
standard means the harness can read what the tree already contains, instead of
inventing a second skill format next to it — which is, again, the ADR-002
defect.

### Bar 5: threat model

**Stateable in full, which is precisely why this one clears the bar and Hermes
does not.**

A skill is a directory containing `SKILL.md` — YAML frontmatter (name,
description) plus markdown instructions — and *optionally* bundled scripts,
templates and reference files. Two hazards, and both are closable by decision
rather than by mechanism:

1. **The body is untrusted prompt content.** A skill's instructions reach a
   model's context. A hostile or merely wrong skill is prompt injection with a
   filename. Mitigation: skill text is treated exactly as this repo already
   treats other untrusted text — it is *content*, never *authority*. It may not
   name a provider, may not select a lane, and may not widen an egress
   decision. `sensitivity.lane_for_host` answers "where do the bytes go" from
   the host and nothing else; a skill must not become a second input to that
   question. This is enforceable by a test that asserts the loader's output
   type carries no lane, provider or path-policy field.

2. **Bundled scripts are the entire remaining attack surface, and this repo
   declines them.** Adoption is of the *metadata and instruction* half only.
   The loader parses frontmatter and body; it does not execute, import, or
   place on `PATH` anything in a skill directory. This repo already has a tool
   dispatch path it controls (`daedalus/file_bridge.py`: `enqueue` →
   `watch` → `process_request` → archive, exercised end to end by
   `tools/system_check.py`'s `bridge.enqueue_watch_report_archive` check), so
   there is no functional reason to execute a stranger's script.

With scripts excluded, the adopted artifact is **inert text**. No process, no
socket, no network call, no new dependency, no new transport. Compare ADR-002's
rejection sentence — "an independent, unauthenticated WebSocket server" — and
note that a text format cannot be any of those four words.

### Bar 6: replacement cost

**A parser and its tests; deletable in one commit.** No runtime dependency, no
vendored code, no upstream release cadence to track (the format is stable by
construction; that is what a standard is for). If the standard dies, the
already-written `SKILL.md` files remain readable markdown.

### Decision on Candidate 2

**Accepted as a data format, conditional on three things**, all of which must
be true in the commit that implements it:

1. the spec revision is pinned by tag or sha in the loader's docstring;
2. the loader executes nothing from a skill directory, and a test goes red if
   `subprocess` is so much as named in the loader module — the same structural
   pattern `daedalus/spine/picker.py` already uses to make "the picker cannot
   apply a patch" true rather than promised;
3. the loader's return type carries no lane, provider, or path-policy field, so
   a skill cannot participate in a safety decision.

**Note the honest ordering: this is not urgent.** It unblocks nothing in
ADR-016. It is listed here because the research was done and the answer is
cheap and durable, not because it should be done next.

---

## Alternatives checked and set aside

Both are serious, both are better-licensed for embedding than Hermes, and both
lose for the same Bar 5 reason on this machine.

**goose** — Block, moved to the Linux Foundation's Agentic AI Foundation
(2026-04-07), **Apache-2.0**, Rust, ~51.3k stars, 500+ contributors (FETCHED).
Ships `goose` (core library: agents, providers, config, session management,
OAuth, security, telemetry), `goose-cli`, `goose-server` (`goosed`, REST +
WebSocket API), `goose-mcp`, `goose-acp`. Genuinely embeddable — the crate
boundary is a real integration seam, which is more than Hermes offers, and
Apache-2.0 + foundation stewardship is a better governance story than a single
lab. **Set aside for two reasons.** (i) Adopting it means adopting a Rust
toolchain and a second process into a stdlib-Python repo whose acceptance
harness (`tools/system_check.py`) clones the working tree and runs everything
through `python -m`; that is a large, real cost with no offsetting safety gain.
(ii) `goose-server` is a REST **and WebSocket** API. Standing up a second
network transport in the repo that deleted "an independent, unauthenticated
WebSocket server" requires its authentication model to be stated and measured
first — and I did not measure it, so under this ADR's own rule I must not
recommend it. **That is a gap in my research, named rather than papered over.**

**Letta** (formerly MemGPT) — **Apache-2.0**, ~23k stars, self-hostable; the
server exposes a REST API on port 8283 "with password authentication enabled by
default" (FETCHED). Solves exactly the memory gap this repo has, and is the
narrowest-scoped of the three. **Set aside** because it is a long-lived
stateful *service* — a second daemon holding a second store of what the
assistant knows, alongside `spine/ledger.py`, `memstore.py` and
`council/bus.py`. Memory is where this repo's egress fence has the most to lose:
distilled project context is precisely what `slice_egress_rule` withholds, and
a memory service is a component whose entire job is to retain and re-emit that
content. Adopting it before ADR-016 P2 (a boundary that bounds egress) would
put the most sensitive corpus in the repo behind the least-examined new
component. Revisit for the memory gap specifically, after P2, and prefer the
embedded-library shape over the server shape if one exists.

---

## Consequences

- The name "Hermes" stays reserved (ADR-010 §1) and stays unused. `kadmos`
  remains the crew scribe. MEASURED: 48 occurrences of "hermes" across 11
  files, **all documentation, zero code, zero config**. Two of those are stale
  and should be corrected by whoever owns those files:
  `docs/architecture-narrative.md` claims "VERIFIED: `daedalus/hermes/` still
  exists on disk containing only `__pycache__`" — MEASURED: that directory does
  not exist. `docs/FEATURE_INVENTORY.json` carries the same stale claim. (Not
  corrected here: those files are outside this ADR's ownership.)
- The assistant layer is **built here**, and the reason is on the record: not
  because building is cheaper, but because the five capabilities an upstream
  would supply are not what is blocking, and the boundary an upstream assumes
  does not exist on this machine.
- The Agent Skills format is accepted for skills, with the three conditions
  above, and is explicitly **not** scheduled ahead of ADR-016's preconditions.
- **This ADR expires.** Its Bar 5 argument is a fact about win32 containment on
  2026-07-29 and about ADR-016 P1/P2 being red. When those go green, re-read
  it; the rejection may no longer follow from its own evidence.
