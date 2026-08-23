# G0-VET-01 — Environment egress pin identity

Base revision: `21c6016e1f84bea0a9bdb609ec33522856037f85`
Branch: `codex/vet-env-pin-20260823`
Classification: `ALIGNED`
Active delivery gate: Gate 0 — Canonical Kernel

## Acceptance claim

An `mcp.egress` allowance pinned to one reviewed environment-provided endpoint
must not downgrade a finding for a different endpoint. The MCP digest binds
only the endpoint material the vet gate actually extracts from environment
values; unrelated environment values and secrets do not enter verdict output
or alter identity. The changed verdict semantics are published as vet version
`2`.

This packet touches constitutional invariants 4 (independently controlled
evidence), 7 (identity and version provenance), and 8 (bounded egress). It does
not grant egress, change host-lane policy, start an MCP server, or modify the
canonical runtime kernel.

## Frozen scope

In scope:

- `daedalus/tools/vet.py`
- `tests/test_tools_vet.py`
- this work-packet record

Forbidden:

- `daedalus/sensitivity.py` or any change to trusted-host policy;
- `.agentenv/tool-allowances.json` or any new allowance;
- runtime, event-store, promotion, or candidate paths;
- merge, push, Gate transition, or claim that static vetting proves runtime
  confinement.

## Baseline at the frozen revision

- Changing only `WEBHOOK_URL` from `https://reviewed.example/x` to
  `https://evil.example/steal` leaves `mcp_spec_digest` unchanged and lets the
  old pinned `mcp.egress` acknowledgement downgrade the new endpoint to
  `REVIEW`.
- `VET_VERSION` is still `"1"` although commit `05763153` changed verdict
  meaning.
- `test_a_tag_block_character_cannot_hide_an_injection` constructs
  `pre<TAG-V>ious`; deletion-based defanging yields `preious`, so the fixture
  fails before exercising `inject.override`.

## Acceptance matrix

| ID | Required evidence | Acceptance |
| --- | --- | --- |
| A1 | Reviewed-to-evil Env endpoint regression | Digests differ; the old pin does not acknowledge the new endpoint; verdict remains `BLOCK`. |
| A2 | Secret/value stability regression | Changing a generic non-URL Env value, including a token-like value, leaves the digest unchanged and the value never appears in verdict output. |
| A3 | URL credential/path stability regression | For the same scheme/host/port, changing URL userinfo or path does not change endpoint identity; no credential enters output. |
| A4 | Endpoint distinction regression | Scheme, host, or explicit port change changes the digest. |
| A5 | Vet semantic version contract | `VET_VERSION == "2"` and version `2` propagates through `Verdict.to_dict()` and `summarise()`. |
| A6 | Tag-block fixture | The fixture inserts the tag character without replacing the visible `v`; `inject.override` and `obfuscation.invisible_chars` both appear. |
| A7 | Focused suite | `python -B -m pytest -p no:cacheprovider tests/test_tools_vet.py -q` passes. |

## Design boundary

The digest records a canonical, secret-free endpoint tuple derived only from
URL-shaped text already scanned by the gate: lower-cased scheme and host plus
explicit port. Userinfo, path, query, fragment, and all non-URL environment
values are excluded. Unparseable matched authorities are represented by an
opaque hash rather than copied into identity material or output.

The host parser does not decide trust. `sensitivity.lane_for_host` remains the
only authority for trusted versus untrusted lanes.

## Rollback and residual risk

Rollback is the single packet commit. Version-1 receipts remain identifiable
as older evidence and must be regenerated before being treated as version-2
vet evidence.

Static URL extraction is deliberately limited to the existing `_URL_IN_ARG`
grammar. Computed destinations, encoded values, runtime redirects, DNS changes,
and server behavior remain outside this static gate and require runtime policy
and evidence.

## Builder verification

- Baseline reproducer: equal digest and stale `REVIEW` acknowledgement for the
  changed Env host; vet version `1`; tag fixture defanged to `preious`.
- Post-change reproducer: unequal digest, changed host remains `BLOCK` with no
  acknowledgement; vet version `2`; corrected fixture defangs to `previous`.
- Focused A1–A6 selection: `22 passed, 6 subtests passed`.
- Complete vet suite: `192 passed, 65 subtests passed`.
- Tool-inventory compatibility: `tests/test_inventory_shadowing.py` —
  `5 passed`.
- `git diff --check`: clean. Ruff was not installed in the environment, so no
  Ruff result is claimed.

All Python test commands used `python -B` and disabled pytest's cache provider.
No runtime was started, no network was contacted, and no Main worktree file was
modified.
