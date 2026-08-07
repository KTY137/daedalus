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
3. a `ClaudeWorkspaceGrant` naming the exact request digest, execution digest,
   attempt, source revision, and isolated worktree handed to the subprocess.

The provider passes the private invocation callback to
`run_runtime_provider("provider.claude", ...)`. Therefore:

- lease grant and start are durable before `claude` is spawned;
- exact replay does not spawn Claude or extract output evidence again;
- runtime trust is rechecked after output and fenced through `COMPLETED`;
- malformed/missing output evidence produces no successful release;
- the public result is released only after a terminal receipt is durable.

## Exact invocation and replay identity

A persisted execution may be replayed inertly only when it denotes the same
provider operation. The provider therefore derives one canonical invocation
digest over:

- entrypoint and runtime identity;
- objective;
- exact resolved worktree;
- normalized path hints;
- agent payload;
- selected model and timeout;
- attempt id, source revision, and lease-request digest.

The execution idempotency key must equal `claude-<invocation_sha256>`. Changing
the objective, path set, model, timeout, worktree, attempt, revision, or request
cannot reuse a prior execution identity. This comparison happens before grant,
start, or subprocess invocation.

The current agentic CLI can inspect or edit any file in its isolated worktree,
not merely the optional path hints. Its execution scope must therefore declare
all four real effects—filesystem write, process spawn, network egress, and
spend—lease the isolated worktree root `.`, name the exact `claude` tool, and
carry a positive explicit spend ceiling. A falsely narrowed scope is refused.

## Direct-bypass removal

The old `daedalus.claude_bridge.ask_claude` import path remains, but is now a
compatibility adapter over `ClaudeCLIProvider.run()` and requires the same
explicit authority. Calls from legacy surfaces without runtime context fail
before subprocess creation.

`python -m daedalus.claude_bridge` is retained only as a fail-closed message:
an in-memory authority cannot be safely reconstructed from ordinary CLI flags,
so the module entrypoint performs no external effect.

The sole subprocess implementation is the private
`claude_bridge._invoke_claude_cli()` helper. Package-wide static tests assert
that it has exactly one importer and one caller and that it is the only Claude
subprocess owner.

## Workspace and evidence

The provider checks that:

- workspace grant attempt equals the authenticated lease request attempt;
- workspace grant revision equals the authenticated request revision;
- workspace grant request and execution digests match the supplied objects;
- `repo_root` resolves to the exact granted existing directory;
- path hints cannot be absolute, drive-qualified, or traverse outside it;
- Daedalus self-work is outside the primary checkout fence.

The bridge no longer writes `last_claude_prompt.md` or
`last_claude_report.json` into the Daedalus checkout. It returns canonical
prompt/report digests in memory. Before terminal completion, the provider
recomputes the report digest and binds the invocation, prompt, report, provider,
and agent identities into one output digest. Explicit CAS retention is a later
evidence packet rather than an ambient file write.

Unrecognized provider stderr/stdout is never inserted into terminal evidence or
raised verbatim; only its digest is retained in the error. A recognized Claude
wrapper limit remains a structured blocked report, preserving the pre-existing
adapter contract while still passing through the broker terminal boundary.

## Adversarial cases

The focused tests cover:

- missing runtime authority or workspace grant;
- worktree, request, execution, attempt, or source-revision substitution;
- objective, path, model, or timeout change under a stale idempotency key;
- understated write surface or spend scope;
- path traversal;
- non-central registry row refusal before invocation;
- exact replay without a second subprocess or evidence extraction;
- malformed/mismatched report evidence;
- one successful invocation with one completed terminal and content-addressed
  invocation/output evidence;
- legacy `ask_claude` refusal before subprocess creation;
- package-wide private-subprocess ownership inventory.

Mutation seeds:

1. remove the authorization check;
2. remove exact worktree, request, execution, attempt, or revision comparison;
3. omit one invocation input from the idempotency digest;
4. allow a narrower write root than `.` for the agentic CLI;
5. call the private helper before `run_runtime_provider`;
6. return output or extract evidence on replay;
7. accept an empty, malformed, or mismatched prompt/report digest;
8. reintroduce direct `subprocess.run` in `ask_claude`, `main`, or another
   provider path.

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
  tests/providers/test_claude_bypass_inventory.py \
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

## Independent review findings fixed

1. **Provider arguments were not part of the replay identity.** The first draft
   let a caller reuse an execution idempotency key while changing objective,
   paths, model, or timeout. The exact canonical invocation digest is now the
   execution idempotency identity and is checked before grant or subprocess.
2. **Path hints understated an agentic write surface.** The first draft accepted
   an arbitrary bounded writable path although Claude receives the complete
   worktree through `--add-dir`. The effect request must now honestly lease the
   isolated worktree root and path hints are treated only as normalized context.
3. **Output evidence omitted prompt/invocation identity.** The first draft bound
   the semantic report only. Completion now binds exact invocation, prompt,
   report digest, report bytes, provider, and agent, and rejects digest drift.

## Independent review questions

1. Does any public or module entrypoint still reach `subprocess.run` without the
   broker?
2. Can an authorization for another request, execution, attempt, or revision be
   repackaged around a different worktree?
3. Is every semantically relevant provider argument included in the invocation
   idempotency identity?
4. Is replay visibly inert to callers that previously expected a report?
5. Does output evidence bind semantic output without exposing absolute paths or
   secret stderr text?
6. Which production caller should own runtime-authority lookup and injection?
7. Is canonical registry activation premature before that caller is migrated?

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
