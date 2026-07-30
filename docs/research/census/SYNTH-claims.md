# SYNTH — Claims versus Reality

Lane: places where a docstring promises **atomicity, fail-closed behaviour,
determinism, isolation, rollback, or a "never"** that the implementation does
not provide.

Method: 621 `CLAIMS|` lines were filtered to 194 load-bearing ones (guarantee
verbs, not description), 40 of them in the priority modules. Every claim below
was checked by **opening the file**. The census came from a cheap model and
demonstrably hallucinates, so nothing here is repeated on its authority —
refutations are reported as first-class results.

Provenance of every line below: MEASURED by reading the named file at the named
line on 2026-07-30, HEAD `7a5fb07` + working tree.

---

## A. CONFIRMED — the promise is false, with a trigger

### A1. `daedalus/spine/bootstrap.py` — "IT NEVER WRITES THE PRIMARY CHECKOUT"

Module docstring, numbered point 3 (line ~49):

> 3. IT NEVER WRITES THE PRIMARY CHECKOUT. Inherited from
>    :mod:`daedalus.spine.attempt`, which has no apply path at all, and asserted
>    here again because this module is the one that would be tempted.

`refresh_sources()` (line 135) contradicts it, and **the code says so itself**
at line 148:

```
# Refresh writes the generated map into the PRIMARY checkout. A repository
# that explicitly disabled that source chose the curated queue as its
# authority; ...
```

**Trigger:** `refresh_sources(repo_root)` with `picker_sources.map` not disabled
→ `subprocess.run([sys.executable, "-m", "daedalus.cli", "map"], cwd=repo_root)`
(line 171) → rewrites `<repo_root>/docs/architecture-state.json`. The function
proves the write happened: it reads `_recorded_head(snapshot)` before and after
and treats a *changed* stamp as the success criterion.

This is the worst instance in the lane, because bootstrap is the module whose
entire reason to exist is "Daedalus attempts work on Daedalus, and promotes
nothing", and point 3 is the sentence a reader would trust when deciding whether
a shadow run is safe to leave unattended. The write is a derived artefact rather
than source, which is the mitigating fact — but it is not what the docstring
says, and it does not pass through `daedalus.primary_tree`'s fence.

### A2. `daedalus/loop.py` — "There is no code path from this module to a write in `repo_root`"

Module docstring line 39:

> NEVER WRITES THE PRIMARY CHECKOUT, at any setting. There is no code path from
> this module to a write in ``repo_root`` -- it holds no git subprocess of its
> own, and its one write path (``run_wave``) lands candidates in disposable
> worktrees ...

There is a second write path. `loop.py:748`:

```python
base = Path(runs_dir) if runs_dir else Path(self.repo_root) / "runs" / "loop"
self.ledger = LoopLedger(None if self.dry_run else base / f"{self.run_id}.json", ...)
```

and `LoopLedger.save()` (line 408) does `self.path.parent.mkdir(parents=True,
exist_ok=True)` + `os.replace(tmp, self.path)`.

**Trigger:** `python -m daedalus.loop --max-iterations 1` without `--runs-dir`.
**Standing evidence:** `git status` on this branch shows `?? runs/loop/` — an
untracked directory containing ten `loop-*.json` files, created inside the
primary checkout by exactly this path.

Two sub-defects follow from it: the write does not go through the primary-tree
fence (so the fence cannot be the thing that makes the claim true), and the
`os.replace` has no Windows retry (see A3).

### A3. Atomic-publish family — `os.replace` without the Windows retry the repo already measured

The repo has the correct pattern and its measurement, in
`spine/killswitch.py::KillSwitch._atomic_write` (line 536):

> MEASURED, and the reason this retry exists: on win32 a poller reading the
> permit holds it open WITHOUT ``FILE_SHARE_DELETE`` (CPython's ``open()``
> offers no way to ask for it), so ``MoveFileEx`` over it returns
> ERROR_ACCESS_DENIED.

`budget.py::Ledger._store` (line 735) applies it (10 attempts × 50 ms, then
`BudgetUnavailable`). The following publishers **claim atomicity, name a
concurrent reader, and do not retry**:

