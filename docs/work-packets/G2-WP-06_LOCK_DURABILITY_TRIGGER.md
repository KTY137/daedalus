# G2-WP-06 — Durable lifecycle lock records

This temporary staging marker triggers the one-shot branch workflow. The workflow removes itself after applying and verifying the reviewed lock durability patch. This marker remains as the Work Packet note.

Scope: complete partial `os.write` handling and persist lock create/reclaim/remove directory-entry mutations with directory `fsync`.
