# Claims about `task-decomposition.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Comparisons are confounded by different tool interfaces and model capabilities; exact numbers are uncertain and based on recall of evolving leaderboards.
2. [risk] Plan-then-execute includes a spectrum from naive single‑step decompose‑to‑the‑end to iterated refinement; simple ablation may not capture the nuance.
3. [risk] Tree‑search evidence is largely from reasoning tasks (e.g., Game of 24, Creative Writing) with few rigorous coding‑task studies.
4. [risk] Fabrication risk: names like "SWE-agent" and percentages are from memory, not verified against current publications.
5. [todo] Design a head‑to‑head experiment: same LLM, same agent scaffold, vary only the decomposition‑then‑execute vs. ReAct strategy.
6. [todo] Search for any coding‑focused tree‑search paper (e.g., MCTS for code repair) and extract quantitative comparisons.
7. [todo] Re‑read the SWE-agent paper to confirm if they measured a decomposed baseline.
8. [todo] Audit the SWE-bench Lite leaderboard for up‑to‑date resolve rates.