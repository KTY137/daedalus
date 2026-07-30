# Verification: v-budget

Reviewed 9 claims from budget.md against daedalus/budget.py. 7 refuted, 1 undecidable, 0 confirmed. The alleged _num syntax error does not exist; price_call safely handles host=None; Ledger enforcement is fully visible. Subscription handling risk cannot be confirmed without tests.

## Verdicts

- REFUTED: Core correctness of budget enforcement is fully visible in the provided file; the Ledger class implements reserve with a check-before-commit invariant and uses atomic file replacement via a temp file and replace.
- REFUTED: price_call contains an else clause for untrusted_endpoint = False when host is None, so it does not raise NameError.
- UNDECIDABLE: Subscription vendor handling risk cannot be assessed without tests.
- REFUTED: Module contains no _num function; no syntax error present.
- REFUTED: There is no _num function to fix.
- REFUTED: price_call does not have a NameError when host=None; regression test unnecessary.
- REFUTED: The suggested 'else: untrusted_endpoint = False' is already present in the code.
- REFUTED: Full Ledger class implementation is provided in the file.
- REFUTED: Module imports without a _num function; no syntax error to fix.
