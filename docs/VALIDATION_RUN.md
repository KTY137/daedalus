# Validation Run — "sunny_garden" (Era 2)

**Date:** 2026-07-06 (overnight autonomous run) · **Branch:** `feat/api-webapp-agent-os`
**Question answered:** does the whole system work end-to-end on a real (friendly) project —
routing, live local writes, greenfield creation, quality gates, rollback, escalation, and the API layer?

**Verdict: PASS.** Every claim below is backed by git evidence in the demo repo or a
command run during the session (raw JSON: era2_results.json in the session scratchpad).

---

## The example project

`C:\Users\nukei\Desktop\sunny_garden` — a tiny plant-care tracker, registered as the
daedalus project `sunny_garden` (`projects/sunny_garden.json`):

- `garden/plants.py` (registry) · `garden/care.py` (logic) · `garden/cli.py` · `tests/test_care.py` (3 tests)
- Own policy in `.agentenv/agentenv.json`: allow `garden/ docs/ tests/ .md`, deny `.agentenv/`,
  high-risk terms `architecture, rewrite, state machine`; test gate `python -m unittest discover tests`
- Own crew in `.agentenv/agents/`: **flora** (plants), **rune** (care), **quill** (README),
  **chronicle** (CHANGELOG), **tippy** (docs/), **probe** (tests/) — all repo-local,
  routed via the Era-1 `repo_root` threading fix
- git-initialized with a baseline commit (`94b16c9`) so every write is provable

## The live sweep (Ikarus → real qwen2.5-coder:7b, 138 s wall)

| agent | mode | outcome | wrote (disk truth) |
|---|---|---|---|
| flora | write | **escalated_after_verify_fail** | — (rolled back) |
| rune | write | offloaded | `garden/care.py` |
| quill | write | offloaded | `README.md` |
| chronicle | write | offloaded | `CHANGELOG.md` |
| tippy | write | offloaded | `docs/watering_tips.md` ← **greenfield CREATE** |
| probe | write | offloaded | `tests/test_care.py` |
| (high-risk task) | write | **bounced to Claude** | — |

**git proof** (uncommitted working-tree changes after the sweep):

```
 CHANGELOG.md       |  5 ++++-
 README.md          | 10 +++++++++-
 garden/care.py     |  2 ++
 tests/test_care.py |  5 +++--
 4 files changed, 18 insertions(+), 4 deletions(-)
untracked: docs/watering_tips.md
```

Garden suite after the sweep: **4 tests OK** (was 3 — qwen wrote a *working* new unit test).

## What each outcome validates

1. **Real local writes** — 4 in-place edits landed and passed gates (`did_work` verified on
   disk via content-hash snapshot; syntax gate on the .py files; project test suite green).
2. **Greenfield CREATE** (new Era-1 capability) — `docs/watering_tips.md` did not exist;
   the rewrite path created file + directory; rollback support covered by unit test.
3. **Test-gate rollback (the star of the run)** — flora added `basil` to `PLANTS`, which
   *broke* `test_plan_covers_all_plants` (it pins the exact plant set). The gate failed,
   the write was **rolled back cleanly** (`wrote: []`, file byte-identical), the task
   escalated to Claude. That is precisely correct: the task was underspecified (the test
   needed updating too) — senior work.
4. **Fail-closed risk routing** — "rewrite the whole architecture …" was bounced to the
   senior lane before any local model ran.
5. **Honest reporting** — every "wrote" cell above comes from `result["wrote"]`
   (before/after disk snapshot), not from model self-reports or `action == offloaded`.
6. **API layer end-to-end** — with the server up (`python -m daedalus.web_api`):
   `GET /api/dashboard?project=sunny_garden` (ok, project listed) ·
   `GET /api/projects/sunny_garden/hierarchy` (30 nodes / 65 edges; all 6 agents) ·
   `POST /api/queue` (queued with lane + category). No secret values in any response.

## Era-1 fixes this run exercised (commit `569219c`)

| Fix | Where | Validated by |
|---|---|---|
| `wrote` ground-truth field | `offload.py`, `ikarus.py` | every table row above + `tests/test_era1_robustness.py` |
| `repo_root` → routing | `provider_router.py`, `ikarus.py` | 6 repo-local agents routed (previously `RuntimeError`) |
| greenfield CREATE | `providers/ollama.py` | `docs/watering_tips.md` + unit tests |
| `.js`/`.html` verify gates | `verifier.py` | unit tests (truncation tripwire, `node --check`) |

## Known limits (honest)

- The bench remains **single-file-rewrite-scoped** (≤3 files, ≤24k chars) — multi-file
  features stay frontier work by design.
- The advisory lane produces drafts that currently land in the result report only; no
  automated "Claude applies the draft" step yet.
- `test_cwd` other than repo root is supported but not exercised by this run.

## Repro

```
python -m unittest discover tests            # 212 green (daedalus repo)
python <scratchpad>/era2.py                  # rebuilds + re-runs the sweep (destructive to the demo repo)
python -m daedalus.web_api                   # then hit the endpoints above
```
