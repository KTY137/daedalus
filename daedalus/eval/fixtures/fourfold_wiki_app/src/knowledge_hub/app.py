from __future__ import annotations

import argparse
from pathlib import Path

from .repository import ArticleRepository
from .search import search_articles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse the Fourfold reference wiki")
    parser.add_argument("--data", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--show")
    group.add_argument("--search")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = ArticleRepository(args.data)
    if args.list:
        for article in repository.published():
            print(f"{article.slug}\t{article.title}")
        return 0
    if args.show:
        article = repository.by_slug(args.show)
        print(article.title)
        print(article.body)
        return 0
    for article in search_articles(repository.published(), args.search or ""):
        print(f"{article.slug}\t{article.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
