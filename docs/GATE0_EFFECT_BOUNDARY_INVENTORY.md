# Gate-0 effect-boundary inventory

Status: `STATUS` — a revision-bound measurement, not a timeless claim.
Measured: 2026-08-17 on `work/g0-trunk-20260817` @ `60b2bfe`.
Registry sha256 at measurement: `b8cab096e4bf2dfdc56866d1a5c4d726c34a2eb6091d9693a1b101ca1e17950d`.
Scope: investigation and inventory. **No production code was changed to produce
this document.**

Iron Plan: ALIGNED · Iron Gate: 0 · Invariant touched: 8 (bounded effects),
1 (one kernel), 7 (provenance).

---

## 0. Why this document exists

`tools/effect_boundary_check.py` reports 66 discovered targets against a 53-row
registry. That gap was quoted as "13+ unregistered entrypoints". Both halves of
that arithmetic are wrong in opposite directions, and the true migration
population is larger than either number. This document reconciles the counts,
names every gap with `file:line`, and ranks the whole population by how much
risk central routing would actually remove.

Everything below is reproducible:

```
python -c "import sys; sys.path.insert(0,'.'); \
from daedalus.spine.effect_boundary import check_conformance; \
r=check_conformance('.'); d=r.to_dict(); \
print(len(d['matrix']), len(d['discoveries']), d['structurally_conformant'])"
# -> 53 66 False
```

---

## 1. The arithmetic, reconciled

`66 - 53 = 13` is a coincidence of two errors cancelling. The real ledger:

| quantity | count | note |
| --- | ---: | --- |
| registry rows (`ENTRYPOINTS`) | 53 | |
| ... of which non-discoverable | 1 | `mcp.runtime`, target `<absent>` |
| ... discoverable registry targets | 52 | |
| discovered targets | 66 | |
| discovered **and** registered | 51 | |
| discovered but **unregistered** (blockers) | **15** | all under `tools/` |
| registered but **not rediscovered** | 1 | `daedalus.claude_bridge:main` |

Check: `51 + 15 = 66` ✓ and `51 + 1 = 52` ✓.

So the correct figure for "discovered and unregistered" is **15, not 13**. The
`13` fell out of `66 − 53` because the non-discoverable `mcp.runtime` row and
the stale `cli.claude_bridge` row each hid one.

Current wiring distribution across the 53 rows:

| wiring | rows |
| --- | ---: |
| `central` | 1 (`python.offload`) |
| `local_guards` | 11 |
| `inventory_only` | 40 |
| `absent` | 1 (`mcp.runtime`) |

32 of 53 rows declare **zero** guard contracts.

---

## 2. Population A — the 15 discovered-but-unregistered (`entrypoint.unregistered`)

These are hard blockers today. Effects are as the scanner infers them; the
"real effects" column corrects the ones the scanner structurally cannot see
(see §5).

| # | file:line | target | discovered effects | real effects (corrected) |
| --- | --- | --- | --- | --- |
| A1 | `tools/audit_swarm.py:282` | `tools.audit_swarm:main` | `process_spawn` | **`spend`**, `network_egress`, **`secrets`**, `filesystem_write`, `process_spawn` |
| A2 | `tools/funnel.py:587` | `tools.funnel:main` | `process_spawn` | **`spend`**, `network_egress`, **`secrets`**, `filesystem_write`, `process_spawn` |
| A3 | `tools/iron_plan_guard.py:1999` | `tools.iron_plan_guard:main` | `filesystem_write`, `process_spawn` | + **`repository_mutation`** (git plumbing, commit-msg/pre-commit hooks (removed 2026-08-22)) |
| A4 | `tools/gui_check.py:441` | `tools.gui_check:main` | `filesystem_write`, `network_egress`, `process_control`, `process_spawn` | as discovered (spawns `node`/playwright, binds and kills a dev server) |
| A5 | `tools/gate_discrimination.py:1087` | `tools.gate_discrimination:main` | `filesystem_write`, `process_spawn` | + **`repository_mutation`** (mutates a tree, runs the corpus, writes a receipt) |
| A6 | `tools/bootstrap_receipt.py:739` | `tools.bootstrap_receipt:main` | `filesystem_write`, `process_spawn` | + **`repository_mutation`** |
| A7 | `tools/operability_drill.py:709` | `tools.operability_drill:main` | `filesystem_write`, `process_spawn` | + **`repository_mutation`** |
| A8 | `tools/gate_host_preflight.py:363` | `tools.gate_host_preflight:main` | `filesystem_write`, `process_spawn` | + **`repository_mutation`** |
| A9 | `tools/mutation_score.py:709` | `tools.mutation_score:main` | `filesystem_write` | as discovered |
| A10 | `tools/audit_triage.py:248` (removed 2026-08-21) | `tools.audit_triage:main` | `filesystem_write` | as discovered |
| A11 | `tools/agent_findings.py:282` (removed 2026-08-21) | `tools.agent_findings:main` | `filesystem_write` | as discovered |
| A12 | `tools/lane_invariants.py:274` | `tools.lane_invariants:main` | `filesystem_write` | as discovered |
| A13 | `tools/funnel_report.py:438` | `tools.funnel_report:main` | `process_spawn` | as discovered (reads a run dir; the `fan_out` mention is docstring only) |
| A14 | `tools/run_gate_checks.py:46` | `tools.run_gate_checks:main` | `process_spawn` | as discovered |
| A15 | `tools/iron_plan_hook_runner.py:44` (replaced by daedalus/hooks/, 2026-08-23) | `tools.iron_plan_hook_runner:main` | `process_spawn` | as discovered |

