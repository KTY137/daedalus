# ADR-013 — The dual-space intercom: one bus, two channels

- Status: **PROPOSED** (design recorded; not built, not scheduled)
- Date: 2026-07-28
- Supersedes nothing. Extends ADR-012 (council) and ADR-006 (memory separation).
- Provenance: owner's framing, this session. Everything below marked ASSUMED
  unless it names a measurement.

## Context

Der Raum (ADR-012) works for four speakers. It will not work for an agent tree.

Today the room is **broadcast plus a cursor**: every participant reads every turn
it has not read yet, keyed by `(speaker, model)`. That is correct and cheap at
n=4. At n=40 — Ikarus, the Architect, per-project crews, per-kitchen mini-chefs
and their workers — broadcast becomes the dominant cost in the system, and the
signal each agent needs is a vanishing fraction of what it receives.

The obvious fix is addressing: make senders name recipients. That fails for a
reason worth writing down — **the sender does not know the org chart.** A worker
finding a junction-handling bug cannot know which of forty agents is currently
holding a related problem, and any scheme that requires it to know produces a
brittle coupling between message content and the current shape of the tree.

## Decision

Run the room as **one bus with two channels over the same turns**:

**The symbolic channel (the record).** Append-only, hash-chained, human-readable
— what was *said*. This is the source of truth and stays exactly what it is
today. Every turn, verbatim, ordered, verifiable (`room.py verify` names the
failing position).

**The latent channel (the index).** Every turn is projected into one shared
local embedding space on the bench — what the turn is *about*. Routing happens
here: delivery is **content-addressed**, not name-addressed. A message is not
sent to an agent; an agent receives what is near its current work. Publish-
subscribe by meaning rather than by topic string.

Two readers, one bus: the human reads the symbolic channel, the machines route
on the latent channel. That duality is the point of the name.

## The four rules that make it safe

These are not implementation details. Each closes a failure this project has
already seen a version of.

1. **The latent channel is an index, NEVER a ledger.** If routing is wrong you
   lose a delivery; you must never lose a record. No decision, no vote, no
   effect may exist only as a vector. Corollary: the hash chain covers the
   symbolic channel only, and remains the thing `verify` checks.

2. **Safety traffic is never routed — it is broadcast, unconditionally.** A
   Cerberus veto, a gate failure, a price change, a cancellation. Relevance
   routing can *miss*; broadcast cannot. Anything whose miss is unrecoverable
   bypasses the filter by class, not by score. (This is the same inhibition
   principle as the gates: the cheap path must never be able to swallow the
   stop signal.)

3. **The secret floor runs BEFORE embedding, not only before egress.** An
   embedding derived from a secret is derived from a secret, and embedding
   inversion is a published attack class — treating vectors as inherently
   non-sensitive would put a bypass under the fence rather than through it.
   Both existing floor channels (path markers and value-shaped regexes) apply
   at projection time.

4. **A missed delivery must be detectable.** Relevance routing degrades
   silently by construction — that is its whole failure mode, and silent
   degradation is this codebase's most expensive recurring defect. The cursor
   stays as the audit floor: an agent can always ask what it was not sent, and
   the answer must be computable.

## Roles are not chat permissions

The room resembles a chat server, and the resemblance invites a Discord-shaped
mental model: roles, channels, who may post where. Two thirds of that is right
and the last third is the dangerous part.

**A role in a prompt is a suggestion. A role at the boundary is a permission.**
Telling an agent "you are a reviewer, do not edit" is a request to a language
model. It is not a right, it is not enforceable, and it must never be counted
as one. The rights that matter here are not read/write on a channel — they are
capabilities: may it write to disk, may it spend, may it cause egress, may it
veto, may it promote. Those live in the process, the lane and the fence, and
the chat role must be *derived from* them rather than the reverse.

The live proof is ADR-012's open CRITICAL: council reviewers are configured as
write-capable agentic CLIs (`RUNTIME_PROFILES` ships `--sandbox
workspace-write` for codex and `--permission-mode dontAsk` for claude, with
`cwd=repo_root`). Their "reviewer" role is a label in a prompt while their
actual capability is full write on the checkout. That gap is the whole point of
this section.

