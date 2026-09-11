# Failure diagnosis: test_run_mission.py / test_desktop_packaging.py

Session HEAD: `54f0975398fd77120383c3af0ac5bb9291ef7064` (recorded before AND after
every measurement below; never moved during this session — no VOID redo
required). Note: the task brief's stated base `b3cc415b` had already advanced
to `54f09753` by the time this session started; the tree kept moving under
peers before I began, not during.

Interpreter used throughout: `.venv/Scripts/python.exe` (never bare `python`).
All temp files under `/tmp/diag_missdesk/`. All exit codes captured on a
separate statement after redirecting output to a file (never through a pipe).

---

## Subject A — `tests/orchestration/test_run_mission.py::test_migrated_surfaces_delegate_without_a_second_execution_path`

**Status:** Reproduces solo, deterministically.

### Run table

| Run | Command | Result |
|---|---|---|
| solo 1 | `pytest tests/orchestration/test_run_mission.py -q` | 1 failed, 6 passed |
| solo 2 | same | 1 failed, 6 passed |
| solo 3 | same | 1 failed, 6 passed |
| `--basetemp="C:/t/s1"` (8 chars) | same file | 1 failed, 6 passed |
| `--basetemp="C:/t/<75-char pad>/xx"` (~90 chars) | same file | 1 failed, 6 passed |

Exact command (RC captured separately, never through a pipe):
```
.venv/Scripts/python.exe -m pytest tests/orchestration/test_run_mission.py -q > /tmp/diag_missdesk/A_run1.txt 2>&1; echo "RC=$?"
```
RC=1 on all 5 arms. Failure text identical in every arm:
```
bridge = _function(FILE_BRIDGE, "_process_request_claimed")
>       assert len(_name_calls(bridge, "process_bridge_payload")) == 1
E       AssertionError: assert 0 == 1
```

**Verdict: DETERMINISTIC, path-length independent.** [MEASURED] The
tmp_path-length probe that solved the `test_chip_cli_canonical.py` sibling does
not apply here: this specific test (`test_migrated_surfaces_...`) takes no
`tmp_path` fixture at all — it is a pure `ast`-based static check reading
`daedalus/file_bridge.py` from a fixed `ROOT`-relative path. Identical failure
under an 8-char and a ~90-char `--basetemp`. Not order-dependent (only file
under test, no interaction with other tests observed) and not evidently
load-dependent by construction (no timing, no concurrency in the assertion
path) — load-dependence proper (`-n auto --dist loadfile`) was not measured
per the hard rule against running the full suite or `-n auto`; if this needs
final confirmation, it requires a quiet-box `-n auto` run, but nothing in this
test's logic gives xdist a channel to change its outcome.

### Classification: **(c) instrument went blind — not a real second execution path**

The test's `_name_calls(node, name)` helper only matches `ast.Call` nodes whose
`func` is a bare `ast.Name` (e.g. `process_bridge_payload(...)` called
directly by that literal name). It does **not** match an `ast.Attribute` call
(`ports.process_bridge_payload(...)`) and it only looks inside the AST of
`_process_request_claimed` in `daedalus/file_bridge.py`.

