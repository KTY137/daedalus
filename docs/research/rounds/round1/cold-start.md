# Claims about `cold-start.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Transfer learning may fail if target project has unique coding patterns or domain-specific bugs.
2. [risk] Synthetic data may introduce systematic biases not representative of real defects.
3. [risk] Active learning requires a human-in-the-loop, which may be a bottleneck.
4. [todo] Evaluate convergence by measuring F1 score on a held-out test set after each batch of 50 labels.
5. [todo] Design a seed set of 10-20 common defect patterns (e.g., null pointer, off-by-one).
6. [todo] Implement active learning to select 200 most uncertain examples for human labeling.
7. [todo] Use an LLM to generate 1000 synthetic code variants with injected defects.