# Security model

Knowledge Hub performs no network access and has no write path. The repository
layer in [`repository.py`](../src/knowledge_hub/repository.py) opens one declared
CSV file for reading. The Fourfold compiler additionally rejects path traversal,
symlink escape, broken local links, undeclared files, and unsupported claim
kinds.

See [Operations](Operations.md) for the run procedure.
