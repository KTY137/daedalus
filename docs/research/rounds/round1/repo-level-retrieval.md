# Claims about `repo-level-retrieval.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Dense embeddings can be brittle on rare identifiers or project-specific patterns
2. [risk] Context budget (e.g., 8K tokens) limits number of snippets, forcing trade-offs
3. [risk] Agentic search incurs high latency and LLM cost; unreliable recall metrics
4. [risk] BM25 misses semantic matches, harming recall on synonyms/abstractions
5. [risk] Call-graph expansion may add irrelevant noise if over-extended
6. [todo] Measure recall on internal repo-level dataset with actual context budget
7. [todo] Benchmark coverage of repo’s call graph to estimate expansion benefit
8. [todo] Evaluate hybrid pipeline: BM25 + dense reranking + graph expansion