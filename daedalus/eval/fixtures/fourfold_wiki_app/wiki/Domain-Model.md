# Domain model

The canonical in-memory record is the `Article` dataclass in
[`models.py`](../src/knowledge_hub/models.py). It has six fields: `id`, `slug`,
`title`, `body`, `status`, and `tag`.

The durable representation is [articles.csv](../data/articles.csv), while
machine-readable constraints are retained in
[article.schema.json](../schemas/article.schema.json).

The Fourfold compiler verifies each declared field alignment independently. A
matching name in prose is not enough.
