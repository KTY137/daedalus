# Cluster 7 — work-packet index vs. packet files

Auditor: lead (done in-session; worker slots reserved for other clusters).
Base: `main @ 54f09753`. Read-only. No tracked file modified.
Interpreter for all measurement: `C:/Users/Administrator/daedalus/.venv/Scripts/python.exe`.

Scope: `docs/work-packets/index.json`, `docs/work-packets/G1-WP-INDEX-01_TRACKED_WORK_PACKET_REGISTRY.md`,
and the repo-wide question "which packet IDs are referenced but have no packet document".

---

## CONFIRMED

### [CONFIRMED] `G1-HIER-13`, `-14`, `-15` are referenced but have no packet document at HEAD — HIGH for the reader of the branch brief, LOW for the reader of `target-layout.md`

- **Claim under test**: a chronicle packet reported that `G1-HIER-14` and `-15` are referenced
  while no packet doc exists. Verified, and extended to `-13`.
- **Measured reality**: the tracked `G1-HIER-*` set at HEAD is exactly
  `G1-HIER-01, 02, 02A, 02B, 03A, 03B, 03C, 03D, 04, 04B, 05, 06A, 06B, 06C, 06D, 06E, 07A, 07B, 08, 09, 10, 11, 12`
  — **23 files, `01` through `12` only**. `13`, `14`, `15` are absent.
  - `G1-HIER-13` is cited four times in `docs/architecture/target-layout.md`
    (lines 221, 414, 415, 511) — but that doc **explicitly marks it "not at HEAD"**
    and gives the `git show packet/g1-hier-13:...` recovery command. Honest.
  - `G1-HIER-14` is cited in `tests/contracts/test_import_scc_hierarchy.py:94`
    ("1624 -> 1630 in G1-HIER-14, the same repoint for all 33 `daedalus/runtimes`")
    — a **test comment attributes a measured constant to a packet that has no
    document**. This is the load-bearing case: the constant's justification is
    unreadable from the tree.
  - `G1-HIER-15` appears in **no tracked artifact other than `target-layout.md:517`**,
    which itself says it "appears in no tracked artifact found".
- **Evidence command**:
  ```
  ls docs/work-packets/ | grep -E "G1-HIER"          # -> 23 entries, 01..12 only
  grep -rn "G1-HIER-1[345]" docs/ tests/ --include='*.md' --include='*.py' \
      --exclude-dir=archive --exclude-dir=inventory
  ```