| Site | Claim | Concurrent reader named by the code itself |
|---|---|---|
| `arch_memory.py::save` (l.170–183) | "Publish whole or not at all… no lock is needed" | "A post-commit hook writes this while a prompt hook may be reading it" |
| `arch_memory.py::_remember_shown` (l.235) | (same pattern, no claim) | `render_delta` reads it every turn |
| `shift.py::_write_atomic` (l.174) | header comment: "publish via a temp file plus `os.replace`, which is atomic on POSIX and Windows" | header comment: "A ticker polls it, a prompt hook reads it on every turn" |
| `file_bridge.py::_write_json_atomic` (l.174) | "Publish a small JSON file whole or not at all" | the watcher polls the inbox; report paths are FIXED and re-written |
| `loop.py::LoopLedger.save` (l.431) | — | `daedalus status` / web API read `runs/loop/` |

**Trigger (all five):** on win32, any process holding the target open for read at
the instant of `os.replace` → `PermissionError`. In `arch_memory.save` and
`shift.declare` (l.256) it propagates uncaught, so the *reader* breaks the
*writer*. The same shape already broke the operator's own stop command once —
that is what the killswitch comment is recording.

Note the asymmetry these three modules make explicit: `shift.py`'s own header
says "on Windows you cannot replace a file another handle holds open", and then
`_write_atomic` does exactly that without a guard. The knowledge is present; the
code is one commit behind it.

`file_bridge._archive_once` and `write_heartbeat` are **correct** — both catch
`OSError` and degrade (`shutil.move` fallback / silent skip). Not findings.

### A4. `daedalus/sensitivity.py::load_policy` — "a project can extend, but never weaken, the baseline"

Docstring (l.236):

> Generic secret protections are always unioned in so a project can extend, but
> never weaken, the baseline.

Only two of the seven fields are unioned (`deny_substrings`,
`high_risk_path_substrings`). Three are project-controlled in the widening
direction:

* `allow_substrings=tuple(p.get("allow", GENERIC_ALLOW_SUBSTRINGS))` — **replaced**, not unioned.
* `allow_exceptions=tuple(p.get("allow_exceptions", ()))` — purely project-supplied.
* `default_deny=bool(p.get("default_deny", True))` — settable to `False`.

And the order in `_path_is_sensitive` (l.372) puts the project-controlled list
**first**:

```python
if any(exc in norm_path for exc in policy.allow_exceptions):
    return None                       # ← before the deny list runs at all
for deny in policy.deny_substrings:
    ...
```

**Trigger, and it is shipped by default:** `config.STARTER` (l.174) writes
`"allow_exceptions": ["_simulated.py"]` into every scaffolded repo. In such a
repo, `secrets/credentials_simulated.py` returns `sensitive=False` from
`classify_data` despite matching two entries of `GENERIC_DENY_SUBSTRINGS`, and
is inlined to DeepSeek/codex by `read_inlined_context`. A more direct trigger:
`"allow_exceptions": [""]` or `"allow": [""]` in a target repo's own
`.agentenv/agentenv.json` disables the egress gate entirely — and that file
lives in the *target* repo, i.e. outside the harness's trust boundary.

**Calibration:** the *secret floor* (`secret_floor_rule`) is genuinely
unconditional and project-independent, and `slice_egress_rule` /
`read_inlined_context` both run it first, so a PEM block, an AWS/GitHub/Slack/
Stripe token, a JWT, or a quoted credential literal is still caught. The gap is
real but it is a narrowing of the allow-list gate, not a total bypass. The
docstring sentence, however, is false as written and it is the sentence an
operator reads when writing a policy.

### A5. `daedalus/eval/harness.py::eval_task_tier1` — "NEVER RAISES"

Docstring (l.220) promises every failure becomes an ERRORED row. The body
(l.233) catches `(ValueError, OSError)` only, while `task["repo"]`,
`task["target"]` and (in the success return) `task["id"]` are unguarded
subscripts, and `is_correctness_task(task)` runs *outside* the `try`.

