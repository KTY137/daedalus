# Data contract

The application reads [articles.csv](../data/articles.csv) through
[`repository.py`](../src/knowledge_hub/repository.py). The CSV header must match
the `Article` dataclass exactly. A second representation,
[article.schema.json](../schemas/article.schema.json), defines the same six
properties and rejects undeclared fields.

A schema or CSV drift therefore breaks compilation before a Fourfold snapshot
can be published.
