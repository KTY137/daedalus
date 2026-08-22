# Architecture Decision Records

One namespace. `docs/adrs/NNN-slug.md`, three digits, never renumbered again
except by a merge recorded in the table below.

## What an ADR may and may not do

Per the authority table in `docs/IKARUS_ARIADNE_MASTER_PLAN.md` sec. 0, an ADR
is **history/backlog**: it supplies evidence and proposals. It does not define
goals, invariants, priors, or delivery order, and it never overrides the master
plan. A record that needs to change an invariant is an amendment (sec. 15), not
an ADR.

## The namespace merge (2026-08-22)

`docs/adr/` (two records, created on the g0 trunk) and `docs/adrs/` (001-019)
were two ADR namespaces in one tree — the second source of truth the plan's
own forbidden-directions list names. They are now one. Moves, never deletes:
`git log --follow` reaches the pre-merge history of both files.

| before | after | title |
| --- | --- | --- |
| `docs/adr/ADR-0001-FOREST-FOURFOLD-AUTHORITY.md` | `docs/adrs/020-forest-fourfold-authority-boundary.md` | Forest and Fourfold authority boundary |
| `docs/adr/ADR-0002-PROMOTION-RECEIPT-AUTHORITY.md` | `docs/adrs/021-promotion-receipt-authority.md` | One promotion receipt authority |

Numbers 020 and 021 rather than the free slot 014: appending keeps every
existing citation of 001-019 true, and the two records postdate 019 (dated
2026-08-01 and 2026-08-03). Inbound citation updated in the same commit:
`docs/work-packets/G0-PRM-12C_PROMOTION_RECEIPT_AUTHORITY.md` (2 references,
ADR-0002 -> ADR-021). No other reference to either old path exists
[MEASURED 2026-08-22, `grep -rn "ADR-0001\|ADR-0002\|docs/adr/" --include=*.md
--include=*.py --include=*.json .` — the only remaining hits are the inventory
and plan documents that recorded the collision].

**014 never existed** [MEASURED 2026-08-22, `git log --all --diff-filter=A
--name-only -- "docs/adrs/014*"` returns nothing]. The gap is not a lost
record; do not fill it.

## The authority-title check

The question this check answers (raised by codex against the g0 trunk): is
`ADR-0001-FOREST-FOURFOLD-AUTHORITY.md` a filename claiming authority — a
fourth authority surface incubating — or a naming collision?

**Check:** no ADR title may claim that the ADR itself is authoritative. Naming
an authority boundary *in the system* is the ADR's job; being an authority is
not.

**Result 2026-08-22 [MEASURED]:** 21 ADRs, 2 titles contain the token
"authority" — ADR-020 "Forest and Fourfold authority boundary" and ADR-021
"One promotion receipt authority". Both name the subject of the decision (which
artifact is authoritative for the Forest, and which receipt is canonical for
promotion), neither claims the record is an authority. ADR-020 states it in its
own header: `Authority: derived decision record; cannot override the Iron Plan`
(line 6). ADR-021 carries `Decision scope: promotion contracts and persisted
execution accounting`. Verdict: **naming collision, not a fourth authority
surface** — and the collision is now gone, because the namespace is one.

The check as a command, for the next reader:

```sh
for f in docs/adrs/*.md; do head -1 "$f"; done | grep -in "authority"
```

Two hits is the expected state. A third means someone wrote a new title
containing "authority": read it and decide whether it names a subject or claims
a rank. Zero hits means 020/021 were renamed — check why.

## The records

| # | file | subject |
| ---: | --- | --- |
| 001 | `001-component-roles.md` | Component roles |
| 002 | `002-hermes-upstream.md` | Hermes as Ikarus upstream |
| 003 | `003-mission-api-trust-boundary.md` | Mission API as trust boundary |
| 004 | `004-execution-transactions.md` | Execution transactions |
| 005 | `005-task-groups.md` | Task groups (agent crews) |
| 006 | `006-memory-separation.md` | Memory separation |
| 007 | `007-root-of-trust.md` | Root of trust |
| 008 | `008-universal-agent-adapter.md` | Universal agent adapter protocol |
| 009 | `009-ariadne-forest-evolution-engine.md` | Ariadne forest evolution engine |
| 010 | `010-naming-namespaces.md` | Naming namespaces |
| 011 | `011-event-spine.md` | The event spine |
| 012 | `012-council-cross-vendor-review.md` | Der Rat — cross-vendor review council |
| 013 | `013-dual-space-intercom.md` | The dual-space intercom |
| 014 | — | never existed |
| 015 | `015-ariadne-preconditions.md` | Ariadne preconditions |
| 016 | `016-autonomy-preconditions.md` | Preconditions for an unattended loop |
| 017 | `017-assistant-upstream.md` | The assistant layer — upstream reconsidered |
| 018 | `018-skill-format.md` | The `SKILL.md` format, adopted as inert text |
| 019 | `019-one-decision-point.md` | Guards are six predicates over one noun |
| 020 | `020-forest-fourfold-authority-boundary.md` | Forest and Fourfold authority boundary |
| 021 | `021-promotion-receipt-authority.md` | One promotion receipt authority |
