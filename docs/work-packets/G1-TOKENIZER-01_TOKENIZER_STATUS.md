# G1-TOKENIZER-01 - The canonical token counter reports its own status

Packet ID: `G1-TOKENIZER-01`
Artifact role: `primary`
Status: `built; builder-verified; awaiting independent review; not merged`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `24e229c0f34e5404bc219637b646386529f82035`
Dependencies: `none`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet cannot open, enter, or satisfy Gate 3.

## Primary acceptance claim

**One** claim: *`daedalus.structcore.tokens` reports, per process, whether its
counts are BPE-exact or a `chars/4` heuristic, and reaches `exact=True` only
by measurement (the loaded encoder reproduces pinned probe ids), never by
declaration; and Daedalus code never triggers tiktoken's BPE download.*

Why this matters (plan §4 invariant 9, §11 Gate 3 "tokens" measure): G3-BASE-01
finding F2 recorded that every token count in this repository was a heuristic
because the project venv has no `tiktoken` and the old `_encoder()` swallowed
every exception into `None` without saying so. A count that cannot say whether
it is exact cannot be a budget denominator.

G3-BASE-01 finding F2 motivates this packet; nothing depends on it yet.

What this packet is **not**:

- not a change to which tokenizer is canonical (`cl100k_base` stays; it is an
  OpenAI tokenizer and is *not* the tokenizer of the Claude or Ollama models
  this repository drives -- `daedalus/providers/ollama.py:768` already says it
  over-counts qwen tokens);
- not a claim that `chars/4` is comparable to a BPE count (it never is; the
  status makes the difference visible instead of hiding it);
- not Gate-3 evidence and not a sealing mechanism.

## Scope

In scope (exact file ownership):

| Path | Change |
| --- | --- |
| `daedalus/structcore/tokens.py` | `TokenizerStatus`, `TokenizerDegradedWarning`, `tokenizer_status()`, cache-only probe, fallback counter; `_encoder()` / `tokenizer_name()` become views over the cached status |
| `daedalus/eval/harness.py` | lines 52-59: dead `try/except` import replaced by one unconditional import of `count_tokens, tokenizer_name, tokenizer_status` (structcore is imported unconditionally at lines 47-50, so the `except` branch could never run) |
| `pyproject.toml` | new extra `tokenizer = ["tiktoken==0.14.0"]` after `root` |
| `uv.lock` | adds `tiktoken 0.14.0` and `regex 2026.9.3`; `requests` chain reused |
| `tests/test_tokenizer_status.py` | new, 21 tests |
| `docs/work-packets/G1-TOKENIZER-01_TOKENIZER_STATUS.md`, `docs/work-packets/index.json` | this document and the registry render |
| `tests/contracts/test_work_packet_index.py` | moving-census pins only |

Forbidden and untouched: `daedalus/kernel/**`, `daedalus/spine/**`, the plan,
amendments, `AGENTS.md`, `CLAUDE.md`, `.agentenv/`, every `count_tokens`
caller (`daedalus/providers/ollama.py`, `daedalus/council/session.py`,
`daedalus/council/vendors.py`, `daedalus/eval/tier2.py`), the `test` extra.

Invariants kept byte-for-byte: `count_tokens` never raises; the two name
literals `tiktoken/cl100k_base` and `chars/4 (heuristic)`; the heuristic
`max(1, len(text) // 4)`; importing the module does no work.

## Contracts and behavior

```text
TokenizerStatus (frozen dataclass)
  name            "tiktoken/cl100k_base" | "chars/4 (heuristic)"
  exact           bool   True iff degrade_reason is None iff probe_digest is set
  library         "tiktoken <version>" when importable, else None
  degrade_reason  None when exact, else a sentence naming the cause
  probe_digest    sha256(canonical JSON of PROBE_IDS) when exact, else None
  bpe_cache_path  the resolved cache file that was checked, also when absent;
                  None only when tiktoken is missing or its cache is disabled
  heuristic_fallback_calls   property: live read of the module counter
  as_dict()       plain dict including the live counter, for receipts
```

`tokenizer_status()` is `lru_cache(1)`, computed lazily, and decides in this
order. Each row is a visible degrade path, never a silent one:

