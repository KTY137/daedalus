# G1-SETTINGS-01 — One typed settings read/write contract

- Packet ID: G1-SETTINGS-01
- Artifact role: primary
- Classification: ALIGNED
- Target gate: Gate 1
- Owner: repository owner
- Base revision: a05f4b266471e09fbfcafd3302ee18e146c8d720
- Dependencies: G1-CAPS-13, G1-BUDGET-12
- Plan SHA-256: 04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639
- Invariants touched: 1 (one kernel), 7 (provenance), 8 and 4.1 (bounded
  effects and the owner-controlled execution limit policy)
- Promotion: forbidden

## Primary acceptance claim

One typed descriptor describes every setting the tree already has — its id,
group, type, default, effective value, **the source of that effective value**,
whether it widens authority, whether it needs confirmation, and whether it is
per-project — and one admission path owns every write. Nothing introduces a
second store: every value is projected from the code defaults, the existing
normalized desktop document, and the existing process environment.

## Problem

The owner reports that settings are scattered and confusing. Measured on
2026-09-10, the UI is not the cause; the contract underneath it is. There is
no single description of what a setting is, so four mechanisms each own part
of the answer and none agrees with the others about where the effective value
comes from.

| Store | Path | Written by | Validated by |
| --- | --- | --- | --- |
| `config/connections.json` | `PUT /api/desktop/settings` | `effects.save_settings` → `_authorize_settings` (`daedalus/interfaces/desktop/effects.py:1303`, `:863`) | `configuration.normalize_config` (`daedalus/interfaces/desktop/configuration.py:202`) |
| process environment | export before start | nothing in-repo | nothing |
| `projects/<name>.json` | `POST /api/projects`, `rewrite_project_team` (`daedalus/foundation/projects.py:214`, `:304`) | identity and `team` only | name and root only |
| `<repo>/.agentenv/agentenv.json` | `config.init_repo` (`daedalus/config.py`), then hand edits | never overwritten after scaffold | per-key resolvers only |

The desktop store is not the defect. `save_settings` is a single-writer path
with whitelist validation, a widening confirmation, an `EffectLease`, an
atomic publish and a receipt. The defect is that the desktop store is not what
the kernel reads.

## Measured surface

### The one admission path that behaves

`PUT /api/desktop/settings` (`daedalus/interfaces/desktop/http.py:158`) →
`manager.save_settings` (`daedalus/desktop_runtime.py:280`) →
`effects.save_settings` (`daedalus/interfaces/desktop/effects.py:1303`) →
`settings.prepare_settings` (`daedalus/interfaces/desktop/settings.py:106`) →
`_authorize_settings` (`daedalus/interfaces/desktop/effects.py:863`) → atomic
publish to `config/connections.json` (`:946`) → `environment_projection`
(`daedalus/interfaces/desktop/settings.py:265`).

`config/connections.json` has exactly one writer; a grep over `daedalus/`
finds no second one. `GET /api/desktop/settings` (`http.py:148`) is the only
reader exposed to a client.

The chat shell writes no settings at all. `daedalus/orchestration/ikarus/shell.py`
contains no call to `save_settings`, `rewrite_project_team`, or any write to
`.agentenv/agentenv.json` or `projects/*.json`. It reads project rows through
`core.team_config(project)` (`shell.py:838`) and reads `OLLAMA_MODEL` from the
environment (`shell.py:2239`, `:2254`, `:3842`).

### The reader that admission path does not control

`Ledger` resolves every monetary axis from the process environment, never from
the persisted document:

- `Ledger.ceiling_usd()` → `_env_float(ENV_CEILING, DEFAULT_CEILING_USD)`
  (`daedalus/kernel/policy/ledger.py:654-657`)
- `Ledger.max_calls()` → `_env_int(ENV_MAX_CALLS, DEFAULT_MAX_CALLS)`
  (`:717-722`)
- `Ledger.execution_limit_policy()` → `load_limit_policy_from_env()` whenever
  `DAEDALUS_EXECUTION_LIMIT_POLICY` is present (`:702-703`)
- `Ledger.period()` → `ENV_PERIOD` (`:725`); `Ledger.__init__` → `ENV_LEDGER`
  (`:641`)

`environment_projection` bridges the gap by writing the persisted values into
the desktop's **own** `os.environ` (`settings.py:288-293`). Nothing bridges it
for any other process.

## Named defects

### D1 — The persisted value does not reach the kernel; an ambient variable does

Executed 2026-09-10 in this worktree:

```
UI-persisted budget           : {'period_ceiling_usd': 200.0, 'max_calls': 5000}
fresh process ceiling_usd()   : 5.0   <- NOT 200.0
fresh process max_calls()     : 40    <- NOT 5000
with ambient env ceiling_usd(): 999999.0
with ambient env max_calls()  : 1000000
with ambient env caps mode    : unbounded_execution | period_usd enforced: False
```

Both directions are wrong. A CLI run, a test, or any process the desktop did
not start reads the code default and ignores what the owner saved. A stale or
hostile `DAEDALUS_BUDGET_USD` inherited from a parent shell beats the saved
document inside the desktop too, because `environment_projection` only assigns
and never verifies.

### D2 — Authority widening with no confirming path (plan section 4.1)

Section 4.1 requires an explicit transient confirmation, verified by the
effectful backend, for every transition that widens authority. The desktop
door honours this. Executed:

```
A. caps.mode=unbounded_execution -> refused: caps.confirm_widening=true is required for
   execution-limit widening affecting: period_usd, billable_calls, mission_spend,
   tokens, wall_time, attempts, concurrency, work_scope
B. budget.period_ceiling_usd=500 -> refused: ... affecting: period_ceiling_usd
C. budget.period_ceiling_usd=1   -> ACCEPTED without confirmation  (narrowing; correct)
```

The environment path is the gap. The same widening is reachable with no
confirmation, no validation parity and no receipt:

| Setting | Variable | What it widens | Reader |
| --- | --- | --- | --- |
| execution limit policy | `DAEDALUS_EXECUTION_LIMIT_POLICY` | all eight resource axes at once | `ledger.py:702` |
| period USD ceiling | `DAEDALUS_BUDGET_USD` | monetary ceiling | `ledger.py:657` |
| billable call ceiling | `DAEDALUS_BUDGET_MAX_CALLS` | call ceiling | `ledger.py:722` |
| ledger path | `DAEDALUS_BUDGET_LEDGER` | presents zero recorded spend to the same ceiling | `ledger.py:641` |
| flat-rate vendors | `DAEDALUS_SUBSCRIPTION_VENDORS` | named vendors bill `$0` against the USD ceiling | `pricing.py:71` |
| egress trust root | `DAEDALUS_TRUSTED_HOSTS` | moves an address inside the egress trust boundary, so repository content may leave this machine (`sensitivity.py:602`, `:751`) | `sensitivity.py:633` |
| Ollama remote consent | `DAEDALUS_OLLAMA_REMOTE_OK` | exact-host egress consent | `providers/ollama.py:390` |

`DAEDALUS_TRUSTED_HOSTS` is additionally read **once**, at
`desktop_runtime.py:238`, into `_base_trusted`, then re-projected verbatim on
every save. It cannot be changed at runtime and has no field.

### D3 — A live consent value is revoked as a side effect of saving settings

`environment_projection` unconditionally appends `DAEDALUS_OLLAMA_REMOTE_OK` to
its removals list (`settings.py:305`). That variable is not dead: it is the
exact-host egress consent read by `providers.ollama.remote_endpoint_consented`
(`providers/ollama.py:390`). Saving any unrelated desktop setting therefore
revokes Ollama remote consent for the process, and the response says nothing.
The direction is fail-closed, so this is a correctness and honesty defect, not
a hole. `DAEDALUS_OLLAMA_TUNNEL_FORWARD` genuinely has no reader anywhere in
`daedalus/` and is dead.

### D4 — Settings the API accepts, reports as saved, and discards

Executed:

```
requested bridge.auto_start = True -> stored False
requested ide.auto_start    = True -> stored False
requested ollama.auto_start = True -> stored False
```

`normalize_config` validates each flag as a boolean and then assigns `False`
(`configuration.py:237-239`, `:283-285`, `:313-315`). The PUT returns 200 with
the full snapshot, so a client cannot distinguish "saved" from "silently
refused". `lifecycle.bootstrap` still branches on all three
(`daedalus/interfaces/desktop/lifecycle.py:10`, `:12`, `:17`); those three
branches are unreachable.

### D5 — A validated, persisted section that nothing consumes

The whole `ide` block (`mode`, `endpoint`, `executable`, `docker_image`) is
validated against a loopback rule and a pinned-image regex
(`configuration.py:279-306`) and persisted. `start_ide` and `stop_ide` raise
`MANAGED_IDE_UNAVAILABLE` unconditionally (`effects.py:1429-1441`). The only
reader is the read-only status projection (`projection.py:41-42`). The same
holds for `ollama.mode = "remote_ssh"` and the entire `ollama.remote` block:
`_authorize_settings` refuses `remote_ssh` before anything happens
(`effects.py:883-884`).

