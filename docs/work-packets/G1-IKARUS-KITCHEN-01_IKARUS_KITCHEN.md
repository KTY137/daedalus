# G1-IKARUS-KITCHEN-01 — Ikarus kitchen: Waiter, Chef, Sous-Chef, Grey Matter

## Frozen packet metadata

- Packet ID: `G1-IKARUS-KITCHEN-01`
- Active gate: **Gate 1** (Renovation, owner-directed Genesis, general computer assistance)
- Classification: `ALIGNED` with Masterplan §7 (Ikarus compiles intent into a
  bounded mission), §7.1 (owner-directed Genesis with visible defaults), §8.1
  (self-Renovation leakage boundary), §9.1 (Atlas/motif retrieval as a
  regenerable index), Invariant 2 (content-addressed candidate trees),
  Invariant 3/4 (a candidate never authors its own evaluator; models propose,
  deterministic checks decide), Invariant 5 (nomination, never promotion).
- Owner instruction (2026-09-12): "bau mir nh app" / "improve diese App" must
  run autonomously; two Ikarus roles — the Waiter who talks and the Chef who
  runs the Daedalus kitchen; feed Ariadne with repositories; make the tensor
  embedding and "grey matter" work; **containment of builder agents is
  deferred by explicit owner decision** and is stated, not claimed, in every
  evidence packet.
- Base revision: `bac41130` (main).

## What landed

`daedalus/orchestration/ikarus/kitchen/`

| Module | Role |
| --- | --- |
| `orders.py` | Deterministic bilingual order recognition. Only whole applications/projects are kitchen orders (`bau mir …`, `improve diese App`, `verbessere dich selbst`, `füttere Ariadne mit <repo>`). Component imperatives (`improve the parser`, `verbessere Daedalus`, `entwickle ein CLI-Tool`) stay with the confirm-gated computer task of G1-IKARUS-46. |
| `waiter.py` | The conversational front: answers at once, hands the order to the Chef (background thread, or synchronous with `DAEDALUS_KITCHEN_SYNC=1`), reports status from the ledger. Never touches a workspace. |
| `chef.py` | Pipelines `build_app`, `improve_app`, `self_improve`, `feed_ariadne`: Grey Matter retrieval → builder lane → toolchain checks → bounded repair (≤2) → content-addressed tree digest → candidate twin → evidence packet → **nomination**. Self-Renovation rejects candidates touching the §8.1 protected prefixes and retains them as negative evidence. |
| `builders.py`, `report.py` | Builder lanes: `ollama` (Sous-Chef), `claude` (`claude -p`), `codex` (`codex exec`). Default chain `ollama,claude,codex`; `DAEDALUS_KITCHEN_BUILDERS` overrides. |
| `souschef.py` | The low-context local lane: plan → one file per call with only that file's context (plan, signatures of written files, Grey Matter motifs) → kitchen-owned structural evaluator for static-web candidates → triage-scoped repair. Existing tests are a frozen evaluator in Renovation mode. |
| `toolchain.py` | `daedalus-candidate.json` manifest or lockfile/layout detection; bounded command execution; verdict = observations, never promotion. |
| `greymatter.py` | The latent atlas: four-plane Node Cards (Python `ast`, JS/TS regex, JSON/CSV/SQL/YAML/TOML, Markdown sections), deterministic hashed embeddings (`hashed-blake2b/256`, no third-party dependency), sparse plane×plane×relation tensor projection, literal-verified and latent (unverified) cross-plane binding proposals, license/revision/temporal provenance per repository. SQLite, fully regenerable. |
| `ledger.py` | Order ledger (SQLite) behind `/api/kitchen[/<order-id>]` and "Küche Status". |
| `__main__.py` | `python -m daedalus.orchestration.ikarus.kitchen order|feed|status|search`. |

