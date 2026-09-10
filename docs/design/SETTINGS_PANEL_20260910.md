# Settings panel — inventory and design

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: static measurement of `main` @ `a05f4b26`, 2026-09-10. Every row
carries `file:line`. Nothing was inferred from documentation. Nothing was
exercised at runtime — see §4.6.

Owner request (2026-09-10): *"wir müssen die settings besser machen das ist zu
unübersichtlich am besten die kriegen ein eigenes geordnetes panel"*.

This document is **design only**. It writes no backend contract, implements no
panel, and proposes the removal of no safety boundary. Plan §4.1 makes part of
this surface authority-widening; those rows are marked and kept visually
separate throughout.

---

## 0. The headline

**14 surfaces. 81 persisted settings, plus ~65 environment variables.**

Of the 81:

| | count |
|---|---|
| reachable from a product surface (cockpit UI or chat) | **37** |
| rendered in the UI but **inert or unreachable** | **11** |
| reachable only by hand-editing JSON | **33** |
| dead — declared, never read by anything | **4** |

Of the ~65 environment variables, **8** are curated into the UI's allowlist
(`daedalus/foundation/env.py:16,22`) and even those are display-only; no
product surface writes an environment variable.

The clutter is not primarily a layout problem. The Settings drawer renders 22
setting controls in one unbroken scroll and **11 of them can never change
anything** — they are disabled by construction and drawn anyway. Meanwhile the
settings that decide *what the assistant may touch* are not in the drawer at
all: they live behind `/computer` in chat, and they bind to the installation,
not to the project selected in the cockpit.

A panel that only re-arranges the 22 controls will look tidier and be exactly
as confusing. The deliverable is §3.

---

## 1. Inventory

### 1.1 The 14 surfaces a user must visit today

| # | Surface | How it is reached | Settings owned |
|---|---|---|---|
| 1 | Settings drawer "Einstellungen" | rail `apps/web/src/app/Cockpit.tsx:920`; keyboard `Cockpit.tsx:648` | 22 controls, 11 inert |
| 2 | Theme Studio drawer | rail `Cockpit.tsx:919` (`Palette`) | appearance catalogue |
| 3 | BrainPicker | conversation header `apps/web/src/features/conversation/Conversation.tsx:1608` | brain |
| 4 | EffortPicker | composer `Conversation.tsx:1620` | effort |
| 5 | Client slash commands | `apps/web/src/features/conversation/commands.ts:28` | `/modell`, `/aufwand`, `/neu`, `/abbrechen` |
| 6 | `/computer …` | `daedalus/orchestration/ikarus/computer_loop.py:1323` | the entire computer policy — 14 mutating verbs |
| 7 | Project dialog | `apps/web/src/features/projects/ProjectDialog.tsx:90` | 2 of 33 project keys |
| 8 | Genesis form | `apps/web/src/features/genesis/Genesis.tsx:132,146` | per-request, not persisted |
| 9 | `config/connections.json` | hand edit — `daedalus/desktop_runtime.py:38`, `:221`. **Absent in this checkout ⇒ defaults apply** | the only door to `ide.*` |
| 10 | `projects/<name>.json` | hand edit — loader `daedalus/foundation/projects.py:361` | 33 keys, 6 UI-reachable |
| 11 | `.env` | hand edit — `daedalus/foundation/env.py:14,44`. **Absent in this checkout** | 3 secrets + 5 public keys |
| 12 | `.agentenv/agentenv.json`, `tool-allowances.json`, `promotion_allowed_signers` | hand edit — `daedalus/config.py:33`, `daedalus/tools/vet.py:289`, `daedalus/kernel/promotion_trust_root.py:95` | repo-local policy, tool acknowledgements, trust root |
| 13 | `daedalus` CLI | `daedalus/interfaces/cli/entry.py:393,404,415,484` | agent registry, categories |
| 14 | Process environment | launcher / shell | ~65 vars |

### 1.2 Settings drawer — rendered today, in render order

Sections: Brain (`Settings.tsx:1203`) → Team (`:1294`) → Control Plane (`:1296`)
→ Rechenlage (`:1301`) → Bauteile (`:1306`) → Ausführungsgrenzen (`:1309`) →
Dienste & Verbindungen (`:1619`) → Erreichbarkeit (`:1923`).

**Widening** legend: `4.1` = plan §4.1 authority-widening, backend-gated today ·
`4.1*` = widens authority, **not** gated today · `–` = ordinary preference ·
`RO` = read-only.

