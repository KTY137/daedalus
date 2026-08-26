"""wiki -- the knowledge plane: read a vault, and generate one.

Two halves, deliberately separate.

**Read** (``vault``, ``links``): nested Obsidian-format vaults, read-only by
construction. Vault format compatibility is deliberate: Obsidian itself is
closed and cannot be embedded, but plain ``.md`` + ``[[wikilinks]]`` + YAML
frontmatter is the de-facto standard, so a user can open the same folder in
Obsidian and keep working. The write path needs its own gate list and a
Cerberus review -- ``kairos.gated_writes`` is a provider-attempt pipeline, not
a write fence, and wiring a human editor's PUT through it would fail every save
silently. See docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md.

**Generate** (``plan``, ``verify``): the deterministic halves of automatic wiki
generation. ``plan`` surveys a tree and partitions it into topic buckets with
dispatchable task prompts; ``verify`` decides whether the resulting pages are
true about that tree. Neither calls a model, touches the network, or writes
outside its declared output -- the effectful half (fan out, search, write
pages) is a separate step so spend, egress and write roots stay at one
boundary. They are imported as submodules, not re-exported here, because both
carry a ``main`` and a tree walk that package import should not pay for.
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
