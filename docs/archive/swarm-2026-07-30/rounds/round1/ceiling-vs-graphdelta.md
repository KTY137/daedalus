# Claims about `ceiling-vs-graphdelta.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Dynamic typing or missing type annotations could yield incomplete type edges, understating ceiling.
2. [risk] Building type graphs per historical revision is expensive and may require project build steps.
3. [risk] The parent commit may contain syntax errors or incomplete refactors, breaking type extraction.
4. [risk] Rename resolution adds complexity and potential alias probe failures (understatement risk).
5. [todo] Implement a type-edge extractor (e.g., via Pyre/mypy dump or custom AST walk for type annotations, inheritance, and typed imports).
6. [todo] Integrate git checkout of parent commit and type analysis into the ceiling pipeline, caching results per revision.
7. [todo] Write a render_ceiling_type analogous to render_ceiling with clean/leaky arms and reopen thresholds.
8. [todo] Add temporal-style rename resolution for focus/defining files at the parent revision.
9. [todo] Extend _classify function with TYPE_REACHABLE class and add type-edge query logic.
10. [todo] Test on the existing corpus to establish baseline type ceiling.