| Step | Condition | Result | Warning |
| --- | --- | --- | --- |
| a | `import tiktoken` raises `ImportError` | heuristic, reason `tiktoken not installed` | none (documented optional extra) |
| b0 | `TIKTOKEN_CACHE_DIR` or `DATA_GYM_CACHE_DIR` set to `""` | heuristic, reason `cache disabled ...`, `bpe_cache_path=None` | one `TokenizerDegradedWarning` |
| b | cache file absent at `<dir>/9b5ad71b2ce5302211f9c61530b329a4922fc6a4` | heuristic, reason names the path and the one-shot fetch command; `get_encoding` **not** called | one |
| b' | file present but sha256 != `223921b7...b2a7` | heuristic, reason names both digests; `get_encoding` **not** called (tiktoken would delete and re-download) | one |
| c | `get_encoding('cl100k_base')` raises | heuristic, reason `<ExcType>: <msg>` | one |
| d | probe encode raises or ids != `PROBE_IDS` | heuristic, reason `probe encode failed: ...` / `probe mismatch: got [...], expected [...]` | one |
| e | ids == `PROBE_IDS` | exact, `probe_digest` set, encoder retained | none |

Cache-path resolution mirrors `tiktoken.load.read_file_cached` (tiktoken
0.14.0) without importing tiktoken: precedence `TIKTOKEN_CACHE_DIR` >
`DATA_GYM_CACHE_DIR` > `<tempfile.gettempdir()>/data-gym-cache`, key
`sha1(url)`. The one-shot fetch command the owner runs by hand is
`python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`; Daedalus
never runs it.

Probe: `"Daedalus counts tokens: 4 planes, 11 arms, 9 measures.\n"` encodes with
`disallowed_special=()` to 18 ids `[31516, 291, 87227, 14921, 11460, 25, 220,
19, 25761, 11, 220, 806, 11977, 11, 220, 24, 11193, 627]` [MEASURED 2026-09-08
`uv run --frozen --with tiktoken==0.14.0 --project C:/Users/Administrator/Desktop/projects/daedalus python -c "import tiktoken; print(tiktoken.get_encoding('cl100k_base').encode('Daedalus counts tokens: 4 planes, 11 arms, 9 measures.\n', disallowed_special=()))"`].
`'hello world'` -> `[15339, 1917]` [MEASURED 2026-09-08, same command].

`count_tokens`: unchanged contract. When an encoder exists and `encode`
raises, the call returns `chars/4` and increments `_HEURISTIC_FALLBACK_CALLS`
(monotone for the process; not zeroed by a cache reset; the increment is not
thread-atomic and is advisory). A consumer snapshots
`tokenizer_status().heuristic_fallback_calls` before and after a run.

`_reset_tokenizer_cache()` is test-only; after it the warning re-fires by
design (one warning per measured cache state).

`daedalus/eval/harness.py` re-exports `tokenizer_status` next to
`count_tokens` and `tokenizer_name`; no other line of the harness changes and
its `"tokenizer": tokenizer_name()` fields keep their literals.

Packaging: the new `tokenizer` extra is installed by every
`uv sync --locked --all-extras` bootstrap (`bootstrap.ps1`, `bootstrap.sh`;
pinned by `tests/test_gpu_extra_contract.py`). Consequence: a bootstrapped
host has `tiktoken` importable, so it will see the `TokenizerDegradedWarning`
with the fetch command until the owner fetches the BPE file once. The `test`
extra stays BPE-free, so the CI contracts matrix keeps measuring the
`tiktoken not installed` path.

## Acceptance matrix

All rows in `tests/test_tokenizer_status.py`; stubs are installed with
`monkeypatch.setitem(sys.modules, "tiktoken", ...)` so the matrix runs without
the extra. `_cached_bpe()` writes a stub file and patches `_sha256_of_file` to
the pinned digest (the real file, 1681126 bytes [MEASURED 2026-09-08 `os.path.getsize` on the host cache file], is not copied into tests).

