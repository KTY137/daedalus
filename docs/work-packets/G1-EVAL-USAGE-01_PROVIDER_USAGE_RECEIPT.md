# G1-EVAL-USAGE-01 - Provider-reported usage in the Tier-2 harness receipt

Packet ID: `G1-EVAL-USAGE-01`
Artifact role: `primary`
Status: `built; builder-verified; awaiting independent review; NOT merged`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `24e229c0f34e5404bc219637b646386529f82035`
Dependencies: `none`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge and promotion are forbidden.
Branch: `packet/g1-eval-usage-01` (worktree `daedalus-usage-20260908`)

Plan alignment in one line: ALIGNED -- Invariant 7 (provenance: material
claims carry inputs, cost, outcome and evidence) and Invariant 9 (honest
claims) applied to the one place in the tree that grades live model text.
No new effect path, no new transport call, no policy or evaluator change.

## Primary acceptance claim

**One** claim: *the token usage a provider reports for a Tier-2 call reaches
the Tier-2 receipt with provenance, and absent, malformed, reported and
locally estimated counts can never be summed together.*

Before this packet `daedalus/eval/tier2.py::_ask` discarded everything in the
provider reply except `choices[0].message.content`; `run_tier2` reported only
`tokens_A`/`tokens_B`, which are local `chars/4` estimates
(`harness.count_tokens`). The reply's `usage` block was parsed by `_send` and
thrown away. After this packet:

- `daedalus/providers/_openai_compat.py::chat_completion_receipt` returns a
  frozen `ChatReceipt` (text, typed `ProviderUsage` or `None`, malformed
  reason, bounded canonical raw JSON, its SHA-256, response model, finish
  reason, userinfo-free endpoint, request model). `chat_completion` is
  `chat_completion_receipt(...).text` -- same signature, same body, same
  transport call, same errors.
- `tier2._ask` records the receipt's usage provenance next to the text
  evidence; `run_tier2` keeps per-arm provider sums in their own fields and
  only when every scored call of that arm was `reported`; `render_tier2`
  prints one optional ASCII line.

What this packet does **not** claim: that provider counts are comparable
across providers, that they are budget-equality evidence for Gate 3, or that
they measure the same thing as `tokens_A`/`tokens_B`. See the honest limits
under "Evidence".

## Scope

**In scope (only these paths changed):**

| Path | Change |
| --- | --- |
| `daedalus/providers/_openai_compat.py` | `PROVIDER_TOKENIZER_UNKNOWN`, `ProviderUsage`, `parse_usage`, `ChatReceipt`, `chat_completion_receipt`; `chat_completion` delegates |
| `daedalus/eval/tier2.py` | `_ask` usage fields; `run_tier2` rows + `provider_usage` aggregate; `render_tier2` line |
| `tests/providers/test_openai_compat_usage_receipt.py` | new |
| `tests/test_eval_tier2_usage.py` | new |
| `tests/test_eval_tier2_integrity.py` | three patch targets repointed to `chat_completion_receipt` |
| `docs/work-packets/G1-EVAL-USAGE-01_PROVIDER_USAGE_RECEIPT.md`, `docs/work-packets/index.json` | this packet, registry projection |
| `tests/contracts/test_work_packet_index.py`, `tests/contracts/test_import_scc_hierarchy.py` | census pins only |

**Forbidden (untouched, verified by `git diff --stat`):** `daedalus/kernel/**`,
`daedalus/spine/**`, `daedalus/eval/harness.py`, `daedalus/budget.py`,
`chat_raw`, `chat_stream`, `_post`, `_send`, `run_cancellable`, the master plan,
amendment chain, `AGENTS.md`, `.agentenv/`.

**Deferred, named:** wiring provider usage into the Gate-3 baseline arms
(`daedalus/eval/gate3`, branch `packet/g3-base-01`) is Part B of the design
and belongs to that packet branch; it is not on this branch and this packet
makes no claim about it.

## Contracts and behavior

### Provider module (`_openai_compat.py`, stdlib only, no module state)

