---
name: council
description: Convene the cross-vendor Council -- four independent model vendors (Anthropic claude, OpenAI codex, Google agy, local Ollama) deliberate over a patch or a design question and return every dissent verbatim. Use when asked for a cross-vendor or independent second opinion, to have a patch reviewed by models other than the one that wrote it, to check a decision against other vendors, or to "convene the council" / "ask the council" by name. Also use to publish an existing council transcript to a GitHub PR, or to read a PR thread back for a follow-up round. The verdict is ADVISORY and promotes nothing.
---

# Council

Four independent vendors deliberate over evidence and produce a transcript. You
read the dissents. **THE GATE DECIDES, NOT A MODEL.**

## The doctrine (read before using the output)

- **Advisory only.** A council result promotes nothing, merges nothing, gates
  nothing. It is EVIDENCE for the deterministic gate (tests, fences, diffs) to
  act on, and the gate's result is the only verdict. Never report a council
  outcome as if it were a passing gate.
- **There is no majority / consensus / score field, and you must not invent
  one.** The absence of the field IS the control -- a field named "majority" is
  one refactor from being read as a verdict, and a verdict is one convenience
  commit from gating a promotion. Report **convergence** (an observation about
  what the vendors said), never a majority, a vote, or a confidence number.
- **Dissent is the product.** The value of paying four vendors is the one that
  disagreed -- it is the only output that could not have been produced by asking
  one model twice. Every dissent is recorded and rendered VERBATIM with its
  author, and ahead of the convergence. Never summarise, average, or "resolve"
  dissents.
- **Unanimity is not confirmation.** Four models trained on overlapping data
  agreeing is weak evidence of correctness. Say so when reporting agreement.
- **The premise is untested.** Whether independent vendors have independent
  blind spots is measured, not assumed -- see the falsification protocol in
  `daedalus/council/__init__.py`. Do not claim the council caught something
  without checking the claim against the gate.

## Honesty rule: degraded quorum

If fewer vendors answered than were requested, that is **the first thing you
report**, not a footnote. Name which vendors did not answer and state that the
result is a weaker signal than a full council -- the absent vendors'
independence is exactly what the roster buys and it was not obtained.

`render_markdown` enforces this in the rendering (a `DEGRADED QUORUM` warning
block in the first lines). Match it in prose when you report to the user.

## Vendor roster and availability caveats

| vendor | reached via | caveat |
| --- | --- | --- |
| Anthropic | `claude` CLI, local | generally available |
| OpenAI | `codex` CLI, local | npm `.CMD` shim on Windows; resolve the real path before spawning |
| Google | `agy` CLI on the **remote bench** | needs a **one-time interactive sign-in on the bench**. It cannot be automated: if agy has never been signed in, this vendor will not answer and the council runs degraded. Sign in on the bench once, then it persists. |
| local | Ollama | free and always up, but the weakest voice; a 7B dissent is a hint, not a finding |

A vendor that does not answer is a degraded quorum, never a silent drop.

## Measured operating notes (2026-09-05, owner's Windows box)

These are the reasons a live council came back 0 of 3 that day, each with
its fix. Read them before blaming a vendor.

- **Codex CLI version.** The npm global `@openai/codex` was 0.146.0 while the
  owner's `~/.codex/config.toml` selects `gpt-6-astra`; the API refuses that
  model on an old CLI with HTTP 400 "requires a newer version". `codex
  --version` must be at least 0.153; upgrade with `npm install -g
  @openai/codex@latest`. The `.CMD` shim is resolved by `_resolve_command`.
- **Per-call timeout.** A one-word reply takes ~21 s from `claude -p` and
  ~60 s from Codex at the owner's "ultra" reasoning effort; a review over
  ~29k evidence tokens exceeded 420 s under load. Defaults are now 600 s per
  call and 2400 s wall clock; pass `--timeout`/`--wall-clock` larger for big
  evidence, and do not run three test suites next to a council.
- **Local seat context.** The local `qwen2.5-coder:7b` runs with
  `num_ctx=6144` on a 2 GB GPU / 15.7 GB RAM box, so its usable input window
  is ~5100 tokens. Evidence above that is REFUSED loudly by the adapter
  (`over_context_budget`) rather than head-truncated; the bus records it as
  `transport_error` and the render now shows the vendor detail behind it.
  Give the local seat small evidence (one test file, a diff) or accept the
  honest refusal. Use `--ollama-host http://127.0.0.1:11434`; the bench host
  is another machine and is often asleep.