- **Misleadingness**: HIGH for anyone reading the "G1-HIER-01..15" range as a
  complete series (the brief's phrasing); LOW for a reader who arrives via
  `target-layout.md`, which already records the gap with a `[MEASURED]` stamp
  rather than papering over it. **`target-layout.md` is the doc that got this right.**

### [CONFIRMED] `index.json` does *not* declare `G1-HIER-13/14/15` at all — MEDIUM

- **Claim**: the registry claims "Every Git-tracked artifact under `docs/work-packets/`
  is represented exactly once" (`G1-WP-INDEX-01...md:12-14`).
- **Measured reality**: that claim is **true and holds** — `index.json`'s
  `counts.tracked_files == 278` equals the live file count, and
  `packet_artifacts (277) + registry_artifacts (1) == 278`. The registry is
  tracked-file-derived and therefore *cannot* see a packet ID that has no file.
- **Why it is still a finding**: the registry is a **file census, not a reference
  census**. It is silent by construction about IDs referenced from tests and
  architecture docs that never got a document. A reader who treats `index.json`
  as "the list of packets" will not learn that `G1-HIER-14` is cited as the
  authority for a constant in a live contract test.
- **Evidence command**:
  ```
  .venv/Scripts/python.exe -c "import json;d=json.load(open('docs/work-packets/index.json',encoding='utf-8'));print(d['counts'])"
  # {'assigned_artifacts': 275, 'legacy_artifacts': 204, 'packet_artifacts': 277,
  #  'packet_ids': 212, 'post_index_artifacts': 73, 'registry_artifacts': 1,
  #  'tracked_files': 278, 'unassigned_artifacts': 2}
  ls docs/work-packets/ | wc -l          # 278
  grep -c "G1-HIER-13" docs/work-packets/index.json   # 0
  ```
- **Misleadingness**: MEDIUM — the registry's own numbers are correct; the gap is
  in what it is *scoped* to see, which the doc does not say out loud.

### [CONFIRMED] The registry acceptance matrix quotes a command with bare `python` — HIGH

- **File:line**: `docs/work-packets/G1-WP-INDEX-01_TRACKED_WORK_PACKET_REGISTRY.md:56`
  > "1. `python tools/index_work_packets.py --check` exits zero only when the
  >  committed canonical JSON equals a fresh tracked-only measurement."
- **Claim**: a reader copy-pastes this to verify the registry.
- **Measured reality**: the tool and the `--check` flag both exist and are really
  parsed (`tools/index_work_packets.py:728`), so the *flag* is fine. But bare
  `python` on this machine resolves to the **Hermes agent venv
  (`...\hermes\hermes-agent\venv\Scripts\python.exe`, Python 3.11.15)**, not the
  repo venv (3.13.5). See the systemic finding below.
- **Evidence command**:
  ```
  grep -n "add_argument" tools/index_work_packets.py    # :728 mode.add_argument("--check", ...)
  python -c "import sys;print(sys.executable, sys.version)"
  # C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe 3.11.15
  ```
- **Misleadingness**: HIGH — this is the doc's *primary verification command*.

### [CONFIRMED — SYSTEMIC, repo-wide] Bare `python` in current docs runs the wrong interpreter; 52 quoted `python -m pytest` lines hard-fail — HIGH

- **Claim**: 215 command lines across 69 **current** doc files (archive/ and
  inventory/ excluded) instruct the reader to run `python -m ...`, `python tools/...`
  or `python -c ...`.
- **Measured reality**: bare `python` here is the Hermes agent venv, Python
  3.11.15, and **it has no `pytest` installed**. The repo interpreter is
  `.venv/Scripts/python.exe`, Python 3.13.5. Therefore every one of the **52
  quoted `python -m pytest ...` lines fails immediately** with
  `ModuleNotFoundError: No module named 'pytest'` — it does not run a reduced
  suite, it does not run at all.
  - Nuance, stated honestly: `python -m daedalus.X` *does* import (repo cwd is on
    `sys.path`, and `daedalus/__init__.py` resolves from the checkout in both
    interpreters), so those lines mostly work but silently execute under 3.11
    instead of the pinned 3.13.
  - Second nuance: PATH is operator-specific. This is measured on **this** box.
    On a box without Hermes the resolution differs. The finding is "the docs
    never name the interpreter", which is machine-independent.
- **Evidence command**:
  ```
  which -a python | head -8
  python -c "import sys;print(sys.executable);print(sys.version)"
  python -c "import pytest"           # ModuleNotFoundError: No module named 'pytest'
  .venv/Scripts/python.exe -c "import sys;print(sys.executable);print(sys.version)"
  grep -rlE '(^|[`$ ])python (-m|tools/|-c)' docs/ *.md --include='*.md' \
      --exclude-dir=archive --exclude-dir=inventory | wc -l     # 69 files
  grep -rnE '(^|[`$ ])python (-m|tools/|-c)' docs/ *.md --include='*.md' \
      --exclude-dir=archive --exclude-dir=inventory | wc -l     # 215 lines
  grep -rnE '(^|[`$ ])python -m pytest' docs/ *.md --include='*.md' \
      --exclude-dir=archive --exclude-dir=inventory | wc -l     # 52 lines
  ```
- **Misleadingness**: HIGH — and it is the single highest-yield fix in the whole
  audit, because it is one mechanical substitution across 69 files.

---

## PLAUSIBLE

### [PLAUSIBLE] `G1-GARDEN-CONTAINMENT-03` is declared a dependency but has no document — MEDIUM

- **File:line**: `docs/work-packets/G1-LOOP-TERMINAL-250.json:14` and
  `docs/work-packets/index.json:3231` both list
  `"G1-GARDEN-CONTAINMENT-03 branch history"` as a dependency.
- **Measured reality**: no `G1-GARDEN-CONTAINMENT-*` file exists under
  `docs/work-packets/`. The nearest tracked artifact is `G1-TWIN-GARDEN-01R.json`.
- **Why PLAUSIBLE not CONFIRMED**: the dependency string says "**branch history**",
  which may deliberately point at an unmerged branch rather than a HEAD document
  — the same honest pattern `target-layout.md` uses for `G1-HIER-13`. I did not
  enumerate remote branches to confirm the branch exists, so I cannot call this
  a dead reference.
- **Evidence command**:
  ```
  ls docs/work-packets/ | grep -i garden        # G1-TWIN-GARDEN-01R.json only
  grep -rn "G1-GARDEN-CONTAINMENT-03" docs/ --exclude-dir=archive --exclude-dir=inventory
  ```
- **Misleadingness**: MEDIUM.

### [PLAUSIBLE] `G1-IKARUS-07` and `G1-IKARUS-07D` referenced as bare IDs that exist only as sub-lettered packets — LOW

- **File:line**: `docs/work-packets/G1-IKARUS-06_CANONICAL_EFFECT_BRIDGE.md:80`
  ("G1-IKARUS-07 should connect one selected provider…") and
  `G1-IKARUS-07C_PROVIDER_RUNTIME_EXECUTABLE_BINDING.md:94`
  ("`G1-IKARUS-07D` should perform the actual broker cutover…").
- **Measured reality**: no `G1-IKARUS-07.md` or `G1-IKARUS-07D.md` exists, but
  `07A, 07B, 07C, 07C1, 07D1, 07D2, 07D3, 07D4, 07S` all do. Both sentences use
  the future modal "should", i.e. they were written as forward references and the
  work was later split into sub-packets.
- **Why PLAUSIBLE**: this is a naming-granularity artifact, not a false claim.
  A reader searching for "G1-IKARUS-07D" finds four successors immediately.
- **Evidence command**:
  ```
  ls docs/work-packets/ | grep "G1-IKARUS-07"
  ```
- **Misleadingness**: LOW.

---

## Not findings (checked and cleared — recorded so the next auditor does not re-derive them)

| Candidate | Verdict |
| --- | --- |
| `G1-IKARUS-01`, `G1-LEASE-01` "absent" | **False positive** of my ID-normalisation regex. Both files exist (`G1-IKARUS-01-supervisor-slice.md`, `G1-LEASE-01-ignition-crosses-its-boundary.md`) — they use a `-lowercase-slug` suffix instead of `_UPPER_SNAKE`. |
| `G1-TEST-01`, `G1-OTHER-01` | Synthetic fixtures inside `tests/contracts/test_work_packet_index.py`. Never intended as real packets. |
| `G1-IKARUS-16` | Appears only as a `.quarantine/` path inside `tools/docs_reference_check.py:133`. Out of audit scope by instruction. |
| `G0-RPT-08`, `G0-RTC-06`, `G1-HIER-03` | Prefix-truncation artifacts of family references (`G0-RTC-06` = the `06A..06Z` family). Sub-lettered members all exist. |
| `index.json` counts | **Accurate at HEAD.** `tracked_files: 278` == `ls docs/work-packets/ \| wc -l` == 278. Not drifted. |
| `G1-WP-INDEX-01`'s "204 artifacts / 140 Markdown / 64 JSON / 140 packet IDs" | **Correctly framed as a frozen baseline**, explicitly stamped to parent revision `151b8d180e321cfba48b4c7d62f9be56579d52a5` with a `paths_sha256`. 140+64 = 204 checks out. A live tree of 278/212 does not contradict a stamped historical baseline. Not drift. |

## Method note

Referenced-vs-present was computed as a set difference, not by reading:

```
ls docs/work-packets/ | sed -E 's/_.*//; s/\.(md|json)$//' | sort -u > present.txt
grep -rhoE 'G[0-5]-[A-Z]+(-[A-Z]+)?-[0-9]+[A-Z]?[0-9]?' docs/ *.md tools/ tests/ daedalus/ apps/ \
    --include='*.md' --include='*.json' --include='*.py' --include='*.ts' --include='*.tsx' \
    --exclude-dir=archive --exclude-dir=inventory --exclude-dir=node_modules --exclude-dir=dist \
  | sort -u > ref.txt
comm -23 ref.txt present.txt
```

14 raw candidates; 3 confirmed genuinely-absent-and-load-bearing (`G1-HIER-13/14/15`),
1 plausible (`G1-GARDEN-CONTAINMENT-03`), 2 granularity artifacts, 8 false positives.
The `sed` normalisation is the known weak point — it truncates at the first `_`,
which mis-handles the two `-lowercase-slug` filenames. Corrected by hand above.
