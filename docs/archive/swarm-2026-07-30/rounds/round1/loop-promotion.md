# Claims about `loop-promotion.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Sibling integration branches: LoopLedger.claim is a heuristic based on declared paths, not measured changed paths, so real collisions can be missed.
2. [risk] Attempt id mismatch: LoopLedger records attempt_task_ids that picker cannot query, so picker's attempt memory is blind to loop history.
3. [risk] Candidate's own gate is dropped: _curated_gate drops gate_paths and base_revision, potentially weakening gate accuracy.
4. [risk] Governance red is normal: loop continues attempting but never promotes, which may surprise operators expecting a halt.
5. [risk] Stop latency: previously non-uniform, now fixed via cancellation token in re-gate.
6. [todo] Document that sibling integration branches require human merge; consider auto-merge or sequential promotion.
7. [todo] Consider making _curated_gate forward gate_paths when curated argv is absent, to avoid silent degradation.
8. [todo] Verify that LoopLedger.claim uses measured changed_paths from promote report, not just declared paths.
9. [todo] Add integration test that governance red loop produces inert mode report and no promotions.
10. [todo] Evaluate if picker's attempt memory can be made to query loop's ledger for convergence.