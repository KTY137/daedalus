# Verification: v-loop-promotion

Source file loop-promotion.py not provided; all claims undecidable.

## Verdicts

- UNDECIDABLE: Claim 1 - LoopLedger.claim heuristic uses declared paths, not measured changed paths; cannot verify without loop-promotion.py.
- UNDECIDABLE: Claim 2 - LoopLedger records attempt_task_ids picker cannot query; need loop-promotion.py to confirm.
- UNDECIDABLE: Claim 3 - _curated_gate drops gate_paths and base_revision; need source to verify.
- UNDECIDABLE: Claim 4 - Governance red loop continues attempting but never promotes; need source to confirm behavior.
- UNDECIDABLE: Claim 5 - Stop latency now fixed via cancellation token in re-gate; need loop-promotion.py to verify fix.
- UNDECIDABLE: Claim 6 - Sibling integration branches require human merge; need code to validate.
- UNDECIDABLE: Claim 7 - _curated_gate might silently degrade; need loop-promotion.py to assess.
- UNDECIDABLE: Claim 8 - LoopLedger.claim uses measured changed_paths; need implementation to check.
- UNDECIDABLE: Claim 9 - Need integration test for governance red loop; requires codebase context.
- UNDECIDABLE: Claim 10 - Picker's attempt memory cannot query ledger; need cross-module view.