**A1 and A2 are the two that spend real money.** Verified call sites:

- `tools/audit_swarm.py:54` `from daedalus.lanes.fanout import FanoutTask, fan_out`; called at `tools/audit_swarm.py:314`.
- `tools/funnel.py:71` same import; called at `tools/funnel.py:652`.

`fan_out` does install the process guard (`daedalus/lanes/fanout.py:371-372`),
so these calls *are* priced — but the pricing is a property of the callee, not
of the entrypoint, and neither entrypoint appears in the effect registry at all.

Correctly excluded (have `main`, genuinely read-only, scanner right to skip):
`tools/assert_gate_report.py`, `tools/effect_boundary_check.py`.

---

## 3. Population B — effectful `tools/` entrypoints the scanner cannot see at all

These are **not** in the 66 and **not** in the 15. They are invisible by
construction, which is worse than being a named blocker.

| # | file:line | why the scanner misses it | real effects |
| --- | --- | --- | --- |
| B1 | `tools/guarded_call.py:47` (`main`) | the only call is `DeepSeekProvider.run(...)` — a **cross-module** call, and the fixed point in `discover_entrypoints` resolves same-module names only. `spend`/`secrets` additionally have no sink at all. | **`spend`**, **`secrets`**, `network_egress` |
| B2 | `tools/system_check.py:1095` (`main`) | `main → acceptance_run → spec["fn"](sb)` — dispatch through the `CHECKS` **table**, so no call name resolves; and `sb.build()` is an instance-method call from a module-level function, which the class-qualified fallback only handles for callers that are themselves methods. | `filesystem_write`, `process_spawn`, `network_egress`, `process_control`, `repository_mutation` (clones the working tree, `subprocess.Popen` @663/@788, `urlopen` @676, writes probes @458/@604/@764/@844/@871/@913) |

B1 is the sharpest item in this whole inventory. `tools/guarded_call.py` is the
repository's **deliberate external-model door** — its own module docstring calls
itself an application of invariant 8 — and it is absent from the inventory that
invariant 8 is supposed to be enforced through.

B2 means the file that verifies the system's safety properties end-to-end,
including spawning servers and reaching the network, is not itself an
inventoried effect.

---

## 4. Population C — the four directories the scan never opens

`SCAN_PACKAGES = ("daedalus", "tools")` (`daedalus/spine/effect_boundary.py:973`).
Measured by re-running the identical discovery over every python-bearing
top-level directory:

| top-level dir | `.py` files | scanned | unregistered entrypoints found |
| --- | ---: | --- | ---: |
| `daedalus` | 275 | yes | 0 |
| `tools` | 20 | yes | 15 |
| `runs` | 12 | **no** | **9** |
| `scripts` | 82 | **no** | **73** |
| `tests` | 470 | **no** | 17 |
| `examples` | 5 | **no** | 0 |

Widened discovery: **165 targets, 114 unregistered.**

### C-runs: production-capable, spends money, entirely outside the registry

`runs/` is the one unscanned directory that is unambiguously in Gate-0 scope:
`daedalus/budget.py:BILLABLE_SITES` lists five of its functions as billable.

