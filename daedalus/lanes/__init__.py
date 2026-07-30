"""daedalus.lanes -- what every write lane must do, in one place.

A "lane" is a path by which a model's output becomes a file on disk: the local
Ollama lane, the paid DeepSeek lane, the Claude CLI lane. Each one used to carry
its own hand-rolled sequence of guards, and on 2026-07-30 that cost the repo
three modules:

  * two new guards (content substitution, invented first-party imports) went
    into ``providers/deepseek.py`` and, within the same hours, not into
    ``providers/ollama.py``;
  * the external, untrusted, PAID lane was therefore strictly safer than the
    local, free, DEFAULT one, for the two failure modes that had just been
    measured.

Nobody decided that. It is what per-provider copies do when one of them
improves. So the baseline lives here, every lane calls :func:`checks.run_checks`
instead of writing its own sequence, and a lane may ADD checks but may never
skip the baseline.

What deliberately does NOT move here: claims about a specific model. The elision
markers are a statement about what one vendor's model emits when it truncates,
and two lanes must stay free to disagree about that without silently re-tuning
each other's guard. Those arrive as policy; the baseline is shared.
"""
from __future__ import annotations

from .checks import (
    BASELINE,
    BASELINE_POLICY,
    CheckPolicy,
    WriteAttempt,
    imports_resolve,
    no_elision,
    not_substituted,
    not_truncated,
    parses,
    run_checks,
    toplevel_defs,
)
from .graph_brief import GraphBrief, graph_brief, render_brief
from .grounding import ReferenceAudit, audit_references, claim_text, judge

__all__ = [
    "BASELINE",
    "BASELINE_POLICY",
    "CheckPolicy",
    "GraphBrief",
    "ReferenceAudit",
    "WriteAttempt",
    "audit_references",
    "claim_text",
    "graph_brief",
    "judge",
    "imports_resolve",
    "no_elision",
    "not_substituted",
    "not_truncated",
    "parses",
    "render_brief",
    "run_checks",
    "toplevel_defs",
]