Commit `24f5102b` ("refactor(bridge): extract claimed dispatch state
machine") moved the actual invocation out of `_process_request_claimed`
entirely and into `daedalus/interfaces/bridge/dispatch.py`, where it is
injected via dependency injection as a port:

- `daedalus/file_bridge.py:766` — `from .core import process_bridge_payload`
- `daedalus/file_bridge.py:797` — `process_bridge_payload=process_bridge_payload,`
  (a **keyword-argument value**, not a call — `_name_calls` never sees this)
- `daedalus/interfaces/bridge/dispatch.py:695` — `report = ports.process_bridge_payload(payload, **dispatch_kwargs)`
  (the real call site — an **attribute** call, so `_name_calls`, which only
  matches bare-`Name` calls, would not catch it even if it looked in the right
  function)

**Enumeration — is there a second execution path?** [MEASURED] `Grep` for
`process_bridge_payload` across the whole tree (excluding comments/tests)
finds exactly **one** production call site:

```
daedalus/interfaces/bridge/dispatch.py:695:            report = ports.process_bridge_payload(payload, **dispatch_kwargs)
```

Every other hit is either the definition (`daedalus/core.py:1455`), the
import/passthrough in `file_bridge.py` (import + keyword-arg wiring, not a
call), the `ClaimedDispatchPorts` field type declaration
(`daedalus/interfaces/bridge/dispatch.py:187`), a docstring/comment mention
(`categories.py`, `ikarus_os.py`, `system_check.py`), or test-file
`monkeypatch`/direct-call usage. **Set size: 1 call site, 1 caller
(`_process_request_claimed` via `claim_and_dispatch_request` →
`process_claimed_request` → `ports.process_bridge_payload`).** No second path
exists — this is exactly the `f088f40e`-shaped blindness the brief warned
about: DI erased the name the detector keys on and relocated the call.

### First failing commit

`24f5102b` ("refactor(bridge): extract claimed dispatch state machine"),
2026-08-31 18:41:21 +0200. **This predates the entire given bisection range.**
[MEASURED] `git merge-base --is-ancestor 24f5102b f60ffd3d` → RC=0 (true);
`f60ffd3d` is the *oldest* commit in the range b3cc415b‥f60ffd3d. Confirmed
directly: `git show f60ffd3d:daedalus/file_bridge.py` already contains the
`process_bridge_payload=process_bridge_payload` keyword-arg wiring, and
`git show f60ffd3d:tests/orchestration/test_run_mission.py` already contains
the same `_name_calls(bridge, "process_bridge_payload") == 1` assertion. So
per the brief's own escape hatch: **"pre-existing, no commit in range
introduces it."**

### Root cause

**TEST expectation (instrument), not product code.** The one-execution-path
invariant (Master Plan §4 Invariant 1 / §13) actually holds — verified by
direct enumeration above. The AST detector is stale relative to a legitimate
DI refactor (callables passed as keyword arguments into a `ClaimedDispatchPorts`
dataclass rather than called by bare name at the audited call site).

**Release-blocker: NO.** No second execution path exists; the guard itself is
miscalibrated, not the architecture.

### Fix sketch

Owner: whoever maintains the architectural guard in
`tests/orchestration/test_run_mission.py` (test-dev / the author of the
bridge DI refactor, `24f5102b`, since they know where the call moved).
Options, in order of fidelity to the original intent:
1. Point the check at the new canonical call site: assert
   `_attribute_calls(_function(DISPATCH, "process_claimed_request"), "process_bridge_payload") == 1`
   where `DISPATCH = ROOT / "daedalus" / "interfaces" / "bridge" / "dispatch.py"`,
   in place of (or in addition to) the current bare-name check on
   `file_bridge.py`.
2. Extend `_name_calls`/`_attribute_calls` to also recognize a callable being
   threaded through as a keyword argument to a named ports/DI object, then
   verify only that DI target calls it exactly once — more invasive, not
   recommended for a narrow test fix.
Recommend option 1: smallest diff, directly re-establishes "exactly one call
site" as ground truth using the same AST-audit style already used elsewhere
in the same test file.

---

## Subject B — `tests/test_desktop_packaging.py::test_desktop_backend_readiness_is_child_nonce_bound`

**Status:** Reproduces solo, deterministically.

### Run table

| Run | Command | Result |
|---|---|---|
| solo 1 | `pytest tests/test_desktop_packaging.py -q` | 1 failed, 41 passed, 12 skipped |
| solo 2 | same | 1 failed, 41 passed, 12 skipped |
| solo 3 | same | 1 failed, 41 passed, 12 skipped |
| `--basetemp="C:/t/s2"` (8 chars) | same file | 1 failed, 41 passed, 12 skipped |
| `--basetemp="C:/t/<75-char pad>/yy"` (~90 chars) | same file | 1 failed, 41 passed, 12 skipped |

RC=1 on all 5 arms. Identical failure text every time:
```
>       assert 'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"' in web_api
E       assert 'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"' in '"""Local HTTP API and static webapp host for Daedalus Agent OS."""...'
```

**Verdict: DETERMINISTIC, path-length independent.** [MEASURED] This specific
test also takes no `tmp_path` fixture — it is a pure source-text
substring check over `daedalus/web_api.py`, `daedalus/interfaces/http/read.py`,
`tools/smoke_tauri_sidecar.py`, `scripts/daedalus_desktop_sidecar.py`.
Identical result at 8-char and ~90-char `--basetemp`. (Note: `--basetemp`
itself is orthogonal here by construction, same reasoning as Subject A —
noted this file *does* have other tmp_path-using tests, which is why the long
basetemp arm needed a pre-created padding directory to avoid an unrelated
`tmp_path_factory.mktemp` `FileNotFoundError` on other tests; the subject test
itself was unaffected in either arm.) Full `-n auto` load-dependence was not
independently measured (forbidden by the hard rules); nothing in this test's
logic gives concurrency a channel to change the outcome.

### Classification: **(b) stale test expectation after a facade repoint — NOT a broken trust boundary**

The literal string `'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"'`
no longer appears in `daedalus/web_api.py`. It was moved to its new owner,
`daedalus/interfaces/http/server.py:16`, by commit `50324965`
("refactor(http): extract bind admission owner"). `web_api.py` now only
re-exports it:

```
daedalus/web_api.py:1144:  DESKTOP_STARTUP_NONCE_ENV = http_server.DESKTOP_STARTUP_NONCE_ENV
daedalus/interfaces/http/server.py:16:  DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"
```

The same commit also moved the hex-nonce validation regex `r"[0-9a-f]{64}"`
out of `web_api.py` into `daedalus/interfaces/http/server.py:28`
(`desktop_startup_nonce()`), which is why the test's second assertion
(`assert 'r"[0-9a-f]{64}"' in web_api`, line 172) would fail too if the run got
that far — pytest stops at the first failed `assert` (line 170), so the run
output only shows the first miss, but the source-grep independently confirms
line 172 would also fail against current `web_api.py` (no occurrences of
`[0-9a-f]{64}` in that file).

**Is the nonce binding itself actually broken?** [MEASURED, read-only] No.
Traced the live implementation:
- `daedalus/interfaces/http/server.py:16` defines the env var name.
- `daedalus/interfaces/http/server.py:24-32` (`desktop_startup_nonce()`) reads
  it from `os.environ`, and — if non-empty — enforces `re.fullmatch(r"[0-9a-f]{64}", nonce)`
  or raises. This is the real validation the test line 172 wants to see; it
  is present, just relocated.
- `daedalus/interfaces/http/read.py:104-113` serves `/api/desktop-ready`,
  reading `self.server.daedalus_desktop_startup_nonce` (the per-process bound
  value) and returning it in the JSON body under `"nonce"`, refusing (404) if
  unset. This exactly matches what the test's remaining assertions (lines
  171, 173) check and those *do* still pass content-wise (not reached in this
  run because pytest stopped at line 170, but independently grepped and
  confirmed present).
