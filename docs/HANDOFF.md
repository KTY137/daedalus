# Daedalus — Session Handoff (2026-07-20)

## TL;DR
Correctness-and-speed session, run with **Codex working the frontend in parallel**. Four crashes/regressions
found and fixed, the scan is **2.47× faster warm** (76× on the per-file phase), Rust reached **parity**, Ikarus
**streams**, and a CERN/HEP research pass produced an 11-item defect list that applies far beyond HEP.

**The single most important finding is not a feature — it's a diagnosis.** The scan is CPU-bound Python running
*inside* the web server, so the GIL starves every other request for the whole scan. That one mechanism explains
the frozen UI, the crash on panel-switch, and Claude vanishing from the Ikarus picker. **Fixing it is the top
priority and is the next task.** See §4.

**Suite: 390 passing. Eval: 100% recall @ 79.0% compression** (tokenizer-exact, tiktoken 0.13.0 installed).

---

### Session 2 addendum (same day)

- **§4 is CONFIRMED and sharpened** — measured across a full 216s scan, not inferred. It is *not* a spin-loop,
  and the culprit is specifically the **clone passes**; the per-file phase already runs out-of-process and
  starves nothing. See §4. *A first measurement sampled only the first 20s of a cold scan and looked like a
  disproof — sample the whole scan or you measure the wrong phase.*
- **Project scope shipped** (`center` + `.daedalusignore`) — see §4b. On project_tct: **171.0s → 22.3s
  (7.68×)**, and **93% of the duplication report was noise**; hotspots had been ranking vendored Printrun,
  wxPython and Cython files instead of the app. **7.68× from ~40 lines of Python vs 2.1× for the entire Rust
  engine — scoping the input beats optimizing the kernel.**
- **Suite: 415 passing** (390 + 25 new scope tests).

---

## 1. Git state (READ THIS FIRST)
- Branch **`checkpoint/2026-07-20-session`**, checkpoint commit **`a98e2b1`**. `main` is untouched.
- The checkpoint was taken mid-session as a recovery point while two agents wrote `apps/web` concurrently.
  **~13 files changed after it** (scan parallelization, cache/perfile, eval fixture, pyproject, CSS, Codex's
  frontend). Commit or review before doing anything destructive.
- `.gitignore` gained `target/`, `.captures/`, `.edge-capture/`. **`structcore-rs/target/` is ~0.6 GB and was
  NOT ignored** — `git add -A` would have committed it. Check before any bulk add.
- Stray artifact committed: `ui-baseline.png` at repo root (a Codex screenshot). Safe to delete.

## 2. What shipped (all verified, not claimed)

**Crashes / correctness**
- **RecursionError killed every large scan.** `parse.py` + `imports.py` walked the tree-sitter AST recursively;
  deeply nested real ASTs blew Python's 1000-frame limit and took down the whole `/api/structure` request. Both
  are now iterative pre-order walks (`stack.extend(reversed(node.children))` preserves source order).
  *The old 60s project_tct number in the previous handoff was measuring a run that crashed early.*
- **Single-flight lock on `cached_index`.** The cache only populated *after* a build finished, so every
  concurrent caller started its own full 6.8k-file scan. Switching panels mid-index spawned a second scan and
  took the page down. Verified: 6 concurrent callers → 1 build.
- **`runtime_registry._run_version` spawned the bare command name**, not the resolved path. npm ships `codex` as
  a `.CMD` shim and CreateProcess can't launch it by name (WinError 2), so codex reported unavailable while
  installed and logged in. `claude`/`ollama` are real `.EXE`s — which is why only codex broke.
- **Two determinism bugs, both pre-existing**, caught by seed-varying the parallel scan:
  `fan_in` tie order inherited hash order; and **ambiguous import resolution produced *wrong edges***
  (`AVR/MarlinSerial.cpp` → `AVR/MarlinSerial.h` under one seed, `DUE/MarlinSerial.h` under another). Both fixed
  by iterating `sorted(...)`. **`agent_env` cannot expose this class of bug — it has no duplicate basenames.**
- **The wheel shipped without the engine.** `pyproject.toml` listed only `daedalus` + `daedalus.providers`;
  explicit lists disable auto-discovery, so `daedalus.structcore` and `daedalus.eval` were absent from any
  non-editable `pip install .`. Invisible locally because everything uses `-e`.

