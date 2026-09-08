from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    id: str
    slug: str
    title: str
    body: str
    status: str
    tag: str
