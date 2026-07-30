---
title: Knowledge layer
type: spec
status: partial
updated: 2026-07-30
---

# Knowledge layer

This vault. Obsidian format on purpose: Obsidian itself is closed and unembeddable,
but plain markdown plus wikilinks plus YAML frontmatter is the de-facto standard, so
the same folder opens in Obsidian and keeps working.

The read side lives in [[code:daedalus/wiki/vault.py]] and
[[code:daedalus/wiki/links.py]]. The write side does not exist yet:
`kairos.gated_writes` is a provider-attempt pipeline, not a write fence, so a human
editor's save would fail silently through it. The path validator is already written
and refuses traversal, NTFS alternate data streams, reserved device names and
symlinks.

Local graph at depth 1, never the global hairball. Backlinks and unlinked mentions.