| # | file:line | target | effects | in `BILLABLE_SITES`? |
| --- | --- | --- | --- | --- |
| C1 | `runs/council/room.py:1184` | `runs.council.room:main` | `filesystem_write`, `network_egress`, `process_spawn`, **`spend`**, **`secrets`** | yes — `ask_codex`, `ask_fable`, `ask_opus`, `ask_agy`(ssh), `ask_ollama` |
| C2 | `runs/council/summarize.py:1011` | `runs.council.summarize:main` | `filesystem_write`, `process_spawn`, **`spend`** | yes — `cli_summariser`, `ollama_summariser` |
| C3 | `runs/ab/run_arm.py:147` | `runs.ab.run_arm:main` | `filesystem_write`, `process_spawn`, **`spend`**, **`repository_mutation`** | yes — `call_claude` |
| C4 | `runs/council/room_server.py:540` | `runs.council.room_server:main` | **`listen_socket`**, `filesystem_write`, **`spend`** (drives `room.py`) | server itself no; the room it drives yes |
| C5 | `runs/council/room_server.py:472` | `runs.council.room_server:Handler.do_POST` | `filesystem_write` | — |
| C6 | `runs/ab/score.py:145` | `runs.ab.score:main` | `filesystem_write`, `process_spawn`, `repository_mutation` | — |
| C7 | `runs/ab/oracle_check.py:132` | `runs.ab.oracle_check:main` | `filesystem_write`, `process_spawn` | — |
| C8 | `runs/council/stream_hook.py:448` | `runs.council.stream_hook:main` | `filesystem_write` | — |
| C9 | `runs/council/dead_letter_replay.py:338` | `runs.council.dead_letter_replay:main` | `filesystem_write` | — |
| C10 | `runs/ab/blind.py:38` | `runs.ab.blind:main` | `filesystem_write` | — |

C4 is a **third discovery blind spot**, independent of B1/B2:
`runs/council/room_server.py:546` constructs `RoomServer(("127.0.0.1", port), Handler)`
where `RoomServer` is declared at line 523 as `class RoomServer(ThreadingHTTPServer)`.
`_HIGH_IMPACT_CALLS` matches the literal name `ThreadingHTTPServer`, so **a
listen socket opened through a subclass is invisible**. The same evasion works
anywhere in the tree, including inside `daedalus/`.

### C-scripts / C-tests: harness, lower priority, but not zero

73 unregistered under `scripts/` (almost all `run_*_mutations.py` mutation
runners: `filesystem_write` + `process_spawn`, several also git-touching) and
17 under `tests/` (fault-injection fixtures and stub providers). These are
developer/CI harness rather than product surface. They belong in the inventory
as an explicitly-classified **out-of-scope** class, not as silence — otherwise
the next widening of `SCAN_PACKAGES` produces 90 new blockers overnight and the
gate gets turned off rather than closed.

---

## 5. What the scanner can never infer (measured, not asserted)

Fixture: a `main` that reads `os.environ["DEEPSEEK_API_KEY"]`, then runs
`git commit`, `git push`, and `claude -p <key>` via `subprocess.run`.

```
discovered: daedalus.probe:main -> ['process_spawn']
EVER inferable from a sink: filesystem_write, listen_socket, network_egress,
                            process_control, process_spawn
NEVER inferable:            repository_mutation, secrets, spend
```

**3 of the 8 `Effect` members can only ever enter the registry by hand.** The
consequence is precise and load-bearing:

- `entrypoint.effect_drift` — the blocker that fires when a registered target
  gains an undeclared effect — **can never fire for `spend`, `secrets`, or
  `repository_mutation`.** A row that starts spending money tomorrow stays
  green forever.
- This is why every "real effects" correction in §2 and §4 had to be made by
  reading source, and why the columns disagree with the tool.

### The concrete casualty: `provider.deepseek`

`daedalus/spine/effect_boundary.py:636-642` declares
`provider.deepseek` → `(Effect.FILESYSTEM_WRITE,)` only.

Ground truth: `daedalus/providers/deepseek.py:178` reads `DEEPSEEK_API_KEY`;
`run` at line 451 calls `chat_completion` at lines 550/556; `chat_completion`
is listed in `BILLABLE_SITES` as vendor `deepseek`, `how: urlopen(base_url)`.

So the busiest paid lane in the repository is registered with the lowest-risk
effect in the enum, with **zero guard contracts**, and no mechanism in the
checker can notice. Same for `provider.deepseek.rollback`.

### `Effect.SECRETS`: enforceable but unreachable

0 of 53 rows declare it. Meanwhile `daedalus/kernel/effects.py` has full support:

- line 268 — `Effect.SECRETS in values and not scope.secret_refs` → scope error;
- line 329/331 — `secret_refs` and the `SECRETS` effect must agree both ways;
- line 270 — `Effect.SPEND` requires `max_cost_microusd`.