**Speed (engine)** — `daedalus/structcore/perfile.py` + `cache.py` are new
- project_tct 6,799 files: **252.0s → 154.0s cold (1.64×) → 102.0s warm (2.47×)**. Per-file phase
  **145.5s → 1.9s (76×)**. agent_env: 3.90 → 2.13s warm.
- `_lizard_cc` was **72%** of `file_metrics` (a whole separate tokenizer chain, 963k calls). A duplicated
  `ast.parse` per Python file also existed but was worth only **~2%** — an earlier *contended* run made it look
  like 1.71×; those numbers were discarded.
- Content-hash keyed disk cache in `%LOCALAPPDATA%\daedalus\structcore` (43 MB / 6,799 files). Keyed on content,
  not mtime, so staleness isn't representable. LRU-bounded to 20 DBs.
- Knobs: `DAEDALUS_NO_CACHE=1`, `DAEDALUS_CACHE_DIR`, `DAEDALUS_SCAN_WORKERS`, `DAEDALUS_SCAN_MIN_PARALLEL`.
- **Determinism is load-bearing and enforced**: the 40.7 MB index is byte-identical across 4 `PYTHONHASHSEED`s ×
  4 execution paths. `all_units` is consumed *positionally* by the clone passes, so parallel results are
  index-tagged and written into preallocated slots — never appended in completion order.

**Movement II (code map)** — shipped end-to-end
- `index.py` exposes `import_edges` (unified rel→rel, all languages) and `module_heat` (full ranking;
  `hotspots` is now `module_heat[:15]`). `report.py` exposes `graph` (nodes/edges/totals/`truncated`).
- **It deliberately does NOT reuse `dependencies`/`fan_in`** — those key Python by *dotted module name* and
  everything else by rel path, so they cannot be joined against `modules`. The map recomputes its own fan-in.
- `CodeMap.tsx`: Sigma.js v3 + graphology, ForceAtlas2 in a real Worker. Heat uses `log1p` (heat is long-tailed;
  linear flattens everything below the top file). Size = `fan_in`, not `loc` (`score` already folds in
  complexity). Truncation is stated in the UI, never silent.

**Ikarus latency** — `GET /api/ikarus/stream` (SSE: `start` / `delta` / `final`)
- Ollama evicted→warm: **44,487ms → 1,386ms**. Full turn: 21.5s blank → first text at **3.4s**. Claude: 14.7s
  blank → first text at 13.4s.
- **`keep_alive` is silently dropped by `/v1/chat/completions`** — it must go to native `/api/generate`. The
  naive implementation looks correct and does nothing.
- **The client MUST call `es.close()` on `final`** — EventSource auto-reconnects on server close, which re-runs
  the whole chat turn and re-spends.
- **Claude warm-start is not viable** (measured, not assumed): pre-spawned `claude -p` blocks on stdin and never
  reaches init. The ~13.4s floor is irreducible without leaving the CLI for the API.

**Rust engine** — tree-sitter structural normalization replaces the lexical one
- Cluster-membership parity: **100% agent_env, 96.87% project_tct → 99.96%** excluding 4 files Python's
  `ast.parse` rejects outright. **Zero normalization-attributable diffs remain.**
- **Rust is only ~2.1× faster, not 14×.** The old 14× came from the *lexically* normalized (incorrect) version;
  correctness ate the speedup. project_tct: oracle 5m59s vs Rust 2m52s. **The roadmap must be re-scoped: Rust is
  worth finishing for the Tauri story, but it is NOT the performance answer.**
- Caught along the way: the first tree-sitter attempt **fabricated clone clusters** (tree-sitter-python exposes
  only `escape_sequence` children of string content, so literal text between them vanished). Merging code that
  isn't duplicated is this product's worst failure mode.
- Still unported: T2/T3/window clusters, hotspots, dependencies, metrics.

**Frontend (Codex, parallel session)**
- Startup JS **580 KB → 198 KB** (gzip 171 → 63 KB); CSS 59 → 44 KB. Network + WebGL map lazy-load behind their
  panels. Request timeouts, progressive loading, `Ctrl/Cmd+K`, `Esc`.
- **Fast mode is now default OFF** (`loadPerformanceMode`). The glass surface is the product identity, and blur
  was never the deep cost — see §6.

