# Claims about `mutation-operators.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] WEAKEN_COMPARISON can produce equivalent mutants when the boundary shift does not affect control flow (e.g., x < 5 → x <= 5 when x is always integer and the condition is followed by an else that handles equality).
2. [risk] DROP_CALL on a guard whose result is unused and has no side effect produces an equivalent mutant that trivially_equivalent() misses because bytecode differs (the call instruction is removed).
3. [risk] EARLY_RETURN inserted after a docstring but before a return statement can be equivalent if the function always returned None anyway.
4. [risk] CHANGE_CONSTANT on a constant that is later overwritten or unused produces an equivalent mutant missed by trivially_equivalent().
5. [todo] Add a static analysis pass to detect when a call's return value is unused and the call has no side effects, to filter DROP_CALL mutants that are equivalent.
6. [todo] Add a redundancy check for WEAKEN_COMPARISON: if the comparison is already implied by a prior check, the mutant is equivalent.
7. [todo] Consider adding SWAP_BRANCHES and REMOVE_SIDE_EFFECT operators to broaden the corpus.