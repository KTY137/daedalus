# G1-TESTS-01 — the shell routing tests stop spawning a live vendor

Packet ID: G1-TESTS-01

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: `585b7ea4e141332928ad6c9578b9c9997e55f247`

Working-tree context: branch `loop/lane5-shell-test-order`, worktree
`.claude/worktrees/lane5-shell-test-order`

Dependencies: none

Stage: lane 5 of the owner-directed 2026-09-05 parallel loop.

## Primary acceptance claim

`tests/test_ikarus_shells.py` no longer probes this machine's installed model
runtimes and no longer spawns a vendor CLI. Its routing verdicts are therefore
a function of the router and nothing else, and the file's own "No network"
docstring is true by construction rather than by intention.

The reported defect was
`GermanActRequestTest::test_declining_queues_nothing` failing with
`AssertionError: 'error' != 'chat'` at `tests/test_ikarus_shells.py:444` in a
combined 16-file, 855 s run while passing alone. **The order dependency does
not exist.** The test fails alone too, at a measured rate of 2 in 7. The
combined run was not the cause; it was extra opportunity.

## Scope

In scope, and the only files changed:

- `tests/test_ikarus_shells.py`

Explicitly out of scope:

- **`daedalus/` is untouched.** The production behaviour that turns a bad
  vendor answer into `intent="error"` is deliberate and documented in
  `_chat` ("Nothing was silently replaced with a deterministic chat answer").
  It is the correct fail-loud direction. There is no production defect here to
  fix, and this packet does not invent one.
- `tests/conftest.py` is unchanged. It pins the latent route, the operator
  `.env` declarations, the spine DB, the budget ledger and the worktree root,
  but not the Ikarus voice. That gap is suite-wide (11 test files call
  `ikarus_os.ask`), and closing it needs a full-suite non-weakening proof this
  packet did not run. Recorded below as follow-on work, not silently widened
  into this packet.
- The other 15 files of the reported combined run are unmodified. They were
  investigated and cleared (see below).

## Contracts and behavior

### What was actually happening (measured, not inferred)

With `provider=None` and a message that is neither an act request nor a
confirmation, `_route` sends the turn to `_chat`. `_chat` asks
`IkarusLLMClient.resolve(None)`, which:

1. finds no `DAEDALUS_IKARUS_PROVIDER` default, so it enters the automatic
   preference order and calls `cached_runtime_status` for each candidate —
   i.e. it probes whichever model CLIs this particular box has installed; then
2. returns the first available one. On this box:
   `{"provider": "claude_code_cli", "requested": "auto", "auto_selected": true,
   "max_attempts": 1, "reason": "first available provider in automatic
   preference order"}`.

`_llm` then spawns that vendor for real. When the single permitted attempt
returns nothing usable, `_chat` returns

```
core.envelope(project, intent="error", shell=SHELL_VOICE,
              assistant=f"{selection.provider} did not return a usable answer …")
```

which is exactly the observed `'error' != 'chat'`. Two independent failure
sources ride on that: *which* vendors the operator has installed (a different
box resolves to a different provider, or to none, and `provider=None` with no
available runtime is also `intent="error"`), and *whether* that one live call
succeeds on this invocation.

Three tests in the file took that path: `test_declining_queues_nothing`,
`test_without_conversation_state_a_confirmation_clears_nothing`, and
`FalsePositiveDoesNotReachTheHandTest::test_does_that_make_sense_is_answered_not_queued`.
All three assert `intent == "chat"`, which is precisely what a vendor hiccup
flips. The reported failure caught one of the three.

### The fix

A module hook, `setUpModule` / `tearDownModule`, installs two pins:

- `DAEDALUS_IKARUS_PROVIDER=claude` — `resolve` returns a *configured*
  provider and never reaches the probe loop, so the verdict stops depending on
  the machine.
- `_llm` returns a fixed triple — the resolved provider is never spawned.

Both are required. `DAEDALUS_IKARUS_PROVIDER=deterministic` does **not** work
and the packet records why: automatic selection deliberately never lands on the
local index (`resolve` short-circuits on `deterministic` only for an *explicit*
request), so an env default of `deterministic` falls straight through into the
probe loop. MEASURED:

```
resolve(None) with pin=claude:         reason='configured provider'
resolve(None) with pin=deterministic:  reason='first available provider in automatic preference order'
```

A module hook rather than a pytest fixture so that
`python -m unittest tests.test_ikarus_shells` is pinned as well; pytest honours
`setUpModule`. Both runners were verified.