- **Budget accounting.** Every CLI seat reserves `anthropic_cli` $3.00 /
  `openai_cli` $2.00 worst case against the day ledger
  (`runs/budget/ledger.json`, default ceiling $5.00). Since 2026-09-05 a
  Claude seat settles at the CLI's own `total_cost_usd` (a one-word reply is
  ~$0.34) and a seat whose executable never spawned is released, not charged;
  a timed-out or unpriced seat keeps the worst case. `budget_exhausted` in the
  render means the ceiling, not the vendor: raise it deliberately as the owner
  (desktop cap menu, or `DAEDALUS_BUDGET_USD`), declare a flat-rate vendor with
  `DAEDALUS_SUBSCRIPTION_VENDORS` (the owner's Codex uses ChatGPT auth), or
  wait for the day to roll over. Never point `DAEDALUS_BUDGET_LEDGER` elsewhere
  to get around it.
- **Cheap liveness first.** `daedalus canary --live --quick --vendors
  anthropic,openai,local --ollama-host http://127.0.0.1:11434` asks each lane
  one checkable question before you spend a review on it.

## The canonical record

The transcript is an append-only, hash-chained JSONL bus at
`runs/council/<council_id>.jsonl` (`daedalus/council/bus.py`). That file is
**canonical**. Anything rendered elsewhere -- a PR comment, a chat summary -- is
a RENDERING of it. If a rendering and the bus disagree, the bus is right: a
comment can be edited or deleted, a chain link cannot.

Verify a transcript offline with the bus module's chain verifier before quoting
it as evidence.

## Convening locally

The convening entrypoint lives in `daedalus/council/session.py`, with the vendor
adapters in `daedalus/council/vendors.py`. Read the current signatures there
before calling -- that module is newer than this skill. Convene with the
evidence (a patch, a diff, a file digest) and a single sharp question; a vague
question produces four vague answers at four times the cost.

## Publishing to a GitHub PR

`daedalus/council/publish.py`. The PR comment is a human-facing rendering of the
bus plus an async channel -- it never becomes the record.

```python
from daedalus.council.publish import publish_to_pr, read_pr_thread, render_markdown

# 1. ALWAYS preview first. dry_run renders and runs the egress gate but never
#    invokes gh. If a dry run is refused, the live call would be refused too.
res = publish_to_pr(verdict, transcript, pr="7", repo="KTY137/daedalus",
                    dry_run=True)
print(res.markdown)

# 2. Post it.
res = publish_to_pr(verdict, transcript, pr="7", repo="KTY137/daedalus")

# 3. Read replies back for a later round (the async channel).
thread = read_pr_thread(pr="7", repo="KTY137/daedalus")
for turn in thread.turns:
    print(turn.author, turn.created_at, turn.body)
```

**Branch on `res.status`. It never raises for an operational failure.**

| status | meaning | what to do |
| --- | --- | --- |
| `published` | comment posted (`res.comment_url`) | report the URL |
| `dry_run` | rendered, gh not invoked | show `res.markdown` |
| `refused_secret` | the secret floor fired; nothing left the machine | report the rule from `res.detail`; do NOT retry, do NOT strip and resend without the operator |
| `unsafe_argument` | the `pr` or `repo` value would reach `gh`'s argv as something other than data; `gh` was never invoked | fix the value at its source -- it must start alphanumeric; do NOT resend it quoted or escaped |
| `gh_missing` | gh not installed / not on PATH | tell the operator; do not fall back to raw git |
| `gh_unauthenticated` | no valid credentials | operator runs `gh auth login` |
| `pr_not_found` | no such PR, or no access to it | check the number and the repo |
| `rate_limited` | GitHub rate / abuse limit | back off; the bus already has the record, nothing is lost |
| `gh_error` | anything else | report `res.detail` verbatim |
| `read_ok` | thread read (`read_pr_thread` only) | -- |
| `bad_payload` | gh exited 0 with unparseable JSON | report it; do not guess the content |

### Egress gate

Every string bound for GitHub -- the whole comment body, the PR reference, the
repo slug, every evidence path -- passes `sensitivity.secret_floor_rule` before
the gh runner is touched. A hit returns `refused_secret` and the offending text
never reaches argv or the child's stdin. The refusal detail names the channel and
the rule, never the matched secret; do not go looking for the secret to quote it.

The gate runs in `dry_run` too, so a preview can never show a body the gate would
refuse to post.

## Reporting a council result to a user

State, in this order: the outcome; the quorum (loudly, if degraded); **every
dissent with its author**; then where the vendors converged; that it is advisory
and gated nothing; the bus path so they can check it.

Lead with what was CONTESTED, not with what was agreed. And if a vendor did not
speak -- `unavailable`, `refused`, `budget_exhausted` -- say which one and why;
`bus.py` records that instead of dropping the vendor precisely so it can be
reported, and "three vendors agreed" reads very differently from "one was never
asked".

### Measured operating notes, addendum (2026-09-05 evening)

- **Evidence path must pass the untrusted egress lane.** The Codex seat runs in the `untrusted` lane; `slice_egress_rule` default-denies any evidence path outside the allow-list substrings (`docs/`, `/tests/`, `test_`, `.md`, `readme`). A scratchpad or `.diff` path is WITHHELD silently: the seat answers "evidence withheld", and the dry run shows no `withheld` field. Put council evidence under a repo-relative path with an allowed name (e.g. `runs/council/evidence/<name>.md`).
- **Snapshot the evidence when nobody else edits the file.** A round taken while an adversarial agent had a mutant applied in place reviewed the mutant, not the tree; record the sha256 of the evidence and of the file it was cut from in the report.
- **Round-2 attrition.** The Anthropic seat's reply can trip the secret floor (a key-shaped string in its own prose) and is then dropped unread as `refused`; the local 7B seat's 5,120-token window is consumed by prior turns, so round 2 fails at 0 ms as `transport_error` (pre-dispatch context refusal). A "3 of 3 responded" render can hide a one-voice refutation round: read per-round statuses.
- **A killed council process leaves its open reservation in the ledger** (worst case, pid recorded); it is not released automatically. Report it; never rewrite the ledger.