Because `begin_effect` refuses undeclared effects, **no entrypoint can currently
obtain a secret-scoped lease**, and `daedalus/env.py:16-20` loads all three API
keys into `os.environ` process-wide where every provider reads them out of band.
The lease ledger's secrets machinery is correct and currently unreachable.

---

## 6. Registry rows that are wrong today

| row | problem | evidence |
| --- | --- | --- |
| `cli.claude_bridge` | **stale.** Declares `filesystem_write, process_spawn`. `daedalus/claude_bridge.py:246` is now a fail-closed stub that calls `parser.error(...)` and performs no effect. This is the single `entrypoint.not_rediscovered` review finding. | `daedalus/claude_bridge.py:246-265` |
| `provider.deepseek` | **under-declared.** Missing `spend`, `network_egress`, `secrets`. Zero guards. | §5 |
| `provider.deepseek.rollback` | under-declared / unguarded write to the checkout | `daedalus/providers/deepseek.py` |
| `mcp.runtime` | **`ABSENT`.** Not a gap in wiring — the surface does not exist. `daedalus/tools/vet.py` and `daedalus/tools/inventory.py` inspect MCP *configuration*; nothing brokers an MCP *runtime* effect. `.mcp.json` names serena, playwright, context7, shadcn — four external process/network surfaces with no Daedalus boundary at all. | registry row, `daedalus/tools/` |

---

## 7. Two inventories, one kernel

`daedalus/budget.py:1230` maintains `BILLABLE_SITES` — an independent,
hand-audited register of every spending site, with its own drift test
(`tests/test_budget.py:756-799`). It covers `runs/`. `ENTRYPOINTS` does not.
`ENTRYPOINTS` covers `tools/`. `BILLABLE_SITES` does not.

Two registries, two drift tests, disjoint scopes, no cross-check. Under
invariant 1 ("one canonical contract and event spine") that is itself a Gate-0
defect, and it is the reason the spend picture only assembles by hand.

`BILLABLE_SITES` also self-documents four sites it calls `static_visible: False`
— e.g. `daedalus/council/vendors.py::_CliAdapter._dispatch`, where the argv is
built in one file and spawned in `daedalus/spine/cancel.py::ManagedProcess`.
Those are additional entrypoints no AST scan of either file can attribute.

---

## 8. Ranked migration order

Ranking = risk that central routing removes. Weighting used, highest first:
`spend` and `secrets` (unrecoverable, external, unbounded) > `network_egress`
(exfiltration) > `repository_mutation` (destroys the authoritative artifact) >
`listen_socket` (remote reachability) > `process_spawn` (compute + inherited
effects) > `filesystem_write` (usually recoverable) > `process_control`.
A row with **no guard contract** is treated as 1.5× a guarded row with the same
effects, because nothing currently stands in front of it.

### Tier 0 — money and keys leave the machine with no registry row at all

| rank | item | why first |
| ---: | --- | --- |
| 1 | **B1** `tools/guarded_call.py:47` | the declared external-model door; `spend` + `secrets` + `network_egress`; invisible to the checker; and it is the file that *claims* to implement invariant 8 |
| 2 | **`provider.deepseek`** (registry row, §6) | busiest paid lane, declared `filesystem_write` only, zero guards, drift-undetectable |
| 3 | **C1** `runs/council/room.py:1184` | five billable vendors incl. `ssh`, `spend` + `secrets` + egress, outside the scan entirely |
| 4 | **A1** `tools/audit_swarm.py:282` | paid fan-out, ~750 billed calls historically |
| 5 | **A2** `tools/funnel.py:587` | paid fan-out, tiered, highest per-run volume |
| 6 | **C2** `runs/council/summarize.py:1011` | billable, found by the budget drift detector *after* a hand audit missed it |
| 7 | **C3** `runs/ab/run_arm.py:147` | billable + `repository_mutation` |

### Tier 1 — high-value registry rows already inventoried but not central

| rank | row | wiring | effects |
| ---: | --- | --- | --- |
| 8 | `web.mutations` | `inventory_only` | fs, spawn, egress, **spend** — remotely reachable |
| 9 | `file_bridge.process` | `inventory_only` | fs, spawn, egress, **spend** |
| 10 | `file_bridge.watch` | `inventory_only` | fs, spawn, egress, **spend** — `python -m` bypasses the guard install |
| 11 | `provider.claude` | `inventory_only` | fs, spawn, egress, **spend** |
| 12 | `provider.codex` | `inventory_only` | fs, spawn, egress, **spend** |
| 13 | `cli.daedalus` | `local_guards` | all five; the guard is one anchored `install_process_guard` call |
| 14 | `adapter.subprocess` | `inventory_only` | spawn, egress, fs — the shared spawn primitive |