- `ProviderUsage(input_tokens, output_tokens, total_tokens, tokenizer)` is
  frozen. `__post_init__` refuses `bool`, negative, `float`, `None` and
  strings for the two primary fields and a non-count `total_tokens`
  (`ValueError`). `ProviderUsage(0, 0, 0)` is a valid report.
- `parse_usage(raw) -> (usage | None, error | None)` is total (never raises):

  | input | result | class |
  | --- | --- | --- |
  | `None`, key missing | `(None, None)` | absent |
  | `{}`, details-only block | `(None, None)` | absent |
  | not a JSON object | `(None, "usage is <type>")` | malformed |
  | exactly one primary counter | `(None, "<other> missing")` | malformed |
  | primary counter not a non-bool int >= 0 | `(None, "<field>=<repr>")` | malformed |
  | `total_tokens` present, not a count | `(None, "total_tokens=<repr>")` | malformed |
  | `total_tokens != prompt + completion` | `(None, "total mismatch")` | malformed |
  | otherwise | `(ProviderUsage, None)` | reported |

  A self-inconsistent report is deliberately not typed: it is not a
  measurement. `repr` fragments in the reason are bounded to 80 characters
  [MEASURED 2026-09-08 `grep -n _MAX_USAGE_ERROR_REPR_CHARS daedalus/providers/_openai_compat.py`].
- `ChatReceipt.usage_status` is derived: `reported` iff `usage` is not `None`;
  `malformed` iff `usage` is `None` and `usage_error` is non-empty; else
  `absent`. It is a property, not a stored field, so it cannot disagree with
  the data.
- `usage_raw_json` is `json.dumps(payload["usage"], sort_keys=True,
  separators=(",", ":"))` bounded to 2048 characters
  [MEASURED 2026-09-08 `grep -n _MAX_USAGE_RAW_CHARS daedalus/providers/_openai_compat.py`];
  `usage_raw_truncated` flags the cut; `usage_raw_sha256` always covers the
  full canonical bytes when a `usage` key exists. `None`/`False`/`None` when
  the key is absent.
- `endpoint` is `base_url` rebuilt from scheme, hostname, port and path only
  (`urllib.parse.urlsplit`): userinfo, query and fragment never enter a
  receipt. `OLLAMA_HOST`/`prov["host"]` is an unparsed environment URL.
- `chat_completion_receipt` has exactly `chat_completion`'s signature
  (pinned by `inspect.signature` equality). The body construction and both
  `_post` branches moved verbatim; the no-probe branch still makes the
  historic four-positional `_post(base_url, body, api_key, timeout_s)` call.
  `ProviderCancelled` and `ProviderHTTPError` propagate unchanged; a cancelled
  call builds no receipt (pinned by spying on the `ChatReceipt` constructor).
- `text` passes through verbatim. A `null` content is returned as `None` by
  both entrypoints -- today's behaviour, now pinned.
- No new transport call: `urlopen(` occurs 4 times in the module source
  [MEASURED 2026-09-08 `grep -c "urlopen(" daedalus/providers/_openai_compat.py`
  at base `24e229c0` and after the change], and exactly one `_send` per
  `chat_completion` / `chat_completion_receipt` invocation on both branches.

### Tier-2 harness (`tier2.py`)

- `_ask(prov, question, context)` signature unchanged. The receipt dict gains
  `usage` (`None` or `{input_tokens, output_tokens, total_tokens, tokenizer}`),
  `usage_status` (`reported | absent | malformed | error`), `usage_error`
  (through `_clean_error`), `usage_raw_json` (through the same control-byte
  filter), `usage_raw_truncated`, `usage_raw_sha256`, `provider_call`
  (`{kind, host_endpoint, request_model, response_model, finish_reason}`, each
  string through the control-byte filter and the 512-character bound
  [MEASURED 2026-09-08 `grep -n _MAX_ERROR_CHARS daedalus/eval/tier2.py`]).
  `error` is the exception path only, with `provider_call = None`. The
  `EmptyProviderResponse` path keeps the usage fields: the spend happened.
