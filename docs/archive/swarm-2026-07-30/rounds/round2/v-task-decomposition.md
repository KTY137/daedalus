# Verification: v-task-decomposition

Source file `task-decomposition.py` was not located; unable to verify any claims. All verdicts are UNDECIDABLE.

## Verdicts

- UNDECIDABLE [risk] Comparisons are confounded by different tool interfaces and model capabilities; exact numbers are uncertain and based on recall of evolving leaderboards.
- UNDECIDABLE [risk] Plan-then-execute includes a spectrum from naive single‑step decompose‑to‑the‑end to iterated refinement; simple ablation may not capture the nuance.
- UNDECIDABLE [risk] Tree‑search evidence is largely from reasoning tasks (e.g., Game of 24, Creative Writing) with few rigorous coding‑task studies.
- UNDECIDABLE [risk] Fabrication risk: names like "SWE-agent" and percentages are from memory, not verified against current publications.
- UNDECIDABLE [todo] Design a head‑to‑head experiment: same LLM, same agent scaffold, vary only the decomposition‑then‑execute vs. ReAct strategy.
- UNDECIDABLE [todo] Search for any coding‑focused tree‑search paper (e.g., MCTS for code repair) and extract quantitative comparisons.
- UNDECIDABLE [todo] Re‑read the SWE-agent paper to confirm if they measured a decomposed baseline.
- UNDECIDABLE [todo] Audit the SWE-bench Lite leaderboard for up‑to‑date resolve rates.
