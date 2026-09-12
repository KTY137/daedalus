"""Ikarus kitchen: the Waiter takes orders, the Chef runs the Daedalus kitchen.

Two Ikarus roles, one kernel:

* **Waiter** (``waiter.py``) -- the conversational front. It recognises an
  order in free text ("bau mir eine App", "verbessere diese App", "füttere
  Ariadne mit <repo>"), answers immediately, and hands the order to the Chef.
  It never builds anything itself.
* **Chef** (``chef.py``) -- the orchestrator. It runs one order through the
  kitchen: Grey Matter retrieval, builder agents (Claude Code / Codex CLI),
  toolchain checks, bounded repair, content-addressed candidate identity,
  an evidence packet, and a NOMINATION. It never merges and never promotes.
* **Grey Matter** (``greymatter.py``) -- the latent atlas over ingested
  repositories: four-plane Node Cards, deterministic embeddings, a relation
  tensor projection and verified/unverified cross-plane binding proposals.

Owner decision 2026-09-12: containment of the builder agents is deferred; the
kitchen states this in every evidence packet instead of claiming isolation.
Invariant 5 stays: every result is a nominated candidate awaiting owner
approval, with ``automatic_promotion`` always ``False``.
"""
from __future__ import annotations

from .orders import Order, parse_order
from .waiter import maybe_serve, order_status, place_order

__all__ = ["Order", "parse_order", "maybe_serve", "order_status", "place_order"]