**CSS fixes**
- `.dockbtn { place-content: center }` — the legacy `nav button` rule sets `justify-content: flex-start`, and
  `Dock` renders a `<nav>`. `place-items` does **not** cover this: it sets `justify-items` (icon within its
  track) while `justify-content` places the *track*, which was parked flush-left.
- `.railcard { flex-shrink: 0 }` — cards compressed instead of letting the rail scroll.
- `.rail .inspector { flex-shrink: 0 }` — **caused by the fix above.** Once the cards stopped shrinking, the
  Inspector became the only shrinkable child, and it has `overflow:auto` so its automatic minimum resolves to 0:
  it collapsed to a hairline and could not be scrolled to. *Never leave a scroll container as the only
  shrinkable item in a flex column.*

---

## 3. How to run / verify
- **App:** `python -m daedalus.cli web` → http://127.0.0.1:8765. Dev: `cd apps/web && npm run dev` (5173).
- **Suite:** `python -m pytest -q` → **390**. *`tests/test_ui_contract.py` fails under load* — it starts its own
  server and times out if another scan is saturating the box. Kill stray servers and re-run before believing it.
- **Eval:** `python -m daedalus.eval` → **100% recall / 79.0% compression**.
- **Structural CLI:** `python -m daedalus.structcore <repo>` · `python -m daedalus.structcore.slice <repo> <file[::symbol]>`
- **Rust:** WinLibs MinGW env vars are required in every shell — see §6.

---

## 4. NEXT TASK: get the scan out of the server process

**This is the top priority.** Diagnosed and measured, not hypothesised:

| endpoint | fresh process | over HTTP during a scan |
|---|---|---|
| `/api/runtimes/status` | 0.54s | **18–21s** |
| `/api/dashboard` | 1.64s | **26–40s** |

Server measured burning **96% of one core continuously** while nominally idle, 768 MB resident. Neither endpoint
is slow — they are **GIL-starved** by `build_index` running CPU-bound in a `ThreadingHTTPServer` thread.

Downstream, all one bug:
- The cockpit freezes during indexing.
- `request()` aborts at 20s (`api.ts:3`), so `/api/runtimes/status` lands *straddling* the timeout →
  `setRuntimes` never fires → `runtimes` stays `[]` → **`runtimes.filter(r => r.available)` renders nothing but
  "deterministic", i.e. Claude disappears from the Ikarus brain picker.** Intermittent, not broken.
- `test_ui_contract` timeouts.

**Speeding the scan up does not fix this** — 102s of in-process CPU still freezes everything for 102s.

**Design:** `POST /api/structure/scan` → returns a job id immediately; scan runs in a **subprocess** (not a
thread — the GIL is the whole problem); progress pushed over the existing `/api/events` SSE channel;
`GET /api/structure` returns a cached result or `{status: "scanning", progress}` instead of blocking.

**CONFIRMED 2026-07-20 (session 2), and sharpened.** Measured against a live server (PID sampled over a full
216s scan, `Get-Process().TotalProcessorTime` deltas + latency probes):

| state | server CPU | RSS | `/api/runtimes/status` |
|---|---|---|---|
| idle, never scanned | 0% | 76 MB | 0.51s |
| **during clone passes** | **91–116% of one core** | **768–791 MB** | **20.4s / 12s / 16.2s / 17.9s** |
| after scan returns | 0% | 452 MB | 0.51s |

- **Not a spin-loop.** CPU drops to 0% the moment the scan returns, so the "96% while nominally idle"
  reading was a scan in progress, not a runaway loop. The §4 restructure is the right fix.
- **The culprit is specifically the CLONE PASSES, not `build_index` as a whole.** The per-file phase already
  runs in a `ProcessPoolExecutor` (`index.py:153`), so it does *not* starve anything — a first measurement
  that sampled only the first 20s of a *cold* scan saw 5% CPU and 0.45s latency and looked like a
  disproof. **Sample the whole scan, or you will measure the wrong phase.**
- Practical consequence: whatever moves out of process only needs to cover the clone passes to fix the
  freeze, though moving all of `build_index` is simpler and no worse.

## 4b. PROJECT SCOPE — shipped session 2, and it changes the perf story

