from __future__ import annotations

from collections.abc import Iterable

from .models import Article


def search_articles(articles: Iterable[Article], query: str) -> tuple[Article, ...]:
    """Case-insensitive search over title, body, slug, and tag."""

    needle = query.strip().casefold()
    if not needle:
        return tuple(articles)
    matches = []
    for article in articles:
        haystack = " ".join(
            (article.title, article.body, article.slug, article.tag)
        ).casefold()
        if needle in haystack:
            matches.append(article)
    return tuple(sorted(matches, key=lambda article: article.slug))