Wiring: `shell._ask_inner` and `_ask_stream_inner` call `kitchen.maybe_serve`
before the ordinary routes; `interfaces/http/read.py` gains the read-only
`/api/kitchen` projection. Kitchen state lives in `~/.daedalus/kitchen`
(override `DAEDALUS_KITCHEN_ROOT`), deliberately outside every repository tree.

## Measured evidence (2026-09-12, this host, Windows, RTX 16 GiB)

Live orders through the CLI door (`MEASURED`):

| Order | Lane | Result | Files | Checks | Repairs | Wall |
| --- | --- | --- | --- | --- | --- | --- |
| "bau mir nh app: Pomodoro-Timer …" | claude (sonnet) | nominated | 16 | test ✓ | 0 | 385 s |
| "bau mir nh app: Einkaufslisten-App …" | ollama `qwen2.5-coder:7b` | nominated | 9 | build ✓ test ✓ | 0 | 21.7 s |
| "improve diese App: Mengenangabe + Liste leeren" (project `einkaufsliste`) | ollama `qwen2.5-coder:7b` | nominated patch (4 files), checkout untouched | 9 | build ✓ test ✓ | 0 | 18.6 s |
| "füttere Ariadne …" 3 repos (daedalus, flask, typer) | — | done | — | — | — | 16.7 s |
| feed 50 MIT repos (`DAEDALUS_KITCHEN_LICENSE_ALLOW=MIT`) | — | 49 ingested, 1 skipped (date-fns: license undeclared) | — | — | — | 277.6 s |

Sous-Chef task division on the Einkaufsliste build (`MEASURED`): 7 model
calls, maximum context 5,155 characters per call, 26,874 characters total; the
7B model never saw more than one file's task at a time.

Grey Matter after the feeds (`MEASURED`): 64 repositories, 210,031 cards
(code 151,247 / type 6,662 / data 2,589 / knowledge 44,546), 408,647 edges,
16,524 binding proposals of which 16,153 literal-verified; search latency
≈3 s per query at this size.

Negative evidence retained (`MEASURED`): first local Einkaufsliste attempt
failed (`llama-server.exe` missing in the installed Ollama 0.32.5; repaired by
a portable 0.34.0 on port 11435); second attempt failed because the 7B model
wrote Selenium tests — the kitchen now owns the static-web evaluator; first
local improve attempt failed because the model rewrote the existing tests —
Renovation now freezes existing tests.

Tests (`MEASURED`): `tests/orchestration/test_ikarus_kitchen.py` +
`test_ikarus_souschef.py`: 47 passed. Affected legacy suites (49 files) plus
the import census and HTTP wire-literal contracts: 1195 passed; the 3 failures
(`test_web_distribution` mirror, `test_ikarus_computer_autonomy`,
`test_ikarus_computer_history`) are identical on `origin/main` (host-specific
baseline). Import census re-pinned 526→537 modules / 2128→2149 edges with
**no new SCC** (14 components, max 19, digest byte-identical); read
wire-literal pin 740→758 for the `/api/kitchen` GET.

## What this packet does not claim

- No containment of builder agents (owner decision 2026-09-12); every evidence
  packet says `containment: deferred`.
- No promotion, merge or publication: results are nominated candidates and
  patches awaiting owner approval.
- Hashed embeddings are a reproducible baseline, not a learned model; retrieval
  quality is unmeasured against a baseline (Gate-3 obligation, untouched).
- The relation tensor is the kitchen's projection of the card graph, not the
  Twin `TensorView` contract; unifying them is follow-up work.
- Genesis blueprints (`item-collection-v1`, `kanban-board-v1`) remain the
  canonical `python.genesis` path; the kitchen is a Gate-1 product strand that
  produces real applications through builder agents.

## Follow-ups

- Route builder spawns through the sealed runtime bundle once containment is
  re-prioritised.
- Optional `nomic-embed-text` backend behind `embed()` with an A/B against the
  hashed baseline.
- Cockpit surface for `/api/kitchen` (Perdix/Iris).
- Copilot as an additional builder lane needs an adapter (no CLI exec mode on
  this host today).
