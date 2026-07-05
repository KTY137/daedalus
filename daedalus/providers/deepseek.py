from __future__ import annotations

import os
from typing import Any

from ..sensitivity import classify_data, read_inlined_context
from ._openai_compat import ProviderHTTPError, chat_completion
from ._report import MAX_CONTEXT_CHARS, blocked_report, build_prompt, coerce_report, extract_json
from .base import Provider, ProviderCapabilities
from .personas import persona_for

# DeepSeek exposes an OpenAI-compatible endpoint. Per docs/PROVIDERS_RESEARCH.md:
# json_object mode only (no GA strict schema) -> validate-and-retry; and the
# legacy deepseek-chat/reasoner ids deprecate 2026-07-24, so default to v4-flash.
# POLICY: DeepSeek trains on inputs by default and is PRC-hosted -> non-sensitive
# content only (enforced below by classify_data).
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekProvider(Provider):
    """Cheap external lane. READ-ONLY and NON-SENSITIVE ONLY: it may never
    receive denylisted (device/vendor/IP) content, and cannot write."""

    caps = ProviderCapabilities(
        name="deepseek",
        can_write=False,
        local=False,
        trusted_with_ip=False,
        agentic=False,
    )

    def __init__(self) -> None:
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self.model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)

    def available(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int = 300,
        policy: Any | None = None,
    ) -> dict[str, Any]:
        persona = persona_for(self.caps.name, agent.get("name"))
        # Hard egress gate: refuse if the task itself is sensitive.
        verdict = classify_data(paths, extra_text=objective, policy=policy)
        if verdict.sensitive:
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": blocked_report(
                    "Refused: task contains sensitive/proprietary content that must "
                    "not leave the machine. " + "; ".join(verdict.reasons)[:300],
                    "Route this task to Claude or local Ollama.",
                    offending=verdict.offending,
                ),
            }

        context, skipped = read_inlined_context(
            paths, repo_root, MAX_CONTEXT_CHARS, allow_sensitive=False, policy=policy
        )
        system, user = build_prompt(agent, objective, context)
        try:
            kw = dict(base_url=self.base_url, model=model or self.model, system=system,
                      api_key=self.api_key, timeout_s=timeout_s, force_json=True, temperature=0.0)
            raw = chat_completion(user=user, **kw)
            try:
                report = coerce_report(extract_json(raw))
            except ValueError:
                # exactly one deterministic re-ask for valid JSON before escalating
                raw = chat_completion(user=user + "\n\nReturn ONLY the json object, no prose.", **kw)
                report = coerce_report(extract_json(raw))
        except (ProviderHTTPError, ValueError) as exc:
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": blocked_report(
                    f"DeepSeek call failed: {exc}", "Retry or fall back to Claude."
                ),
            }

        report = self._enforce_read_only(report)
        if skipped:
            report["handoff"] = {**report.get("handoff", {}), "skipped_sensitive": skipped}
        return {
            "provider": self.caps.name,
            "persona": persona,
            "agent": agent.get("name"),
            "report": report,
        }
