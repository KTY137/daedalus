# Environment switches Daedalus reads

**Revision bound:** measured 2026-09-03 against the working tree.
**Classification:** `ALIGNED` — documentation of existing behaviour. No source
file changed; nothing here grants a capability or widens a boundary.

The architecture drift gate tracks two failure modes for environment switches.
A switch read in code that no prose mentions is **code-only** drift: an
undocumented lever that changes runtime behaviour, which this repository treats
as a defect class rather than a detail. The mirror case, prose naming a switch
no code reads, is **doc-only** drift.

This page exists to close the code-only half. Every entry was read at the call
site named beside it; none is inferred from its name. Names appear in prose
rather than in fenced blocks on purpose — `daedalus/mapping/drift.py` drops
fenced code at index time, so a switch documented only inside a code fence is
still dark.

## The switches

**DAEDALUS_FANOUT_CONCURRENCY** — `daedalus/lanes/fanout.py:84`, read by
`default_concurrency()`. An integer, clamped to a minimum of 1. Unset, empty, or
unparseable falls back to `DEFAULT_CONCURRENCY`; a `ValueError` is swallowed
deliberately so a malformed value degrades to the default rather than killing a
fan-out. This is a read-only-worker concurrency axis in the sense of master plan
§4.1, so the owner-controlled execution limit policy governs it.

**DAEDALUS_BUDGET_ENVELOPE** — `daedalus/kernel/policy/ledger.py:523` and `:543`.
Not an operator knob. It is the process-boundary half of spend attribution: a
comma-separated list of open `SpendEnvelope` identifiers that
`SpendEnvelope.__enter__` writes into the environment and `__exit__` restores,
so a child process that inherited the scope draws on the same envelope. The
other half is a pid check; `_attributed()` requires either. Setting it by hand
does not raise or lower any ceiling — the worst it can do is attribute a spend
to an envelope that did not make it, and the module states the floor plainly: a
spend satisfying neither test "is bounded by the period ceiling alone".

**DAEDALUS_BUDGET_USD** — `daedalus/kernel/policy/ledger.py:657`, read as
`_env_float(ENV_CEILING, DEFAULT_CEILING_USD)`. The spend ceiling for one
activation period, defaulting to `$5.00`. This is the monetary axis master plan
§4.1 and amendment Revisions 9 and 10 govern; raising it is a decision someone
makes, not a default someone inherits. `.env.example` has always described it.

**DAEDALUS_BUDGET_MAX_CALLS** — `daedalus/kernel/policy/ledger.py:722`, read as
`_env_int(ENV_MAX_CALLS, DEFAULT_MAX_CALLS)`, default 40. The billable-call
ceiling for the same period. Its constant lives in
`daedalus/kernel/policy/pricing.py`.

**DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED** — `daedalus/kernel/policy/ledger.py:704`,
read as `_env_bool(ENV_PERIOD_CEILING_ENABLED, True)`. The legacy switch that
**turns the period USD ceiling off**: false yields a policy in custom mode with
`period_usd` unconfigured. Default true, and a value that is neither boolean nor
empty raises rather than guessing "whether the period USD ceiling is active".
`DAEDALUS_EXECUTION_LIMIT_POLICY`, checked immediately above it, takes
precedence when present.

These three were invisible to the switch inventory until 2026-09-03. All are
read through a helper that takes the variable name as a parameter, which the
scanner could not follow, so the two documented ones were reported as *dead
configuration* and this third one was not reported at all. A switch that
disables the monetary ceiling should not be able to hide from the instrument
that lists switches.

**DAEDALUS_EMBED_TIMEOUT_S** and **DAEDALUS_EMBED_COLD_TIMEOUT_S** —
`daedalus/orchestration/semantic_route.py:242` and `:270`. Wall-clock ceilings
for the embedding call on the warm and cold paths respectively; the cold one is
separate because a first call pays model load. Same helper indirection, same
reason they were invisible.

**DAEDALUS_DESKTOP_STARTUP_NONCE** — `daedalus/interfaces/http/server.py:27`,
read by `desktop_startup_nonce()`. The nonce the desktop parent issues to its
own backend. Validated strictly: exactly 64 lowercase hex characters, or the
call raises `ValueError` rather than proceeding with malformed evidence. Empty
is a legitimate state and means no parent-issued nonce.

