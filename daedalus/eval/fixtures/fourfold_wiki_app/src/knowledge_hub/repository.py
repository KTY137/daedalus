from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import Article


class ArticleRepository:
    """Read-only repository for the reference wiki catalogue."""

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)

    def all(self) -> tuple[Article, ...]:
        with self.csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle)
            required = {"id", "slug", "title", "body", "status", "tag"}
            if rows.fieldnames is None or set(rows.fieldnames) != required:
                raise ValueError("article CSV header does not match the Article contract")
            return tuple(Article(**row) for row in rows)

    def published(self) -> tuple[Article, ...]:
        return tuple(article for article in self.all() if article.status == "published")

    def by_slug(self, slug: str) -> Article:
        for article in self.all():
            if article.slug == slug:
                return article
        raise KeyError(slug)

    def iter_tag(self, tag: str) -> Iterable[Article]:
        return (article for article in self.published() if article.tag == tag)
