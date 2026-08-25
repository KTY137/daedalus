# What is in `docs/`, and which of it is still true

683 tracked files [MEASURED 2026-08-25, `git ls-files docs`]. Most of them are
evidence: a page that recorded what was measured on a particular day, which
stays valuable exactly by *not* being updated afterwards. A handful describe the
system as it is now. Confusing the two is the failure this page exists to
prevent.

This is a map, not an authority. It ranks nothing, decides nothing, and is
overridden by every document it points at. Semantic authority is
`IKARUS_ARIADNE_MASTER_PLAN.md`; where the truth is today is `STATUS.md`.

## Start here

| | |
|---|---|
| [`STATUS.md`](STATUS.md) | Where the truth is today, and what is unsettled. The one page that claims to be current. Read it first. |
| [`../README.md`](../README.md) | What Daedalus is, the rules that do not bend, the command surface. |
| [`IKARUS_ARIADNE_MASTER_PLAN.md`](IKARUS_ARIADNE_MASTER_PLAN.md) | Sole semantic authority: invariants, gates, priors, delivery order. Revision 7. |
| [`IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`](IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl) | The amendment chain. 7 records, hash-linked. The plan changes only by appending here. |
| [`DAEDALUS_GESAMTPLAN.md`](DAEDALUS_GESAMTPLAN.md) | Program authority: the build program *within* the plan's bounds. Where they conflict, the plan wins. |
| [`architecture-narrative.md`](architecture-narrative.md) | Why the structure is what it is, paired with the mechanical snapshot `architecture-state.json`. |

## The four kinds of document here

Everything in `docs/` is one of four things. The distinction is not stylistic —
it decides whether a dead path inside the page is a defect or the point.

**Current.** Describes the system as it is now, and is expected to be repaired
when the system moves. `STATUS.md`, `architecture-narrative.md`,
`PROJECT_SCOPE.md`, `COMMS_PROTOCOL.md`, `FALLBACK.md`, `GUI_CATALOGUE.md`,
`ENGINE_PARITY.md`, `wiki/`.

Two top-level pages carry a **tombstone banner** in their first line —
`ARCHITECTURE.md` (an Era-3 snapshot; the live architecture is
`architecture-narrative.md`) and `MISSION_CONTROL.md` (a surface that was never
shipped, pinned as unreachable by a test). They are kept at their paths so old
links resolve. A tombstone is the honest form of a document that would otherwise
read as a feature list.

**Authority.** The plan, its amendment chain, and the Gesamtplan. Ordinary
sessions do not edit these; section 16 of the plan says how they change.

**Evidence.** Dated measurements, findings, decisions and receipts. A path that
no longer exists inside one of these is *what makes it evidence* — it records
the tree as it stood. `archive/`, `inventory/`, `recovery/`, `missions/`,
`decisions-taken/`, `architecture_history/`, `research/`, the `GATE0_*` and
`GATE2_*` findings, `HANDOFF*.md`, `AMENDMENT_PROPOSAL_*.md`.

**Backlog.** Proposals and plans, which name modules that do not exist yet, by
definition. `work-packets/`, `design/`, `decisions-pending/`, `adrs/`, and
`ABSORPTION.md` — a 2026-07-29 survey cut down to a list of decisions, several
of which are still being executed (`pyproject.toml` cites its D1 bar by name).

`tools/docs_reference_check.py` encodes exactly this split: it fails on a dead
reference in a *current* page and merely counts the ones in evidence and
backlog. 149 of the latter today, and that number is not a debt.

## The directories, by size

| | files | what it is |
|---|---:|---|
| [`archive/`](archive/) | 158 | Superseded pages, kept at a stable path so old links resolve. Evidence. |
| [`work-packets/`](work-packets/) | 157 | One bounded change each, with its acceptance matrix. Backlog, then evidence once run. |
| [`design/`](design/) | 135 | UI/UX direction, prototypes, vendor design reviews. Backlog. |
| `docs/*` (top level) | 49 | The current pages, the authority documents, and the dated gate findings. Mixed — see above. |
| [`inventory/`](inventory/) | 49 | Census and triage runs: what the tree contained on a given day. Evidence. |
| [`recovery/`](recovery/) | 47 | One-shot repair kits and their reports. Evidence; the kits are why the graph reports islands under `docs/`. |
| [`research/`](research/) | 40 | Research notes, night-shift results, prior art. Evidence. |
| [`adrs/`](adrs/) | 21 | Decision records, one namespace, `adrs/README.md` first. History/backlog — they never override the plan. |
| [`wiki/`](wiki/) | 10 | The knowledge-plane pages, including `wiki/feature-backlog.md`. Current. |
| [`architecture_history/`](architecture_history/) | 4 | Older architecture snapshots. Evidence. |
| [`decisions-pending/`](decisions-pending/) | 4 | Waiting for the owner's pen. Backlog. |
| [`superpowers/`](superpowers/) | 4 | Skill specs written during hook/skill work. Evidence. |
| [`decisions-taken/`](decisions-taken/) | 3 | Closed decisions, dated. Evidence — and worth reading, because several record *why* a thing turned out not to be blocking. |
| [`missions/`](missions/) | 2 | Per-session mission contracts and ledgers. Evidence. |

## How to keep this honest

```powershell
python tools/docs_reference_check.py     # do current pages still name files that exist?
python -m daedalus.cli map --check       # does the narrative still match the tree?
```

The first is cheap and exits non-zero only on current pages. The second is the
architecture gate; read `STATUS.md` before trusting its baseline, which is
currently irreproducible for reasons recorded there.

Both are local, and deliberately so: CI is not a third option today — no
Actions job starts at all. `STATUS.md` carries the three measured reasons and
the order they have to be repaired in.

And note what the first command does *not* do. It checks whether a reference
resolves to a file that exists. It cannot check whether a sentence is true, and
sentences are how these pages actually rot — this paragraph itself asserted
something false for the length of one afternoon. A green from it means "current
pages point at real files", never "current pages are correct".

Two rules that have already cost real time here:

- **Do not repair evidence.** If a page is dated, its dead paths stay. Add a
  new dated page instead; that is what the `docs/decisions-taken/` and
  `docs/inventory/` trees are for.
- **But frozen is append-only, not immune.** A history page that a *current*
  page routes readers into, and that contains a live false instruction, gets a
  correction banner at the top. Dead paths in evidence are harmless; an
  instruction a reader will act on is not. `docs/HANDOFF.md:23-25` is the open
  case — `docs/GATE0_INTEGRATION_GAPS_20260825.md` measured that its most
  alarming line is false at HEAD, while `STATUS.md` still routes readers to it.
- **Authority pages are not repairable here at all.** The plan, its amendment
  chain, the Gesamtplan, `AGENTS.md` and `CLAUDE.md` change only by the
  amendment protocol. `tools/docs_reference_check.py` reports dead references
  in them under a separate heading and never blocks on them, because a tool
  that demands an edit an ordinary session may not make will eventually get
  one.
- **Do not copy a number out of a page into another page.** Copy the command
  that produced it. Every number in a current page should name how it was
  measured, and `[MEASURED]` / `[INHERITED]` / `[ASSUMED]` is the vocabulary.