**DAEDALUS_OLLAMA_TUNNEL_FORWARD** and **DAEDALUS_OLLAMA_TUNNEL_TARGET** —
`daedalus/desktop_runtime.py:303-304`, and the target again at `:1176`. A pair;
neither does anything alone. Together they wrap `sensitivity.lane_for_host` so
that a request naming the forward address is classified as if it named the
target address. This participates in **egress lane classification**, so it is
worth stating exactly what it does and does not do: it substitutes the real
destination for a local tunnel endpoint *before* the existing classifier runs,
so the lane reflects where traffic actually goes instead of where it was
addressed. It does not bypass the classifier, and an unrecognised host is passed
through untouched.

**DAEDALUS_RTX_SSH_HOST** — `daedalus/health.py:132`. The bench ssh endpoint for
the two diagnostics Ollama's HTTP API cannot answer (is the auto-start task
configured to survive a headless reboot, and is `llama-server.exe`
crash-looping). Note that this one carries a **hardcoded default**,
`Administrator@100.119.126.9`, so it is live without being set. The far-end
calls are read-only `Get-ScheduledTask` / `Get-WinEvent`; nothing there stops or
restarts anything, and the whole round trip is capped at 9 seconds.

**DAEDALUS_RTX_TASK_NAME** — `daedalus/health.py:133`. The scheduled-task name
queried on that bench. Also defaulted, to `DaedalusOllamaServe`.

**DAEDALUS_EDITOR_CONTEXT_DIR** — `daedalus/orchestration/editor_context.py:70`,
read by `_artifact_root()`. Overrides where transient editor-session
projections are written. Unset falls back to `runs/artifacts/editor-contexts`
under the repository. The value is `resolve()`d, so a relative path is taken
against the process working directory.

**DAEDALUS_REPO_ROOT** — `daedalus/interfaces/cli/shift.py:241`, read by
`_path()`. Locates the declared-shift file when no explicit repo root is passed.
Falls back to `.`, the process working directory.

**DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET** — `scripts/gate0_release.py:179`.
A secret consumed by the owner-facing CLI over the sealed Gate-0 release receipt
contract. Documented here as a name only. Its value belongs in the environment
and never in this repository, a transcript, or a model context.

## Read, but not Daedalus's to define

These also appear as code-only drift and are deliberately **not** given
entries above, because documenting them would imply Daedalus owns a lever it
does not.

`tools/gate_host_preflight.py:126` reads `PROCESSOR_IDENTIFIER` for a
human-readable CPU model, and `:392` reads `USER` when naming the account a
discrimination receipt was produced under.
`docs/recovery/production_key_ceremony_kit.py:149` reads `USERDOMAIN` to lock a
path down to the current user.

All three are supplied by the operating system. Daedalus reads them; it does not
define them, and setting them is the OS's business — which is why they get this
paragraph rather than entries above.

They are also, as of 2026-09-03, members of `_PLATFORM_ENV` in
`daedalus/mapping/switches.py`, which is where that scope boundary is actually
enforced. That set already held `USERNAME` and `USERPROFILE`; these three are
the same category and were simply missing. Prose alone could not have fixed it:
naming an OS variable in the strict operator form the scanner recognises closes
the *read-but-undocumented* row and immediately opens a *documented-but-unread*
one, because no Daedalus module owns the name. Trading one false row for another
is not documentation, so this paragraph deliberately does **not** use that form.

`F2_S01_PATH` (`experiments/forest_v2/s06_cards/s01_upstream.py:143`) is local
to one frozen Forest-v2 experiment and locates that experiment's own package.
It is not a product switch and is not intended to survive the experiment.

## What this page is not

It is not a configuration guide and it grants nothing. Under master plan §4.1
the owner-controlled execution limit policy decides which resource axes are
bounded, and under invariant 8 the trust boundaries — egress admission, write
roots, secret and tool policy, the kill switch — are enforced at effect
boundaries, never by an environment variable. An entry here documents that a
switch exists and what it reads; it does not make that switch an authority.

---

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: every entry read at the cited file and line on 2026-09-03; the
code-only set enumerated from daedalus.mapping.drift.scan(...)["doc_drift"].`