| # | Test | Passes when |
| --- | --- | --- |
| A1 | `test_not_installed_is_heuristic_without_warning` | `sys.modules['tiktoken']=None` -> heuristic status equals the pinned dataclass, no warning, `count_tokens` = chars/4 |
| A2 | `test_installed_but_uncached_warns_names_path_and_never_fetches` | stub whose `get_encoding` raises `AssertionError('must not fetch')` is never called; reason names the path and the fetch command; exactly one warning |
| A3 | `test_cache_dir_precedence_matches_tiktoken` | env precedence and `sha1(url)` key reproduce tiktoken's path |
| A4 | `test_empty_cache_dir_means_every_load_would_fetch_so_refuse` | `TIKTOKEN_CACHE_DIR=""` -> heuristic, `bpe_cache_path=None`, one warning, no fetch |
| A5 | `test_cached_file_with_wrong_hash_is_refused_without_fetch` | wrong-content file -> reason names both digests, no fetch, one warning |
| A6 | `test_get_encoding_raising_yields_heuristic_with_exception_type` | reason `ValueError: Hash mismatch ...`, encoder None, one warning |
| A7 | `test_probe_mismatch_yields_heuristic_and_warning` | stub encoder returning `[1,2,3]` -> heuristic, reason starts `probe mismatch`, encoder never used for counting |
| A8 | `test_probe_encode_raising_yields_heuristic` | reason `probe encode failed: RuntimeError: ...` |
| A9 | `test_probe_match_is_exact_with_probe_digest` | pinned ids -> exact status equals the pinned dataclass with the sha256 probe digest; `tokenizer_status()` returns the same cached object |
| A10 | `test_heuristic_fallback_counter_is_live_and_monotone` | counter unchanged on success, +2 after two raising encodes, readable through the old status object, survives a cache reset |
| A11 | `test_warning_fires_once_per_cache_state` | one warning across repeated status/name/count calls; one more after reset |
| A12 | `test_count_tokens_never_raises[5 scenarios]` | `""`->1, 8 chars->2, 4000 chars->1000 under every degrade path |
| A13 | `test_real_tiktoken_is_exact_when_bpe_is_cached_on_this_host` | `importorskip('tiktoken')`; exact on this host, `count_tokens('hello world')==2`, `[15339, 1917]` |
| A14 | `test_harness_reexports_the_canonical_status` | `harness.tokenizer_status is tokens.tokenizer_status` (and the other two names) |
| A15 | `test_tokenizer_extra_is_pinned_and_test_extra_stays_bpe_free` | `extras['tokenizer'] == ['tiktoken==0.14.0']`, no tiktoken in `test` or core deps |
| A16 | `test_import_emits_no_warning_and_does_no_work` | subprocess with `warnings.simplefilter('error')`: import succeeds, cache empty, no encoder |
| A17 | `test_module_is_a_leaf_without_daedalus_imports` | tokens.py imports no daedalus module and does not import tiktoken at module scope |

Refusal rows: A2, A4, A5 are the "never fetch" refusals; A7 is the "never
declare exact" refusal.

Mutation evidence (each mutant applied to `tokens.py`, suite run, file
restored byte-identical) [MEASURED 2026-09-08 `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_tokenizer_status.py` per mutant]:

| Mutant | Killed by |
| --- | --- |
| uncached branch calls `get_encoding` anyway | 3 failed (A2, A11, A12[uncached]) |
| probe comparison removed | 2 failed (A7, A12[probe_mismatch]) |
| fallback counter not incremented | 1 failed (A10) |
| sha256 check skipped | 1 failed (A5) |
| warning suppressed | 7 failed |
| `exact=True` declared without probing | 9 failed |

## Migration and rollback

Additive. No caller changes; the two name literals and the never-raise
contract are unchanged, so `ollama.py`, `council/*`, `eval/tier2.py` and the
harness behave as before on a host without tiktoken (the only measured
configuration on `main` today).

Behavior change on a host **with** tiktoken but without the cached BPE file:
before, the first `count_tokens` call performed an untimed HTTP GET from
inside `_encoder()`; now it returns `chars/4`, emits one
`TokenizerDegradedWarning` with the fetch command, and never opens a socket.
This is the intended refusal, not a regression.

Rollback: `git revert` of the packet commit. Manually: delete the `tokenizer`
extra from `pyproject.toml`, run `uv lock` (removes the `tiktoken` and `regex`
entries and the `provides-extras` item), restore `tokens.py` and the harness
import lines from `24e229c0`, delete `tests/test_tokenizer_status.py` and this
document, re-render `docs/work-packets/index.json`, restore the three pins in
`tests/contracts/test_work_packet_index.py`.

## Evidence, expected failures and review

Environment: Windows 11, CPython 3.12.13 in `.venv` (no tiktoken), `uv` with
`--frozen`; real-library rows via `uv run --frozen --with tiktoken==0.14.0`
overlay, which touches no lock file.

