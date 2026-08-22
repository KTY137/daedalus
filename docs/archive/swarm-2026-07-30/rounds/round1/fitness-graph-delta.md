# Claims about `fitness-graph-delta.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] change_constant mutants are invisible to the 'literals' layer because repr() of string literals is identical before/after (e.g., 'claude_cli' vs 'claude_cli' both repr to "'claude_cli'"). The multiset key uses repr, so no delta.
2. [risk] Corpus is 300 mutants but only 62 are change_constant; the rest are deletions/insertions that naturally move AST refs or structure. This operator mix bias inflates overall detection rate.
3. [risk] Leaky layer (code.refs.leaky) includes comment tokens, so marker words 'SEEDED DEFECT' cause false detections. This inflates the headline number.
4. [risk] Specificity arm (real commits) is not fully implemented in the excerpt; without it, false alarm rate is unknown.
5. [todo] Run clean arm (SCORING_LAYERS excluding 'code.refs.leaky') on full corpus and report detected/applied. Compare to headline 75.3%.
6. [todo] Fix 'literals' layer to detect changes in string literal values (e.g., compare raw values, not repr).
7. [todo] Complete specificity arm (measure_commit) to measure false alarm rate on real commits.
8. [todo] Report detection rate per defect class separately, especially change_constant.