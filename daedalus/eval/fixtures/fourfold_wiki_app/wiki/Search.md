# Search behavior

Search is implemented in [`search.py`](../src/knowledge_hub/search.py). It is
case-insensitive and checks title, body, slug, and tag. Results are sorted by
slug to remain deterministic.

Only published records returned by
[`repository.py`](../src/knowledge_hub/repository.py) are exposed by the CLI.
