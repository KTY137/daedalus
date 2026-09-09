"""Small read-only wiki catalogue used by the Fourfold reference compiler."""

from .models import Article
from .repository import ArticleRepository
from .search import search_articles

__all__ = ["Article", "ArticleRepository", "search_articles"]