`_llm` is pinned with `mock.patch.object(..., return_value=...)` — a MagicMock
that cannot go stale against `_llm`'s signature. That is the drift
`tests/test_ikarus_llm_voice.py::_assert_mirrors_real_llm` exists to catch for
doubles that spell the parameters out; this one has nothing to drift from.

### What the pin does not hide

- Routing is decided in `_route`, above `_chat`. Nothing the pin touches
  participates in a routing decision.
- A test that *names* a provider is unaffected: an explicit request never
  consults the env default. `ProviderFenceTest::test_an_unwired_voice_fails_closed`
  (`provider="gemini"` → `provider_used == "unavailable"`, `intent == "error"`)
  still exercises the real refusal, and
  `test_chat_still_honors_the_clients_choice_of_voice` still asserts
  `provider_used == "claude_code_cli"` through its own inner `_llm` patch.
- The auto-selection path itself remains covered hermetically in
  `tests/test_ikarus_llm_voice.py` against a fake client, including the
  no-voice-available case
  (`test_chat_without_available_llm_is_loud_not_fake_deterministic`), so the
  `intent="error"` behaviour this packet stops *accidentally* triggering is
  still tested *deliberately* somewhere.

### Nothing weakened; three assertions added

No assertion was removed or relaxed. Three were added, so that a pin which
accidentally short-circuited a turn would be visible instead of quietly
satisfying the existing assertions:

| Test | Added |
| --- | --- |
| `test_declining_queues_nothing` | `shell == SHELL_VOICE`, `assistant == _PINNED_VOICE_REPLY` |
| `test_without_conversation_state_a_confirmation_clears_nothing` | `shell == SHELL_VOICE`, `assistant == _PINNED_VOICE_REPLY` |
| `test_does_that_make_sense_is_answered_not_queued` | `assistant == _PINNED_VOICE_REPLY` |

The declining/confirmation tests previously did not check that the turn
reached the Voice at all.

## Acceptance matrix

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| 1 | The reported failure reproduces **alone**, refuting the order-dependency premise | `pytest "tests/test_ikarus_shells.py::GermanActRequestTest::test_declining_queues_nothing" -q` × 7 at base | 2 failed (34.8 s), 5 passed (74.7 / 80.3 / 90.5 / 118.4 / 118.6 s) — same `'error' != 'chat'` |
| 2 | The live vendor is the mechanism | direct call, base revision | `llm.provider == "claude_code_cli"`, `auto_selected: true`, `max_attempts: 1` |
| 3 | `deterministic` is not a usable env pin | `IkarusLLMClient().resolve(None)` under each pin | `configured provider` vs `first available provider in automatic preference order` |
| 4 | The whole file passes and stops paying for vendor calls | `pytest tests/test_ikarus_shells.py -q` | 42 passed, 34 subtests, **18.58 s** (baseline: see row 5) |
| 5 | Baseline for the same file, unpinned | `pytest` on `git show HEAD:tests/test_ikarus_shells.py` copied in as a temporary module | 42 passed, 34 subtests, **259.06 s** |
| 6 | The reported 16-file order no longer fails in the shell file | the exact reported file set, one process, same order | **zero** failures in `tests/test_ikarus_shells.py`; run total 21 failed, 347 passed, 44 skipped, 7 xfailed, 34 subtests, 103.20 s — every one of the 21 is a named baseline failure, see below |
| 7 | The single test still passes alone, repeatedly and cheaply | `pytest …::test_declining_queues_nothing -q` × 5 | 5/5 passed, 0.84 / 0.90 / 0.90 / 1.30 / 1.83 s (baseline 34.8–118.6 s, 2/7 red) |
| 8 | The pin holds under the other runner | `python -m unittest tests.test_ikarus_shells.GermanActRequestTest -v` | 7 tests OK in 1.901 s |

## Migration and rollback

No migration: this packet adds a module hook and three assertions to one test
file. Nothing in `daedalus/` changed, no contract moved, no fixture in
`tests/conftest.py` changed, so no other test file can be affected by it.

Rollback is `git revert` of the single commit on
`loop/lane5-shell-test-order`, which restores the live-vendor behaviour
together with its measured 2-in-7 flake rate and the ~240 s of vendor calls it
adds to every run of this one file (259.06 s → 18.58 s).

## Evidence, expected failures, and review

