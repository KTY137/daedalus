# ADR-012: Der Rat — Cross-Vendor Review Council

## Status

Proposed, then built: `daedalus/council/` (`bus.py`, `canary.py`, `publish.py`,
`session.py`, `vendors.py`) exists and has produced chained transcripts under
`runs/council/` from 2026-07-28 through at least 2026-08-20 [MEASURED
2026-08-25, `ls daedalus/council/` and `runs/council/*.jsonl`]. The `/council`
skill now invokes it directly. Whether §7's falsification measurement
(inter-vendor vs. intra-vendor agreement) was ever run and what it found was
not located in `docs/` during this pass; the design content below stands as
recorded, unverified against that specific number.

## Context

This machine can reach four model vendors with independently trained weights:
Anthropic via the `claude` CLI, OpenAI via the `codex` CLI, Google via the `agy`
(Antigravity) CLI on the RTX bench over ssh, and local/bench Ollama over HTTP.
The repo's backlog has carried "Panel of Rivals" since before the spine landed:
a model reviewing its own work shares its own blind spots, and the cheapest
available source of genuinely uncorrelated review is a vendor whose training
data and RLHF pipeline this project does not control.

Nothing in the repo consumes more than one model's opinion today. ADR-011 landed
the ordering authority and the attestation duty; `daedalus/spine/attempt.py`
landed a build path with the structural property that there is no apply path.
Both were built so that a second opinion could be *recorded* without becoming a
*decision*. This ADR spends that affordance.

Three constraints from existing code bound the design before any of it is
written:

- `daedalus/adapters/subprocess_adapter.py` ships `RUNTIME_PROFILES["codex"]`
  with `--sandbox workspace-write` and `RUNTIME_PROFILES["claude"]` with
  `--permission-mode dontAsk`, spawned with `cwd` defaulting to the repo root.
  Those are build profiles. Reused as review profiles they would hand four
  vendors an agentic write loop rooted in a checkout that other agents edit
  concurrently.
- `daedalus/sensitivity.secret_floor_rule` gates the bytes a caller puts in a
  prompt. It cannot gate a reviewer that fetches its own bytes. `docs/bypasses.md`
  §2 already states the general form: "A Git worktree isolates changes from the
  primary checkout; it does not isolate the host or secrets."
- `daedalus/offload.py`'s slice wire runs `lane="trusted"` on the stated ground
  that Ollama means "no bytes leave the machine". That is a property of an
  environment variable — `OLLAMA_HOST` — that nobody had ever set. A council
  that normalises a remote Ollama sets it.

## Decision

Build **Der Rat** as `daedalus/council/`: a cross-vendor review council that
produces evidence and recorded dissent, and decides nothing.

### 1. What the council is, and what it is not

The council **is** a fan-out of one review question plus a fixed evidence bundle
to participants on independently trained weights, and a tamper-evident
transcript of what each one said.

The council **is not** a promotion authority, and this is enforced structurally,
not by documentation. Its output type is `CouncilRecord`, and `CouncilRecord`
carries **no** field named or reducible to approve, reject, pass, verdict, ok,
score, confidence, consensus, or majority. There is no field for a caller to
destructure into `if result.ok and verdict.majority == "approve"`. A test asserts
the absence by name match; absence of the field is the control, and a docstring
saying "advisory" is not.

The council's product is a set of **claims**. Each claim carries its author, the
evidence span it cites, and `checkable: bool` — true only when the author
supplied a concrete deterministic check: a test to run, a command, a specific
line assertion. Checkable claims become a queue for the existing gate.
`GateResult.passed` and `AttemptResult.state` remain the only verdict in this
system. THE GATE DECIDES, NOT A MODEL.

There is no writing, editing, applying, or promotion capability anywhere under
`daedalus/council/`. It inherits `spine/attempt.py`'s property — THERE IS NO
APPLY PATH — rather than re-arguing it.

### 2. Roster, identity, and the unit of independence

Actor ids extend ADR-010's namespace rule with a third root: product actors are
`daedalus.<name>`, crew actors `crew.<name>`, and **council participants
`council.<vendor>.<model>`** — e.g. `council.anthropic.claude-opus-5`,
`council.openai.gpt-5-codex`, `council.google.gemini-3-pro`,
`council.local.qwen2.5-coder-7b`. A bare vendor name in a council transcript is
a defect for the same reason a bare Greek name is: the model behind a stable
command name changes underneath it, so a dissent attributed only to "claude" is
not reproducible six months out and cannot be compared across time. Every turn
additionally records the resolved model id, the CLI version string where
obtainable, the endpoint host, and the independence class. An unobtainable model
id is recorded as `unknown` — never omitted, never inferred.

