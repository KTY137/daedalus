# Work Packet G1-IKARUS-04 — stateless one-shot runtime port

**Status:** IMPLEMENTED ON BRANCH / EXACT-HEAD CI REQUIRED. **Classification:** `ALIGNED`.
**Gate:** 1. **Authoring base:** `68721e3208194391d71b0ae64d24157fd1876207`. **Reconciled main:** `24c2f1ecbaac0244a121b08f13d0f4ba623f7bf2`.
**Depends on:** G1-IKARUS-02 runtime-role identity and the canonical Gate-0 runtime manifest/conformance contracts.

## One claim

Ikarus can now describe a small LLM request as a **single, sessionless, tool-less invocation** whose only model inputs are the explicitly retained system/user messages, whose runtime identity is the exact immutable role binding, and whose token/wall-time/cost limits reuse `ResourceBudget`. That request can be joined to a selected runtime only when its `RuntimeManifest` exactly matches the role binding and its existing canonical `RuntimeConformanceReceipt` is current and passed.

This packet does **not** execute a provider and does not claim that an arbitrary provider is internally stateless. That stronger claim remains blocked until one real broker-bound adapter supplies independently inspectable provider observations. The packet closes the Ikarus interface half of the Hermes one-shot behavior and creates the exact request/evidence seam that a later live adapter must consume.

## Source-backed Hermes comparison

Pinned source: `NousResearch/hermes-agent` tag `v2026.8.19`, commit `fcbd1076a93841fa88855acce810e342a5b78101`, `agent/oneshot.py` SHA-256 `235053f5b384af07a981f1dd03816a828e0eefb5f1805fca4a1abcbc19e76c2a`.

Hermes' reusable behavior is narrow and useful: `run_oneshot` builds an optional system message plus exactly one user message, calls the shared LLM helper once, and explicitly runs outside conversation history. Ikarus adapts that behavior rather than the implementation.

| Concern | Hermes v2026.8.19 | Ikarus G1-IKARUS-04 |
| --- | --- | --- |
| conversation state | one-shot helper promises no session history | request schema has no session/thread/history/memory/transcript field |
| turn count | one `call_llm` invocation | immutable `iteration_limit = 1` |
| message shape | optional system + one user message | same explicit message shape |
| runtime selection | optional `main_runtime` dict or task routing | exact `(role, runtime_id, binding_sha256)` identity |
| token/time bounds | helper arguments `max_tokens`, `timeout` | canonical `ResourceBudget`; positive token + wall-time bounds required |
| tool behavior | outside the one-shot contract | empty tool scope; manifests declaring tools fail closed until tool-scope projection lands |
| runtime trust | helper invokes configured provider | evidence binding requires exact current canonical runtime conformance; still grants no execution |
| templates | process-global mutable `PROMPT_TEMPLATES` dict | deliberately omitted; prompt preparation remains caller-local/data-only |
| provider effect | direct helper call | none; future live execution must use `daedalus.runtimes.broker` |

The differences are intentional improvements in identity, budgeting, fail-closed tool behavior and authority separation, not claims that Ikarus already has a live Hermes-equivalent provider.

## Exact scope

- NEW `daedalus/ikarus_oneshot.py`
- NEW `tests/test_ikarus_oneshot.py`
- NEW `.github/workflows/g1-ikarus-oneshot.yml`
- UPDATE `docs/research/hermes-agent-v2026.8.19-provenance.json`
- this packet

**Forbidden here:** `daedalus/kernel/**`, `daedalus/spine/**`, `daedalus/runtimes/**`, provider implementations, scheduler/loop ownership, SessionDB/memory, global prompt-template registry, tool registry, credentials, network calls, subprocess execution, promotion, or master-plan amendment.

## Canonical seams reused

- runtime identity: `RuntimeRoleSnapshot` from `daedalus.ikarus_runtime_role`;
- execution budget: `ResourceBudget`;
- declared runtime subject: `RuntimeManifest`;
- measured generic runtime evidence: `RuntimeConformanceReceipt` plus `verify_current_conformance`;
- future provider execution: existing `daedalus.runtimes.broker` only.

`OneShotRuntimeEvidenceBinding` is explicitly a **read-only projection**, not a new kernel contract, admission decision, runtime trust row, effect lease, or permission to execute. It only joins digests that canonical contracts already own.

## Acceptance matrix

| # | Claim | Red if |
| --- | --- | --- |
| 1 | request carries only explicit optional system + exactly one user message | a history/session input appears |
| 2 | one-shot has one structural iteration and no retry loop | caller can request multiple iterations |
| 3 | token and wall time are positive canonical bounds | unbounded one-shot is accepted |
| 4 | runtime/binding/prompt/budget drift changes the request/evidence-binding identity | changed inputs retain the same digest |
| 5 | selected manifest exactly matches runtime id, adapter id/version and source revision | loose or role-only fallback is accepted |
| 6 | failed/stale/different canonical conformance refuses | declaration alone becomes an evidence binding |
| 7 | tool scope fails closed | a manifest with declared tools is bound before the tool-scope packet |
| 8 | a cost-bound request requires cost reporting | a cost ceiling is accepted with no observable cost signal |
| 9 | module performs no I/O/provider/session work | subprocess/network/file/database/provider call appears |
| 10 | no second runtime/effect/conformance authority is introduced | evidence binding starts execution or mints a competing receipt |

## Evidence

Authoring environment:

```text
python -m py_compile daedalus/ikarus_oneshot.py tests/test_ikarus_oneshot.py
exit 0

isolated dependency-stub smoke: passed
```

The smoke exercised request construction, exact two-message shape, digest creation, successful evidence binding, empty-prompt refusal and deny-by-default tool refusal. It used stubs for the imported canonical types because this authoring environment does not contain a checkout of the private repository. Therefore it is **not** represented as repository-exact pytest evidence.

`.github/workflows/g1-ikarus-oneshot.yml` now runs the focused packet against the real GitHub checkout on Python 3.10 and 3.12: py_compile, JSON validation and the one-shot/runtime-role/runtime-conformance test set. Until that exact-head workflow is green, the PR stays draft.

## Deferred, precisely

1. Instrument one real broker-bound runtime adapter and retain evidence showing that it sends only the one-shot message vector and does not attach conversation/session state.
2. Bind that adapter's exact executable target and provider observation authority before changing any `source-only` role to executable.
3. Project canonical tool/effect policy into a future one-shot invocation instead of the temporary deny-all tool posture.
4. General agent-loop iteration budgets remain separate from this one-call contract; this packet only fixes one-shot iteration count to one.
5. Do not tick the parity-ledger “stateless one-shot runtime conformance” item as fully complete until item 1 is independently evidenced.

Iron Plan: ALIGNED
Iron Gate: 1