| Setting | Set at | Controls | Widening | Scope | Persisted |
|---|---|---|---|---|---|
| Brain | `Settings.tsx:1211`, apply `:773` | which runtime answers | – | browser-global | `localStorage['daedalus-brain']` (`Cockpit.tsx:540`) |
| Max. Worker | `features/settings/Team.tsx:473` | wave size; read `daedalus/build.py:413`, default `3` | `4.1*` | per project | `team.max_workers` |
| Default-Lane | `Team.tsx:496` | routing default; read `daedalus/core.py:99,337,433`, default `local_only` | – | per project | `team.default_lane` |
| Aktive Agents | `Team.tsx:517` | which agents get work; read `daedalus/offload.py:404` | `4.1*` | per project | `team.active_agents` |
| Agentenprofil | `features/system/SystemCapabilities.tsx:264` | *view only* — chooses which profile the card shows | RO | — | — |
| Projekt-Autonomie | `SystemCapabilities.tsx:285`, apply `:322` | `manual`/`semi_auto`/`autonomous` per agent | **`4.1*`** | per project | `team.autonomy`, `daedalus/orchestration/control_plane.py:236,163,271` |
| Cap master mode | `Settings.tsx:1406` | `bounded`/`custom`/`unbounded_execution` | `4.1` (UI only — C14) | global | `caps.mode` |
| Cap axes ×8 — `period_usd`, `billable_calls`, `mission_spend`, `tokens`, `wall_time`, `attempts`, `concurrency`, `work_scope` | `Settings.tsx:1453` | defined `daedalus/kernel/policy/limits.py:81-88`; default `true` each | `4.1` | global | `caps.configured.*` |
| USD fallback | `Settings.tsx:1471` | default `$5.00` (`daedalus/kernel/policy/ledger.py:49`) | `4.1` on raise | global | `budget.period_ceiling_usd` |
| Call fallback | `Settings.tsx:1492` | default `40` (`ledger.py:51`) | `4.1` on raise | global | `budget.max_calls` |
| Widening confirmation | `Settings.tsx:1528` | the §4.1 transient confirmation | — | per request | **never persisted** — popped `daedalus/interfaces/desktop/settings.py:196-199`, verified `:251-257` |
| `bridge.auto_start` | `Settings.tsx:1662` | **nothing** — forced `False`, `daedalus/interfaces/desktop/configuration.py:239` | INERT | global | `bridge.auto_start` |
| `ollama.model` | `Settings.tsx:1709` | local model | – | global | → env `OLLAMA_MODEL` (`settings.py:295`) |
| `ollama.mode` | `Settings.tsx:1719` | local / remote_ssh (**remote `<option disabled>` at `:1723`**) | – | global | `ollama.mode` |
| `ollama.auto_start` | `Settings.tsx:1735` | **nothing** — forced `False`, `configuration.py:315` | INERT | global | `ollama.auto_start` |
| `ollama.local_host` | `Settings.tsx:1749` | endpoint, numeric loopback only | – | global | → env `OLLAMA_HOST` (`settings.py:304`) |
| Remote SSH ×9 — `host`, `user`, `port`, `local_port`, `remote_port`, `identity_file`, `host_key_fingerprint`, `start_method`, `trust_remote_host` | `Settings.tsx:1765-1856` | **unreachable** — `<fieldset disabled>` `:1758`, gated on a disabled option `:1723`, save `disabled={… \|\| remoteMode …}` `:1908` | `4.1*` (`trust_remote_host` = egress) | global | `ollama.remote.*` |
| Runtime "Testen" | `Settings.tsx:1952` | probes one runtime | RO | — | — |

### 1.3 Cockpit, outside the drawer

| Setting | Set at | Scope | Persisted |
|---|---|---|---|
| Brain (again) | `Conversation.tsx:1608` → `Cockpit.tsx:537` | browser-global | `localStorage['daedalus-brain']` |
| Effort `low/medium/high` | `features/conversation/EffortPicker.tsx:16`; `Conversation.tsx:1620,1145,134` | per project | `localStorage['daedalus-effort:<project>']` |
| Active project | `Cockpit.tsx:302-315` | browser | URL `?project=` + preference chain |
| Cockpit view | `Cockpit.tsx:549` | browser | `localStorage['daedalus-cockpit-view']` |
| Last focus per structure | `Cockpit.tsx:579` | per project | `localStorage['daedalus-last-focus:<structure>']` |
| Current theme | `shared/ui/theme/store.ts:255` | browser | `localStorage['daedalus-theme-id']` |
| Custom themes | `store.ts:238` | browser | `localStorage['daedalus-themes']` |
| Thread id | `Conversation.tsx:88` | per project | `localStorage['daedalus-thread:<project>']` |
| Project `repo_root`, `name` | `ProjectDialog.tsx:102,124` | new project | `projects/<n>.json` |
| Genesis `target`, `stack` | `Genesis.tsx:132,146` | per request | not persisted |

### 1.4 Chat-only — the computer policy

Dispatcher `daedalus/orchestration/ikarus/computer_loop.py:1323`. Authority
root is `Path(__file__).resolve().parents[3]` (`:1327`) — the **installation**,
not the selected project. `project` is a label only.

