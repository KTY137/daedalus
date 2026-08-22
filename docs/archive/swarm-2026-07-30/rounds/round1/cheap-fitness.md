# Claims about `cheap-fitness.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Coverage-based heuristics assume tests covering changed code are most relevant; may not hold for all bugs.
2. [risk] Test suite reduction may miss failures in excluded tests, leading to false positives.
3. [risk] Learned surrogates require training data and may overfit.
4. [todo] Measure correlation between reduced suite verdict and full suite verdict on your benchmark.
5. [todo] Implement random subset test suite reduction (e.g., 10% of tests) as cheap fitness signal.
6. [todo] Consider static analysis warnings as auxiliary signal, but do not rely on them alone.
7. [todo] Compare with coverage-based reduction (only tests covering changed lines).