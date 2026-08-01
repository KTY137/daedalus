# Operations

The reference application is read-only. Operators update
[articles.csv](../data/articles.csv), validate it against
[article.schema.json](../schemas/article.schema.json), run the application, and
then rebuild the Fourfold snapshot.

Persistence behavior is centralized in
[`repository.py`](../src/knowledge_hub/repository.py). A failed header check is a
hard error rather than a best-effort import.
