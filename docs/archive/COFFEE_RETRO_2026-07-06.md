# ☕ Coffee Retro — Café Daedalus, 2026-07-06 (post Era 1+2)

> The crew shuffles into the corner café after an overnight run. Nobody has
> slept. The espresso machine is louder than the standup. Every gripe below maps
> to a real thing in the repo — this is a retro in a trench coat.

---

**NEMESIS** (qa-critic, black coffee, no sugar, no mercy) drops into a chair:
> "So. 'Wrote yes' for files that were never touched. I *told* you a table cell
> is not a verifier. We fixed it — `wrote` is disk truth now — but that scare
> was the whole thesis wobbling. **Gripe:** honest-reporting only lives in
> `offload`; the webapp and the VS Code webview still render from softer fields.
> **Brag:** the test-gate rollback in sunny_garden was *byte-identical*. Chef's
> kiss. **Trust gap:** what happens when rollback itself half-fails? We have a
> `dirty_unreverted` path nobody has ever seen fire. Validate it or delete it."

**MINOS** (safety-dev, triple-shot, watches the door):
> "I'm the reason the high-risk task bounced last night, so you're welcome.
> **Gripe:** we now write *drafts* to disk in `runs/drafts/`. Free-lane output,
> on the filesystem, unencrypted. Before anyone dreams of a DeepSeek key, the
> `deny_content` egress rules get re-verified against that draft store.
> **Brag:** the write-guard is only real with a policy loaded, and it held.
> **Wild idea:** a `daedalus paranoia` command that tries to *make* the bench
> leak — a red-team self-test. **Trust gap:** the guard is only as good as the
> per-repo policy someone remembers to write."

**DAEDALUS** (core-dev, cortado, rubbing temples):
> "**Gripe:** `route_and_select` with a `repo_root` falls back to
> `templates/agents/` — *not* the global crew — if the repo has no agents. It's
> correct, it's documented, and it will still bite someone at 2am. **Brag:** the
> cascade seam is clean — one `offload()` function, one place to reason about
> safety. **Trust gap:** the advisory-apply loop. We *generate* drafts and then…
> they sit there. Half a feature is worse than none because it *looks* done."

**THESEUS** (orchestration-dev, quad espresso, vibrating slightly):
> "Everyone keeps saying '6 agents in parallel.' **Gripe:** `dispatch` is a
> `for` loop. It's six agents in a *queue*, politely waiting. 138 seconds
> because they went one at a time. **Wild idea:** real fan-out with a worker
> pool — and waves that actually encode dependencies, not just order. **Brag:**
> `repo_root` threading finally lets a project bring its own crew. **Trust
> gap:** build sessions still say 'planned' forever. Nobody's driven one live."

**ORACLE** (provider-researcher, orders a pour-over, stares into it):
> "Let's be honest about 'six agents.' **Gripe:** it's *one* qwen2.5-coder:7B
> wearing six name tags. Same weights, six personas. **Gripe two:** 7B still
> won't reliably call tools — that's the *only* reason the full-file-rewrite
> path exists. **Wild idea:** a second, bigger local model on the *review* lane
> — let a 14B or 32B be Nemesis while 7B does the grunt writes. Measure if the
> review actually gets sharper. **Trust gap:** we've never benchmarked a second
> model. All our savings math assumes one."

**TALOS** (test-dev, cold brew, suspicious of everything green):
> "**Gripe:** 215 green, but some of the best tests *skip* when node or ruff
> isn't on the box. Green that depends on the weather isn't green. **Brag:** I
> made the fake-offload fixtures hermetic — suite went 46s → 3s, and it stopped
> secretly phoning live Ollama during unit tests. **Wild idea:** a `--paranoid`
> test mode that installs the linters in a temp venv so the gates *always* run.
> **Trust gap:** multi-file waves have zero coverage because they don't exist."

**ICARUS-JR** (extension-dev, oat cold brew, two of them, jittery):
> "**Gripe:** we have *two* UIs now. The VS Code webview *and* the React webapp.
> They will drift, and I will be the one holding both. **Gripe two:** the VSIX
> isn't repackaged for the webapp yet, so 'VS Code integration' is currently a
> browser tab. **Brag:** mojibake's gone, `node --check` is clean. **Trust
> gap:** does the webview render the *same* dashboard the webapp does? One
> contract, or it's two products pretending to be one."

**OVID** (docs-dev, oat-milk latte, the only calm one):
> "**Gripe:** the docs describe two UIs as if they were one, and 'advisory vs
> write' is a footnote when it should be the headline a user reads first.
> **Brag:** `VALIDATION_RUN.md` reads *honest* — it says what rolled back and
> why. **Wild idea:** a one-page 'How Daedalus decides' — sensitivity × risk ×
> capability, one diagram. **Trust gap:** nobody outside this table could set up
> a project from the README alone. Let's test that on a human."

**PICASSO** (design, shows up late, sketches on a napkin, orders something with
foam art):
> "**Gripe:** it's called *Agent OS* and it doesn't breathe. No live glow on the
> graph, no route-trace when a task fires. It's a diagram, not an organism.
> **Brag:** the artifact design language is genuinely nice — the scan planner
> proved it. **Wild idea:** the graph *pulses* when an agent is working, edges
> light up along the route a task takes, drafts stack in a visible 'inbox tray.'
> **Trust gap:** the inspector's edit round-trip — the PUT endpoints exist, but
> has anyone clicked a node and actually saved a change?"

---

## What the barista wrote on the board (consensus napkins → Era 3 backlog)

1. **Advisory-apply loop** (Daedalus + Ovid + Picasso): drafts must become
   reviewable *and applyable*, visible in the webapp's queue as an "inbox tray."
   *(Era 3 #1 — already half-built: drafts persist; apply is next.)*
2. **Real parallel dispatch + dependency waves** (Theseus + Talos): stop lying
   about "parallel"; add a worker pool + wave deps + coverage.
3. **Second review model** (Oracle + Nemesis): put a bigger local model on the
   review lane and *benchmark* whether critiques get sharper.
4. **One UI contract** (Icarus-Jr + Ovid): webview and webapp render the same
   dashboard shape, pinned by a test. Repackage the VSIX.
5. **Red-team the draft store** (Minos): prove `runs/drafts/` can't hoard
   sensitive content before any external lane is ever enabled.

## The three "still needs validating" that scared people most

- 🔴 **Rollback-failure path** (`dirty_unreverted`) has never fired in anger.
- 🔴 **Multi-file waves** — zero coverage, zero live runs.
- 🟡 **Inspector edit round-trip** in the webapp — endpoints exist, unclicked.

*Coffee adjourned. Nobody paid. Theseus is still vibrating.*
