# Diagnosis: tests/test_ikarus_llm_voice.py

Checked-out tree: branch `main` @ `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291`
(subagent hook: "TREE: daedalus | main @851ff43c"). The assigned commit
`74008fab` is an ANCESTOR of this HEAD
(`git merge-base --is-ancestor 74008fab HEAD` → true; `git log --oneline -3 HEAD`
→ `851ff43c` merge, `dc321950`, `74008fab`). Diagnosis was run against the
checked-out HEAD, which is `74008fab` plus one further merge
(`dc321950`/`851ff43c`, "close the remaining 11 leaked sqlite connections",
which does not touch `daedalus/ikarus_os.py`, `daedalus/llm_client.py`, or
`daedalus/kernel/policy/limits.py`), so the finding applies identically at
`74008fab`.

Interpreter used throughout: `/c/Users/Administrator/daedalus/.venv/Scripts/python.exe`.

## Both nodes share one root cause

Both failing node IDs fail with the **same** `TypeError`, at the **same**
call site, on **every** solo run. They are reported together because the
evidence and fix are identical; only the assertions that would run *after*
the crash differ.

---

## test_chat_auto_route_uses_llm_client_and_records_resolved_provider

**Verdict: deterministic.** Not order- or load-dependent.

**Evidence (MEASURED):**

Command, run 3 times in isolation:
```
cd /c/Users/Administrator/daedalus && .venv/Scripts/python.exe -m pytest tests/test_ikarus_llm_voice.py -q > /tmp/runN.txt 2>&1; echo "RC=$?"
```
- run1: `RC=1`, tail: `2 failed, 1 passed in 0.46s`
- run2: `RC=1`, tail: `2 failed, 1 passed in 0.39s`
- run3: `RC=1`, tail: `2 failed, 1 passed in 0.73s`

Identical failure set and identical traceback shape on all 3 runs — no
flakiness, no order sensitivity within the file (it is also the only file in
scope per the task's hard rules, so cross-file pollution was not and could
not be tested here).

Exact captured failure (run1, `/tmp/run1.txt`):
```
    def test_chat_auto_route_uses_llm_client_and_records_resolved_provider(monkeypatch):
        monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient())
        seen = {}
        def fake_llm(provider, message, model=None, effort=None, project=None,
                     conversation_id=None, timeout_s=None, limit_policy=None):
            ...
        monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
>       out = ikarus_os._chat("project", "hello", None, conversation_id="conv_test")
...
        for attempts in attempt_numbers:
>           reply, model_used, ctx = _llm(
                selection.provider, message, model, effort, project,
                conversation_id=conversation_id, timeout_s=selection.timeout_s,
                limit_policy=limit_policy, additional_context=additional_context)
E           TypeError: test_chat_auto_route_uses_llm_client_and_records_resolved_provider.<locals>.fake_llm() got an unexpected keyword argument 'additional_context'

daedalus\ikarus_os.py:1033: TypeError
```

**First failing commit:** `151b8d18` — `chore(wip): freeze Gate-1 dirty tree
before hierarchy refactor` (2026-08-31 12:18:28 +0200), qualified below.

