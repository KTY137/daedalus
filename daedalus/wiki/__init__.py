"""wiki — nested Obsidian-format vaults, read-only.

Vault format compatibility is deliberate: Obsidian itself is closed and cannot be
embedded, but plain `.md` + `[[wikilinks]]` + YAML frontmatter is the de-facto
standard, so a user can open the same folder in Obsidian and keep working.

READ-ONLY by construction. The write path needs its own gate list and a Cerberus
review — ``kairos.gated_writes`` is a provider-attempt pipeline, not a write
fence, and wiring a human editor's PUT through it would fail every save silently.
See docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md.
"""
from .vault import (PAGE_SUFFIX, PROJECT_VAULT_DIR, VAULT_VERSION, Page, Vault,
                    discover_pages, discover_vaults, page_tree, parse_frontmatter,
                    read_page, vault_rel)
from .links import (CODE, DOC, LINKS_VERSION, TYPE, VAULT, LinkIndex, WikiLink,
                    backlinks, build_index, extract_wikilinks, local_graph,
                    unlinked_mentions)

__all__ = ["Vault", "Page", "vault_rel", "read_page", "discover_pages", "discover_vaults",
           "page_tree", "parse_frontmatter", "PAGE_SUFFIX", "PROJECT_VAULT_DIR",
           "VAULT_VERSION", "WikiLink", "LinkIndex", "extract_wikilinks", "build_index",
           "backlinks", "unlinked_mentions", "local_graph", "LINKS_VERSION",
           "DOC", "CODE", "TYPE", "VAULT"]