Baseline before any change [MEASURED 2026-09-08, logs in
`runs/G1-TOKENIZER-01/baseline-*.log`, command
`(cd <worktree> && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <path>)`]:

| Suite | Baseline |
| --- | --- |
| `tests/test_tokenizer_status.py` | file absent, `no tests ran` (exit 4) |
| `tests/test_honest_denominator.py` | 9 passed, 1 skipped |
| `tests/test_eval.py` | 6 passed |
| `tests/test_eval_tier2_integrity.py` | 15 passed, 8 subtests passed |
| `tests/contracts/test_work_packet_index.py` | 24 passed |
| `tests/contracts/test_import_scc_hierarchy.py` | 3 passed |
| `tests/test_gpu_extra_contract.py` | 11 passed |

Test-first evidence: with the new test file against the unchanged module the
suite reported `21 errors` (`_reset_tokenizer_cache` absent) [MEASURED
2026-09-08].

After the change [MEASURED 2026-09-08, logs `runs/G1-TOKENIZER-01/after-*.log`,
same commands; the `FAILED`/`ERROR` lines of every after-log were diffed
against its baseline log and the diff is empty for every pre-existing suite]:

| Suite | After |
| --- | --- |
| `tests/test_tokenizer_status.py` | 20 passed, 1 skipped (A13 skips: no tiktoken in `.venv`) |
| `tests/test_honest_denominator.py` | 9 passed, 1 skipped |
| `tests/test_eval.py` | 6 passed |
| `tests/test_eval_tier2_integrity.py` | 15 passed, 8 subtests passed |
| `tests/contracts/test_work_packet_index.py` | 24 passed (pins re-measured: 473 tracked files, 407 packet IDs) |
| `tests/contracts/test_import_scc_hierarchy.py` | 3 passed |
| `tests/test_gpu_extra_contract.py` | 11 passed |

Real library [MEASURED 2026-09-08 `(cd <worktree> && PYTHONIOENCODING=utf-8 uv run --frozen --with tiktoken==0.14.0 --project C:/Users/Administrator/Desktop/projects/daedalus python -m pytest -q -p no:cacheprovider tests/test_tokenizer_status.py)`]:
`21 passed` (A13 runs, `exact=True` because
`<tempdir>/data-gym-cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4` exists on
this host with sha256 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`
[MEASURED 2026-09-08 by re-hashing the file]). Same overlay on
`tests/test_honest_denominator.py`: `10 passed` (its tiktoken-gated test runs).

Lock [MEASURED 2026-09-08 `(cd <worktree> && uv lock)` then
`git diff --stat uv.lock`]: `1 file changed, 210 insertions(+), 1 deletion(-)`;
`uv lock` reported `Added regex v2026.9.3`, `Added tiktoken v0.14.0`; the only
removed line is the old `provides-extras` list, re-added with `tokenizer`. The
tiktoken entry depends on `regex` (new) and `requests` (already locked at
`uv.lock:2547`). `uv lock --check --project <worktree>`: `Resolved 128
packages` with no drift.

Import census: `tests/contracts/test_import_scc_hierarchy.py` 3 passed after
the change with `CENSUS_MODULES = 485`, `CENSUS_EDGES = 1931` unchanged
(tokens.py imports no daedalus module; harness already imported tokens).

Expected failures recorded before the build:

- A13 is host-dependent by design: it skips on a host without tiktoken and on
  a host without the cached file (it prints the fetch command). It is not a
  CI row.
- A bootstrapped host (`--all-extras`) that has never run the fetch command
  will emit `TokenizerDegradedWarning` on the first `count_tokens` call. That
  is the packet's point; it is not silenced.

Review questions for the independent reviewer:

1. Is there any path from Daedalus code to `tiktoken.get_encoding` while the
   cache file is absent or mismatching? (Rows b, b', b0.)
2. Can `exact=True` be reached without the probe comparison having run?
3. Does any caller depend on `_encoder()` being an `lru_cache` object
   (`cache_clear`) rather than a function? (`grep` found only
   `tests/test_honest_denominator.py:32-34`, which only calls it.)
4. Is the fallback counter observable across the cached status object, and is
   its non-atomicity acceptable for an advisory counter?
5. Does `--all-extras` pulling `requests` and `regex` into every bootstrap
   change any egress or supply-chain assumption recorded elsewhere?

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: `tests/test_tokenizer_status.py` (21), mutation table above, lock
diff, `runs/G1-TOKENIZER-01/*.log`.
