# Architecture

Knowledge Hub is deliberately small. The command-line layer in
[`app.py`](../src/knowledge_hub/app.py) delegates persistence to
[`repository.py`](../src/knowledge_hub/repository.py) and query semantics to
[`search.py`](../src/knowledge_hub/search.py). The immutable domain record lives
in [`models.py`](../src/knowledge_hub/models.py).

The system keeps four concerns separate:

1. code executes behavior;
2. types define the in-memory contract;
3. data files carry durable records and schema constraints;
4. this wiki records intent, operations, and decisions.

See [Domain model](Domain-Model.md) and [Data contract](Data-Contract.md).
