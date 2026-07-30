"""tools — the capability layer: what tools exist, and what they are cleared for.

Two modules, one seam:
  * ``vet``       — the gate. Static-only, fail-closed inspection of a skill or an
                    MCP server. Returns findings with evidence, never a score.
  * ``inventory`` — the derived list of every skill and MCP server visible from a
                    project, each carrying its verdict.

Neither installs, enables, starts nor routes anything. Provisioning and
capability routing are separate lanes; routing in particular belongs to
``provider_router``, which already owns lane policy.
"""
from .vet import (BLOCK, CLEAR, REVIEW, UNSCANNABLE, Finding, Verdict, VET_VERSION,
                  scan_text, summarise, vet_mcp_server, vet_skill)
from .inventory import INVENTORY_VERSION, ToolRecord, build, render

__all__ = [
    "CLEAR", "REVIEW", "BLOCK", "UNSCANNABLE", "VET_VERSION",
    "Finding", "Verdict", "vet_skill", "vet_mcp_server", "scan_text", "summarise",
    "INVENTORY_VERSION", "ToolRecord", "build", "render",
]
