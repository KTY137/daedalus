# Ikarus: literal intent at the existing dispatch boundary

Classification: ALIGNED; derived work packet, no constitutional amendment.
Active gate: Gate 1. Parent: 97a2b54a8beaf289605123ad14b8165ff91b8838.
Primary claim: question/quotation normalization does not manufacture an action
or confirmation in the existing may_act -> _decide -> _route -> _ask_inner path.

## Scope

Modify `daedalus/ikarus_act.py`; add
`tests/test_ikarus_act_literal_intent.py` and
`tests/test_ikarus_act_literal_dispatch.py`. The live shell source is NOT changed.
No new executor, state store, provider, authority, tool activation or dependency.
Existing action/affirmative/negative vocabularies are byte-semantically unchanged.
Neither the master plan nor AGENTS, policy, budgets or promotion are modified.

## Baseline and repair

The source copy was checked against Git blob
`fa812196804ba63045ec79b145ed71cc8c21ee3c` at b6903c0b.
Against the 124 new predicate cases, that baseline produced 75 failures and
49 passes. Examples: `yes?` confirmed a pending action; `"yes"` also confirmed;
`"run tests"` reached the imperative rule; `run tests?!` was not interrogative;
quoted/questioning `no` could clear an offer as a decline.

The repair retains quotation and question markers during normalization,
recognizes trailing question/bang combinations, and refuses a quoted leading
command before the offer/imperative branches. It detects common quotation
marks, backticks, blockquotes and tilde fences, including after polite filler.
It deliberately stops at the first non-filler word, preserving explicit
commands such as `build a "settings" dialog`. A literal does not generate a
new executable offer either. Plain `yes`, `ja!`, `Confirm.` and `no` retain
their previous behavior. No new affirmative word or action verb is introduced.

## Builder measurements, 2026-09-11

Linux x86-64, CPython 3.13.5, isolated source copies:

- Runtime replay: 103 passed (the preceding packet, unchanged).
- Literal input boundary: 124 passed.
- Existing shell routing seam: 15 passed.
- Combined: 242 passed at PYTHONHASHSEED=0, 1 and 8675309.
- py_compile passed for the two changed modules and three focused test files.
- 2,640 generated message/offer combinations: no new allowed action versus the
  baseline. This is a bounded check, not an exhaustive linguistic proof.
- Removing the quote guard: 52 failing tests.
- Stripping question marks again: 20 failing tests.
- Restoring the old trailing-question check: 4 failing tests.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONHASHSEED=0 python -m pytest -q -p no:cacheprovider tests/test_ikarus_runtime_events.py tests/test_ikarus_act_literal_intent.py tests/test_ikarus_act_literal_dispatch.py
```

The routing tests compile the repository's actual `_decide`, `_route` and
`_ask_inner` function definitions with controlled dependency doubles. They force
an enqueue intent, observe which path is called, and verify original-objective
handoff plus fail-closed conversation lookup. Locally those exact definitions
came from a connector-read excerpt of shell blob
`8b10c2c82220b39c37e0875d697fada9de4be908`; this excerpt is NOT a replacement
module and is NOT committed. In a full checkout the tests read the real file.
These are source-level routing-seam tests, not a fully initialized package,
real tool execution, authenticated provider, HTTP, streaming, GUI or CI proof.

## Remaining obligations

This lexical narrowing is not general natural-language authorization, a full
Markdown parser, or an injection/security boundary. Semantic negation,
conditional instructions and offer freshness remain separate obligations.
The canonical kernel must still admit every actual effect. The runtime replay
packet is still not activated as real provider recovery.

The existing Ikarus line is deliberately preserved. It has an older layout
than main: selective transfer must map `daedalus/ikarus_act.py` to
`daedalus/orchestration/ikarus/act.py`, and the shell path in the seam test to
`daedalus/orchestration/ikarus/shell.py`, updating imports without reverting
main's newer language support. Do not merge the whole divergent branch.

Full legacy suites, supported-platform checks, independent review and main
integration remain open. Rollback is a selective revert; no data migration,
branch reset, force push or archive mutation is involved.
