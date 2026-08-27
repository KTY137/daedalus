# Opus fleet watchdog (isolated experiment)

Iron Plan: `EXPERIMENT`  
Iron Gate: `0`

This package runs a one-shot, read-only advisory campaign.  It does not create
agents with repository tools.  Each seat is a fresh, single-participant
Daedalus Council: Claude uses the Council profile with every tool denied and
an exact empty native `--tools` set; Codex uses the Council profile's read-only
sandbox with user config/rules ignored and ephemeral session state.  Only files explicitly
listed in the JSON configuration are placed in `Evidence`; the Council secret
floor checks every path and file before egress.

The campaign identifier is the re-arm token.  Re-running a terminal campaign
does not call a vendor.  A slot is atomically marked `in_flight`, and its call
attempt is persisted, before dispatch.  If the process dies, the next run marks
that slot `unknown` and never retries it automatically.

Claude/Opus is probed exactly once before the remaining slots start.  Codex is
eligible only when the Claude CLI returned a JSON object with `is_error: true`
and a numeric top-level `api_error_status` of 429, 503, or 529.  Text that says
"429", authentication failures, timeouts, malformed JSON, generic non-zero CLI
exits, budget refusals, and policy/secret-floor refusals do not select Codex.
An exact typed wrapper remains usable when the Claude CLI exits non-zero,
because that is how current capacity errors are emitted; a simultaneous
authentication marker takes precedence and still forbids fallback.

Local evidence for that wrapper field exists: the retained
`runs/last_claude_report.json` contains status 429 and a session id, and the
only bridge path that creates those fields reads the top-level
`payload.get("api_error_status")` from the complete `claude -p --output-format
json` stdout wrapper.  The original stdout bytes were not retained, so this is
derived live evidence rather than a replayable raw receipt; the exact complete
wrapper shape is pinned in unit tests.  Claude's local session JSONL also
records the originating 429 as `apiErrorStatus`.  If a future CLI changes the
stdout schema, parsing fails closed and Codex does not start.

Transcripts and operational state live below
`runs/watchdog/mission-<campaign_id>/`.  Council transcripts are append-only
and hash-chained.  Operational state contains no model prose.

`run_campaign(...)` also requires the supervisor's injected `session_probe`.
It returns an object shaped as
`{"ok": bool, "active_sessions": int, "sources": [str], "reason": str}`
after checking real Claude/Codex/Daedalus session evidence.  Missing, raising,
or malformed probes fail closed.  A positive observation is persisted and the
campaign waits with all slots still pending; the next 20-minute tick may check
again. Selected evidence is not read or frozen until this gate first reports
idle, so edits made by an active session do not poison a waiting campaign with
a stale digest. A machine-global OS advisory lock at the default watchdog runs
root closes the race between two distinct campaign IDs. No PID file is used.
Council's outer seat deadline includes the full canonical ManagedProcess
cancellation ladder, so the lock and kill-switch watcher outlive bounded child
cancellation rather than releasing at the provider timeout.

The 20-minute scheduled supervisor may monitor forever, but a campaign cannot:
once its finite slots are terminal, `run_campaign` returns the retained state
before another session check or vendor call.  More work requires a deliberately
new Work Packet/campaign ID.  There is no rolling timestamp ID, implicit re-arm,
or automatic spend loop in this package.

## Configuration

The runner accepts one explicit JSON file:

```json
{
  "campaign_id": "tensor-review-20260825-a",
  "live": true,
  "projects": [
    {
      "project": "agent_env",
      "objective": "Review the tensor integration and propose deterministic checks.",
      "context_paths": [
        "docs/research/TENSOR_EMBEDDING_SURVEY_2026-08-25.md"
      ],
      "enabled": true
    }
  ],
  "roles": ["tensor mathematics", "integration contract", "adversarial tests"],
  "max_agents": 20,
  "max_parallel": 4,
  "timeout_s": 180,
  "token_ceiling": 12000,
  "max_calls": 21,
  "max_spend_usd": 65.0,
  "codex_model": "gpt-5.4",
  "max_evidence_bytes": 1000000
}
```

`max_spend_usd` and `max_calls` are enforced through a campaign-local Daedalus
budget ledger as well as the durable call counter.  The existing machine-wide
budget can remain stricter at the outer watchdog boundary.

Deletion/expiry: delete this directory and its thin watchdog wiring after the
canonical brokered Claude and Codex runtimes have live exact-revision
conformance receipts.  Review the experiment no later than 2026-09-30.