`ide.executable` is accepted **without** confirmation while carrying spawn
authority (executed: `ide.executable=C:/Windows/System32/cmd.exe` → ACCEPTED).
Today that is inert because the feature is dead; if the managed IDE is ever
revived the persisted value is already there and no confirmation was ever
asked for. Latent, not live.

### D6 — Two "defaults" for the same setting

`DEFAULT_CONFIG["ide"]["mode"]` is `"native"`; `defaults()` rewrites it to
`"docker"` on Windows (`configuration.py:128-129`). A consumer that treats
`DEFAULT_CONFIG` as the default reports a fresh Windows install as having
"persisted" an editor choice the owner never made. Caught by
`test_untouched_document_reports_default_not_persisted`.

### D7 — Settings with no admission path at all

`projects/<name>.json` rows carry `policy.write_allow`, `policy.allow`,
`policy.deny`, `policy.default_deny`, `policy.high_risk_paths`,
`policy.external_write_lanes`, `write_wave_policy`, `test_command`,
`test_timeout_s`, `test_cwd`, `default_branch`, `claude_model`, `center` and
`ignore` (measured across the four committed rows). `register_project` writes
`{"name", "repo_root"}` only (`projects.py:190`); `rewrite_project_team`
writes `team` only (`projects.py:304`). Every other key is hand-edited JSON,
including `external_write_lanes`, which authorises a paid untrusted external
lane to APPLY changes.

## Contracts and behavior

One typed descriptor, one admission path.

```
SettingDescriptor(
    id, group, value_type, default, effective, source,
    widens_authority, requires_confirmation, per_project,
    write_path, environment_variable, note,
)
```

`source ∈ {default, persisted, environment, forced}` is the field the current
UI cannot express and the one the owner's complaint is really about: it says
which of the three inputs decided the value shown.

`write_path ∈ {desktop_settings, environment_only, project_file, none}` names
the admission path. The contract's single machine-checkable rule is:

> No setting may have `requires_confirmation=True` and
> `write_path=environment_only`.

That rule is violated today by exactly four rows, which is D2, and satisfying
it is the acceptance criterion for closing it.

**The one admission path.** All writes continue through `prepare_settings` →
`_authorize_settings`. Closing D1 and D2 means the kernel reads the admitted
document, or an environment value the admitted document verifiably produced —
not that the environment gains a second validated writer.

**Compatibility.** The read side adds a module and changes no existing
response. `GET /api/desktop/settings` keeps its current body and its
`settings_update_contract: "section_updates_v1"` marker until the write half
lands; the inventory is deliberately not wired into it here, because changing
that response is a contract change that belongs with the write half.

## Acceptance matrix

Read half, implemented in this packet:

1. One descriptor type describes every setting in the four stores; the
   vocabulary for `group`, `source` and `write_path` is closed and asserted.
2. `describe_settings(config, environ)` is a pure function of its two
   arguments: no global environment read, no file open, no mutation of either
   input, deterministic ordering, JSON-serializable output.
3. Reported `default` is the value `defaults()` produces on the running host,
   not the `DEFAULT_CONFIG` literal (D6).
4. Reported precedence reproduces the canonical readers exactly: a non-blank
   variable wins; a blank one is absent; a value the reader would refuse is
   reported as `None`, never as raw text.
5. **Refusal test.** `DAEDALUS_BUDGET_USD=free` and
   `DAEDALUS_BUDGET_MAX_CALLS=-3` report `effective is None`, matching
   `_env_float` and `_env_int` refusing to guess.
6. **Refusal test.** `DAEDALUS_EXECUTION_LIMIT_POLICY={invalid` reports
   `caps.mode` and all eight axes as `None` with a fail-closed note, matching
   `execution_limit_policy()` raising `BudgetUnavailable`.
7. **Refusal test.** A non-mapping `config` or `environ` raises `TypeError`
   rather than producing a partial inventory.
8. **Refusal test.** Descriptors are frozen; assignment raises.
9. **Refusal test.** `unconfirmed_widening_settings()` returns exactly the four
   known rows (`budget.ledger_path`, `budget.subscription_vendors`,
   `trust.declared_hosts`, `trust.ollama_remote_consent`). A fifth turns the
   suite red.