| Command | Sets | Widening | Persisted |
|---|---|---|---|
| `/computer setup` | policy + isolated workspace, no tool grants | – | `control_root/computer-policy.json` (`daedalus/runtimes/computer.py:563`) |
| `/computer configure <json>` | all 10 `ComputerPolicy` fields (`daedalus/kernel/policy/computer.py:131-141`) | **`4.1*`** | same, compare-and-replace on `expected_policy_sha256` |
| `/computer planner <provider> [model] [confirm-remote]` | `planner_provider`, `planner_model`, `allow_remote_context` | **`4.1`** — transient word `confirm-remote` (`:1479`) | same |
| `/computer enable\|disable daedalus [confirm-remote]` | `DAEDALUS_TOOLS` grant | **`4.1`** — transient (`:1397`) | same |
| `/computer enable\|disable ariadne [confirm-campaigns]` | `ARIADNE_TOOLS` grant | **`4.1`** — transient (`:1341`) | same |
| `/computer remember\|forget\|skill` | product memory, skill context | – | SpineLedger (`computer_context.py:207,216,222`) |
| `/computer queue\|every\|schedule\|cancel\|run-due\|run` | durable / scheduled missions | – | SpineLedger (`computer_schedule.py:213,224,261`) |

`max_steps` (16), `timeout_s` (300), `max_file_bytes` (1 MiB) at
`computer.py:139-141` are resource caps in every meaningful sense and are
**not** among the eight §4.1 axes.

### 1.5 File-only settings, no UI anywhere

**Desktop config (`config/connections.json`), not rendered:**

| Key | Declared | Read by | Note |
|---|---|---|---|
| `ide.endpoint` | `configuration.py:37`, validated `:286` | `daedalus/desktop_runtime.py:306` builds the IDE iframe URL | **live and invisible** |
| `ide.mode` | `configuration.py:36`, validated `:279` | — | `docker` on Windows (`:129`) |
| `ide.executable` | `configuration.py:38`, validated `:293` | — | |
| `ide.docker_image` | `configuration.py:39`, validated `:295` | — | |
| `ide.auto_start` | `configuration.py:36` | forced `False` at `:285` | INERT |
| `budget.period_ceiling_enabled` | `configuration.py:74` | Rev-9 migration `:262-270`, `settings.py:209-224`; CLI `interfaces/cli/token_monitor.py:266` | superseded — C1 |

**Project / repo-local policy (`projects/*.json`, `.agentenv/agentenv.json` —
same schema, `daedalus/config.py:1-8`):**

| Key | Read by | Default | Note |
|---|---|---|---|
| `policy.write_allow` | `daedalus/sensitivity.py:327`; intersected `daedalus/config.py:264` | `()` = unconfined | **THE write gate — not scaffolded by `init_repo`.** See C1 |
| `policy.allow` | `daedalus/sensitivity.py:304` | 5 patterns | **egress only; does NOT gate writes** |
| `policy.default_deny` | `sensitivity.py:319` | `True` | safety boundary |
| `policy.deny` | `config.py:146`, floor `config.py:270` | 5 substrings + generic floor | safety boundary |
| `policy.allow_exceptions` | `sensitivity.py:305` | `()` | |
| `policy.deny_content` | `sensitivity.py:306` | generic | regex, content-level egress |
| `policy.high_risk_paths` | `sensitivity.py:316`, unioned `config.py:270` | generic floor | |
| `policy.high_risk_terms` | `config.py:150` | 7 terms | |
| `policy.mid_risk_terms` | `sensitivity.py:308` | generic | **present in zero JSON file, not scaffolded** — C7 |
| `policy.external_write_lanes` | `config.py:117`, known lanes `:91` | `()` | repo-local only; registry deliberately ignored (`config.py:124`) |
| `write_wave_policy` | `config.py:60` | `"never"` — **the only accepted value** (`config.py:45`) | C13 |
| `test_command`, `test_cwd`, `test_timeout_s` | `daedalus/offload.py:729,732,733` | `None`, `"."`, `120` | |
| `center`, `ignore` | `interfaces/cli/entry.py:331,332`; `interfaces/http/web_api.py:155,176` | `[]` | |
| `claude_model` | `daedalus/kairos/orchestrate.py:80` | `"sonnet"` | only reader |
| `team.squads` | `daedalus/core.py:101,320` | `DEFAULT_SQUADS` | not in the Team panel |
| `team.model_assignments` | `daedalus/core.py:102,330`; `offload.py:604` | `{}` | not in any UI |
| `team.semi_auto` | `daedalus/core.py:103,340` | literal at `core.py:103` | not in any UI |
| `work_queue.{enabled,path}` | `daedalus/spine/picker.py:550` | `false`, `.agentenv/work-queue.json` | file absent ⇒ source reports `disabled` (`picker.py:552-556`) |
| `picker_sources.{map,inventory,eval_baseline}` | `picker.py:522`; `spine/bootstrap.py:166` | `"enabled"` each | |
| `spine.ledger_path` | `picker.py:504` | `runs/spine/spine.sqlite3` | second resolver — C16 |
| `default_branch` | **nothing** | declared in all 4 registry rows | **DEAD** — C6 |
| `name` (in `.agentenv/agentenv.json`) | **nothing** on that path (`config.py:286-293`) | — | **DEAD** — C6 |

**Tool acknowledgements (`.agentenv/tool-allowances.json`):** shape
`{"allow": {<subject>: {<rule_id>: <reason>}}}`, read at `daedalus/tools/vet.py:292,317`,
applied `:535`. Downgrades `BLOCK`→`REVIEW` only; no wildcards. `_doc` is never
read (`vet.py:317`). The pinned `{"reason","body_sha256"}` shape is supported
(`vet.py:331-340`) but unused in this checkout.