Interpreter: `.claude/worktrees/lane5-shell-test-order/.venv/Scripts/python.exe`
(CPython 3.13.14, `uv venv` + `uv pip install -e . pytest` in the worktree, so
the editable `daedalus` resolves to the worktree and not to the main checkout).
No `pytest-randomly` is installed, so collection order is file order and the
runs above are the orders they claim to be.

### Baseline failures, named separately (Plan §10.7)

The 16-file acceptance run reports 21 failures. **None is in this packet's
file and none is caused by this packet.** All 21 are in
`tests/test_ikarus_computer_schedule_autonomy.py`, which is file 15 of 16 in
that ordering — it finishes before `tests/test_ikarus_shells.py` is even
imported, so this packet's module hook has not run when they fail. Run alone at
the same revision that file is `20 failed, 14 passed, 1 skipped in 18.26 s`,
e.g.

```
tests/test_ikarus_computer_schedule_autonomy.py:78: AssertionError
assert 'reconciliation_required' == 'completed'
```

so it is red at `585b7ea4` independently of anything here. Worth passing to
whoever owns the computer-schedule lane: it is 20 red alone and 21 red in the
16-file run, so that file additionally has a mild order dependency of its own.
This packet does not touch it.

The run also collects fewer tests than the 855 s figure in the brief, because
this worktree's `.venv` installs only `pytest` (per the lane setup) and not the
`pytest-asyncio` / `pytest-xdist` extras. The 103.20 s total is therefore **not**
comparable to the reported 855 s, and this packet claims no speed-up from it.
The like-for-like timing claim is row 4 versus row 5, same file, same
interpreter: 259.06 s → 18.58 s.

### Ruled out, with the measurement that ruled it out

- **An environment-variable polluter among the other 15 files.** None of them
  assigns `os.environ[...]` at all; every one uses `monkeypatch` or
  `patch.dict`, which restore. (`grep -c 'os\.environ\['` = 0 for all 15.)
- **A poisoned `runtime_registry` status cache.** `cached_runtime_status` is a
  process-wide TTL cache and would be a real order-dependency vector, but none
  of the 15 files references `runtime_registry`, `cached_runtime_status` or
  `_status_cache`.
- **A leaked ledger, spine DB or worktree root.** `tests/conftest.py` already
  pins all three per test and resets `budget.reset_default_ledger()`.
- **Order dependency of any kind.** Falsified directly by acceptance row 1: the
  test fails with no other file in the process.

### Expected failures

The pinned voice is a *module* pin. A future test added to this file that wants
to exercise real provider selection must patch `_voice_client` or `_llm` itself
(the inner patch wins) rather than assume `provider=None` reaches a vendor — it
will not. `setUpModule`'s docstring says so at the point of use.

### Residual risk and follow-on work, not done here

`tests/conftest.py` pins the latent route, the operator declarations, the spine
DB, the ledger and the worktree root, but not the Ikarus voice. Any test in the
suite that calls `ikarus_os.ask(..., provider=None)` on a chat-routed message
still probes the box's runtimes and spawns a vendor. Eleven test files call
`ask`: `test_conversation_legacy_entrypoint_binding.py`,
`test_conversation_requests.py`, `test_ikarus_chat_shim_argv.py`,
`test_ikarus_context.py`, `test_ikarus_os.py`, `test_ikarus_os_boundary.py`,
`test_ikarus_project_grounding.py`, `test_ikarus_shells.py` (fixed here),
`test_ikarus_stream.py`, `test_wires.py`. A suite-wide voice pin in
`tests/conftest.py` is the systemic answer and is the natural next packet; it
was not taken here because proving it weakens no test requires a full-suite
run, and this lane's scope was one file. This is stated rather than quietly
attempted.

### Review questions

1. Is a *module*-level voice pin the right granularity, or should the three
   affected tests each carry their own visible `with` block? The module hook
   was chosen because it also makes the file's "No network" docstring
   enforceable and because it survives `python -m unittest`; the cost is that
   the pin is not visible at the three call sites.
2. `DAEDALUS_IKARUS_PROVIDER=claude` is a real vendor name for a test that
   never calls a vendor. Is that acceptable as "the configured provider that
   `_llm` is then stubbed out of", or should the file instead patch
   `_voice_client` with the `_FakeClient` shape used in
   `tests/test_ikarus_llm_voice.py`?
3. Should the suite-wide conftest pin in the residual-risk section be raised as
   a Gate-1 packet now, given that it silently spends the operator's money on
   every full-suite run?