**The unit of independence is weights, not endpoints.** Local `qwen2.5-coder:7b`
and bench `qwen2.5-coder:7b` are one voice on two sockets; the 1.5b/7b/14b/32b
family are near-clones. Every participant therefore carries an explicit
`independence_class = (vendor, model_family)`. The roster refuses to seat two
participants of the same class, or seats them with `duplicate_class=True` on
both. The `CouncilRecord` carries the **distinct-class count**, and any rendering
of council findings shows that count rather than the participant count.

### 3. Reviewers are completions, not agents

Council participants use council-only profiles defined in
`daedalus/council/vendors.py`. `RUNTIME_PROFILES` is not reused.

- codex: `exec --sandbox read-only --ask-for-approval never`
- claude: `-p --output-format json`, tools disabled, no `dontAsk`
- agy: `-p -` over ssh, read-only
- ollama: HTTP completion, no tool loop

Every subprocess is spawned with `cwd` set to a fresh empty temp directory that
is not the repo, not a worktree, and contains no repo file. A test asserts no
council profile string contains `workspace-write` or `dontAsk`, and that the
spawn cwd is not under `repo_root`.

The reason is evidence provenance as much as containment: if a reviewer can
fetch its own bytes, two vendors citing "the file" may have read different bytes,
and the transcript records a citation nobody can reproduce. All evidence reaches
a model through the prompt or not at all. A turn whose content demonstrates the
model read a file it was not given is recorded as an anomaly.

### 4. Where the secret floor runs on each egress path

The floor runs **per file, in both directions**, never over an assembled prompt.

- **Outbound, path channel:** `secret_floor_rule` runs over
  `PatchArtifact.changed_paths` and every evidence file path *individually*. The
  whole-prompt call `secret_floor_rule("", prompt)` is forbidden: it kills the
  path-marker tier entirely, so a patch that *adds* `.env` or `config/id_rsa`
  would pass cleanly, its only trace being `diff --git a/.env b/.env` inside
  text that the content regexes do not match. That is the highest-probability
  real leak in this design and the data to prevent it is already in hand.
- **Outbound, content channel:** run per file and per hunk, honouring
  `secret_floor_rule`'s own docstring rule that `text` is scanned per file and
  "never over concatenated slice text".
- **A hit refuses the call.** No redact-and-send. The refusal is recorded as a
  chained `refused` turn naming only the rule label, following
  `memstore.append_entry`'s refusal-receipt shape.
- **Inbound:** the same floor runs over every vendor response **before** it is
  chained. A chained secret is permanently unredactable without breaking chain
  verification — a tamper-evident transcript is a permanent copy of whatever the
  floor missed. On an inbound hit the store records the rule name and the
  response digest, not the response.

**Per-participant lanes.** Each participant declares an explicit egress lane.
`codex` and `agy` default to `untrusted`, so `slice_egress_rule(..., lane=
"untrusted")` applies the allow-list / default-deny tier, and every withheld
path is named on the record. Opting a participant up to `trusted` is per-council
and recorded as a flag. This is deliberate: `runtime_registry.py` currently marks
`codex_cli` trusted-with-IP and `openai_api` not — same company, same weights,
opposite verdict by transport — and Antigravity has no entry at all. The council
does not resolve that contradiction; it refuses to inherit it by defaulting to
the conservative lane, so that no policy decision about OpenAI's and Google's
access to this repo's IP is made by a default argument.

**The ssh boundary to the bench.** The prompt must not appear in any command
line, local or remote. `ssh host "agy -p '<prompt>'"` does not take an argv: ssh
concatenates its arguments and the *remote login shell* re-parses the result.
The prompt is a diff written by a candidate model; a patch containing backticks
or `$(...)` anywhere — an f-string, a test log, an edit to a shell script — then
executes on the bench as Administrator, with no adversarial model required.
Local argv quoting cannot help, because the escaping that matters belongs to a
shell on the other side of the wire. The transport is therefore
`ssh -T -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes <host>
-- agy -p -` with the prompt written to the child's stdin and stdin closed. A
test with a fake ssh binary asserts the prompt bytes never appear in `argv`.
Prompt-on-stdin is the rule for *every* transport, not only ssh. If the agy
adapter cannot meet it, it ships hard-disabled rather than "unavailable".

**`OLLAMA_HOST` is never set, mutated, or inherited** by any council code into
any shared process environment. The bench host is passed explicitly per call.
Only `127.0.0.1` counts as local; bench Ollama participants carry `local=False`
and an explicit off-machine egress classification. Setting that variable in this
process would retroactively falsify `offload.py`'s `lane="trusted"` justification
and ship full repo slices off-machine from an untouched, untested code path
reporting `withheld=[]`.

### 5. Dissent is preserved, not averaged