`center` + `.daedalusignore` (`daedalus/structcore/ignore.py`, docs/PROJECT_SCOPE.md). Declare which subtree
IS the project; everything else in the repo is **shell** — still indexed and still resolvable as an import
target, but withheld from metrics and not expanded through by the slicer.

`project_tct` with `center: ["TCT_app"]` (now set in `projects/project_tct.json`):

| | whole repo | center=TCT_app |
|---|---|---|
| wall | 171.0s | **22.3s (7.68×)** |
| core files | 6,798 | 385 |
| exact clone clusters | 2,794 | 196 |
| `import_edges` | 8,558 | **8,558 — unchanged** |

- **93% of the duplication report (11,001 of 11,859 clusters) contained no `TCT_app` file at all.**
- **Hotspots were pointing at the wrong codebase entirely** — top 4 were Printrun, wxPython `.pyi` stubs,
  Cython's `ExprNodes.py`, and Marlin firmware. The product's headline question ("what should I distill?")
  was answering about vendored dependencies.
- **7.68× from ~40 lines of Python, versus 2.1× for the whole Rust engine.** Scoping the input beats
  optimizing the kernel. Re-check this ordering before spending on either.
- Slice fan-out is fixed as a side effect: `slice._py_maps` reads from `modules`, and shell files are not in
  `modules`, so the slicer cannot expand through the boundary.
- ⚠️ **Rust does not know about any of this.** `structcore-rs/src/index.rs` has its own `const IGNORE`
  hand-mirroring `_IGNORE_DIRS`; the two engines will now disagree about the same repo. Scope must become a
  shared contract before the Rust engine is user-facing.

## 5. Backlog, in recommended order

1. **Scan job / subprocess** — §4. Makes the app stop freezing. Also delivers the "index in the background"
   request directly. Now confirmed to be the clone passes specifically.
2. **Set `center` on every project** — §4b. Cheapest large win available; `sunny_garden` still unscoped.
   Consider warning in the UI when a repo has no center and >2k files.
3. **S1 + S2 (~23 lines, unblocks all C/C++)** — see §7. Highest value-per-line in the codebase.
4. **Clone passes are now 96% of a warm scan** (near 38.3s + renamed 37.8s + unit 17.8s + window 4.6s of 102s).
   Per-file optimization is spent; this is the only remaining speed lever *within* the engine — but §4b shows
   scoping the input is worth more than optimizing the kernel, so do that first.
5. **`resolve_internal` accuracy** — now deterministic but prefers the lexicographically-first candidate, which
   is frequently wrong (`TEENSY40_41/HAL.cpp` binds `AVR/timers.h`). Prefer a same-directory sibling. Changes
   output, so it needs its own task + eval.
6. **Wire the streaming UI** — `/api/ikarus/stream` exists and is unused by the frontend. Remember `es.close()`.
7. **Ikarus chat cost**: `_claude()` inherits the server cwd, so every message loads the repo's CLAUDE.md +
   memory + skills — measured **25,666 cache-creation tokens, $0.28 for "say hi"**. Agreed fix: run from a
   neutral cwd and inject a *distilled slice* when the question needs project knowledge. Dogfoods the product.
8. **Codex as an Ikarus chat brain** — the picker offers it; `_llm()` returns `None` for it and silently drops to
   the deterministic layer. `providers/codex_cli.py` exists but is task/report-shaped (timeout 1500s), not chat-
   shaped. Needs a chat path **plus** an egress-gate decision: Codex sends code to OpenAI.
9. **Remaining layout audit findings**: `.draft-row` inherits `.feed-row`'s 92px grid track (its `flex:1` is
   inert — the parent is a grid), squeezing drafts to ~6 visible chars; topbar `.iconbtn` lacks `flex:none` and
   deforms into ovals under ~700px.
10. Eval Tier-2 (LLM A-vs-B), Movement III (orchestration loop), Movement V (Tauri).

---

## 6. Performance facts worth not re-deriving

- **Blur is not the bottleneck, and there is no blur stacking to remove.** Five real `backdrop-filter` surfaces,
  none nested, 21 explicit `backdrop-filter: none` overrides. `GlassPanel` — the one component that could have
  nested blur inside a sheet — is **dead code**. A static blurred surface rasterizes once and stays cached.
