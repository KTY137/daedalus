"""Bounded, advisory Opus/Codex watchdog experiment.

This package is deliberately outside the production runtime.  It can ask
completion-style Council seats to review explicitly selected files, but it has
no checkout-write, patch, Attempt, merge, promotion, or evaluator path.
"""

from .core import (
    CampaignBusy,
    CampaignCorrupt,
    ConfigError,
    ExecutableCodexAdapter,
    SessionProbeResult,
    StructuredClaudeAdapter,
    campaign_status,
    dry_plan,
    fallback_provider,
    load_config,
    parse_claude_json_wrapper,
    run_campaign,
)

__all__ = [
    "CampaignBusy",
    "CampaignCorrupt",
    "ConfigError",
    "ExecutableCodexAdapter",
    "SessionProbeResult",
    "StructuredClaudeAdapter",
    "campaign_status",
    "dry_plan",
    "fallback_provider",
    "load_config",
    "parse_claude_json_wrapper",
    "run_campaign",
]
