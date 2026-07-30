# Claims about `budget.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Core correctness of budget enforcement (Ledger.reserve, atomic replace on Windows) not visible; no assurance that the check-before-call invariant holds.
2. [risk] price_call raises NameError when called without explicit host, crashing any budget check that relies on the default host=None path.
3. [risk] Subscription vendor handling may silently widen the cap if not thoroughly tested, but no tests seen.
4. [risk] Module unimportable due to syntax error in _num function.
5. [todo] Fix incomplete _num function (complete the raise statement with an appropriate BudgetError).
6. [todo] Write a regression test for price_call with host=None to catch the NameError.
7. [todo] Add 'else: untrusted_endpoint = False' in price_call to handle host=None.
8. [todo] Provide the full implementation of Ledger class for a complete audit.
9. [todo] Test module import after fixing _num.