- **What actually prevents the compositor idling: four `infinite` animations** — `breathe` on 4 live dots,
  `sheen`, `think`, `struct-spin`. They run even when nothing is happening, so the blur never stays cached.
  The fix is gating them on real activity, not deleting glass. `prefers-reduced-motion` already handles a11y.
- `--blur: 22px` + `saturate(180%)` is a large radius; ~12px would be visually subtle and materially cheaper.
- **Rust: 2.1×, not 14×.** See §2.
- **Measure uncontended.** Several numbers this session were wrong because agents were saturating the CPU. The
  1.71× → 2% correction is the cautionary example. Kill background work before benchmarking.

## 7. CERN / HEP research — verdict and the defect list

Full document: the workflow output; the plan section was extracted to scratch during the session. **18 research
claims were corrected by an adversarial verification pass** — treat unverified lane claims with suspicion.

**Verdict: a proving ground and credibility source, not a market. Plan for zero HEP revenue.** No CIO, no budget
line, no procurement path; adoption is one postdoc at a time. The value is a brutal correctness forcing-function
plus citable credibility that transfers to regulated-enterprise buyers (which the codebase's own `/hv/`,
`interlock`, `motion/`, `volatile`, `__asm` vocabulary suggests was the original target).

**Local-first/BYOK is a licence to operate, not a moat.** CelloAI (arXiv:2508.16713, HEP-CCE/Brookhaven) is
already a locally-hosted RAG assistant over ATLAS/CMS/DUNE code with tree-sitter chunking and Doxygen callgraphs,
whose stated rationale is verbatim ours. aider has shipped a PageRank-ranked tree-sitter repo-map since 2023, free.
The defensible claims are narrower: **procurement avoidance** (CERN requires a DPIA + Cloud Licence Officer review
before any external AI service) and **unpublished/blinded analysis code** — not "your code never leaves the
machine", which is falsified by CMSSW/ROOT/Athena being public on GitHub and in every model's training set.

**Corrections worth carrying:** ATLAS *already* runs Lizard complexity trending over 219k functions
(J.Phys.Conf.Ser. 1085 032047 §3.3) — "nobody does churn×complexity" is too strong; **clone clustering is the
genuinely uncontested ground**. And the Windows case-sensitivity worry is **unfounded**: NTFS is case-preserving,
`Path("Macro.C").suffix` returns `.C` intact. Only the `.lower()` in `languages.py` destroys the signal — but do
not simply delete it, `.CPP`/`.PY` resolve *through* that fold. Required shape is exact-suffix-first with a
lowercase fallback.

**Defect list (verified against the tree):**
- **S1 — `_ts_name` cannot name a C/C++ function** (`parse.py:139`). It scans *direct* children; C/C++ nests the
  name under `declarator → function_declarator`. Blast radius: **Type-3 detection entirely dead for C/C++**
  (`clones.py` filters `name != <anonymous>`), `file.cpp::Func` never resolves (silently degrades to whole file),
  and the call graph is empty (all units collide on `<anonymous>`). On templates it grabs the *return type*.
  **~8 lines. CUDA inherits it the moment it ships.**
- **S2 — the distilled slice is Python-only in practice** (`slice.py:68`, and the whole expansion behind
  `if tgt_dotted:`). For non-Python targets the neighborhood stays empty and the slice degrades to the focus
  file — *even though `import_edges` is already computed correctly*. **The feature the product is named for does
  not work outside Python. ~15 lines**, routed through `idx["import_edges"]` + a reverse index.
- **S3 — `.h` resolves to the C spec.** On C++ headers the C grammar *manufactures phantom units and loses real
  ones* (emitted a unit literally named `namespace`). ~26,000 `.h` files across ROOT + CMSSW.
