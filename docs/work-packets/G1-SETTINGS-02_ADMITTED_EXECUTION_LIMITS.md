# G1-SETTINGS-02 — The kernel reads what the owner admitted

- Packet ID: G1-SETTINGS-02
- Artifact role: primary
- Classification: ALIGNED
- Target gate: Gate 1
- Owner: repository owner
- Base revision: 77c9a672791a9a8c6dfc39e7ed32bc50902b9a99
- Dependencies: G1-SETTINGS-01, G1-CAPS-13, G1-BUDGET-12
- Invariants touched: 1 (one kernel), 7 (provenance), 8 and 4.1 (bounded
  effects and the owner-controlled execution limit policy)
- Promotion: forbidden

## Primary acceptance claim

A value the owner saves through the admitted path reaches the kernel, and a
value that reaches the kernel cannot widen past what was admitted. Budget and
execution-limit resolution takes the **strictest** of the admitted desktop
settings document and the process environment, per axis, and reports which of
the two decided.

Nothing here introduces a second store or a second validator, and nothing here
can widen authority: composing two inputs by taking the strictest can only ever
narrow, so reading the document never becomes an unconfirmed widening path.

## The problem

G1-SETTINGS-01 defect D1, measured 2026-09-10 and reproduced in this worktree
2026-09-11 on a temp runtime root holding an admitted document of
`period_ceiling_usd=200.0, max_calls=5000, caps=bounded`:

```
kernel anchor ROOT       : .../.claude/worktrees/settings-write
ROOT/config exists       : False

A. fresh process, no budget env  -> {'ceiling_usd': 5.0, 'max_calls': 40, 'caps_mode': 'bounded'}
   direction (a): the admitted document does not reach the kernel

B. fresh process, hostile ambient env -> {'ceiling_usd': 999999.0, 'max_calls': 1000000,
                                          'caps_mode': 'unbounded_execution',
                                          'period_usd_enforced': False}
   direction (b): an unadmitted variable reaches the kernel

C. fresh process, deliberately NARROWER env -> {'ceiling_usd': 1.0, 'max_calls': 2}
   the shell workflow that must keep working
```

Direction (b) is the security-relevant one: master plan section 4.1 requires an
explicit transient confirmation, verified by the effectful backend, for every
transition that widens authority. The desktop door honours it. The environment
was a door beside it with no lock at all.

## The two design questions, answered

### 1. When the document and the environment disagree, which wins?

**Neither. The narrower wins, per axis.** For the numeric ceilings that is the
minimum; for the eight limit axes it is "enforced when EITHER input enforces
it".

The argument is from the invariants, not from convenience:

- **Invariant 8 / section 4.1.** The confirmation exists so that a *GUI or API
  transition* cannot widen authority silently. A composition that can only
  narrow cannot widen authority at all, so making the kernel read the document
  needs no new confirmation surface and cannot become the defect it closes. A
  rule where "the document wins outright" would need one, because a hand-edited
  document would then raise a cap with nothing verifying anything — the same
  hole moved, not closed.
- **Invariant 4, evidence boundary.** An environment variable is a claim about
  what this process may spend. An admitted document is a claim that passed
  `prepare_settings` → `_authorize_settings` → `EffectLease` → receipt. Where
  the two conflict about *more* authority, the unverified claim loses. Where
  they conflict about *less*, neither claim needs verifying: a narrowing is
  accepted by the desktop path without a confirmation too (measured in D2 case
  C), so honouring a narrower variable is consistent, not an exception.
- **Same-user authority.** An operator who can export a variable can also edit
  the file. Neither is a boundary against the other, and this packet does not
  pretend otherwise. What it closes is the direction that *matters in practice*:
  a stale `DAEDALUS_BUDGET_USD` exported months ago in a shell profile, and a
  child process that inherits one, can no longer silently raise the ceiling
  above what the owner set.

**The cost, named rather than discovered.** A shell workflow that deliberately
*widens* through `DAEDALUS_BUDGET_USD` stops widening once an admitted document
exists that is narrower. Measured blast radius today: **zero**. There is no
`config/` directory in the checkout and none is tracked (`git ls-files config`
is empty), so no test, CI job or dev shell has an admitted document, and every
one of them keeps the exact behaviour it had. The cost lands the first time an
owner saves a setting — which is the point of the packet.