- `run_tier2` rows gain `provider_usage_A/B`, `provider_usage_status_A/B` and
  `provider_usage_evidence_A/B` (`{error, raw_json, raw_truncated, raw_sha256,
  call}`) so the raw block and its digest survive into the run result. A
  receipt without `usage_status`, or with a value outside the vocabulary,
  is `unknown` -- its own bucket, never folded into `absent`.
- Result gains `provider_usage = {calls, reported, absent, malformed, error,
  unknown, tokenizer, provider_input_tokens_A, provider_output_tokens_A,
  provider_input_tokens_B, provider_output_tokens_B}`. Counts cover every
  per-task row (two calls per row). Sums cover scored rows only and are
  `None` unless every scored call of that arm is `reported` (also `None` when
  no row scored). There is no combined or total tokens field. `tokens_A` /
  `tokens_B` are untouched and never added to these.
- `render_tier2` prints, only when the result carries `provider_usage`:
  `provider-reported tokens (tokenizer unknown): A in=<n|n/a> out=<n|n/a>
  B in=<n|n/a> out=<n|n/a> ; <r>/<n> calls reported, <k> absent, <m>
  malformed, <e> error, <u> unknown`. Every value crosses the terminal
  boundary through `_safe_ascii`. Results without the key render unchanged.

## Acceptance matrix

Deterministic, offline; the provider tests use a loopback `http.server` in
the shape of `tests/providers/test_openai_compat_cancellation.py`.

### Provider module (`tests/providers/test_openai_compat_usage_receipt.py`)

| # | Test | Passes when |
| --- | --- | --- |
| P1 | `test_provider_usage_accepts_a_reported_zero_and_defaults_to_unknown_tokenizer` | `(0,0,0)` valid; frozen; tokenizer unknown |
| P2 | `test_provider_usage_refuses_non_count_primary_fields` | bool/negative/float/None/str -> `ValueError` naming the field |
| P3 | `test_provider_usage_refuses_a_non_count_total_but_allows_none` | non-count total refused; `None` allowed |
| P4 | `test_parse_usage_reported` | with and without total |
| P5 | `test_parse_usage_absent` | `None`, `{}`, details-only -> `(None, None)` |
| P6 | `test_parse_usage_malformed` | 13 shapes incl. `"12"`, negatives, bools, floats, one-field, total mismatch, null total |
| P7 | `test_parse_usage_error_text_is_bounded_for_huge_values` | 100k-char value -> reason < 256 chars |
| P8 | `test_usage_status_is_derived_from_usage_and_error` | derived property; empty error is absent |
| P9 | `test_reported_usage_is_typed_and_raw_is_retained_with_digest` | typed + canonical raw + sha256 + model/finish/endpoint |
| P10 | `test_absent_usage_keeps_text_and_records_only_what_was_there` | missing / `null` / `{}` / details-only -> absent; raw is what was there |
| P11 | `test_malformed_usage_is_retained_raw_never_typed_and_text_still_returned` | six shapes; `chat_completion` still returns the answer |
| P12 | `test_chat_completion_is_the_receipt_text_with_a_byte_identical_request_body` | same text; two request bodies byte-identical |
| P13 | `test_receipt_signature_mirrors_chat_completion_exactly` | `inspect.signature` parameters equal |
| P14 | `test_receipt_without_probe_keeps_the_legacy_four_positional_post_call` | mirror of the G1-KERNEL-02 boundary test |
| P15 | `test_cancellation_mid_call_raises_and_builds_no_receipt` | `ProviderCancelled` within 5 s of a 60 s stall; `ChatReceipt` never constructed |
| P16 | `test_null_content_passes_through_as_none_for_both_entrypoints` | today's behaviour pinned |
| P17 | `test_unexpected_shape_still_raises_provider_http_error` | `choices: []` -> `ProviderHTTPError` |
| P18 | `test_endpoint_identity_drops_userinfo_query_and_fragment` | `u:p`, query, fragment absent from the receipt |
| P19 | `test_oversized_usage_block_is_bounded_hashed_and_leaves_text_intact` | 1 MiB block -> 2048 chars, truncated flag, full-bytes sha256, text intact |
| P20 | `test_exactly_one_send_per_call_and_no_new_transport_call` | one `_send` per call on both branches; `urlopen(` count pinned at 4 |