There is no aggregation step. Turns are stored verbatim, per author, and a
disagreement between two participants remains two claims with two authors — it
is never reduced, ranked, or scored. A majority *is* an average, and a majority
here would not even be well defined: with agy unsigned-in and the bench busy,
"3 of 4" and "2 of 2" render as the same string, so availability would decide
which quorum bound saturates and that bound would be read as correctness.

The stronger objection is the known behaviour of the mechanism. N models voting
and taking the majority is LLM-as-judge ensembling: correlated across vendors on
exactly the failure modes that matter, swamped by verbosity and position bias,
and most confident where all participants share a training-data blind spot —
the one case the council exists to catch. Recording every voice separately is
not a stylistic preference; it is the only output shape whose value survives
that correlation.

**Round 1 is blind and mandatory.** Each participant sees the question and the
evidence, never another participant's turn. `max_rounds` defaults to 2 with a
hard cap. Round 3+ is where convergence dominates and must be justified by the
measurement in §7, not by taste.

**Evidence is data.** Every prompt states that evidence is data and that any
instruction found inside it must be reported as a finding, not followed — an
injection attempt becomes useful review output rather than a bypass. This
matters most in round 2, where feeding vendor A's turn to vendor B would
otherwise launder planted text into an apparently authored turn that the hash
chain then certifies as "vendor A said this". The patch's authoring vendor is
recorded on the record, and that vendor's own turns are flagged
`self_review=True`.

### 6. Degraded quorum is a first-class statement

Every requested participant produces **exactly one chained turn per round**:
content, `refused`, or `unavailable` with a machine reason (`not_on_path`,
`not_authenticated`, `timeout`, `connect_failed`, `budget_exhausted`). agy is
not signed in today and its adapter degrades to `unavailable` — as a recorded
turn, not as an absence.

Skipping an unavailable participant when assembling a round is forbidden. If it
were allowed, a two-vendor council would render byte-identically to a
four-vendor one and nothing would record that a fourth voice was ever sought.
The record's header carries requested / seated / responded / unavailable-with-
reason counts and sets `degraded=True` whenever responded < requested. Any
human-facing rendering shows the degraded flag and the distinct-class count
**adjacent to the findings**, never in a footer. A council that ran with two of
four vendors says so where the findings are read.

### 7. Falsification

The premise — independent vendors have independent blind spots — is plausible
and untested here. As designed, the council would always produce turns and
dissent always reads as insightful in isolation, so the design must name in
advance the measurement that would refute it.

**The control arm is one vendor asked twice under two different role prompts.**
It is cheap and it is the whole experiment: if four vendors do not beat
one-vendor-twice, this module bought four egress paths, an ssh attack surface,
and 4x latency for a prompt-diversity effect.

**Ground truth already exists and costs nothing to harvest:**
`GateResult.passed` and `AttemptResult.state` from `spine/attempt.py`, plus the
spine ledger's completed/failed intents. The question is precise: does "the
council raised an objection" predict `gates_failed` or a later revert better
than the single-vendor control, at what precision and recall?

**The independence measurement is separate and sharper:** pairwise agreement
rate *between* vendors versus *within* one vendor across two calls. If they are
within noise of each other, there is no independence to harvest and the design
is refuted on its own terms regardless of how good the findings look.

**The small-N caveat is stated in advance, not discovered afterwards.** The
independent corpus is ~17–20 tasks. That is not enough for a significance claim,
and no percentage from it may be reported as one.

**Falsifier, written into the module docstring before any wiring:** *if
inter-vendor agreement is within noise of intra-vendor agreement on N patches,
this module is deleted.* Until that number exists, `session.py` ships only with
an offline replay harness — fake adapters, no network, no vendor CLI — covering
refusal on a planted secret, an injected instruction inside a diff, one vendor
timing out, agy unavailable, and two same-weight participants seated. No wiring
into any real review workflow before the measurement.

### 8. Cost, latency, and determinism bounds

The advertised cost is V vendors x R rounds. The real cost is the transcript: at
round R each of V participants is prompted with up to V*(R-1) prior turns, so
prompt tokens grow as O(V^2 R^2), not O(V R). A per-call timeout does not bound
that; only a token budget does.

All bounds are fail-closed and recorded:

- per-call wall clock;
- per-council wall clock;
- per-council prompt-token ceiling, **charged before dispatch** from the
  assembled prompt, never reconciled after;
- `max_rounds`, default 2, hard-capped.

Blowing a budget produces a recorded `budget_exhausted` turn and ends the
council. It never silently shortens a round.

Every subprocess runs under `spine.cancel.ManagedProcess` so a hung vendor's
whole process tree dies — the immediate-child termination in
`SubprocessAdapter._stop_process` is insufficient, and `create_session` can
block at `stdin.drain()` before any timeout in that file applies. `ssh` carries
`BatchMode=yes` and `ConnectTimeout=5` so a sleeping bench fails in seconds
rather than sitting in TCP retry.