- `tools/smoke_tauri_sidecar.py:37` sets `DAEDALUS_DESKTOP_STARTUP_NONCE` in
  the child's env and polls `/api/desktop-ready`, matching lines 174-175.

So the child-nonce-bound mechanism (env-var name → child env injection →
readiness endpoint scoped to `self.server`'s bound nonce → format validation)
is intact end-to-end; only the test's hard-coded expectation that the two
literal strings live inside `daedalus/web_api.py`'s own source text is wrong
after the bind-admission code moved behind a facade — exactly the pattern
the project's own `CLAUDE.md` describes this week ("many modules were
repointed off the `...` facade onto ... owners").

### First failing commit

`50324965` ("refactor(http): extract bind admission owner"), 2026-08-31
17:22:36 +0200. **This predates the entire given bisection range.**
[MEASURED] `git merge-base --is-ancestor 50324965 f60ffd3d` → RC=0 (true).
Confirmed directly: `git show f60ffd3d:daedalus/web_api.py` already shows
`DESKTOP_STARTUP_NONCE_ENV = http_server.DESKTOP_STARTUP_NONCE_ENV` (the
re-export, not the literal), `git show f60ffd3d:daedalus/interfaces/http/server.py`
already has the literal definition, and
`git show f60ffd3d:tests/test_desktop_packaging.py` already contains the
unchanged, already-failing assertion. Per the brief's escape hatch:
**"pre-existing, no commit in range introduces it."**

### Root cause

**TEST expectation (instrument), not product code, and not a trust-boundary
breach.** The nonce-binding security property (readiness signal scoped to the
specific child's server instance and gated on a 64-hex-char nonce format) is
implemented correctly at its new canonical location
(`daedalus/interfaces/http/server.py` + `read.py`). The test's literal-source
scan of `web_api.py` is stale after that code's canonical owner moved behind
the `web_api.py` compatibility facade.

**Release-blocker: NO.** The trust boundary this guard names is real and
currently held; only the assertion's target file/string is out of date.

### Fix sketch

Owner: test-dev (owns `tests/`), coordinating with whoever did the HTTP
admission-owner extraction (`50324965`) since they know the new module
boundary. Retarget the two literal-source assertions from `web_api.py` to
`daedalus/interfaces/http/server.py`:
```python
http_server = (ROOT / "daedalus" / "interfaces" / "http" / "server.py").read_text(...)
assert 'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"' in http_server
...
assert 'r"[0-9a-f]{64}"' in http_server
```
Optionally add a facade-integrity assertion (`web_api.DESKTOP_STARTUP_NONCE_ENV
is http_server.DESKTOP_STARTUP_NONCE_ENV`-style check, already covered
separately by `tests/interfaces/test_http_server_admission_owner.py:29`) so a
future repoint of the facade itself is still caught.

---

## Summary

| Subject | Reproduces solo | basetemp-sensitive | First failing commit | In given range? | Root cause | Release-blocker |
|---|---|---|---|---|---|---|
| A: `test_migrated_surfaces_delegate_without_a_second_execution_path` | Yes, 3/3 + 2 basetemp arms, deterministic | No | `24f5102b` (2026-08-31 18:41) | No — predates `f60ffd3d`, the oldest range commit | TEST instrument blindness (DI erased the bare-name call the AST detector keys on; real call site is a single attribute call in `dispatch.py`) | No |
| B: `test_desktop_backend_readiness_is_child_nonce_bound` | Yes, 3/3 + 2 basetemp arms, deterministic | No | `50324965` (2026-08-31 17:22) | No — predates `f60ffd3d`, the oldest range commit | TEST instrument stale (literal-source check still points at `web_api.py`; canonical definition moved to `daedalus/interfaces/http/server.py` behind a facade) | No |

Both subjects independently confirm the calibration note in the brief: this
round's more valuable result is a **refutation** — neither failure is the
architectural/trust-boundary breach its name suggests. Both are guards that
went stale/blind after this week's facade-repoint refactors
(`24f5102b`, `50324965`), and both predate the entire given bisection range,
so no commit within `b3cc415b..f60ffd3d` (first-parent) introduces either
failure.
