# G1 docs-drift audit — Cluster C1 (root instructions)

Repo: `C:/Users/Administrator/daedalus`, branch `main @ 54f09753` (per task
brief); measurements below were taken read-only against the working tree as
found, which matched `HEAD` for every audited file (`git status --short` /
`git diff --stat` empty for all five, confirmed individually for `CLAUDE.md`).

Scope: `README.md`, `CLAUDE.md`, `AGENTS.md`, `GUTEN_MORGEN_KAYA.md`,
`WATCHDOG_STATUS.md`. Dead-path checking is explicitly out of scope (a
separate tool owns that); this is claims only.

No files were modified. No test suite was run. All evidence commands below
are read-only (`grep`, `ls`, `git log`/`show`, `.venv/Scripts/python.exe -c`).

---

## Pre-note: CLAUDE.md contains no checkable claims at this revision

The task brief's calibration/special-note text describes a `CLAUDE.md` with a
LangGraph-orchestration section, a "measured 2026-09-01 ... 35 passed" claim,
and a Codex-vendor section. **That content is not in the file on disk.**
Current `CLAUDE.md` (verified via `Read` and cross-checked against
`git show HEAD:CLAUDE.md`, byte-identical, no working-tree diff) is:

```
# Daedalus project instructions

@AGENTS.md
@docs/IKARUS_ARIADNE_MASTER_PLAN.md
```

Four lines, no commands, no numbers, no behavior claims. There is nothing to
flag as drift in this file at this revision — it delegates entirely to
`AGENTS.md` and the master plan. (`git log -1 -- CLAUDE.md` → `15fbcd2b`.)

Since the special note's "35 passed" claim doesn't currently appear anywhere
in the audited cluster, it isn't reported as a finding below. For the record
only: `tests/test_langgraph_adapter.py` has 20 statically countable
`def test_` definitions plus four `@pytest.mark.parametrize` decorators (8,
2, 3, and one more of unmeasured arity), so a collected count of 35 is
arithmetically plausible but not verified — runtime collection was
**UNVERIFIED-BY-DESIGN** (pytest execution is out of scope for this audit).

`AGENTS.md` was also audited and produced no findings: every checkable
assertion in it (the iron-plan guard being unenforced, the amendments file
existing) measured true — see the CONFIRMED-clean note at the end.

---

## CONFIRMED

### [CONFIRMED] GUTEN_MORGEN_KAYA.md addresses a different repository on a different machine
- **File:line**: `GUTEN_MORGEN_KAYA.md:36-37, 67, 78`
- **Claim**: The letter instructs "you" (the owner) to run commands and edit
  files in `C:\Users\nukei\Desktop\agent_env_g0` and
  `agent_env/.claude/settings.json` as this session's actionable to-do list.