Archaeology (pure reads only — `git log`, `git show <rev>:<path>`):
- The test file's own history is exactly two commits:
  `git log --oneline -- tests/test_ikarus_llm_voice.py` →
  `5fa1aed0 feat(desktop): ship IDE and execution policy controls` (2026-08-30
  17:10:27, the file's current content and last edit) and
  `0d8400c5 feat(ikarus): make chat LLM-first and conversational` (creation).
  Neither is an ancestor-side change after the regression — the file has not
  been touched since 2026-08-30.
- `git show 5fa1aed0:daedalus/ikarus_os.py | grep additional_context` → no
  output. At the test's last edit, `_chat`/`_llm` had **no**
  `additional_context` parameter at all — the stub was correct for the
  contract at the time it was written.
- `git log --oneline 5fa1aed0..851ff43c -- daedalus/ikarus_os.py` →
  `9633129e`, `ba1254ca`, `151b8d18` (oldest last). `git show ba1254ca --
  daedalus/ikarus_os.py` and `9633129e`'s diff (checked) touch `ask`/
  `ask_stream`/`_ask_stream_inner`, not the `_chat`→`_llm` call site.
- `git show 151b8d18:daedalus/ikarus_os.py | grep -n additional_context` →
  first hit inside `_chat`/`_llm` at the exact call site
  (`limit_policy=limit_policy, additional_context=additional_context)`).
  This confirms `151b8d18` is the commit at which the current-shape call
  first exists in this branch's ancestry.
- Qualification: `151b8d18` is an explicit large WIP squash ("freeze Gate-1
  dirty tree before hierarchy refactor" — this matches the plan's own
  retirement note about a frozen WIP checkpoint). It bundles many files in
  one commit, so the *original, pre-squash* authorship of the
  `additional_context` threading cannot be recovered from this branch's
  linear history — there is no finer-grained commit boundary to bisect
  within the squash. I did not find and do not claim a more precise
  single-purpose commit than `151b8d18`; calling it "the first failing
  commit" means "first commit in this ancestry where the regression is
  observably present," not "the commit whose stated purpose was this
  change."
- Note: a same-named/same-purpose commit `4493e351 feat(ikarus): the Voice
  reads the project, and says what it read` (2026-09-02 03:40:50) also
  touches `additional_context` in `ikarus_os.py`, but
  `git merge-base --is-ancestor 4493e351 851ff43c` → **not an ancestor**
  (it lives on `wip/g1-freeze-2026-08-31`, a sibling branch). It is
  irrelevant to this HEAD's failure and is called out only to avoid a false
  attribution.

**Root cause:** product code vs. **stale test double**, not product vs. test
*expectation*. `ikarus_os._chat` (daedalus/ikarus_os.py:1033) unconditionally
calls `_llm(..., additional_context=additional_context)`. The real `_llm`
signature (daedalus/ikarus_os.py:1096-1101) has accepted
`additional_context: str = ""` since `151b8d18`. The test's local `fake_llm`
double was written to the pre-`151b8d18` five/eight-keyword contract and was
never updated when the product added the `additional_context` parameter to
the internal `_chat`→`_llm` call. This is a test-fixture staleness bug, not a
product defect: the product's real `_llm` happily accepts the extra keyword;
only the hand-written test double does not.

**Fix sketch:** add `additional_context=""` (or `**_ignored`) to both
`fake_llm` definitions in `tests/test_ikarus_llm_voice.py`
(lines 18-19 and 55-56). No product change required.

**Owner:** test suite — owner of `tests/test_ikarus_llm_voice.py`
(test-dev / Talos per `AGENTS.md` role split). Not `core-dev`/Daedalus
kernel, since `daedalus/ikarus_os.py` is already internally consistent.

---

## test_chat_unbounded_policy_removes_attempt_timeout_and_token_caps

**Verdict: deterministic**, same root cause as above.

**Evidence (MEASURED):** same 3 solo runs as above (single pytest invocation
covers the whole file); this node fails identically all 3 times. Exact
captured failure (run1, `/tmp/run1.txt`):
```
    def fake_llm(provider, message, model=None, effort=None, project=None,
                 conversation_id=None, timeout_s=150.0, limit_policy=None):
        ...
    monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
>   out = ikarus_os._chat(
        "project", "hello", None, voice_client=UnboundedClient()
    )
...
>           reply, model_used, ctx = _llm(
                selection.provider, message, model, effort, project,
                conversation_id=conversation_id, timeout_s=selection.timeout_s,
                limit_policy=limit_policy, additional_context=additional_context)
E           TypeError: test_chat_unbounded_policy_removes_attempt_timeout_and_token_caps.<locals>.fake_llm() got an unexpected keyword argument 'additional_context'

daedalus\ikarus_os.py:1033: TypeError
```

**First failing commit:** same as above — `151b8d18`, same qualification
(WIP squash, not further bisectable within this branch's history).

**Root cause — and the plan §4.1 question the task asked me to resolve:**

The crash happens in the harness call itself, **before** any of the test's
unbounded-policy assertions run — this test never reaches the lines that
check `out["llm"]["max_attempts"] is None`, `out["llm"]["timeout_s"] is None`,
or `ikarus_os._generation_extra("high", policy) is None`. So the immediate,
measured failure is the identical stale-stub `TypeError`, and the fix is the
identical one-line stub fix.

Given the task's explicit domain-context warning (§4.1: disabled caps must be
`None`, never `Infinity`/`MAX_INT`/`0`/omitted), I additionally traced —
**by reading source, NOT by executing** (I aborted a scratch-copy pytest run
that hung/contended for >120s in this shared 85-agent checkout; see
"Real-spend risk" below for why I stopped it rather than let it run) —
whether the product's unbounded-mode representation is actually correct, so
this report doesn't stop at "stub is stale" and miss a real product bug
hiding behind it:

- `daedalus/kernel/policy/limits.py:141-143` — `ExecutionLimitPolicy.effective`
  for `mode == "unbounded_execution"` returns `LimitAxes.uniform(False)` for
  **every** axis, i.e. `enforces(axis)` is `False` for all axes including
  `"tokens"`. No `Infinity`, no `0`, no omitted key — a plain boolean flag,
  exactly per §4.1's "explicit enforcement flag" requirement.
- `daedalus/ikarus_os.py:1068-1082` — `_effort_cap`/`_generation_extra`:
  `if limit_policy is not None and not limit_policy.enforces("tokens"): return None`.
  So `_generation_extra("high", policy)` returns `None` for the unbounded
  policy — matching the test's assertion, and matching §4.1 ("NEVER...
  `Infinity`... zero, or an omitted field").
- `LLMSelection` (`daedalus/llm_client.py:98-112`) stores `timeout_s: float |
  None` and `max_attempts: int | None` directly and `to_dict()` echoes them
  verbatim (lines 106-112) — no coercion to a sentinel. The test's
  `UnboundedClient.resolve` constructs
  `LLMSelection("claude_code_cli", "auto", True, None, None, "test")`, i.e.
  `timeout_s=None, max_attempts=None` positionally, which `_chat` then copies
  straight into the envelope's `llm` dict via `selection.to_dict()`.
- `_chat`'s attempt loop (`daedalus/ikarus_os.py:1027-1038`) uses
  `count(1)` (unbounded Python `itertools.count`) exactly when
  `selection.max_attempts is None`, so a `None` cap is honored as "no cap",
  not silently treated as `0` attempts or an infinite float.

**Conclusion on §4.1 (HYPOTHESIS, not measured — I did not get a green run of
this exact test):** the product's unbounded-policy representation appears
correct on static reading — `None`-typed, explicit-flag-gated, never
`Infinity`/`0`/omitted, consistent with §4.1. The only defect found in this
file is the stale test double's missing `additional_context` parameter,
identical to the first test. I am not claiming the second test would go
green solely from this reasoning; that requires an actual pytest run of the
corrected stub, which I did not perform (see below).

**Fix sketch:** same one-line fix as the first test — add
`additional_context=""` to this file's second `fake_llm` definition
(lines 55-56). No product change indicated by this diagnosis.

**Owner:** test suite (same as above).

---

## Why I did not execute a "fixed-stub" verification run

I wrote a scratch copy of the file under `/tmp/scratch_test_llm_voice.py`
(not touching the real test file — read-only rule respected) with
`additional_context=""` added to both `fake_llm` stubs, and ran
`.venv/Scripts/python.exe -m pytest /tmp/scratch_test_llm_voice.py -q`. This
exceeded the 120s foreground timeout and was moved to background; its output
file was empty (no pytest output at all — not even collection had reported),
consistent with contention/hang in this shared 85-agent, ~110-worktree
checkout (conftest fixtures, sqlite state, or a lock held by a concurrent
agent — see recent HEAD commits about "close the remaining 11 leaked sqlite
connections"), not with a real provider call (this scratch test still fully
monkeypatches `ikarus_os._llm` before any `_chat` call, exactly like the real
test, so no real LLM invocation is reachable from it). Per the task's rule 3
("pytest ONLY on the single file assigned to you") I judged running even a
copy under a different path as outside my mandate once it started behaving
anomalously, and I used `TaskStop` to kill the background task rather than
let a stray python process linger in the shared box. I did not retry it. The
§4.1 conclusion above is therefore explicitly a **static-reading hypothesis**,
not a measured pytest result — flagged as required by the task's evidence
rules.

---

## Cluster

Single cluster, single root cause: both nodes in this file fail from one
stale test double (`fake_llm` in `tests/test_ikarus_llm_voice.py`, both
copies) that does not accept the `additional_context` keyword argument that
`ikarus_os._chat` has passed to `ikarus_os._llm` since commit `151b8d18`.
Fix is test-only, one line per stub, two lines total. No product change
indicated.

## Real-spend risk

**None observed and none plausible from this file's own code.** In both
failing tests, `ikarus_os._llm` is monkeypatched to a local fake *before*
`ikarus_os._chat` is called, so the real `_llm` (which is what would reach a
provider CLI/API) is never invoked — the crash happens inside the call to the
fake itself. The third test in the file
(`test_chat_without_available_llm_is_loud_not_fake_deterministic`, which
passes) never reaches `_llm` at all (`selection.provider` is `None`, so
`_chat` returns the "unavailable" envelope early). No API keys were set, no
`codex`/`claude`/`ollama` CLI was invoked, and no ledger-backed spend path
was exercised at any point in this diagnosis, including the aborted scratch
run (which also fully monkeypatched `_llm`).