- **S4 — `.C` resolves to the C spec.** `.C` is C++ (GCC's own suffix list); in ROOT it is Cling-interpreted C++.
- **S6 — silent truncation at `max_files=20000`.** CMSSW is 62,383 files: you'd analyse an arbitrary
  `os.walk`-ordered third and report duplication as if complete. `report.py` already has the `truncated` pattern.
- **S7 — churn silently vanishes on large repos.** `churn.py` hardcodes `timeout=30.0` and returns `{}`; on
  ATLAS-sized history "churn × complexity" degrades to complexity-only with no user-visible signal.
- **S8 — memory.** `all_units` holds full source text of every unit; ~22.5× source bytes here, projected ~790k
  units for CMSSW. The only weeks-long item, and the gate on any "HEP-ready" claim.
- **S9 — the safety fence false-positives on physics vocabulary.** `scan`, `bias`, `motion` are industrial-controls
  terms in the origin domain and *physics* terms in HEP, so `Analysis/MassScan/` gets stamped judgment-gated.
- **S11 — `safety_content` is dead data.** Declared in `languages.py`, populated in 7 specs, **zero readers** —
  and the module docstring claims the fence uses it. Real content rules live in `sensitivity.GENERIC_DENY_CONTENT`.
- **S5 was a FALSE POSITIVE** — both `c_sharp` and `csharp` grammars load fine; the research hit a transient
  download failure.
- **Fixed already:** S10 (the wheel shipped without `structcore`/`eval`).

**Structural facts about HEP code that change the engineering:** ROOT *unnamed* macros are a bare top-level
`{ ... }` with no function definition — a function-level detector extracts **zero units and reports nothing
wrong**. *Named* macros require one function per file matching the filename, so function-level granularity
collapses to file-level and the symbol slice degenerates to `cat`. ROOT 6 macros generally carry **no `#include`**
(Cling autoloads), so the import graph renders as disconnected dots *and looks like a correct answer*. RDataFrame
JIT-compiles physics logic **inside string literals** (`df.Filter("x>0")`) — mandatory from Python — so the
analysis logic is invisible to every parser we have. And `TTree::MakeClass` skeletons will be the **largest,
highest-confidence clone clusters** while being generated, unactionable noise.

**The safety claim has a hole, independent of HEP:** `slice.py` imports nothing from `daedalus.sensitivity`. The
assembled slice reaches `web_api.py` and `eval/harness.py` **ungated**, and `sensitivity.py` deliberately bypasses
the gate for "trusted" lanes (Claude, Ollama) — exactly the BYOK path a privacy-conscious user takes. Fix before
any privacy claim appears in external material.

---

## 8. Gotchas (hard-won today — do not relearn)
- **Stale `daedalus.cli web` servers on 8765 cost two false diagnoses.** A new server that fails to bind stays
  alive and unbound while an old one serves stale code. Always verify the *listening* PID is the one you started:
  `Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like '*daedalus*web*' }`.
  The CLI should fail loudly on bind conflict — it doesn't yet.
- **Killing the server out from under a live user looks exactly like an app bug.** It presented as "indexing
  failed / Failed to fetch". Ask before restarting 8765 if someone is using the app.
- PowerShell `Set-Location` doesn't change the .NET CWD → pass `-WorkingDirectory` to `Start-Process`.
- **PowerShell has no heredocs.** Write commit messages to a file and use `git commit -F`.
- `[regex]::Escape(...)` + `Select-String -SimpleMatch` silently matches nothing (escapes the space). This
  produced a false "Codex clobbered my CSS" alarm. Verify with `git diff` before accusing.
- The Grep tool renders `/*` as `\*` in output — that is display, not a CSS syntax error. Read the file.
- **Benchmark uncontended** (see §6).
- **Python `structcore` is the reference oracle — with a documented blind spot.** `ast.parse` is all-or-nothing,
  so files it rejects yield *zero* units while tree-sitter error-recovers and finds real clones. On those files
  **Rust is more correct.** Do not "fix" Rust to match Python's blindness.
- **Test on `project_tct`, not just `agent_env`.** agent_env has no duplicate basenames and structurally cannot
  expose the ambiguous-import class of bug.
- Near-clone bounds remain load-bearing: `min_shared_rare=4`, `max_cluster=30`, `_MIN_BAG=12`, ubiquitous cutoff
  `max(3, 0.4·n)`.
- Rust toolchain: rustup **GNU** host + **WinLibs MSVCRT** MinGW; export `PATH`, `CC_x86_64_pc_windows_gnu`,
  `AR_x86_64_pc_windows_gnu` in every shell. `walkdir` was removed deliberately (pulled in `windows-sys`→`dlltool`).
- BYOK, SAFETY-CLASS fence, additive-only endpoints, `/api/dashboard` frozen by `test_ui_contract` — all still hold.
- **Plan:** `C:\Users\nukei\.claude\plans\ast-driven-distillation-harness-modular-sprout.md` · **Memory:**
  `daedalus-agentos-moonshot.md`