- **Measured reality**: This repository lives at
  `C:\Users\Administrator\daedalus`. No `agent_env` or `agent_env_g0`
  directory exists anywhere under any user profile on this machine. The
  referenced scripts (`docs/recovery/gate0_production_attest.ps1`,
  `docs/recovery/production_key_ceremony_kit.py`) do exist, but under
  `C:\Users\Administrator\daedalus\docs\recovery\`, not under the quoted
  `agent_env_g0` path. The file is either copy-pasted from a sibling
  session/machine or was written when this tree lived at a different path;
  either way its paths do not resolve here.
- **Evidence command**:
  `ls -d /c/Users/*/agent_env* /c/Users/Administrator/agent_env*` →
  `No such file or directory` (both patterns); `ls docs/recovery/gate0_production_attest.ps1 docs/recovery/production_key_ceremony_kit.py` →
  both present under `C:\Users\Administrator\daedalus\docs\recovery\`.
- **Misleadingness**: HIGH — a new reader following the file's own
  instructions literally would `cd` into a directory that doesn't exist on
  this machine.

### [CONFIRMED] GUTEN_MORGEN_KAYA.md states the wrong plan revision
- **File:line**: `GUTEN_MORGEN_KAYA.md:5-6`
- **Claim**: "Verfassung läuft auf Revision 5, der letzte rote Guard-Test ist
  grün." (the constitution/plan is running at Revision 5).
- **Measured reality**: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` header states
  `Revision: 11`, `Date: 2026-08-31`, `Active delivery gate: Gate 1`. The
  amendment chain has advanced through revisions 6-11 since this note was
  written (revision 8 alone — the Gate-0 closure — postdates this file by
  roughly a week; revisions 9-11 postdate it further).
- **Evidence command**: `head -10 docs/IKARUS_ARIADNE_MASTER_PLAN.md` →
  `Revision: 11`; `tail -3 docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
  → last accepted record is `"result_revision":10` dated
  `2026-08-30T15:28:24+02:00` (an 11th revision followed per the plan header
  date `2026-08-31`).
- **Misleadingness**: HIGH — a reader using this file to orient themselves on
  "where is the plan today" gets a number six revisions stale.

### [CONFIRMED] GUTEN_MORGEN_KAYA.md presents the Gate-0 sealing decision as still pending; it was already made
- **File:line**: `GUTEN_MORGEN_KAYA.md:43-47`
- **Claim**: "**③ Der Stempel**: ... Ob du die 13 Begründungen annimmst (→
  versiegeltes Approval nach `docs/GATE0_SEALED_OWNER_APPROVAL.md`) oder
  einzelne nachverdrahten lässt, ist DIE Abschlussentscheidung von Gate 0."
  — frames the Gate-0 closure call as the one decision still waiting on the
  owner, "today's" endgame.
- **Measured reality**: Gate 0 was closed as a scoped owner decision on
  **2026-08-26**, recorded as amendment revision 8
  (`docs/GATE0_CLOSURE_DECISION_20260826.md`, and
  `IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` record
  `"approval_ref":"conversation-2026-08-26-owner-seals-gate0-scoped"`,
  `"result_revision":8`). The master plan's own §11 now reads "Gate 0 —
  Canonical Kernel (closed 2026-08-26, scoped owner decision)" and "Active
  delivery gate: Gate 1". This closure record is dated after
  `GUTEN_MORGEN_KAYA.md`'s own internal timeline (it references the
  `gate0-closure-20260818` run directory and Watchdog Mission 2/3, i.e.
  2026-08-17/18), so the letter predates the very decision it asks the
  reader to make.
- **Evidence command**:
  `head -7 docs/GATE0_CLOSURE_DECISION_20260826.md` → "Status: **BESIEGELT**
  durch ausdrückliche Owner-Anweisung vom 2026-08-26"; `tail -3
  docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` (record with
  `"result_revision":8`) confirms the accepted amendment.
- **Misleadingness**: HIGH — the file's central call-to-action ("your
  endgame, exactly") is a decision that has already been made and recorded;
  a reader acting on this file would be re-litigating a closed question.

---

## PLAUSIBLE

### [PLAUSIBLE] WATCHDOG_STATUS.md's mission-summary numbers read as current state without a freshness banner
- **File:line**: `WATCHDOG_STATUS.md:1-2` (header) and `:359-360`
  (`Mission-Ziel erreicht: inventory_only 70 -> 12, ...`)
- **Claim**: A reader opening this file today (2026-09-02) sees a final
  "mission achieved" line — `inventory_only 70 -> 12` — with no date at the
  point of the claim itself (dates are attached to individual slice headers,
  e.g. "(2026-08-17)", not to the summary line).
- **Measured reality**: The file *is* internally self-labeled as historical
  ("Append-only. One paragraph per slice, with commit SHA and RAW test
  lines.") and every slice carries a date/commit SHA, so the convention is
  documented — this is why the finding is PLAUSIBLE rather than CONFIRMED.
  What could not be verified read-only within this audit's bounds is whether
  the registry's `inventory_only` count is still 12 at the current HEAD;
  confirming that requires running the gate-report tooling
  (`python -m daedalus.gates report` / `run_gate_checks`), which is a test/
  measurement run outside this audit's read-only mandate. The dated slice
  entries stop at 2026-08-17/18, roughly two weeks before today's date and
  three master-plan revisions (9, 10, 11) before the plan's current state.
- **Evidence command**: `grep -n "^#\|^---" WATCHDOG_STATUS.md | head` shows
  no file-level "last updated" or "superseded" banner; the file's own text
  ("Append-only... with commit SHA") is the only freshness signal, and it's
  a convention statement, not a per-line timestamp on the final summary.
  Registry-count reverification was **not run** (would require executing
  gate-report tooling, out of scope here).
- **Misleadingness**: LOW-MEDIUM — the append-only/dated-slice convention is
  genuinely present and would correct a careful reader, but the final
  headline number has no adjacent date and could be quoted out of context as
  "current."

---

## Audited, no findings

- **README.md** — every checked command/flag was verified against the
  actual argparse wiring and matched the doc: `daedalus.cli health --deep`
  (`daedalus/cli.py:248` `--deep`), `map --check` (docstring + `map` cmd
  dispatch to `daedalus/mapping/render.py`), `daedalus-chip status/scan/lint
  --tool {verilator,verible} --top/tcl {tclsh,vivado,quartus,yosys,
  openroad}` (`daedalus/chip_design/cli.py:1801-1884`, including the
  `--live` "retired" framing matching the doc's "raw `--live` form is
  refused" claim), `daedalus.file_bridge watch/enqueue/status --project/
  mark-read --all` (`daedalus/interfaces/bridge/cli.py:49-126`),
  `daedalus.cli offload --repo-root --paths` (`daedalus/offload.py:968-973`).
  The `[test]` extra / `pytest-xdist` / `-n auto --dist loadfile` measurement
  note is dated 2026-09-02 in both `README.md` and `pyproject.toml:55-74`
  (matching machine: AMD Ryzen 7 9800X3D) — internally consistent, not
  stale. The VS Code claim ("`agentOsHtml()` is the live webview,
  `dashboardHtml` has no live caller") checks out:
  `vscode-agent-env/extension.js:1897` assigns `webview.html =
  agentOsHtml(...)`, and `dashboardHtml` appears nowhere in `extension.js`,
  only in `DESIGN.md`'s own historical commentary. The repository-layout
  table's directories all exist (`daedalus/`, `daedalus/chip_design/`,
  `agents/`, `templates/`, `projects/`, `tests/`, `docs/`, `tools/`,
  `scripts/`, `experiments/`, `apps/`, `structcore-rs/`,
  `vscode-agent-env/`, `outbox/`, `inbox/`, `runs/`, `memory/`, `.room/`),
  and every linked doc path resolves (`docs/STATUS.md`,
  `docs/COMMS_PROTOCOL.md`, `docs/CONTINUOUS_DAEDALUS.md`,
  `docs/MISSION_CONTROL.md`, `docs/chip-design/README.md`,
  `docs/README.md`). `tools/docs_reference_check.py` exists.

- **AGENTS.md** — no commands, version numbers, or test counts to check; its
  one falsifiable factual claim ("nothing enforces [the plan] mechanically
  anymore (owner decision 2026-08-22)") was verified true:
  `tools/iron_plan_guard.py` does not exist on disk, and no hook in
  `.claude/settings.json` references it.

- **CLAUDE.md** — see pre-note above; the file currently contains no
  checkable claims (a 4-line stub delegating to `AGENTS.md` and the master
  plan).