### Tier-2 harness (`tests/test_eval_tier2_usage.py`)

| # | Test | Passes when |
| --- | --- | --- |
| T1 | `test_ask_receipt_reported_usage_is_typed_with_provenance` | all seven keys; `provider_call` complete |
| T2 | `test_ask_receipt_absent_usage` | absent; no raw, no sha |
| T3 | `test_ask_receipt_malformed_usage_keeps_raw_and_cleans_error` | raw + sha kept; error control bytes -> `?` |
| T4 | `test_ask_receipt_error_path_has_no_provider_observation` | `error`; `provider_call is None` |
| T5 | `test_ask_receipt_empty_text_is_measurement_error_but_keeps_spend` | `EmptyProviderResponse` with usage retained |
| T6 | `test_ask_receipt_null_text_is_measurement_error_but_keeps_spend` | `None` text likewise |
| T7 | `test_ask_receipt_control_bytes_in_raw_and_call_fields_are_neutralised` | no C0 bytes survive in the receipt |
| T8 | `test_ask_receipt_never_retains_userinfo_from_the_host_url` | `prov["host"]="http://u:p@127.0.0.1:1"` -> `u:p` nowhere in the receipt (real receipt builder, `_post` stubbed) |
| T9 | `test_run_tier2_sums_reported_usage_per_arm_over_scored_rows` | A in=17 out=5, B in=170 out=11; no combined field; `tokens_A` untouched |
| T10 | `test_run_tier2_one_absent_call_makes_that_arm_none_not_partial` | one absent A call -> A sums `None`, B sums intact |
| T11 | `test_run_tier2_legacy_receipt_without_usage_field_is_unknown_not_absent` | `unknown` bucket, evidence all-`None` |
| T12 | `test_run_tier2_unrecognised_status_is_normalised_to_unknown` | `"estimated"` -> `unknown` |
| T13 | `test_run_tier2_counts_every_call_but_sums_only_scored_rows` | malformed + error on an unscored row counted, not summed |
| T14 | `test_run_tier2_no_scored_rows_yields_none_not_zero` | all four sums `None` |
| T15 | `test_run_tier2_reported_usage_on_a_measurement_error_row_is_counted_not_summed` | truncated answer row: reported=2, sums `None` |
| T16 | `test_render_line_is_present_only_when_the_result_carries_provider_usage` | nemesis `_malicious_result` renders without the line and unchanged; exact line pinned |
| T17 | `test_render_line_neutralises_forged_values_in_the_usage_aggregate` | forged strings in numeric fields -> no control bytes, bounded, evidence unchanged |

### Mutation proof (tests bite)

Six mutations applied one at a time and reverted
[MEASURED 2026-09-08 `python runs/G1-EVAL-USAGE-01/mutate.py`, log
`runs/G1-EVAL-USAGE-01/mutations.log`]:

| Mutation | Caught by |
| --- | --- |
| drop the `total mismatch` branch | P6, P11 |
| `endpoint=base_url` (keep userinfo) | P18, T8 |
| empty-text path drops usage | T5, T6 |
| per-arm sum uses `any` instead of `all` | T10, T16 |
| render numbers via `str` instead of `_safe_ascii` | T17 |
| status not normalised to `unknown` | T12 |

## Migration and rollback

- No data migration. Existing `_ask` receipts and `run_tier2` results are a
  strict superset; every previously present key is unchanged. Callers that
  patch `chat_completion` with strings (`tests/test_deepseek_write_toggle.py`,
  `test_dynamic.py`, `test_wires.py`, `test_ikarus_stream.py`,
  `test_ikarus_context.py`, `test_provider_execution_limit_policy.py`) keep
  passing unchanged because `chat_completion`'s signature and return are
  unchanged.
- The one caller-visible change is that `tier2._ask` now calls
  `chat_completion_receipt`; the three patch sites in
  `tests/test_eval_tier2_integrity.py` are repointed accordingly.