**Trigger:** one task dict without a `"repo"` key — a minted quarantine row from
an older schema, or a hand-added corpus entry — raises `KeyError` out of
`eval_task_tier1`, killing the whole tier-1 run. The aggregation contract the
same docstring describes ("ERRORED rows are aggregated (excluded), reported
(never silently dropped)") depends on the exception never escaping, so the
failure mode is the loudest possible version of the thing it was written to
prevent.

### A6. `daedalus/tools/vet.py::vet_mcp_server` — the byte-pin is inert

`apply_allowances` (l.222) documents the fix for a measured 2026-07-30
adversarial finding:

> AN ALLOWANCE BINDS TO BYTES, NOT TO A NAME. … When it does, the
> acknowledgement applies only to the exact bytes a human reviewed.

The guard is `if pinned and identity and pinned != identity:`. `vet_skill`
passes `identity=getattr(skill, 'body_sha256', '')` (correct — `skills.Skill`
does define `body_sha256`, l.302). **`vet_mcp_server` (l.526) calls
`apply_allowances(findings, name, allowances)` with no `identity=` at all**, so
`identity == ""`, the pin comparison short-circuits, and a `body_sha256`-pinned
allowance downgrades findings for *whatever* command line currently answers to
that name — while the report shows it as pinned (no `UNPINNED` note).

**Trigger:** an allowance `{"allow": {"ctx7": {"exec.subprocess": {"reason": "...",
"body_sha256": "<old>"}}}}`; edit `.mcp.json`'s `ctx7` entry to a different
command → still downgraded.

**Latent, not live:** every `Finding` `vet_mcp_server` constructs today is
`REVIEW`, and `apply_allowances` only rewrites `BLOCK`. It becomes exploitable
the first time an MCP rule is given `BLOCK` severity. Reported because the
guarantee is written as unconditional.

### A7. `daedalus/kairos/worktree.py::_is_reparse_point` — an unstattable ancestor is assumed innocent

```python
try:
    st = os.lstat(path)
except (OSError, ValueError):
    return False
```

`_verify_reachable` (l.479) is the only guard against an ancestor being swapped
for a junction mid-removal, and it asks this predicate about every guarded and
intermediate component. A component whose `lstat` fails is therefore classified
as "not a redirection" and the walk proceeds to `os.scandir`/`os.rmdir` through
it.

For the *pop target* the fail-open is closed one line later (`os.lstat(current)`
re-raises anything that is not `FileNotFoundError`). For **ancestors** it is
not: nothing else stats them.

This directly contradicts the posture the sibling module pins in
`tests/test_spine_attempt_containment.py`, quoted in the census:
*"Fail closed. A path we cannot stat is not assumed innocent."* and *"If we
cannot locate what we are protecting, we protect everything."* Two modules that
compose in the same removal answer the same question in opposite directions.

**Trigger:** during `cleanup_worktree`, an ancestor is replaced by a reparse
point whose `lstat` returns something other than `ENOENT` (Windows: a DACL
denying `FILE_READ_ATTRIBUTES`, or a reparse tag the CRT declines). Low
likelihood; the posture inconsistency is the reportable part.

### A8. `daedalus/spine/__init__.py` — "a crash can never leave an effect the system has no record of intending"

`spine/ledger.py`'s own module docstring is careful and honest: the ledger *can*
be ahead of reality, the effect key "delivers no idempotency on its own", and a
caller whose effect is not identifiable afterwards "gets no crash safety here
and must not pretend otherwise". The package `__init__` re-exports it with the
qualifier removed and states it as a property of *the system*.

**The scope is one caller.** `record_intent` is called from exactly one place in
the tree: `spine/attempt.py:1254`. The offload write lane
(`providers/ollama.py`, `providers/deepseek.py`, driven by `offload.py`) writes
files to disk with no ledger row at all.

### A9. Provider `rollback()` — true in-process, absent across a crash

`OllamaProvider.rollback` / `DeepSeekProvider.rollback`: "Undo **every** write
this instance made". Verified correct within the process — backups are recorded
with `setdefault` (ollama l.491, l.1059; deepseek l.517), so first-write-wins
and a second write to the same file cannot overwrite the pristine bytes with
intermediate ones. `offload.py:448` correctly refuses `writable=True` to a
provider without a callable `rollback`.

The gap is durability: `self._backups` is an in-memory dict, populated at write
time and cleared at rollback. A `SIGKILL`, an OOM kill, or a power loss between
the write and `verify()` leaves the target tree modified with **no** on-disk
record of the originals and no recovery path. `config.py`'s `STARTER` text — the
prose an operator reads when deciding whether to enable an external write lane —
sells this as "keeps a byte-exact rollback of every file it touched", with no
qualifier.

### A10. `daedalus/structcore/dss.py` — "The module is dependency-free"

Line 16 claims it; line 28 is `from .forest import KnowledgeForest`. Trivially
false, mechanically checkable, and the only census/review lead in this class that
survived verification (rv05). Read-only half of the claim holds.

### A11. `daedalus/providers/codex_cli.py` — "A denied path never reaches codex"

`classify_data(paths, extra_text=objective, policy=policy)` runs before the spawn
(l.160), fail-closed, correct. But with `paths == []` the path axis is vacuous
and only the objective text is scanned — after which codex is agentic and reads
whatever it likes. The same docstring discloses this two paragraphs later
("Residual risk (documented, not hidden)"), so this is an **internal
contradiction**, not a hidden defect: the headline sentence overstates what the
paragraph below it correctly bounds. Worth fixing as prose because the headline
is what gets quoted.

Minor, adjacent: every codex call writes the full prompt to
`<daedalus_root>/runs/last_codex_prompt.md` unconditionally (l.169), including
whatever repo content the objective carries.

---

## B. REFUTED — leads that should stop consuming review time

Six of these come from `EXTERNAL_FINDINGS.md`, three of them marked there as
**CONFIRMED**. They are not.

| Lead | Verdict |
|---|---|
| `spine/containment.py` exports `JobLimits` without defining it | **FALSE** — defined at `containment.py:1216`, constructed at 1262, annotated at 1005/1294. |
| `kairos/worktree.py` exports `remove_tree_no_follow` without defining it | **FALSE** — defined at `worktree.py:602`. |
| `containment.py` calls undefined `_log_as_hex`, NameError swallowed by a bare except (EXTERNAL_FINDINGS: "CONFIRMED") | **FALSE** — neither `_log_as_hex` nor `_log_hex` occurs anywhere in the repo (`grep -rn` over all `*.py`: zero hits). The finding names a function that does not exist. |
| `containment.py::_verify_job_config` fails to verify `ActiveProcessLimit` | **FALSE** — `_verify_job_config` does not exist in the repo. Zero hits. |
| `loop.py` claims governance from `core.get_governance()` but does not depend on `daedalus.core` (rv01) | **FALSE** — `loop.py:1039`, `gov = core.get_governance(self.project)`. |
| `budget.py`: atomic replace on Windows / check-before-call not verifiable | **VERIFIED PRESENT** — `Ledger._store` (l.735) retries `PermissionError` 10×50 ms and converts exhaustion into `BudgetUnavailable`; `reserve()` persists under `_BudgetLock` before returning. Fail-closed holds end to end. |
| `budget.py` subscription/`free_local` handling may silently widen the cap | **REFUTED** — `free_local` (zero on *both* axes) requires `is_loopback_host`, which is numeric-literal-only and reads no env var. A `DAEDALUS_TRUSTED_HOSTS` entry yields basis `trusted_remote`: zero dollars, **still counted on the call axis**. An explicit host also forces `vendor → remote_inference` and sets `untrusted_endpoint`, so a subscription declaration cannot re-price it. |
| `_BudgetLock` / `_PromotionLock` may proceed unserialised | **REFUTED** — both `seek(0)` then `msvcrt.locking(LK_NBLCK,1)` / `fcntl.flock(LOCK_EX\|LOCK_NB)`, both raise (`BudgetUnavailable` / `PromotionUnavailable`) on open failure and on timeout. Neither degrades to a no-op. |
| `tools/vet.py` "Static only, never executes anything" | **CONFIRMED TRUE** — the module's entire import surface is `re`, `dataclasses`, `pathlib`, and `sensitivity.lane_for_host`. No `subprocess`, no `importlib`, no network, no `exec`/`eval`. Every rule is a file read plus a regex. |
| `tools/vet.py` "Fail-closed: unknown is not clean" | **CONFIRMED TRUE** — `Verdict.cleared` is `outcome == CLEAR and not self.skipped`; unreadable, oversized, binary, non-UTF-8, truncated-listing and over-bound cases all append to `skipped`, which forces `UNSCANNABLE`. Undecodable files are refused rather than decoded with replacement (which would let a crafted byte sequence hide a match). |
| `kairos/archive.py::load_attempts` "Never raises" | **CONFIRMED TRUE** — `Attempt.from_dict` uses `.get()` throughout and every conversion that can fail (`float`, `tuple(... for ...)`, `dict(...)`) raises `ValueError`/`TypeError`/`AttributeError`, all caught. A JSON line that is a list, a string or a number is handled. |
| `providers/_ollama_native.py::num_ctx_value` "never raises" | **CONFIRMED TRUE**. (Note, not a defect: there is a lower clamp at 2048 and no upper one, so `OLLAMA_NUM_CTX=99999999` is accepted and pushed to the server.) |
| `spine/docref_gate.py` "verifying zero targets is exit 2, never 0" and "fail closed with 0/1/2" | **CONFIRMED TRUE** — and stronger than claimed: `main()` converts *any* escaping exception, and argparse's own usage exit, into `EXIT_INCONCLUSIVE` with a sentence saying so. The denominator check is structurally first (the comment explains the earlier version that got this wrong). |
| `spine/docrefs.py` "Nothing here writes anything" / "never imports the code it inspects" | **CONFIRMED TRUE** — imports are `ast`, `re`, `dataclasses`, `pathlib`, `typing`. No `importlib`, no `__import__`, no `open(`, no `write_text`. |
| `build_exec.py` "refuses parallel=True for writes rather than silently downgrading" | **CONFIRMED TRUE** — raises at `build_exec.py:429`, with the refusal text naming the re-call. |
| `spine/attempt.py` "runner is never told where the repo is (no `repo_root` in `RunnerContext`)" | **CONFIRMED as a field** — `RunnerContext` (l.588) carries `worktree`, `branch`, `base_revision`, `task`, `is_cancelled`; no `repo_root`. Neither `gated_writes._spec_for` nor `picker`'s `TaskSpec` puts a repo root in `metadata`. Caveat, not a refutation: `TaskSpec.instruction` and `TaskSpec.metadata` are unconstrained free text, so the absence is structural, not enforced. |
| `spine/killswitch.py` "os.replace (atomic on both platforms)" | **CONFIRMED TRUE** — this is the one publisher in the repo that handles the Windows case, with the measurement recorded in the docstring. It is the reference implementation A3 asks the others to adopt. |
| `sensitivity.py::_within_write_allow` file entries admit descendants | **REFUTED** (already fixed) — the non-directory branch is exact equality with no `else`, and the docstring records the one-hour window in which it was not. |

---

## C. UNDECIDED

* **`semantic_route.py` "it never breaks routing".** `semantic_route_explained`
  has no top-level `try`; only the HTTP/embedding boundary is guarded. Every
  failure I could construct (`load_agents` on a malformed
  `<repo>/.agentenv/agents/*.json`) also breaks the keyword fallback it would
  degrade to, so no *regression* is demonstrable. The claim is narrowly true and
  structurally unprotected.
* **Provider `_backups` keying under Windows path-case.** Keys are
  `str(target)` from `(root / rel).resolve()`. `resolve()` canonicalises case for
  files that exist but not for files being created, so a create-then-rewrite
  under two spellings could in principle produce two entries, the second holding
  post-write bytes. I could not construct a path through `_resolve` that
  actually does it; flagged, not asserted.
* **`env.py::env_status`.** Returns `configured: bool(...)` for keyed providers
  (correctly redacted), but returns `OLLAMA_HOST` verbatim. A host string of the
  form `http://user:pass@host` would be surfaced to the web UI and the VS Code
  wrapper, against `env.py`'s "must never receive secret values". Depends on
  whether that spelling is reachable; not established.

---

## D. The pattern worth naming

Three of the four most serious confirmed gaps (A1, A2, A3) have the same shape:
**the file contains both the overstated guarantee and the correct qualification,
in different paragraphs, and the guarantee is the one at the top.**
`bootstrap.py` says "never writes the primary checkout" in the docstring and
"Refresh writes the generated map into the PRIMARY checkout" in a comment 100
lines down. `shift.py` says "on Windows you cannot replace a file another handle
holds open" in its header and then does it. `codex_cli.py` says "a denied path
never reaches codex" and then documents the residual risk that makes it
conditional.

That is not a documentation problem. In a repo whose gates read docstrings as
contracts, it means the *summary* line — the one a reader and a reviewing model
both stop at — is systematically stronger than the body. The mechanical fix is
cheap (state the exception in the same sentence as the guarantee); the
structural fix is a test that pins each "never" to a call.

The second pattern, smaller but sharper: **the repo already knows the answer and
one module has it.** `killswitch._atomic_write` and `budget._store` both carry
the Windows `os.replace` retry with the measurement attached; four other
publishers claiming the same atomicity do not. Whatever fix lands should make
that one function, not five copies of it.