### 1.6 Environment (~65 variables)

Curated for the UI: secrets `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` (`daedalus/foundation/env.py:16`); public `OLLAMA_HOST`,
`OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
(`env.py:22`). Secrets are reported presence-only (`env.py:85`).

Kernel/policy-owned, load-bearing: `DAEDALUS_EXECUTION_LIMIT_POLICY`
(`daedalus/kernel/policy/limits.py:46`), `DAEDALUS_BUDGET_USD` /
`_MAX_CALLS` / `_PERIOD` / `_LEDGER` / `_ON_UNKNOWN`
(`ledger.py:34-37`, `policy/pricing.py:15-17`), `DAEDALUS_KILLSWITCH`
(`daedalus/spine/killswitch.py:206,483`), `DAEDALUS_TRUSTED_HOSTS`
(`daedalus/sensitivity.py:528`), `DAEDALUS_OLLAMA_REMOTE_OK`
(`daedalus/providers/ollama.py:53`), `DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS` +
`DAEDALUS_WEB_TOKEN` (`daedalus/interfaces/http/server.py:14,15`).

The remaining ~50 are developer/perf tuning (index layers, embed timeouts,
fan-out concurrency, cache dirs, RTX host, OCI runtime, Ikarus client
timeouts). **They do not belong in a settings panel** and are listed here only
so the count is honest.

Rust side: three env reads total in `apps/web/src-tauri/src/`; two are
test-harness-only (`instance.rs:138-139`, set by the spawner at `:162-163`)
and one is a compile-time `env!()` (`lib.rs:30`). **No user-facing Rust knob.**

### 1.7 Never a preference — read-only, by plan §4.1

These must never acquire a toggle. Listed so the panel can *show* them and stop
the user hunting for a switch that must not exist.

| Boundary | Enforced at |
|---|---|
| Kill switch | `daedalus/spine/killswitch.py:206,475,843,1090`; generation check `daedalus/kernel/authorization.py:68,118-184`. **No HTTP route, no UI toggle** — correct. |
| Egress / lane admission | `daedalus/sensitivity.py:630-667` (typos narrow, never widen); `daedalus/interfaces/desktop/effects.py:296` |
| Bounded write roots | `effects.py:912`; `daedalus/config.py:261-267` (`intersect_write_allow` narrows only); `daedalus/core.py:565-690` |
| Non-loopback bind refusal | `daedalus/interfaces/http/server.py:70,94` — refuses unless both the flag and a token are set |
| Promotion trust root | `daedalus/kernel/promotion_trust_root.py:95` (`.agentenv/promotion_allowed_signers`) |
| Effect leases, evidence gates, provenance | `daedalus/spine/effect_boundary.py` |
| Evaluator isolation; no auto-merge/promotion | plan invariants 3 and 5; `write_wave_policy` pinned to `"never"` (`config.py:45`) |
| Sandbox CPU/RAM/PID/FS quotas; provider quotas and context windows | external — already disclaimed honestly at `Settings.tsx:1588-1594` |

---

## 2. The proposed panel

### 2.1 Sketch

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Einstellungen                          Projekt: [ daedalus        ▾ ] ✕ │
├────────────────────────┬─────────────────────────────────────────────────┤
│                        │                                                 │
│  ● Wer arbeitet        │   WER ARBEITET                                  │
│                        │   ─────────────────────────────────────────     │
│    Dieses Projekt      │   Brain            ( ) Automatisch               │
│                        │                    (•) claude_code_cli          │
│    Team                │                    ( ) ollama_http  · 2 min alt  │
│                        │                    ( ) codex_cli    · offline    │
│    Verbindungen        │                                                 │
│                        │   Aufwand          [gering] (mittel) [hoch]      │
│  ─────────────────     │                    gilt für dieses Projekt       │
│                        │                                                 │
│  ⚠ Grenzen             │   Lokales Modell   [ qwen2.5-coder:7b        ]   │
│                        │                                                 │
│  ⚠ Vertrauen           │   Planer (Computer)[ ollama_http            ▾]   │
│    & Reichweite        │                    Modell [                  ]   │
│                        │                    gilt für DIESE INSTALLATION   │
│  ─────────────────     │                                                 │
│                        │   ┌───────────────────────────────────────────┐ │
│    Aussehen            │   │ Änderungen gelten erst nach Übernehmen.   │ │
│                        │   │            [ Verwerfen ] [ Übernehmen ]   │ │
│  ─────────────────     │   └───────────────────────────────────────────┘ │
│                        │                                                 │
│  🔒 Immer erzwungen    │                                                 │
│                        │                                                 │
└────────────────────────┴─────────────────────────────────────────────────┘

The two ⚠ groups render with a distinct treatment throughout — warning rail
colour, bordered container, and the only red primary button in the product:

┌──────────────────────────────────────────────────────────────────────────┐
│  ⚠ GRENZEN — wie viel darf laufen                                        │
│  ────────────────────────────────────────────────────────────────────    │
│  Master-Modus   (•) Begrenzt (Standard)                                  │
│                 ( ) Individuell                                          │
│                 ( ) Unbegrenzte Ausführung                               │
│                                                                          │
│  Kosten & Provider-Nutzung                              effektiv         │
│    Globale Periodenkosten (USD)      [on ]  $ 5.00       aktiv           │
│    Bezahlte Modellaufrufe            [on ]    40         aktiv           │
│    Mission-/Lease-/Envelope-Beträge  [on ]                aktiv          │
│    Input-/Kontext-/Output-Tokens     [on ]                aktiv          │
│  Laufzeit & Wiederholungen                                               │
│    Ausführungs-/Provider-/Gate-Zeit  [on ]                aktiv          │
│    Retries / Attempts / Schritte     [on ]                aktiv          │
│  Parallelität & Arbeitsumfang                                            │
│    Read-only Worker & Fan-out        [on ]                aktiv          │
│      └ Team „Max. Worker" = 6 zählt gegen diese Achse                    │
│    Queue-Batch / Rewrite-Umfang      [on ]                aktiv          │
│  Computer-Missionen (diese Installation)                                 │
│    Max. Schritte je Mission                   16                         │
│    Zeitlimit je Mission                      300 s                       │
│    Max. Dateigröße                          1 MiB                        │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║ ⚠ Diese Änderung erweitert die Ausführungsautorität              ║    │
│  ║   Betroffen: Globale Periodenkosten (USD), Bezahlte Aufrufe      ║    │
│  ║   [ ] Ich bestätige genau diese Achsen und das Risiko.           ║    │
│  ║       Gilt nur für dieses Speichern; wird nicht gespeichert.     ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
│                                    [ Verwerfen ] [ Grenzen speichern ]   │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  ⚠ VERTRAUEN & REICHWEITE — was angefasst werden darf                    │
│  ────────────────────────────────────────────────────────────────────    │
│  Projekt-Autonomie   docs-dev      ( manual ▾ )                          │
│                      qa-critic     ( manual ▾ )                          │
│                                                                          │
│  Schreibwurzeln      docs/  tests/  README.md            [ Bearbeiten ]  │
│    (policy.write_allow — DAS ist die Schreiberlaubnis)                   │
│  Egress-Allowlist    docs/  /tests/  test_  .md  readme  [ Bearbeiten ]  │
│    (policy.allow — welche BYTES nach außen dürfen; kein Schreibrecht)    │
│  Egress-Denylist     secret  credential  .env  id_rsa  .pem   (+ Floor)  │
│                                                                          │
│  Computer-Werkzeuge  [ ] daedalus  (liest Projektdaten)                  │
│                      [ ] ariadne   (startet Kampagnen)                   │
│  Externer Kontext    [ ] allow_remote_context                            │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║ ⚠ Diese Änderung erweitert die Reichweite                        ║    │
│  ║   Betroffen: Computer-Werkzeug „ariadne", Projekt-Autonomie      ║    │
│  ║   [ ] Ich bestätige genau diese Punkte.  Nicht gespeichert.      ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  🔒 IMMER ERZWUNGEN — kein Schalter, absichtlich                         │
│  ────────────────────────────────────────────────────────────────────    │
│   Kill-Switch              scharf       control_root/killswitch          │
│   Egress default-deny      an           DAEDALUS_TRUSTED_HOSTS: (leer)   │
│   Nicht-Loopback-Bind      verweigert   Flag + Token fehlen              │
│   Promotion-Trust-Root     1 Signer     .agentenv/promotion_allowed_…    │
│   Evaluator-Isolation      erzwungen                                     │
│   Auto-Merge / Promotion   verboten — Owner-Freigabe je Kandidat         │
│   Sandbox-/Provider-Grenzen extern; Daedalus kann sie nicht abschalten   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 The eight groups, and why

Ordering is **frequency of legitimate change, then blast radius**: weekly
things first, authority-widening things last and visually different.

| # | Group | Contains | Why this grouping |
|---|---|---|---|
| 1 | **Wer arbeitet** | brain, effort, `ollama.model`, computer `planner_provider`/`planner_model` | All four answer "which model does the thinking". Today they sit in four surfaces: drawer, composer, `/computer planner`, drawer again. This group alone justifies the panel. |
| 2 | **Dieses Projekt** | `repo_root`, `name`, `test_command`, `test_cwd`, `test_timeout_s`, `center`, `ignore`, `claude_model` | One repository's facts, none of them authority-bearing. 2 of 8 are UI-reachable today. `default_branch` is deliberately **excluded** — nothing reads it (C6). |
| 3 | **Team** | `max_workers`, `default_lane`, `active_agents`, `squads`, `model_assignments`, `semi_auto`, agent capability list (read-only) | Already coherent in `Team.tsx`; needs `squads`, `model_assignments`, `semi_auto` folded in from JSON. `max_workers` gets a cross-link to the `concurrency` axis (C10). |
| 4 | **Verbindungen** | `ollama.mode`/`local_host`, `ide.*` (5), bridge status, runtime reachability, `.env` key presence | "Where does it run and can it be reached" — hosts, ports, binaries, endpoints. Reveals `ide.*`, which is live but invisible. Secrets stay presence-only (`env.py:85`). |
| 5 | **⚠ Grenzen** | 8 cap axes, master mode, USD + call fallbacks, computer `max_steps`/`timeout_s`/`max_file_bytes` | *How much* may run. The §4.1 resource caps and nothing else. |
| 6 | **⚠ Vertrauen & Reichweite** | project autonomy, `write_allow`, `policy.allow`/`deny`/`default_deny`/`high_risk_*`, computer tool grants, `allow_remote_context`, `trust_remote_host`, `external_write_lanes` | *What may be touched and what may leave.* A different question from group 5. Separating them is the point: today autonomy sits beside a read-only capability list, so `manual → autonomous` looks like changing a dropdown. Labels here must name write-vs-egress explicitly (C1). |
| 7 | **Aussehen** | theme, custom themes, view, Theme Studio options | Zero risk. Last and visually light, so nothing in 5–6 reads as equally weighty. Absorbs the second drawer (C15). |
| 8 | **🔒 Immer erzwungen** | kill switch, egress admission, write roots, bind refusal, trust root, evaluator isolation, promotion, sandbox/provider limits | Read-only status rows with live values. The current prose card (`Settings.tsx:1576-1595`) becomes a group. **Adding a control here is a release-blocking defect** under `AGENTS.md` review rules. |

Deliberately **not** in the panel: the ~50 developer-tuning environment
variables (§1.6), `write_wave_policy` (a constant, C13), and the internal
handshake variables (`DAEDALUS_BUDGET_ENVELOPE`, `DAEDALUS_DESKTOP_STARTUP_NONCE`,
`DAEDALUS_TRACE_ID`), which are minted by the runtime and never by a human.

### 2.3 Which actions are authority-widening

These require the §4.1 explicit transient confirmation naming the affected
axes, verified by the effectful backend, never persisted.

**Gated today** (backend, `daedalus/interfaces/desktop/settings.py:242-257`):

1. Disabling any of the 8 cap axes (effective `true → false`).
2. Raising `budget.period_ceiling_usd`.
3. Raising `budget.max_calls`.
4. `unbounded_execution` (reaches the backend as 8 disabled axes).

**Widening, with a transient confirmation that exists only in chat.** The panel
must carry the word over, not drop it because a checkbox is easier to draw:

5. `/computer planner … confirm-remote` → `allow_remote_context` (`computer_loop.py:1479`).
6. `/computer enable daedalus confirm-remote` → tool grant (`:1397`).
7. `/computer enable ariadne confirm-campaigns` → campaign tools (`:1341`).

**Widening, gated nowhere today.** The panel must add a confirmation; it must
not present these as ordinary preferences:

8. Project autonomy `manual`/`semi_auto` → `autonomous` (`SystemCapabilities.tsx:285`).
9. `trust_remote_host` → on (`Settings.tsx:1853`). Validated at
   `configuration.py:360` but **absent** from the widening computation at
   `settings.py:242-250`.
10. Raising `team.max_workers` (`Team.tsx:473`) — concurrency, while the global
    `concurrency` axis *is* gated.
11. Adding to `policy.write_allow`, adding to `policy.allow` (egress), or
    removing from `policy.deny`.
12. Adding a lane to `policy.external_write_lanes` (`config.py:117`) — this
    lets a named untrusted external lane *apply* a write rather than advise.

**Not widening, correctly ungated:** re-enabling an axis, lowering a fallback,
narrowing any allowlist, and everything in groups 1–4 and 7.

Two measured gaps in the existing gate, recorded so the panel does not inherit
them. The backend contract is another agent's packet; this is design input:

- **Gap A** — `bounded → custom` with all axes still `true` produces no
  `disabled_axes`, so the backend requires no confirmation (`settings.py:242-245`).
  The UI does demand one (`Settings.tsx:567-569`). Any non-UI client bypasses it.
- **Gap B** — the wire contract is a bare `caps.confirm_widening: true`. §4.1
  asks the confirmation to *name the affected axes*; the backend derives the
  axis list only to build the error string (`settings.py:253-257`) and never
  binds the confirmation to a specific axis set. A client that always sends
  `true` blanket-authorizes every widening in that request.

---

## 3. What is genuinely confusing

This is the real deliverable. Fixing these is what makes the panel simpler; the
layout in §2 only makes the fix visible.

### The three worst

**C1 — `allow` is not the write permission. The key that is, is never
scaffolded.** `policy.allow` is the **egress** axis (`daedalus/sensitivity.py:304`).
`policy.write_allow` is the write gate (`sensitivity.py:327`, intersected at
`daedalus/config.py:264`). The repository's own comment in
`.agentenv/agentenv.json` records the measured failure verbatim: *"with
allow-only, 8 of 12 paths this policy claims to deny were writable, including
`daedalus/config.py`, which loads this file."* And `STARTER` — the block
`init_repo` scaffolds (`config.py:144-176`) — contains `allow`, `deny`,
`allow_exceptions`, `high_risk_paths`, `high_risk_terms`, `deny_content` and
`external_write_lanes`, but **not `write_allow`, not `default_deny`, not
`mid_risk_terms`**. `write_allow` appears in that block only inside a comment
string (`config.py:161`). So every repository initialized by `daedalus init`
starts with `write_allow = ()` — unconfined — while displaying a populated
`allow` list that reads like permission. Two keys, near-identical names,
opposite meanings, one of them invisible. Any panel that renders a path list labelled "allow" next
to a project will be read as "these are the paths it may write". This is the
first thing the panel must get right and the one place a wrong label is a
safety defect rather than an annoyance.

**C2 — The brain is settable from three places with three different commit
rules, all racing on one unlocked key.** The drawer builds a draft, verifies
reachability, blocks apply while verification is pending or failed, and
requires "Brain übernehmen" (`Settings.tsx:1211,1279-1287`, apply `:773`). The
BrainPicker in the conversation header applies instantly with no reachability
guard (`Conversation.tsx:1608` → `Cockpit.tsx:537`). `/modell` opens that same
picker (`commands.ts:35`, `Conversation.tsx:1178`). All three write
`localStorage['daedalus-brain']` (`Cockpit.tsx:540`); neither surface re-reads
the other while open, so last write wins. The drawer's entire verification
apparatus is defeated by one click in the header — on the most-used setting in
the product.

**C3 — Permission lives in chat and is installation-global; spending lives in
the UI and is confirmation-gated. Neither knows about the other.** The complete
`ComputerPolicy` — workspace, tool grants, `origins`, `applications`,
`planner_provider`, `planner_model`, `allow_remote_context`, `max_steps`,
`timeout_s`, `max_file_bytes` (`daedalus/kernel/policy/computer.py:131-141`) —
is reachable **only** through `/computer configure|planner|enable`. Grepping
`apps/web/src` for `planner`, `computer-policy`, `daedalus_tools` or
`ariadne_tools` returns nothing: the cockpit cannot display, let alone edit,
what the assistant is allowed to do. `/computer` binds its authority root to
the installation directory (`computer_loop.py:1327`) and treats the selected
`project` as a label, so a user who switched projects in the cockpit is
silently editing one global policy. And `max_steps`/`timeout_s` duplicate the
`attempts`/`wall_time` axes with no relation between them: turning off
`wall_time` in the drawer does not touch `timeout_s`, and nothing says so.

### The rest

**C4 — One money cap, two contradictory spellings, and the code knows it.**
`budget.period_ceiling_enabled` (Rev 9, `configuration.py:74`) and
`caps.configured.period_usd` (Rev 10, `limits.py:81`) both mean "is the USD
ceiling enforced", and both are accepted on the same `PUT`. The backend carries
a migration for the collision (`configuration.py:262-270`, `settings.py:209-224`)
and a second for the *confirmation*, which exists twice as
`budget.confirm_widening` and `caps.confirm_widening` and must be actively
rejected when they disagree (`settings.py:226-231`). The projection re-exports
the legacy name (`projection.py:68,116`), the CLI reads it
(`interfaces/cli/token_monitor.py:266`), the env writer deletes it
(`settings.py:288`). Four layers, two vocabularies, one setting.

**C5 — Twenty controls in the drawer that cannot do anything.**
`bridge.auto_start` (`Settings.tsx:1662`) and `ollama.auto_start` (`:1735`) are
`disabled` and forcibly reset to `False` on every write (`configuration.py:239`,
`:315`); `ide.auto_start` is the same (`:285`) and is not even rendered. The
nine remote-SSH fields (`Settings.tsx:1765-1856`) sit behind three independent
locks: `<fieldset disabled>` (`:1758`), a `<option value="remote_ssh" disabled>`
(`:1723`), and a save button `disabled={… || remoteMode …}` (`:1908`). Eleven
rendered controls, zero reachable states. Every one of them is *honestly
labelled* — which is correct behaviour and permanent clutter.

**C6 — Four dead keys.** `default_branch` is declared in all four registry rows
(`project_tct.json` sets it to `root-cleanup`) and in
`daedalus/resources/templates/project.example.json:5`; a repo-wide grep finds
exactly one non-build hit, `daedalus/interfaces/desktop/sidecar.py:60`, which
is a dict *literal* writing `"default_branch": "main"` into an output payload —
not a read. `name` in `.agentenv/agentenv.json` is never read on that path
(`config.py:286-293`). `_doc` in `tool-allowances.json` is never read
(`vet.py:317`). `updateCategory` (`apps/web/src/shared/api/index.ts:590`) has
no caller anywhere in `apps/web/src` — the endpoint is live
(`daedalus/interfaces/http/effects.py:406`) and the CLI is the only door
(`interfaces/cli/entry.py:484`).

**C7 — Live knobs that appear in no file and no scaffold.**
`policy.mid_risk_terms` is read at `sensitivity.py:308`, is present in **zero**
JSON file in the tree, and is not in `STARTER`. `policy.write_allow` is the
same class and is the write gate (see C1). Both are discoverable only by
reading `sensitivity.py`.

**C8 — Five live settings with no UI at all.** `ide.mode`, `ide.endpoint`,
`ide.executable`, `ide.docker_image`, `ide.auto_start` are validated
(`configuration.py:279-297`), persisted, and `ide.endpoint` is *read* — it
builds the IDE workspace URL at `desktop_runtime.py:306`. A user cannot point
the IDE anywhere else without hand-editing JSON. The client's `DesktopConfig`
type does not declare the section at all (`Settings.tsx:140-152`), relying on
its `[key: string]: unknown` index signature to round-trip it.

**C9 — The money caps live in a file called `connections.json`.**
`CONFIG_REL = Path("config/connections.json")` (`desktop_runtime.py:38`) holds
`bridge`, `budget`, `caps`, `ide` and `ollama`. Nothing about the name suggests
the $5.00 ceiling is in there. The file does not exist in this checkout, so
every value in §1.2 is currently a default.

**C10 — `OLLAMA_HOST`/`OLLAMA_MODEL` mean different things in different
processes.** They are documented `.env` keys (`foundation/env.py:23,24`), and
the desktop process *overwrites* them from `config/connections.json`
(`settings.py:295,304`). In the desktop the UI wins; in a plain CLI run `.env`
wins. `/api/env` then reports the overwritten value under the heading "public
env keys" (`env.py:85`), which reads as though it came from `.env`.

**C11 — The same Ollama default is declared three times independently.**
`"qwen2.5-coder:7b"` at `configuration.py:43`, `foundation/env.py:71`, and
`daedalus/council/canary.py:199`. Changing the shipped default means finding
all three.

**C12 — Concurrency is settable twice with no relation.** `team.max_workers`
(`Team.tsx:473`, per project, no confirmation, default `3` at `build.py:413`)
and the global `concurrency` cap axis (`Settings.tsx:1453`,
confirmation-gated). Raising the first is a widening the second was built to
gate.

**C13 — Two project registries for the same project, disagreeing.**
`projects/agent_env.json` sets `repo_root: "."` and explains in a comment that a
machine-specific absolute path had already broken other hosts once.
`.agentenv/agentenv.json` sets `repo_root: "C:/Users/nukei/Desktop/agent_env"`,
which does not exist on this machine. `config.py:1-8` documents the precedence
(registry first, then repo-local, then fail closed), so the stale value is
shadowed rather than fatal — but two files give two answers for one project.

**C14 — A setting that reads as a choice and is a constant.**
`write_wave_policy` accepts exactly one value, `"never"` (`config.py:45-52`);
legacy `"low_risk"`/`"always"` are coerced, not honoured. This is *correct* —
sealed promotion — but it is shaped like a knob, which invites a user to look
for the other settings.

**C15 — The master-mode radio is guarded in the browser only.** Gap A above:
the UI refuses `bounded → custom` without confirmation
(`Settings.tsx:567-569`); the backend does not (`settings.py:242-245`).

**C16 — Two panels for one word.** "Einstellungen" (`Cockpit.tsx:920`) and
Theme Studio (`Cockpit.tsx:919`) are separate drawers on adjacent rail buttons,
mutually exclusive by keyboard (`Cockpit.tsx:640,647,659`). Appearance is the
only settings category with its own top-level surface, and the only one with no
risk attached.

**C17 — Two independent resolvers for one artifact.** `spine.ledger_path`
(`daedalus/spine/picker.py:504`) and `DAEDALUS_SPINE_DB`
(`daedalus/kernel/events/ledger.py:173`) both point at the attempt-memory
database. The comment at `picker.py:495-498` records that three tests
previously conflated them and silently measured the developer's real ledger —
green alone, red in the full suite. Retained negative evidence; not a layout
problem, but the panel must never show one of the two as "the" setting.

---

## 4. Constraints for whoever builds this

1. **Do not remove a safety boundary.** Group 8 is read-only. Adding a toggle
   there is a release-blocking defect under `AGENTS.md`.
2. **The widening confirmation stays transient.** It is popped, never persisted
   (`settings.py:196-199`). Nothing may store a "don't ask again".
3. **Chat's transient words are confirmations too.** `confirm-remote` and
   `confirm-campaigns` must survive into the panel as explicit confirmations.
4. **Retire the Revision-9 vocabulary in the writer only.** The reader must keep
   migrating old documents (`settings.py:209-224`); the panel must stop
   producing them.
5. **`/computer`'s installation-global scope is a contract question**, not a
   layout question. The panel must either state the real scope ("gilt für diese
   Installation, nicht für dieses Projekt") or the scope must change first.
   Drawing it under a project header would be a new lie.
6. **UNVERIFIED:** nothing here was exercised at runtime. Counts are static
   reads of `main` @ `a05f4b26`. Reachability claims for the SSH block and the
   `auto_start` checkboxes come from the `disabled` props and the normalizer,
   not from a click. `config/connections.json` and `.env` are both absent in
   this checkout, so no persisted value was observed — only defaults.
