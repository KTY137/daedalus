# Review: `daedalus/tools/vet.py` — adversarial pass

**Reviewed:** 2026-08-27 against HEAD `16cf061d` (moved to `1b272b58`-line
during the pass; the target file was byte-stable throughout).
**Classification:** `ALIGNED` — read-only adversarial review. No rule,
severity, allowance semantic or policy was changed by this pass. **Iron Gate:** 1.

**Why this exists in the tree and not only in a transcript.** The lesson of
`3c74716` (session 7): a review that lives only inside an agent transcript did
not happen as far as the repository can tell. This record is the durable
artifact for the 2026-08-27 adversarial pass, the way
[`REVIEW_VET_20260826.md`](REVIEW_VET_20260826.md) is for the prior one.

**Relation to the 2026-08-26 review.** That pass found an MCP filesystem
write-root grant invisible to the gate and repaired one stale test; its Finding
1 (a path-argument grant has no rule) still stands and is not re-litigated here.
This pass attacked the five self-declared invariants directly and the
obfuscation surface specifically.

**Scope.** 1668 lines; consumers `daedalus/tools/inventory.py` (`vet_skill`,
`vet_mcp_server`) and the `daedalus.tools` facade; contract neighbours
`daedalus/skills.py`, `daedalus/sensitivity.py`.

## Verdict

