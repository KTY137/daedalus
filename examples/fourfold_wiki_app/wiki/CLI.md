# CLI usage

The entrypoint is [`app.py`](../src/knowledge_hub/app.py).

```text
python -m knowledge_hub.app --data data/articles.csv --list
python -m knowledge_hub.app --data data/articles.csv --show fourfold-overview
python -m knowledge_hub.app --data data/articles.csv --search evidence
```

The command reads [articles.csv](../data/articles.csv) and never mutates it.