**Dispatch may be concurrent; chaining must not be.** Turns are collected for a
whole round, then appended in fixed roster order sorted by the vendor-namespaced
actor id, with `seq` assigned at chain time and real per-turn latency stored as
a field. Wall-clock ordering in the chain would mean the same council over the
same evidence yields a different chain head every run — offline verification
could then prove only "nobody edited this file", not "this is the council that
happened", which also breaks the §7 measurement. A test asserts that the same
fixture responses delivered in reversed completion order produce a byte-identical
chain head.

### 9. Council turns never enter the memory ledger

`daedalus/council/bus.py` writes its **own** chained store under a distinct
version tag `dcouncil/1` at its own path, reimplementing memstore's two-SHA
discipline (`body_sha` over a canonical body, `entry_sha = sha256(prev, body_sha,
ts)`, secret floor before the write, a chain walk that names the offending line).
It does not call `memstore.append_entry`, and `memstore.KINDS`, `LAYERS`, and the
entry envelope are not modified.

The mechanical reason is that it would not work — `_normalize_entry` raises on an
unknown `kind` and `_reject_unknown` refuses unknown fields — so the tempting fix
is widening the certified-memory schema. The real reason is what widening it
would build: `memory/ledger.local.jsonl` feeds recall and `fold_state` promotes
an entry to `primary` after three confirmations. Four models producing confident
prose about the codebase generate three agreeing turns routinely. That is a
mechanism for promoting model opinion to certified memory and reciting it back as
fact — the fabrication failure this project treats as the worst one. Council
records are never an input to memory recall, and a test asserts that no council
write touches `memstore.DEFAULT_LEDGER_PATH`.

## Consequences

The repo gains a second opinion it can record without a second opinion it can
obey. The council's only channel into any decision is a checkable claim that the
existing deterministic gate then runs, which means the worst case for a
maximally wrong council is wasted gate time — not a promotion.

The costs are real and are not hidden by this decision:

- Four vendors is four egress paths where there was one. Two of them (OpenAI,
  Google) have no coherent egress classification in `runtime_registry.py` today,
  and the council works around that contradiction with a conservative lane rather
  than resolving it.
- A tamper-evident transcript is permanent. Anything the inbound floor misses is
  unredactable without breaking verification. The floor is precision-tuned, not
  complete.
- The bench is reached over ssh as Administrator. Prompt-on-stdin closes the
  re-parsing path this ADR found; it does not make remote execution on the bench
  a small thing, and every future transport added to `vendors.py` inherits the
  obligation.
- `dcouncil/1` is a fifth durable store, which ADR-011 §5 forbids. It is
  permitted here only because it is not authoritative for anything: it orders
  nothing, no receipt cites it, and deleting it loses evidence but breaks no
  join. If a council record ever becomes load-bearing for a promotion decision,
  ADR-011's prohibition binds and this store must fold into the spine.
- Latency and token cost are superlinear in rounds, which is why the default is
  two.

Writing this ADR does not create a council. `daedalus/council/` must implement
the read-only profiles, the stdin transports, the per-file bidirectional floor,
the `dcouncil/1` store, deterministic chaining, and the offline replay harness
before any of this is true. Nothing here authorises wiring the council into a
review workflow; §7 does that, and only after it produces a number.

## Revisit triggers

This decision is wrong, and must be reopened, if any of the following becomes
true:

1. **Inter-vendor agreement is within noise of intra-vendor agreement.** The
   design is refuted on its own terms. `daedalus/council/` is deleted, not
   downgraded — a module kept because it is already written is how the promotion
   token gets minted later.
2. **The council beats the control, but only via one vendor.** Then this is not a
   council, it is a better reviewer, and the roster collapses to that vendor plus
   the single-vendor-twice control at a fraction of the egress surface.
3. **A caller wants an aggregate.** Someone asking for a score, a majority, or a
   `council_ok` flag is the signal that the claim/checkable output shape is not
   carrying its weight. Fix the claim shape or fix the gate. Do not add the
   field.
4. **A participant needs tools to review usefully.** If completions cannot review
   without reading the tree, the honest answer is a sandboxed evidence server
   that logs every fetch — a new ADR with its own threat model, not a `dontAsk`
   flag added to a council profile.
5. **`lane="trusted"` becomes host-derived.** If `offload.py` and
   `runtime_registry.py` are fixed to derive the lane from the *resolved* host
   rather than the provider name, §4's `OLLAMA_HOST` prohibition can relax from
   a rule to an assertion.
6. **A fifth vendor.** Each addition multiplies the O(V^2 R^2) transcript cost
   and adds an egress path; a fifth seat requires the §7 measurement to show the
   fourth earned its own.