Three real defects (two HIGH, one MEDIUM) and two test gaps (MEDIUM). The four
structural invariants — STATIC ONLY, findings-not-scores, host-question-only-via
`sensitivity.lane_for_host`, declaration-is-a-request — hold under probing. The
one that does **not** hold in full is invariant 2 (fail-closed / "unknown is not
clean"): the module hardens against zero-width and tag-block obfuscation but is
blind to Unicode **compatibility** and **confusable** spellings, and it bounds
input size but not match time. Both are the same class the module elsewhere
closes: an instrument that cannot say "I could not scan this" and prints a clean
result instead.

None of these were patched in this pass. F1's exec half and F3 are
defence-in-depth for this repository (nothing here executes a skill's
`scripts/`); F1's homoglyph half is live, because `skills.render_catalog` loads
every installed skill's name and description at startup. Fixes touch the safety
fence's own reasoning and belong in their own packet with a Cerberus look, not
bolted onto an unrelated commit.

## Finding 1 — HIGH: NFKC compatibility spellings bypass every rule, silently

The module derives its "invisibles" set from `unicodedata` category `Cf` but
never NFKC-normalises the scanned text. CPython NFKC-normalises identifiers at
parse time, so a fullwidth or otherwise compatibility-equivalent spelling
executes while matching no rule.

`[MEASURED 2026-08-27]` executed proof (`odysseus-vet-02-unicode.py`):

```text
source = 'ｅｖａｌ("__import__(\'os\').getcwd()")'
RESULT = EXECUTED -> 'C:\\Users\\nukei\\Desktop\\agent_env'
```
```text
ASCII eval           -> block  exec.eval           fullwidth eval        -> clear  -none-
ASCII subprocess.run -> block  exec.subprocess     fullwidth subprocess  -> clear  -none-
ASCII __import__     -> review exec.dynamic_import  fullwidth __import__  -> clear  -none-
```

Confirmed independently here: `NFKC('ｅｖａｌ') == 'eval'`, and the fullwidth form
carries no category-`Cf` character, so **no `obfuscation.invisible_chars`
finding fires** — invisible-char count is 0. The gate does not know it knows
less. The existing zero-width and tag-block defences still fire (`e\u200bval(`
→ block; a tag-block spelling → block); the gap is specifically compatibility
and confusable forms.

Second, independent half: **homoglyphs in injection prose.** A single Cyrillic
`і` in "previous" deletes the `inject.override` finding. This is the live half:
per vet.py's own docstring, catalog rendering reads every installed skill's
name and description at startup, chosen or not.

**Repair shape (not done here):** add an NFKC view to `_views` (the machinery
exists; NFKC is not length-preserving, so the offset map needs care), and/or
emit an `obfuscation.*` finding when `NFKC(text) != text` or a confusable sits
in identifier position.

## Finding 2 — HIGH: quadratic backtracking; the gate is disableable per input

`vet.py` bounds input size (`MAX_FILE_BYTES = 2 MiB`) but never match time.
Several rules pair a greedy unbounded class with a required trailing literal.
All payloads are legal skill files: under the size bound, valid UTF-8, no NUL,
`.py` suffix.

`[MEASURED 2026-08-27]` (`odysseus-vet-03b-redos.py`), factor ~3.3–4.7 per size
doubling across five points each = quadratic:

```text
fs.write_outside  \bopen\s*\([^)]*['"][wa]
  open(  16 KiB   ->   1.621s   findings=0
  open( 128 KiB   ->  71.696s   findings=0
fs.rmtree  \bRemove-Item\b[^\n]*-Recurse
  Remove-Item 512 KiB -> 105.398s  findings=0   (confirmed point)
```

`[EXTRAPOLATED, not measured]` at the 2-MiB bound, `fs.write_outside`
≈ 71.7 s × 256 ≈ ~5 hours for one file. A skill may bundle up to 256 files
(`skills.MAX_BUNDLED_PATHS_LISTED`), and `inventory.build()` vets every skill it
finds, so one planted skill stalls the whole tool inventory. Both payloads
return **zero findings** — the cost buys nothing.

This lands on the module's own reasoning: "the whole module is file reads and
regex" is offered as a *safety* argument, but a static scanner with unbounded
match time is itself the attack surface.

**Repair shape (not done here):** bound the greedy classes (`[^)]{0,200}`,
`[^\n]{0,200}`) or add a per-file time budget that yields `UNSCANNABLE` — which
would be invariant-conformant.

## Finding 3 — MEDIUM: the `__pycache__` exemption doesn't check the relation it assumes

`vet_skill` exempts a `.pyc` when its sibling `.py` was scanned. The comment
names the hazard itself ("bytecode can outlive or replace its source") and
treats the sibling condition as sufficient. It is not: PEP-552
`UNCHECKED_HASH` bytecode is loaded by CPython with **no** comparison to source.

`[MEASURED 2026-08-27]` (`odysseus-vet-05-quiet-and-pyc.py`): a 55-byte harmless
`helper.py` beside a `.pyc` carrying `subprocess`/`urlopen` exfiltration vets
`CLEAR`, and CPython loads the unscanned payload (`helper.MARK = 'PAYLOAD: this
bytecode was NEVER scanned'`, `go` present).

**Repair shape (not done here):** exempt only `TIMESTAMP`/`CHECKED_HASH` pycs
validated against the scanned source; otherwise `skipped`.

## Findings 4 & 5 — MEDIUM: two contract behaviours are unasserted anywhere in the tree

Mutation probe: a scratch copy of `vet.py` registered as `daedalus.tools.vet`
before `tests/test_tools_vet.py` imports. Baseline over that path: 208 passed /
102 subtests, GREEN. 17 mutations, **15 killed**. Two survivors:

- **F4.** `bundled_truncated=True → skipped` (→ `UNSCANNABLE`) has no assertion.
  `skills.py:_bundled_paths` calls this "the ONLY channel by which vet learns it
  saw less than the directory holds" and ties it to Cerberus 2026-08-25
  critical 1 (a symlink out of the skill directory). `bundled_truncated` appears
  in `tests/test_tools_vet.py:1234` only as a fixture attribute `= False`, never
  asserted. The cross-module contract carrying a CRITICAL fix is untested.
- **F5.** `meta.allowed_tools_request → REVIEW` has no assertion
  (`grep allowed_tools_request tests/` → 0 hits). This finding **is** the whole
  mechanical effect of invariant 5; it is deletable with no red test.

## Lower, no live bypass

- `_worst()` falls back to CLEAR rank for an unknown severity
  (`_worst('clear','critical') == 'clear'`). Unreachable today (all severities
  are constants), but the default direction is the unsafe one.
- `MAX_FILES_SCANNED = 400` is dead: `skills.MAX_BUNDLED_PATHS_LISTED = 256`
  caps first, so the `skipped`-on-cap branch is unreachable via `load_skill`.

## What held under probing `[MEASURED 2026-08-27]`

| Invariant | How it was attacked | Result |
| --- | --- | --- |
| STATIC ONLY | full AST enumeration of vet.py | 17 imports, all stdlib/self; no `subprocess`/`importlib`/`__import__`/`eval`/`exec`/`compile`/`socket`/`urlopen`; whole I/O surface is `read_text`/`stat`/`read_bytes`; all 6 `getattr` literal; path traversal in `root / rel` not reachable |
| findings, not scores | every `Finding(...)` construction | each carries where/line/excerpt; line numbers back-mapped through the view offset maps |
| host question via one predicate | grep for host logic | exactly one `lane_for_host(url)` call, whole URL; zero loopback literals in live code; schemeless/ftp remote specs fail closed to `UNSCANNABLE` |
| declaration is a request | all 10 `Finding` sites | only downgrades are in `apply_allowances`, gated on the allowance file; `allowed-tools` only escalates CLEAR→REVIEW |

## What a follow-up packet should carry

1. NFKC view or an obfuscation finding for compatibility/confusable spellings (F1).
2. A per-file time budget → `UNSCANNABLE`, plus a test "a legal 2-MiB file is
   decided in < N s, else UNSCANNABLE" (F2).
3. `.pyc` invalidation-mode check (F3).
4. `bundled_truncated=True → UNSCANNABLE` as an assertion (F4).
5. `allowed-tools` alone → REVIEW, not CLEAR (F5).

Belege (executed proof scripts) under the session scratch
`odysseus-vet/odysseus-vet-*.py`.

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: 208 passed / 102 subtests (baseline + final over the scratch path);
full AST enumeration of vet.py; 17-mutation probe (15 killed, 2 survived);
executed bypasses for NFKC identifiers (`cleared=True` on a running
subprocess/urlopen payload), `UNCHECKED_HASH` `.pyc` (CPython loads unscanned
payload), and quadratic backtracking (512 KiB → 105.4 s measured). NFKC folding
of the fullwidth spelling independently reconfirmed in this pass.