- Rollback: revert the packet commit. `chat_completion` returns to its
  inline body; no persisted artifact depends on the new fields.
- Budget register: no new `BILLABLE_SITES` row. `chat_completion` remains the
  registered scan-invisible site and still contains no direct `urlopen`; the
  interposer covers the single `_send` that both entrypoints share.

## Evidence, expected failures and review

### Baseline (before any change) [MEASURED 2026-09-08, base `24e229c0`]

`C:/Users/Administrator/Desktop/projects/daedalus/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <group>`
from the worktree, logs in `runs/G1-EVAL-USAGE-01/baseline-<group>.log`:

| group | paths | result |
| --- | --- | --- |
| providers | `tests/providers` | 160 passed |
| tier2 | `tests/test_eval_tier2_integrity.py tests/test_eval_tier2_text_evidence_nemesis.py tests/test_eval.py` | 36 passed, 8 subtests passed |
| budget-callers | `tests/test_budget.py tests/test_provider_execution_limit_policy.py tests/test_deepseek_write_toggle.py tests/test_dynamic.py tests/test_wires.py` | 227 passed |
| ikarus | `tests/test_ikarus_stream.py tests/test_ikarus_context.py tests/test_ikarus_os_boundary.py tests/test_ikarus_stop_gate_paths.py` | 75 passed |
| contracts | `tests/contracts/test_work_packet_index.py tests/contracts/test_import_scc_hierarchy.py` | 27 passed |

### After (same commands, logs `runs/G1-EVAL-USAGE-01/after-<group>.log`)

See the "After" table appended below once measured; no FAILED/ERROR line
may appear in any after-log that did not appear in its baseline.

### Honest limits (binding on every reader of these numbers)

- Provider counts are **self-reports in an unknown tokenizer**. Ollama's
  OpenAI-compatible `prompt_tokens` is `prompt_eval_count`, which may exclude
  a cached prompt prefix; DeepSeek counts with its own tokenizer. Two
  providers' counts are not comparable and nothing here compares them.
- They are **never budget-equality evidence**. Gate-3 budget equality (plan
  section 11) is declared in the harness's own tokenizer; `tokens_A`/`tokens_B`
  remain that declaration and are never added to provider counts.
- A `reported` count is not proof of spend or of a correct count; it is what
  the provider said, retained raw with a digest so a later reader can check
  the typed value against the retained bytes.
- `absent` on Ollama is expected on some versions/endpoints; it is recorded,
  not repaired. `unknown` means the harness never asked -- a legacy receipt --
  and is kept apart so it cannot inflate `absent`.

### Expected failures recorded before the build

- Callers patching `chat_completion` at their own module would break if
  `chat_completion` changed signature or return type -- it does not, verified
  by the budget-callers and ikarus groups above.
- A `_post` stub returning a non-JSON-serialisable `usage` value would raise
  `TypeError` inside `chat_completion_receipt`. Real payloads come from
  `json.loads` and cannot; this is a loud failure, not a silent degrade.
- The `total mismatch` rule will classify a provider that reports
  `total_tokens` including cached or reasoning tokens as `malformed`. That is
  deliberate (a report that disagrees with itself is retained raw, not
  typed); if a real provider is observed doing this, the follow-up is a new
  classification with its own evidence, not a relaxation.

### Review questions for the independent reviewer

1. Is there any path on which a provider count and a local estimate end up
   in the same number? (Design intent: none; `provider_*` and `tokens_*` are
   disjoint fields and the render line prints them apart.)
2. Can userinfo from `OLLAMA_HOST` reach a retained artifact through any
   field other than `endpoint`? (`ProviderHTTPError` messages built in
   `_send` contain the full URL and reach `_ask`'s `error` field through
   `_clean_error` -- this is pre-existing behaviour, unchanged by this packet,
   and named here as a residual risk rather than claimed fixed.)
3. Does `chat_completion_receipt` add any transport, thread or retry?
   (Pinned: one `_send`, four `urlopen(`, no new probe path.)