### Tier 2 — repository mutation

| rank | item |
| ---: | --- |
| 15 | `worktree.reap` (`inventory_only`, **zero guards**, fs+spawn+repo) |
| 16 | **A3** `tools/iron_plan_guard.py (removed 2026-08-22):1999` — mutates the repo *and* is a guard |
| 17 | `python.promote_candidates`, `python.attempt`, `worktree.create/commit/cleanup` (`local_guards`, guarded, documented migration to lease) |
| 18 | **A5–A8** `gate_discrimination`, `bootstrap_receipt`, `operability_drill`, `gate_host_preflight` |
| 19 | **C6** `runs/ab/score.py:145` |

### Tier 3 — listen sockets and remote reachability

| rank | item |
| ---: | --- |
| 20 | **C4** `runs/council/room_server.py:540` — binds a socket the scanner cannot see, and drives the paid room |
| 21 | `web.server` (`local_guards`, loopback default), `cli.web_api` (`inventory_only`, zero guards) |
| 22 | **A4** `tools/gui_check.py:441` — spawns node, binds, egresses, kills |

### Tier 4 — spawn-only and write-only

| rank | item |
| ---: | --- |
| 23 | **B2** `tools/system_check.py:1095` — broad effects but developer-invoked; high value because it is *invisible*, not because it is dangerous |
| 24 | `cli.doctor` (egress+spawn, zero guards), `cli.bookkeeper`, `cli.dctx`, `cli.eval_*`, `cli.mapping_render`, `cli.arch_memory`, `cli.status` |
| 25 | A9–A15, C5, C7–C10, and the ~17 `filesystem_write`-only registry rows |

### Tier 5 — classify, do not migrate

| rank | item |
| ---: | --- |
| 26 | 73 `scripts/run_*_mutations.py` runners — declare as an explicit harness class |
| 27 | 17 `tests/` fixtures and stub providers — declare as test-only |
| 28 | `mcp.runtime` — `ABSENT` is honest; closing it means *building* the surface, not wiring one |

---

## 9. What this inventory does not cover

Stated so the next reader does not mistake completeness of method for
completeness of coverage:

- **Non-Python effects.** `.claude/hooks/*.py` are Python but outside every
  scanned package; JS/TS under `apps/web`, shell, and `.mcp.json`-launched
  servers are outside the method entirely.
- **Dynamic dispatch.** B2's `CHECKS` table is one instance found by hand.
  There is no reason to believe it is the only one; nothing here bounds that.
- **Subclass evasion.** C4 proves `_HIGH_IMPACT_CALLS` name-matching is
  defeated by a subclass. Every sink in that table has the same weakness.
- **Cross-module resolution.** B1 proves the fixed point stops at the module
  boundary. Any entrypoint whose only effect is a call into another module is
  invisible.
- **`spend`/`secrets`/`repository_mutation`** are hand-maintained (§5). Every
  claim about them in this document was made by reading source, and will rot
  the same way `BILLABLE_SITES` warns its own list rots.
- **This is not a security boundary.** Nothing here prevents a Python caller
  from importing past it, and this document does not claim otherwise.

---

## 10. Recommended next actions (not performed here)

1. Register B1 `tools/guarded_call.py` and correct `provider.deepseek` to
   declare `spend`, `secrets`, `network_egress`. These two changes are small,
   independent, and remove the largest undeclared risk in the tree.
2. Add `runs` to `SCAN_PACKAGES` and register C1–C10 — expect 9 new blockers,
   all of which already exist in reality.
3. Add an explicit `harness` classification before adding `scripts`/`tests`,
   so widening the scan does not produce 90 blockers and a disabled gate.
4. Make `entrypoint.effect_drift` capable of firing for `repository_mutation`
   (git argv is statically visible) and for `secrets` (`os.environ` reads of
   `daedalus.env.SECRET_KEYS` are statically visible). `spend` will remain
   hand-maintained; cross-check it against `BILLABLE_SITES` in one test
   instead of two.
5. Delete or correct the stale `cli.claude_bridge` row.
6. Resolve the two-inventory split (§7) — one registry, or one mechanical
   cross-check between them.

Evidence: `tests/test_effect_boundary.py` 20 passed before and after (this
change is documentation only); `check_conformance` output at
`registry_sha256 b8cab096…`; wide re-scan 165 discovered / 114 unregistered;
effect-inference fixture in §5.
