# G0-RTC-06F — Claude provider broker adoption

## Objective

Remove ambient-authority Claude execution from the public provider and legacy
`ask_claude` paths, then make the Claude subprocess implementation consumable
only through the persisted runtime-provider broker.

This packet is stacked on `G0-RTC-06E`. It prepares one provider for canonical
registry activation but deliberately leaves the canonical `provider.claude`
row non-central until caller injection and exact-head verification are complete.

## Public boundary

`ClaudeCLIProvider.run()` now requires all three of:

1. an exact `RuntimeBoundEffectAuthorization`;
2. one narrowed `EffectExecutionRequest`; and
3. a `ClaudeWorkspaceGrant` naming the same attempt, source revision, and exact
   isolated worktree handed to the subprocess.

The provider passes the private invocation callback to
`run_runtime_provider("provider.claude", ...)`. Therefore:

- lease grant and start are durable before `claude` is spawned;
- exact replay does not spawn Claude or extract output evidence again;
- runtime trust is rechecked after output and fenced through `COMPLETED`;
- malformed/missing output evidence produces no successful release;
- the public result is released only after a terminal receipt is durable.

## Direct-bypass removal

The old `daedalus.claude_bridge.ask_claude` import path remains, but is now a
compatibility adapter over `ClaudeCLIProvider.run()` and requires the same
explicit authority. Calls from legacy surfaces without runtime context fail
before subprocess creation.

`python -m daedalus.claude_bridge` is retained only as a fail-closed message:
an in-memory authority cannot be safely reconstructed from ordinary CLI flags,
so the module entrypoint performs no external effect.

The sole subprocess implementation is the private
`claude_bridge._invoke_claude_cli()` helper. Static tests assert that it is the
only owner of `subprocess.run` in that module and that the provider has exactly
one call site for it.

## Workspace and evidence

The provider checks that:

- workspace grant attempt equals the authenticated lease request attempt;
- workspace grant revision equals the authenticated request revision;
- `repo_root` resolves to the exact granted existing directory;
- Daedalus self-work is outside the primary checkout fence.

The bridge no longer writes `last_claude_prompt.md` or
`last_claude_report.json` into the Daedalus checkout. It returns canonical
prompt/report digests in memory. The broker's terminal receipt binds the
canonical provider/agent/report output digest. Explicit CAS retention is a
later evidence packet rather than an ambient file write.

## Adversarial cases

The focused tests cover:

- missing runtime authority;
- missing workspace grant;
- worktree substitution;
- attempt substitution;
- source-revision substitution;
- non-central registry row refusal before invocation;
- exact replay without a second subprocess;
- one successful invocation with one completed terminal and content-addressed
  output evidence;
- legacy `ask_claude` refusal before subprocess creation;
- static private-subprocess ownership.

Mutation seeds:

1. remove the authorization check;
2. remove exact worktree comparison;
3. remove attempt or source-revision comparison;
4. call the private helper before `run_runtime_provider`;
5. return output on replay;
6. emit an empty/malformed output digest;
7. reintroduce direct `subprocess.run` in `ask_claude` or `main`.

## Deliberate remaining blockers

- The canonical effect registry still marks `provider.claude` as
  `INVENTORY_ONLY`. A runtime-bound lease therefore remains unissuable through
  the default registry. Activation requires a separate small packet after all
  production callers inject runtime authority and no bypass remains.
- `core.process_bridge_payload` and the file watcher do not yet have an
  authenticated runtime-authority resolver. Their Claude fallback now fails
  closed instead of spending from ambient authority.
- No live Claude binary is invoked and no live conformance envelope, provider
  secret, or production key is fabricated.
- GitHub Actions exact-head evidence remains required. Jobs that fail before
  step 1 are infrastructure evidence only.
- Gate 0 remains open.

## Verification contract

```bash
python tools/iron_plan_guard.py verify
python -m compileall -q daedalus tests
python -m pytest -q \
  tests/providers/test_claude_runtime_broker.py \
  tests/runtimes/test_runtime_provider_broker.py \
  tests/runtimes/test_runtime_terminal_fence.py \
  tests/runtimes/test_runtime_terminal_fence_release.py \
  tests/kernel/test_runtime_effects.py \
  tests/test_effect_boundary.py
python -m pytest -q
python -m build
```

Dedicated CI requests Python 3.10/3.12, two hash seeds, Linux and Windows for
the focused boundary, the full suite on Linux, and isolated wheel imports.

## Independent review questions

1. Does any public or module entrypoint still reach `subprocess.run` without the
   broker?
2. Can an authorization for another attempt or revision be repackaged around a
   different worktree?
3. Is replay visibly inert to callers that previously expected a report?
4. Does output evidence bind semantic output without including ambient absolute
   paths or secret stderr text?
5. Which production caller should own runtime-authority lookup and injection?
6. Is canonical registry activation premature before that caller is migrated?

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