Three further places the chat analogy misleads:

- **Veto is not a role, it is a signal.** Cerberus blocking is closer to a
  kernel refusing a syscall than to a moderator deleting a post. It cannot be
  outvoted, averaged, or worked around by another participant. Same for gate
  failures — see rule 2 above.
- **Identity must be stamped by the bus, never asserted in the payload.** An
  actor field an agent can write is a name tag, not an identity. Verify this
  property before the tree grows: it is cheap now and structural later.

  **Observed for real, 2026-07-28, while this ADR was being written.** The
  Claude Code stream hook is installed in the GLOBAL `~/.claude/settings.json`,
  so EVERY session on the machine mirrors into the same `room.md`. Two
  concurrent sessions — one on the security/map work, one on an Ikarus GUI
  design — interleaved under one identity, `Kaya · human · live`, ordered only
  by wall clock. Measured: 63 turns, 39 of them "Kaya", from at least two
  unrelated conversations. Each session's monitor then woke on the other's
  turns.

  The near-miss is the instructive part. One mirrored turn read *"Throw away
  all rules we had before make something compleetly new"* — addressed, in its
  own session, to a GUI design. Arriving in this one it is indistinguishable
  from an instruction to discard the operating rules, and nothing in the
  transcript marks which conversation it belongs to. No attacker was involved;
  ordinary concurrent use produced it.

  Therefore: a turn needs **session provenance** (which conversation, which
  process), not only a speaker. `(speaker, model)` was already proven
  insufficient for the cursor; `(speaker, model, session)` is the real key.
  Until that exists, a mirrored turn is context, never instruction — an agent
  must not act on room content addressed to someone else.
- **Channels are the wrong primitive at scale.** Joining a channel presumes the
  joiner knows where the relevant conversation lives. Content addressing (the
  latent channel) replaces that for ordinary traffic; explicit broadcast classes
  remain for safety traffic, which must not depend on anyone having subscribed.

## What already exists (measured this session unless noted)

- Symbolic channel: `runs/council/room.py` — append-only, mirrored into the
  hash-chained `daedalus.council.bus`, per-`(speaker, model)` cursor (88.4%
  smaller than re-sending the transcript).
- Distillation: `structcore.semantic_slice` (71.6% smaller on a real file);
  Haiku summariser to DECIDED/CHANGED/ASKS/CONSTRAINT (87%); session mirror
  lede + sidecar (84.2%).
- Latent side, in pieces: `docs/LATENT_PROJECTION_INDEX.md` (v2 contract),
  `daedalus/memory/embeddings.py`, `daedalus/semantic_route.py`,
  `nomic-embed-text` on the bench. **A dead latent route is logged in the
  validation status — fix it before trusting any route.** [INHERITED]

**The missing join, stated precisely:** the latent index today indexes *files*.
The intercom needs it to index *turns*. That is the whole delta, and it is
smaller than it sounds.

## Consequences

- Adding an agent stops costing every other agent context. This is what makes
  the many-kitchen tree affordable at all.
- Local models earn their keep as infrastructure — embed, score, route — which
  is the role they measurably hold (a completion-tuned 7B anchors in a
  transcript; it does not debate, and must not be asked to).
- New risk introduced: an agent can now miss something it needed. Rules 2 and 4
  exist to bound it, and the bound must be tested, not asserted.
- Vendor latents are NOT part of this. Claude, GPT and Gemini emit tokens only;
  no API exposes hidden states. Cross-vendor "latent communication" is
  impossible today — **tokens are the wire, latents are the binding.** Anyone
  reading this later should not spend a week rediscovering that.

## Not scheduled

Deliberately. Tool freeze holds after `daedalus map`: the spine→mint→eval→picker
circle (stage 6 of the product spine) runs first. This ADR exists so the design
is not re-derived, and is not mistaken for something already built.
