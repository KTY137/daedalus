# Fourfold Wiki Reference Application

This bounded application is the first end-to-end Fourfold architecture specimen.
It is intentionally small enough to audit and large enough to exercise all four
planes with real artifacts:

- executable Python CLI and repository code;
- a dataclass-backed type model;
- CSV records plus JSON Schema;
- a linked operational wiki with an ADR.

Run it from this directory:

```bash
PYTHONPATH=src python -m knowledge_hub.app --data data/articles.csv --list
PYTHONPATH=src python -m knowledge_hub.app --data data/articles.csv --search evidence
```

`fourfold.json` declares the bounded file set and semantic claims. The Daedalus
reference compiler does not trust those claims directly: it reproduces each one
from Python ASTs, CSV headers, JSON Schema properties, and Markdown links before
publishing a verified binding. Broken links, missing files, path escape, schema
drift, CSV drift, duplicate claims, or unsupported claims fail closed.