10. The `source=forced` claim for the three `auto_start` flags is verified
    against `normalize_config`, not asserted, so removing the forcing turns
    the suite red.
11. `inert_settings()` returns exactly the dead editor and remote surface.
12. Per-project rows report `effective=None` rather than inventing one global
    answer, and `project.write_wave_policy` reports `enum[never]`.
13. Boundaries stay described, never adjusted: the kill switch, egress
    admission, bounded write roots, secret and tool policy, evaluator
    isolation, owner approval and the no-auto-promotion rule appear in the
    inventory only as facts, and no code here can relax one.

Write half, not started in this packet:

14. The kernel resolves budget and caps from the admitted document, or from an
    environment value bound to an admitted document, so D1 disappears in both
    directions.
15. The four `environment_only` widening settings gain the section 4.1
    transient confirmation, or are removed.
16. `environment_projection` stops removing `DAEDALUS_OLLAMA_REMOTE_OK` as a
    side effect, or reports the revocation in the response (D3).
17. The three `auto_start` flags and the dead `ide` and `ollama.remote`
    surface are either revived or removed together with
    `lifecycle.bootstrap`'s unreachable branches (D4, D5).
18. `projects/*.json` policy keys gain an admission path, or an explicit
    "hand-edited, reviewed in version control" declaration (D7).

## Frozen scope

In scope for the read half: `daedalus/interfaces/desktop/settings_inventory.py`
and `tests/test_settings_inventory.py`, both new.

Forbidden:

- no second settings store, event store, HTTP server or configuration file;
- no second validator: `normalize_config` and `prepare_settings` stay the only
  ones, and the projection must never re-derive a rule they own;
- no write, environment mutation, file open or effect entrypoint in the
  read-side module;
- no relaxation of the kill switch, egress admission, write roots, secret or
  tool policy, or the widening confirmation;
- no change to `apps/web/dist/**`, `.gitignore`,
  `apps/web/src-tauri/Cargo.toml` or `tests/test_desktop_*.py`, which other
  lanes hold;
- no edit to the master plan, its amendment chain or `AGENTS.md`.

## Migration and rollback

Migration for the read half is empty by construction: the module is imported by
nothing in production, adds no field to any persisted document, and changes no
response body. Existing `config/connections.json` files, `projects/*.json` rows
and `.agentenv/agentenv.json` files are read as they are.

Rollback is deleting the two new files. No persisted state, no schema version
and no environment variable changes, so a revert cannot strand a document.

The write half's migration is the real one and is deliberately deferred: making
the kernel read the admitted document changes the effective ceiling for every
process that today silently gets `$5.00`, which must be an explicit,
owner-visible transition rather than a side effect of a read-side cleanup.

## Rollback and review questions

- Does any descriptor's `note` state something the code does not do? Each note
  is a claim about the tree and must be checkable at the cited line.
- Does the projection anywhere re-derive a validation rule that
  `normalize_config` owns, instead of reporting it?
- Is `unconfirmed_widening_settings` mistaken for a guard? It is a
  measurement; it refuses nothing and must never be relied on to.
- Are the four pinned env-only widening rows complete, or does a further grep
  of `os.environ` reads turn up a fifth?
- Should the inventory be exposed on `GET /api/desktop/settings` now, or does
  exposing an accurate list of unconfirmed widening knobs before they are
  closed help an attacker more than the owner?

## Evidence, expected failures and review

Read side implemented and green:

- `daedalus/interfaces/desktop/settings_inventory.py` — the projection, 30
  descriptors, imported by nothing in production.
- `tests/test_settings_inventory.py` — `28 passed in 1.08s`, including the
  refusal tests of items 5 to 9 and the pinned defect sets of items 9 to 11.

Baseline and adjacent suites:

- Base revision `a05f4b266471e09fbfcafd3302ee18e146c8d720` on `main`; branch
  `packet/settings-contract-20260910`.
- `tests/test_desktop_runtime.py`, `tests/test_kernel_contracts.py`,
  `tests/test_kernel_contracts_have_producers.py`: `1 failed, 132 passed`.

Expected failure, named rather than hidden:
`test_source_web_cli_wires_settings_get_put_and_closes_manager` is a
pre-existing Windows tmpdir case artifact (`pytest-of-Administra` versus
`pytest-of-administra`). Reproduced on the pristine tree with this packet's
files stashed: `1 failed in 0.57s`. Not caused by this work and not fixed by
it.

Not done, deliberately: nothing that changes how a value is written. Items 14
to 18 are the write half and each of them alters a write path.
