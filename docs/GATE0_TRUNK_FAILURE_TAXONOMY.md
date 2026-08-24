# What actually fails on the Gate-0 trunk

Measured 2026-08-17 by Athena. Worktree `agent_env_g0`, branch
`work/g0-trunk-20260817` at `60b2bfe` (`origin/integration/g0-consolidated-20260807`),
checked out with LF endings. Windows 11, Python 3.10, no `pytest-timeout` installed.

## The headline

Two earlier readings of this trunk were both wrong, in opposite directions.

| reading | claim | verdict |
| --- | --- | --- |
| "7 collection errors, the tree is broken" | the merge produced an incoherent tree | too pessimistic |
| "6501 collect clean, the tree is healthy" | the ~200 merge commits landed fine | too optimistic |
| measured pass/fail | **265 failed, 6186 passed, 51 skipped, 1 xfailed** in 30:20 | this one |

Collecting is not passing. That distinction is the whole finding.

## Where the failures are

```
tests/gates/       109
tests/kernel/       69
tests/runtimes/     57
everything else      ~2
```

The other ~6200 tests are green. The damage is confined almost perfectly to the
new Gate-0 kernel work — which is exactly where ~200 probe branches were merged
together. This is integration damage, not rot.

## The 265 are not 265 problems

Clustered by root cause (line counts from `--tb=line`, roughly 2 lines per test):

| ~tests | root cause | who is wrong |
| --- | --- | --- |
| 54 | `surface origin is invalid` | **the tests** |
| 27 | `HEAD must contain exactly one canonical line` | **the fixtures** (Windows-only) |
| 25 | `write-capable effect scope must declare bounded writable paths` | the tests |
| 21 | `effectful allow decision requires an explicit max_cost_microusd` | the tests |
| 18 | `Regex pattern did not match` | downstream of the above |
| 17 | fixture module has no attribute `_artifact` | genuine merge break |
| 8 | provider-observation store init | not yet diagnosed |
| 5 | `WindowsApps\python.exe` Errno 22 | Windows-only |
| 2 | `daedalus.gates` not importable in a subprocess | not yet diagnosed |

In every cluster diagnosed so far the **production contract is correct and the
test is stale.** That is the good news in this document: the merged kernel is
stricter than its tests, not weaker.

## Fixed today, with measurements

### 1. Fixtures wrote CRLF into byte-exact git files `[MEASURED]`

`Path.write_text` opens in text mode. On Windows the default newline translation
turns `"\n"` into `"\r\n"`. Fixtures hand-building git plumbing then produce bytes
that the strict reader correctly refuses:

```python
(git / "HEAD").write_text(revision + "\n", encoding="utf-8")   # -> b'aaa\r\n'
```

`repository_head_revision.py:66-69` strips exactly one trailing `\n`, sees the
orphaned `\r`, and raises. The reader is right; the fixture is not Windows-safe.

Proven directly:

```
bytes on disk : b'aaaa\r\n'
after strip   : 'aaa\r'
has CR -> rejected: True
with newline=LF: b'aaaaa\n'
```

Fix: `newline="\n"` on the write. Applied to 7 fixture modules (36 calls).

`tests/gates/test_repository_head_revision.py` alone: **20 passed, 2 skipped**
(was 20 failed).

This is the same family as yesterday's `.gitattributes` blocker. The repository
is developed and CI'd on Linux, and Windows-hostile byte assumptions keep landing
in fixtures because CI never sees them. Worth a standing check, not just a fix.

### 2. Four tests used a retired vocabulary for `origin` `[MEASURED]`

`RepositoryWriteSurface.origin` is a closed set:

```python
_ORIGINS = frozenset({"base_v1", "stdlib_delta_v1"})    # inventory_v2.py:31
```

and `inventory_v2.py` is the only producer, emitting exactly those two values at
lines 271 and 284. Nothing in production ever emits `"project"`.

Six sibling gate tests already use `origin="base_v1"` correctly. Exactly four
still passed `origin="project"` and failed in `__post_init__`. Same shape as the
`load_gate_evidence_index` import fix landed this morning: a test left behind when
a contract moved.

Measured effect of changing four string literals:

```
tests/gates/   110 failed, 620 passed   ->   57 failed, 673 passed
```

**53 tests recovered. No production code touched.**

## Not fixed, and why

### `EffectScope` is never constructed in production — the real integration gap

This matters more than the test failures.

Grepping all of `daedalus/`, `EffectScope` appears 11 times:

- defined — `schemas.py:409`
- deserialised — `contracts.py:178`, `contracts.py:280`, `schemas.py:1178` (all `from_dict`)
- annotated as a field — `contracts.py:123`, `contracts.py:201`, `schemas.py:1135`
- consumed — `effects.py:254` `_scope_requirements`

It is never **constructed**. Every `from_dict` deserialises something a producer
must have serialised, and no production path mints the original. The only
producers in the repository are tests.

Gate 0 requires "a centralized start/guard path for every effectful runtime
entrypoint" and invariant 4.8 requires spend, egress, write roots, concurrency,
secrets and a kill switch to be "enforced at effect boundaries". The contract that
carries those bounds is fully specified, rigorously validated, and consumed — and
nothing at runtime originates one.

Bounded honestly: `from_dict` admits an external producer outside this repository,
and `daedalus/kairos/gated_writes.py` materialises its implementation by
`exec()`-ing a retained blob that static search cannot see into. The claim is that
there is **no statically visible production construction**, which is what a grep
can establish and no more.

The ~46 kernel failures demanding `writable_paths` / `max_cost_microusd` are the
same contract being tightened. Migrating those fixtures is mechanical but must be
done per file — each builds its scope differently — and it is not worth doing
before the question above is answered. If nothing production-side builds an
`EffectScope`, the fixtures are the only consumers of the contract, and how they
should be shaped depends on what the real producer will look like.

### `_artifact` fixture drift (~17 tests)

`tests/gates/test_gate0_release_assessment.py:38` loads *another test file*
(`test_evidence_trust_bundle.py`) as a module via `spec_from_file_location` and
calls its private `_artifact` helper. That helper no longer exists — the fixture
file now defines `_provenance`, `_index`, `_repo`, `_bundle`, `_verify`,
`_repack_and_resign`.

One branch removed the helper; another kept calling it; the merge took both. Real
integration break, needs reconstruction rather than a rename. Also worth noting as
a design smell: a test reaching into another test's private helper by name is a
seam that no type checker or import graph protects.

## The blocker that stops all of this from landing

Nothing above can be committed. The pre-commit guard runs
`iron_plan_guard verify` (replaced by daedalus/hooks/, 2026-08-23), which exits **1** on this trunk because its
sealed-promotion check references a constant that no longer exists. Details and
the proposed repair are in `AMENDMENT_PROPOSAL_005_PROMOTION_GUARD_ROT.md`.

Until that is approved, this trunk accepts no commits at all.

## Suggested order

1. Approve proposal 005 — nothing else can land until commits work.
2. Land the two fixes above (73 tests, both proven, neither touches production).
3. Answer the `EffectScope` question. It decides the shape of the ~46 remaining
   kernel fixtures and it is a Gate 0 exit item in its own right.
4. Reconstruct `_artifact`.
5. Add a CI job that runs the suite on Windows, or stop treating Windows as
   supported. Two separate blockers this week came from LF/CRLF assumptions that
   Linux CI structurally cannot catch.
