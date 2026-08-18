"""EXPERIMENT s09 -- eval harness for Forest v2 retrieval slices.

Frozen, isolated, read-only measurement scaffolding (master plan section 1,
section 10 Gate 2 prework, section 13 honesty rules).  Nothing here is
production-capable, nothing in the kernel imports it, and it promotes nothing.

Layout:

``gitio``       thin read-only git plumbing (log, ls-tree, cat-file batch)
``contract``    the adapter contract every measured retriever implements
``taskset``     builds and freezes the task set from the real repo history
``metrics``     Recall@k and MRR over a frozen gold set
``retrievers``  the budget-equal baselines this slice ships itself
``harness``     the runner that measures any retriever on the frozen set
"""
