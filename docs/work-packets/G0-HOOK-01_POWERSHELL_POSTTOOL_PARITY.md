# G0-HOOK-01 - PowerShell PostToolUse parity

## Packet identity

- Classification: `ALIGNED`
- Active gate: Gate 0
- Owner: Codex implementation lane; merge and promotion remain owner decisions
- Base revision: `5f6bfc06f4cbcccbb2d0e6f770ce58ae24209c41`
- Branch: `codex/hooks-powershell-20260823`
- Worktree: `C:\Users\nukei\Desktop\agent_env.worktrees\codex-hooks-powershell`
- Plan digest (SHA-256): `01DF5D2E47DF688ADE80244FBB803D097EF2133269BD731D8B0D178B01D2A89F`
- Amendment-chain digest (SHA-256): `590CC48B6DAA352EE2DB9535903D0AD5ADBB1FC60747BDC55AE6397B9A574039`
- External contract: [official Claude Code hooks reference](https://code.claude.com/docs/en/hooks)

## Objective and alignment

Make the existing `PostToolUse` dispatcher observe successful PowerShell shell
calls with the same semantics as Bash. This is wiring through the already
registered `daedalus.hooks` entrypoint; it creates no subsystem or authority.

The packet touches constitutional invariant 7 (claims about a successful test
run retain the exact command) and invariant 8 (the existing bounded hook effect
is not bypassed or widened). The official hook contract says shell-inspecting
hooks must match `Bash|PowerShell`; PowerShell can be the primary or only shell
tool on Windows.

## Frozen scope

In scope:

- `.claude/settings.json`
- `daedalus/hooks/tools.py`
- `tests/test_hooks_v2.py`
- this Work Packet

Forbidden in this packet:

- Serena routing or wrong-tree guard behavior;
- permissions, effect-boundary registry, ledger format, or promotion policy;
- other hook events, the Iron Plan, its amendment chain, or `AGENTS.md`;
- changes or merges in the primary `main` worktree.

## Reproduced baseline

At the frozen base revision:

```text
matcher= Bash
powershell_pytest_note= ''
uv_run_pytest_recognized= False
uv_run_python_pytest_recognized= False
```

The existing test suite has Bash-only PostToolUse fixtures, so this gap is not a
known failing test at baseline.

## Acceptance matrix

| ID | Acceptance claim | Deterministic evidence |
| --- | --- | --- |
| PWR-01 | Project settings subscribe PostToolUse to both shell tools. | Parse settings and assert the exact matcher `Bash|PowerShell`. |
| PWR-02 | A successful `pytest` call reported by `PowerShell` records the same source fingerprint and delta shape as `Bash`. | Existing Bash delta test plus a PowerShell test parameterized over direct `pytest` and bare `uv run pytest`. |
| PWR-03 | Direct pytest and the bare `uv run pytest` / `uv run python -m pytest` forms are recognized without accepting lookalikes. | Exact positive forms plus negative cases for `uv runner`, `pytestx`, and echoed text. |
| PWR-04 | The post-commit docs reminder also works for PowerShell, while dry runs and non-shell tools remain silent. | Parameterized commit test plus explicit refusal fixture. |
| PWR-05 | Existing hook behavior does not regress. | Full `tests/test_hooks_v2.py` plus focused tests. |

## Budgets and failure semantics

- No network, secret, provider, model, or new process budget.
- The existing 10-second command-hook timeout is unchanged.
- Only successful `PostToolUse` events count as successful tests; failed tool
  calls remain outside this event exactly as before.
- Unsupported tool names fail open and produce no state or context.

## Excluded finding

The separate review finding that the Serena wrong-tree write check allows an
unknown or missing `.mcp.json` is deliberately not addressed here. It needs its
own acceptance matrix because it changes deny/fail-open policy.

The deliberately small `uv run` recognizer does not parse optional uv flags
such as `uv run --frozen pytest`, `uv run -- pytest`, or
`uv --directory DIR run pytest`. Supporting the full uv CLI grammar is a
separate parser change; this packet claims only the exact bare forms in PWR-03.

## Verification and rollback

Builder evidence:

```text
focused acceptance selection: 24 passed, 41 deselected
tests/test_hooks_v2.py: 65 passed
settings JSON parse: passed
compileall: passed
git diff --check: passed
direct handler probe: pytest, uv run pytest, uv run python -m pytest -> test-run-recorded
```

Ruff was unavailable in the selected Python environment (`No module named
ruff`); this failed availability probe is retained rather than reported as a
lint pass. Independent read-only review returned `APPROVE` with no
release-blocking defect and identified only the intentionally excluded uv CLI
option grammar above plus the now-corrected matrix wording.

Rollback is a single revert of this packet's implementation commit. No state
migration or data rollback is required.

Iron Plan: **ALIGNED**

Iron Gate: **0**

Promotion: **not requested**