### 2. What happens to an environment value that never went through admission?

**It is honoured, and it is reported.** Refusing it would break every shell, CI
job and test that has ever exported one, and refusing a *narrowing* would be
absurd, since a narrowing needs no admission. Admitting it at startup with a
recorded provenance was rejected: that is exactly "the environment gains a
second validated writer", which this packet's scope forbids, and admitting a
widening without a confirmation is the defect.

So the answer is split by direction and made visible:

| situation | outcome | reported as |
| --- | --- | --- |
| narrower than the admitted document | honoured | `source: environment` |
| wider than the admitted document | **not honoured** | `refused_environment_value`, `refused_environment_axes` |
| no admitted document, narrower than the code default | honoured | `source: environment` |
| no admitted document, wider than the code default | honoured | `unadmitted_widening: true` |

`Ledger.limit_provenance()` is the machine-readable report and
`daedalus token-monitor` renders it, but only when it has something to say, so
a plain checkout in a plain shell prints the historical line unchanged.

## Contracts and behavior

```
Ledger(runtime_root=...)                 # Python argument, never an env var
load_admitted_settings(runtime_root)     -> AdmittedSettings | None
environment_limit_policy(environ)        -> ExecutionLimitPolicy | None
strictest_number(document, environment, default) -> (value, source, refused)
strictest_policy(document, environment)  -> (policy, source, refused_axes)
Ledger.limit_provenance()                -> JSON-serializable report
```

`source ∈ {admitted_document, environment, composed, default, issued_contract}`.

**Where the document lives, and why not through the environment.** The anchor is
`ROOT / "config" / "connections.json"`, where `ROOT` is the same
`Path(__file__).resolve().parents[3]` that already anchors
`DEFAULT_LEDGER_PATH` and the packaged desktop's `sidecar.bundled_root()`. A
test pins that the two anchors are equal, because direction (a) only closes if
both entrypoints resolve the same root. **No environment variable selects the
document**: a variable that named the file would, together with a crafted file,
be exactly the unconfirmed widening this packet closes. Only an explicit Python
argument moves it, and a test asserts that seven plausible variable names move
nothing.

**Absent is not default.** An unset variable states nothing and imposes no
bound; the code default applies only when *nothing* states anything. Collapsing
those two is what would let a bare `$5.00` default outrank an admitted
`unbounded_execution`. `_env_float_opt` / `_env_int_opt` /
`environment_limit_policy` all return `None` for absent, and a blank value is
absent for all of them — including `DAEDALUS_EXECUTION_LIMIT_POLICY`, which
previously read a present-but-blank value as an assertion of `bounded`.

**Strictest-wins is uniform across all eight axes, `max_calls` included.**
Settled 2026-09-11; do not re-litigate. The objection is that a lower call cap
is *cheaper* rather than *safer*, which is true about cost and beside the point
about authority. Every axis in section 4.1 exists to bound a resource, so a
tighter bound cannot grant anything, and strictest-wins is safe by construction
on all eight regardless of whether the tighter value is also the cheaper one.
The failure it can cause -- a mission dying halfway because the cap was lower
than it needed -- is a liveness cost, and section 4.1 already chose that trade
by making `bounded` the default for every unconfigured process. A per-axis
exception would mean the composition rule is no longer "can only narrow", and
the one axis that could widen would then owe a confirmation surface: the hole
this packet closes, reopened for convenience.

**A present, unusable document is a refusal, and the refusal is narrow.**
`AdmittedSettingsUnreadable` is a `BudgetUnavailable`, so every existing handler
already treats it as one. Falling back to the environment would hand back the
escape hatch: corrupt the file the owner admitted and the ambient variable
decides again. Falling back to the *code default* is available but no better --
a document that set `$1.00` would fall back to `$5.00`, a widening caused by
corrupting a file, which is the shape this packet exists to prevent.

Raising it out of every reader, however, would convert one bad file into total
unavailability -- and that would be a **new** failure mode introduced by this
packet, since before it a corrupt document broke only the desktop. So the
refusal is placed where a **spend or a work admission** consults the cap and
nowhere else:

| path | behaviour with an unreadable document |
| --- | --- |
| `ceiling_usd`, `max_calls`, `execution_limit_policy` | raise |
| `state`, `reserve`, `open_envelope` | raise (they resolve a cap) |
| `limit_provenance` | **never raises**: names the file, the parse error, and reports every axis as `None` |
| `token-monitor`, desktop status, the loop's spend probe | still run, report unavailable, name the file to repair |

The boundary was **not** built for this. It already existed and was measured
before anything was written: `shell.py::process_guard_boundary_decision`
already returns a refusing `GuardDecision` on any exception ("an unknown
ceiling is not an absent ceiling"), `loop.read_spend` already never raises and
signals `readable=False` which the caller treats as a reason to stop, and both
`token_monitor._budget_view` and `projection.budget_status` already catch
`BudgetError`. The only surface that raised where it should report was
`limit_provenance`, which this packet introduced; it is now the one thing that
can still name the broken file when everything else says "unavailable".

**Unreadable is not absent, on either path.** Admission refuses; reporting says
`None`. Neither falls through to the branch where the environment decides
alone, because that fallthrough is exactly how corrupting a file would buy back
an unadmitted widening. Verified with a corrupt document plus
`DAEDALUS_BUDGET_USD=999999`, `DAEDALUS_BUDGET_MAX_CALLS=1000000` and an
unbounded `DAEDALUS_EXECUTION_LIMIT_POLICY`: every reported effective value is
`None`, `unadmitted_widening` is `False`, and mutation M11 -- reporting the
environment's number instead -- turns the suite red.

Every refusal message carries `REPAIR_ADMITTED_SETTINGS`: which file, what
parse error, and that no new spend or work admission will be accepted until it
is repaired or removed while read-only inspection keeps working.

**An already issued contract is not rewritten** (section 4.1, verbatim). The
`ceiling_usd=`, `max_calls=`, `execution_limit_policy=` and
`period_ceiling_enabled=` constructor arguments decide alone and are reported as
`issued_contract`. `offload_lease.py:1019` and `:3295` pass a captured policy on
exactly this contract; an open `SpendEnvelope` keeps the cap it was issued.

**No boundary is relaxed.** The kill switch, egress admission, bounded write
roots, secret and tool policy, evaluator isolation, owner approval and the
prohibition on automatic merge or promotion are elsewhere and untouched. The
ledger, usage and evidence recording are unchanged: no code here writes, erases
or rewrites a ledger record.

## Findings folded in from the independent review of G1-SETTINGS-01

The read half came back from review with seven findings; two were in files this
packet already holds, and leaving them would have shipped a settings panel that
is wrong about the monetary ceiling while the packet next to it fixes the
ceiling. Disposition:

- **F1, taken.** `DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED` is a fifth env-only
  widening knob that the projection did not model. MEASURED 2026-09-11 before
  the fix: with `=0` inherited, the kernel returned `custom` with the period USD
  ceiling unenforced while the projection said `bounded | source: default` and
  no descriptor named the variable. Now the projection asks the ledger
  (`environment_limit_policy`) instead of decoding one variable, the row
  `budget.period_ceiling_enabled` exists, and the pinned widening set is five.
  On the kernel side the variable now composes strictest-wins like every other,
  so an admitted document overrides it; with no document it still decides alone,
  which is what the row now says.
- **F2, taken.** `_env_only` gained `coerce`, and five rows now report what
  their reader makes of the value instead of raw text. The trust row was fixed
  first: `DAEDALUS_TRUSTED_HOSTS=localhost` reported `'localhost'` as a declared
  egress-trust host while `declared_trusted_hosts()` deliberately drops every
  name. The parsing half was extracted as
  `sensitivity.parse_declared_trusted_hosts` and the projection calls it, so
  there is one implementation rather than a copy that drifts.
- **F3, taken.** The ledger branched on `ENV_EXECUTION_LIMIT_POLICY in
  os.environ` while the projection branched on non-blank. The ledger now treats
  blank as absent, matching every other variable it reads and the projection.
- **F4, reduced, not closed.** The write half adds no provenance record to the
  document, so `source: persisted` can in principle still describe a value the
  startup environment supplied. `document_present` removes the common case: when
  no document exists the row reports `environment` (the variable is still in the
  passed environ), and when a document does exist the value genuinely went
  through `save_settings`. The residue — a desktop that started with an ambient
  variable that is later absent from the environ handed to the projection — is
  **not closed** and is not disguised.
- **F5, claim narrowed, no new rows.** The read half's primary acceptance claim
  is narrowed by this packet's record to what the module is: *the desktop
  settings surface plus the budget and trust environment axes*, not "every
  setting the tree has". `DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS`,
  `DAEDALUS_WEB_TOKEN`, `policy.write_allow`, `.agentenv/tool-allowances.json`
  and the `DAEDALUS_KILLSWITCH` lead are **not** modelled here; growing the
  module to match the old claim is a different packet and a different axis.
- **F6/F7** (`inert_settings` asserting its own output; nine undescribed
  leaves) are read-half scope and are **not** taken.

## Acceptance matrix

Deterministic tests, all in `tests/test_admitted_execution_limits.py` unless
stated:

1. An admitted document reaches a process the desktop did not start (ceiling
   and call cap).
2. An admitted `unbounded_execution` reaches the kernel on all eight axes.
3. A missing document leaves every reader byte-identical to before.
4. An unadmitted variable cannot widen the ceiling or the call cap.
5. An unadmitted variable cannot disable a cap the document enforces, and the
   eight refused axes are reported.
6. The retired period boolean cannot disable an admitted ceiling; with nothing
   admitted it still decides alone.
7. A deliberately narrower variable still wins, and is not reported as refused.
8. A narrower variable still narrows an admitted `unbounded_execution`.
9. Mixed narrowing composes axis by axis and reports `composed`.
10. An unadmitted widening is honoured and reported as `unadmitted_widening`.
11. An unadmitted narrowing is not reported as a widening.
12. **Refusal.** A corrupt document refuses on all three readers instead of
    falling back to the environment.
13. **Refusal.** Ten malformed admitted payloads refuse (not an object, budget
    not an object, textual/zero/negative ceiling, negative/boolean/fractional
    call cap, bad caps mode, textual caps).
14. **Refusal.** A directory where the document belongs refuses.
15. **Refusal.** An unusable environment value still refuses when a document
    exists.
16. An unstated axis in a partial document imposes no bound.
16a. **Refusal, narrowed.** A corrupt document stops `state`, `reserve` and
    `open_envelope`.
16b. A corrupt document does not stop `limit_provenance`, which reports the
    path, the parse error and the repair sentence.
16c. **Unreadable is not absent.** A corrupt document plus a hostile ambient
    environment reports every axis as `None`, never the environment's number.
16d. The report shape is identical whether or not the resolution succeeded, and
    is JSON-serializable either way.
16e. An unusable *variable* is reported without blaming the document.
16f. The three read-only surfaces the tree actually has -- `token-monitor`
    (view and rendering), `loop.read_spend`, `projection.budget_status` --
    still run with a corrupt document and each names the file to repair.
17. **Section 4.1, end to end.** A widening `save_settings` raises naming
    `confirm_widening` and `period_ceiling_usd` and leaves **no** document
    behind; the confirmed save writes one; the kernel then reads `500.0`.
18. A narrowing save needs no confirmation and reaches the kernel.
19. An issued contract is not rewritten by a later document, on all three axes,
    and reports `issued_contract`.
20. An open `SpendEnvelope` keeps the cap it was issued across a document
    change.
21. **Refusal.** No environment variable relocates the admitted document
    (seven plausible names tried).
22. The anchor equals `sidecar.bundled_root()`, and the relative location
    equals the single writer's `config/connections.json`.
23. **Anti-drift.** 16 (document ceiling x environment ceiling) pairs: the
    projection's `effective` equals what `Ledger` resolves.
24. **Anti-drift.** 12 (document mode x environment mode, including the retired
    boolean) pairs: the projection's `caps.mode` and all eight axes equal what
    `Ledger` resolves.
25. `describe_settings` refuses a non-boolean `document_present`.
26. In `tests/test_settings_inventory.py`: a wider variable is refused and
    named; without a document the variable decides alone; an admitted bounded
    document refuses an unbounded variable; the retired boolean is modelled and
    reports fail-closed on garbage; nine env-only coercion cases; the widening
    set is pinned at five.

## Mutation evidence — each guard disabled, measured 2026-09-11

Each mutation applied to a throwaway copy of the tree; suites
`tests/test_admitted_execution_limits.py` and `tests/test_settings_inventory.py`
run with `-x`. Command: `docs/evidence/G1-SETTINGS-02/mutations.py`.

| mutation | file | result |
| --- | --- | --- |
| M1 the document is never read | ledger.py | 1 failed in 0.84s |
| M2 the environment wins outright again | ledger.py | 1 failed, 3 passed in 0.75s |
| M3 caps compose by AND instead of OR | ledger.py | 1 failed, 4 passed in 0.93s |
| M4 a corrupt document falls back to the environment | ledger.py | 1 failed, 11 passed in 0.74s |
| M5 an issued contract is re-resolved from the document | ledger.py | 1 failed, 35 passed in 1.63s |
| M6 an absent variable asserts bounded over the document | ledger.py | 1 failed, 1 passed in 0.71s |
| M7 the retired boolean is invisible to the projection again | settings_inventory.py | 1 failed, 65 passed in 1.77s |
| M8 env-only rows report raw text again | settings_inventory.py | 1 failed, 87 passed in 1.85s |
| M10 the reporting surface raises like an admission path | ledger.py | 1 failed, 13 passed in 0.75s |
| M11 the report treats an unreadable document as an absent one | ledger.py | 1 failed, 14 passed in 0.78s |
| M9 the trust parse is re-derived instead of reused | sensitivity.py | 1 failed, 97 passed in 1.96s |

Eleven of eleven turn red. No guard here is decorative.

## Cost, measured 2026-09-11

The document is read fresh on every resolution — no cache, so no staleness race
against a concurrent save. Measured on this host, 2000 iterations after 200
warm-up:

```
load_admitted_settings      58.57 us/call
ceiling_usd() with document 62.20 us/call
ceiling_usd() no document   20.40 us/call
```

`Ledger.state()` resolves once for the whole read rather than three times.
For comparison the surrounding operations already take a cross-process advisory
lock and read the ledger file, so this is not the dominant cost on any path.

## Scope

In scope:

- `daedalus/kernel/policy/ledger.py` — the resolution, the composition helpers,
  `limit_provenance`, `runtime_root`.
- `daedalus/interfaces/desktop/settings_inventory.py` — precedence brought back
  into agreement with the reader it describes, plus F1/F2/F3.
- `daedalus/sensitivity.py` — one pure extraction, `parse_declared_trusted_hosts`,
  with no behaviour change to `declared_trusted_hosts`.
- `daedalus/interfaces/cli/token_monitor.py` — the provenance report surface.
- `tests/test_admitted_execution_limits.py` (new),
  `tests/test_settings_inventory.py` (updated).

Forbidden and untouched:

- no second settings store, event store, HTTP server or configuration file;
- no second validator: `normalize_config` and `prepare_settings` stay the only
  ones; the composition reuses the ledger's own parsers and the projection
  imports the ledger's composition rather than reproducing it;
- no environment variable that names or relocates the admitted document;
- no relaxation of the kill switch, egress admission, write roots, secret or
  tool policy, evaluator isolation, owner approval or the no-auto-promotion
  rule;
- no change to `apps/web/dist/**`, `.gitignore`,
  `apps/web/src-tauri/Cargo.toml`, `tests/test_desktop_*.py` or `vault/**`,
  which other lanes hold;
- no edit to the master plan, its amendment chain or `AGENTS.md`.

## Migration and rollback

Migration is empty for every checkout that has no `config/connections.json` —
which is every checkout in this repository, measured. For a desktop install that
has one, the effective ceiling changes from the code default to the saved value
in processes the desktop did not start: that is the defect being fixed, and it
can only move the effective value **down** relative to what an ambient variable
would otherwise have granted, or **up** to a number the owner confirmed through
the section 4.1 path.

Rollback is reverting this commit. No persisted document gains a field, no
schema version changes and no environment variable is created, so a revert
cannot strand a document.

## Deliberately not closed

- **D1 for `DAEDALUS_BUDGET_LEDGER`.** Repointing the ledger still presents zero
  recorded spend to the same ceiling. It is ledger *location*, not budget or cap
  resolution, and the document has no field for it. Still a row in
  `unconfirmed_widening_settings()`.
- **D1 for `DAEDALUS_SUBSCRIPTION_VENDORS`.** A named vendor still bills $0
  against the USD ceiling. Same reason: not a cap axis, no document field.
- **The egress axes.** `DAEDALUS_TRUSTED_HOSTS` and
  `DAEDALUS_OLLAMA_REMOTE_OK` are a different boundary with a different owner.
  This packet made the trust row *honest* (F2); it did not give it an admission
  path.
- **D3 through D7** of G1-SETTINGS-01, all unchanged.
- **F4's residue** and **F5's missing rows**, as recorded above.
- **The CLI/sidecar anchor divergence.** `sidecar` chdirs to
  `bundled_root() == ROOT`; `interfaces/cli/entry.py::_web` uses `Path.cwd()`.
  They coincide for a dev running from the repo root and for the packaged app.
  Running `daedalus web` from an unrelated directory writes a document the
  kernel will not find. Named, not fixed: that entrypoint belongs to another
  lane.

## Evidence, expected failures and review

- Baseline: `docs/evidence/G1-SETTINGS-02/baseline_d1.py`, executed 2026-09-11.
- After: `docs/evidence/G1-SETTINGS-02/after_d1.py`, executed 2026-09-11.
- Mutations: `docs/evidence/G1-SETTINGS-02/mutations.py`, executed 2026-09-11.
- `tests/test_admitted_execution_limits.py` + `tests/test_settings_inventory.py`:
  `105 passed in 1.09s`.
- `tests/test_budget.py`, `test_budget_is_installed.py`,
  `test_canonical_execution_limit_policy.py`, `test_execution_limit_consumers.py`,
  `test_limit_policy.py`, `test_uncapped_budget_consumers.py`,
  `test_gui_check_budget.py`, `test_provider_execution_limit_policy.py`,
  `test_loop_cap_policy.py`, `test_loop_lease_policy.py`:
  `311 passed in 22.96s`.
- `tests/test_desktop_runtime.py`, `tests/interfaces/`,
  `test_sensitivity_default_policy_pins.py`, `test_sensitivity_write_intent.py`,
  `test_token_monitor_write_roots.py`, `test_dctx_policy_egress.py`:
  `1 failed, 557 passed, 7 skipped, 78 subtests passed in 61.25s`.

Expected failure, named rather than hidden:
`test_source_web_cli_wires_settings_get_put_and_closes_manager` is the
pre-existing Windows tmpdir case artifact (`pytest-of-Administra` versus
`pytest-of-administra`) that G1-SETTINGS-01 already reproduced on the pristine
tree. Not caused by this work and not fixed by it.

## Review questions

Two earlier questions were put to the coordinator and answered on 2026-09-11;
both answers are implemented and recorded above, not left open:

- *Is strictest-wins right for `max_calls`?* Yes, and uniformly. See
  "Strictest-wins is uniform across all eight axes".
- *Is `AdmittedSettingsUnreadable` a self-inflicted denial of service?* It was.
  The refusal is now narrowed to the spend and work-admission paths, and the
  reporting surface never raises. See "A present, unusable document is a
  refusal, and the refusal is narrow".

Open, for the independent reviewer:

- Does `document_present` belong on `describe_settings`, or should the
  projection take the resolved provenance from a `Ledger` instead and stop
  reproducing the composition at all?
- Is `token_monitor` the right first reporting surface, or should
  `GET /api/desktop/settings` carry `limit_provenance` now?
- `limit_provenance` catches `BudgetUnavailable` and reports it. Is there a
  `BudgetUnavailable` a *reporting* caller should still see raised -- a
  corrupt ledger file, say -- or is "report everything, decide nothing" the
  right contract for a surface that admits nothing?
