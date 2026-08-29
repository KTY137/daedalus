from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:90]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    text = read(path)
    out, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: regex matched {count}: {pattern[:100]!r}")
    write(path, out)


LLM_CLIENT = r'''"""Vendor-neutral language-model client policy for Ikarus.

Iron Plan: ALIGNED — this is the vendor-neutral runtime contract required by
master-plan §7.  It deliberately owns *selection and call policy*, not effects:
the actual transports remain in :mod:`daedalus.ikarus_os`, behind the existing
provider effect boundary.  A model is a speaking/proposal surface; selecting it
never grants file, tool, policy, evaluator, or promotion authority.

The client makes the chat default useful: ``auto`` means "pick an available
LLM", never "silently fall back to deterministic help text".  The deterministic
index remains an explicit runtime because status/distill are measurements, not
language-model work.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


_PROVIDER_ALIASES = {
    "claude": "claude_code_cli",
    "claude_cli": "claude_code_cli",
    "claude_code_cli": "claude_code_cli",
    "codex": "codex_cli",
    "codex_cli": "codex_cli",
    "ollama": "ollama_http",
    "ollama_http": "ollama_http",
    "ollama_cli": "ollama_cli",
    "deepseek": "deepseek",
    "deterministic": "deterministic",
}

# Primary frontier voice first, then local/free, then the other connected
# runtimes. Operators can change this without changing code.
_DEFAULT_ORDER = ("claude_code_cli", "ollama_http", "codex_cli", "ollama_cli", "deepseek")
_RUNTIME_STATUS_ID = {
    "claude_code_cli": "claude_code_cli",
    "codex_cli": "codex_cli",
    "ollama_http": "ollama_http",
    "ollama_cli": "ollama_cli",
}


def normalize_provider(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("", "auto", "none"):
        return "auto"
    return _PROVIDER_ALIASES.get(raw, raw)


def _bounded_float(value: str | None, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _bounded_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


@dataclass(frozen=True)
class LLMToolCall:
    """A model-proposed tool call. It is data, never permission to execute."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass(frozen=True)
class LLMRequest:
    """Provider-neutral request contract.

    ``tools`` describes callable shapes for providers that support structured
    tool use. Ikarus Voice currently sends an empty tuple; effectful work stays
    on the Hand/supervisor path and therefore cannot be smuggled through chat.
    """

    message: str
    project: str | None = None
    model: str | None = None
    effort: str | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    conversation_id: str | None = None


@dataclass(frozen=True)
class LLMSelection:
    provider: str | None
    requested: str
    auto_selected: bool
    timeout_s: float
    max_attempts: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "requested": self.requested,
            "auto_selected": self.auto_selected,
            "timeout_s": self.timeout_s,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    attempts: int = 1


class LLMUnavailable(RuntimeError):
    pass


StatusProbe = Callable[[str], Mapping[str, Any]]


class IkarusLLMClient:
    """Selection/configuration seam shared by blocking and streaming chat.

    Transport is intentionally injected/owned elsewhere. That keeps the one
    existing effect boundary authoritative while still centralising model
    choice, timeout and retry policy here.
    """

    def __init__(self, *, environ: Mapping[str, str] | None = None,
                 status_probe: StatusProbe | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self._status_probe = status_probe

    @property
    def timeout_s(self) -> float:
        return _bounded_float(self.environ.get("DAEDALUS_IKARUS_TIMEOUT_S"), 150.0, 10.0, 600.0)

    @property
    def max_attempts(self) -> int:
        # No hidden paid retries by default. Operators can opt into at most two
        # retries; every transport attempt still crosses the budget boundary.
        retries = _bounded_int(self.environ.get("DAEDALUS_IKARUS_RETRIES"), 0, 0, 2)
        return 1 + retries

    def _order(self) -> tuple[str, ...]:
        configured = self.environ.get("DAEDALUS_IKARUS_PROVIDER_ORDER", "")
        if not configured.strip():
            return _DEFAULT_ORDER
        values = tuple(normalize_provider(v) for v in configured.split(",") if v.strip())
        return tuple(v for v in values if v not in ("auto", "deterministic")) or _DEFAULT_ORDER

    def _probe(self, provider: str) -> Mapping[str, Any]:
        if provider == "deepseek":
            return {"available": bool(str(self.environ.get("DEEPSEEK_API_KEY", "")).strip())}
        runtime_id = _RUNTIME_STATUS_ID.get(provider)
        if runtime_id is None:
            return {"available": False, "last_error": "not a wired Ikarus voice runtime"}
        if self._status_probe is not None:
            return self._status_probe(runtime_id)
        try:
            from .runtime_registry import cached_runtime_status

            return cached_runtime_status(runtime_id)
        except Exception as exc:  # a failed probe is not an available model
            return {"available": False, "last_error": str(exc)}

    def resolve(self, requested: str | None = None) -> LLMSelection:
        requested_norm = normalize_provider(requested)
        env_default = normalize_provider(self.environ.get("DAEDALUS_IKARUS_PROVIDER"))

        # A user explicitly selecting the local index is allowed. Automatic
        # selection never lands here.
        if requested_norm == "deterministic":
            return LLMSelection("deterministic", requested_norm, False,
                                self.timeout_s, 1, "explicit local-index selection")

        explicit = requested_norm if requested_norm != "auto" else env_default
        if explicit not in ("auto", "deterministic"):
            if explicit not in _PROVIDER_ALIASES.values():
                return LLMSelection(None, explicit, requested_norm == "auto",
                                    self.timeout_s, self.max_attempts,
                                    f"unknown Ikarus LLM provider {explicit!r}")
            return LLMSelection(explicit, requested_norm, requested_norm == "auto",
                                self.timeout_s, self.max_attempts,
                                "configured provider" if requested_norm == "auto" else "explicit provider")

        failures: list[str] = []
        for candidate in self._order():
            row = self._probe(candidate)
            if bool(row.get("available")):
                return LLMSelection(candidate, requested_norm, True,
                                    self.timeout_s, self.max_attempts,
                                    "first available provider in automatic preference order")
            failures.append(f"{candidate}: {row.get('last_error') or row.get('auth_status') or 'unavailable'}")
        detail = "; ".join(failures[:5])
        return LLMSelection(None, requested_norm, True, self.timeout_s,
                            self.max_attempts,
                            "no configured LLM runtime is available" + (f" ({detail})" if detail else ""))

    def complete(self, request: LLMRequest,
                 invoke: Callable[[str, LLMRequest, float], LLMResponse | str | None],
                 requested: str | None = None) -> LLMResponse:
        """Run a blocking transport under this client's retry policy.

        This method does not open sockets or spawn processes; ``invoke`` is the
        effect-guarded adapter supplied by the caller.
        """
        selection = self.resolve(requested)
        if not selection.provider or selection.provider == "deterministic":
            raise LLMUnavailable(selection.reason)
        last_error = "model returned no text"
        for attempt in range(1, selection.max_attempts + 1):
            try:
                result = invoke(selection.provider, request, selection.timeout_s)
                if isinstance(result, LLMResponse) and result.text.strip():
                    return LLMResponse(result.text, result.provider, result.model,
                                       result.tool_calls, attempts=attempt)
                if isinstance(result, str) and result.strip():
                    return LLMResponse(result.strip(), selection.provider,
                                       request.model, attempts=attempt)
            except Exception as exc:  # caller still owns the typed provider error
                last_error = f"{type(exc).__name__}: {exc}"
        raise LLMUnavailable(f"{selection.provider} produced no usable response after "
                             f"{selection.max_attempts} attempt(s): {last_error}")
'''

MARKDOWN_MESSAGE = r'''import { useMemo, useState, type ReactNode } from 'react';

interface MarkdownMessageProps {
  text: string;
  streaming?: boolean;
}

function safeHref(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** Small, dependency-free Markdown renderer for model output.
 *
 * It intentionally supports the conversational subset Ikarus emits: headings,
 * paragraphs, ordered/unordered lists, quotes, fenced code, inline code,
 * emphasis and http(s) links. React owns escaping, so model text never becomes
 * HTML and a Markdown feature cannot turn into an XSS surface.
 */
function inline(text: string): ReactNode[] {
  const token = /(https?:\/\/[^\s<]+)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*/g;
  const out: ReactNode[] = [];
  let at = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = token.exec(text)) !== null) {
    if (match.index > at) out.push(text.slice(at, match.index));
    if (match[1]) {
      const href = safeHref(match[1]);
      out.push(href ? <a key={key++} href={href} target="_blank" rel="noreferrer">{match[1]}</a> : match[1]);
    } else if (match[2]) {
      out.push(<code key={key++}>{match[2]}</code>);
    } else if (match[3] || match[4]) {
      out.push(<strong key={key++}>{inline(match[3] || match[4])}</strong>);
    } else if (match[5]) {
      out.push(<em key={key++}>{inline(match[5])}</em>);
    }
    at = match.index + match[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="md-codeblock">
      <div className="md-codebar">
        <span>{language || 'code'}</span>
        <button type="button" onClick={() => void copy()} aria-label="Code kopieren">{copied ? 'Kopiert' : 'Kopieren'}</button>
      </div>
      <pre><code className={language ? `language-${language}` : undefined}>{code}</code></pre>
    </div>
  );
}

type Block =
  | { kind: 'code'; language: string; value: string }
  | { kind: 'text'; value: string };

function splitFences(text: string): Block[] {
  const lines = text.split('\n');
  const blocks: Block[] = [];
  let plain: string[] = [];
  let code: string[] = [];
  let language = '';
  let fenced = false;
  const flushPlain = () => {
    if (plain.length) blocks.push({ kind: 'text', value: plain.join('\n') });
    plain = [];
  };
  const flushCode = () => {
    blocks.push({ kind: 'code', language, value: code.join('\n') });
    code = [];
    language = '';
  };
  for (const line of lines) {
    const fence = /^```\s*([\w.+-]*)\s*$/.exec(line);
    if (fence) {
      if (fenced) {
        flushCode();
        fenced = false;
      } else {
        flushPlain();
        language = fence[1] || '';
        fenced = true;
      }
      continue;
    }
    (fenced ? code : plain).push(line);
  }
  if (fenced) flushCode();
  flushPlain();
  return blocks;
}

function TextBlocks({ text }: { text: string }) {
  const lines = text.split('\n');
  const nodes: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const Tag = `h${Math.min(4, heading[1].length + 1)}` as keyof JSX.IntrinsicElements;
      nodes.push(<Tag key={key++}>{inline(heading[2])}</Tag>);
      i += 1; continue;
    }
    if (/^>\s?/.test(line)) {
      const quoted: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quoted.push(lines[i++].replace(/^>\s?/, ''));
      nodes.push(<blockquote key={key++}>{quoted.map((q, n) => <p key={n}>{inline(q)}</p>)}</blockquote>);
      continue;
    }
    const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (unordered) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^\s*[-*+]\s+(.+)$/.exec(lines[i]);
        if (!m) break;
        items.push(m[1]); i += 1;
      }
      nodes.push(<ul key={key++}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ul>);
      continue;
    }
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (ordered) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^\s*\d+[.)]\s+(.+)$/.exec(lines[i]);
        if (!m) break;
        items.push(m[1]); i += 1;
      }
      nodes.push(<ol key={key++}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ol>);
      continue;
    }
    const paragraph: string[] = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s+|^>\s?|^\s*[-*+]\s+|^\s*\d+[.)]\s+/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    nodes.push(<p key={key++}>{inline(paragraph.join('\n'))}</p>);
  }
  return <>{nodes}</>;
}

export function MarkdownMessage({ text, streaming = false }: MarkdownMessageProps) {
  const blocks = useMemo(() => splitFences(text), [text]);
  if (!text && streaming) {
    return <div className="turn-text markdown thinking" role="status"><span>Ikarus denkt</span><i /><i /><i /></div>;
  }
  return (
    <div className="turn-text markdown">
      {blocks.map((block, i) => block.kind === 'code'
        ? <CodeBlock key={i} language={block.language} code={block.value} />
        : <TextBlocks key={i} text={block.value} />)}
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  );
}
'''

LLM_TESTS = r'''from __future__ import annotations

from daedalus.llm_client import IkarusLLMClient, LLMRequest, LLMResponse, LLMUnavailable


def test_auto_selects_first_available_model_not_deterministic():
    seen = []
    def probe(runtime_id):
        seen.append(runtime_id)
        return {"available": runtime_id == "ollama_http", "last_error": "off"}
    client = IkarusLLMClient(environ={}, status_probe=probe)
    selection = client.resolve(None)
    assert selection.provider == "ollama_http"
    assert selection.auto_selected is True
    assert "deterministic" not in seen


def test_explicit_deterministic_is_still_possible_but_never_auto():
    client = IkarusLLMClient(environ={}, status_probe=lambda _: {"available": False})
    explicit = client.resolve("deterministic")
    automatic = client.resolve(None)
    assert explicit.provider == "deterministic"
    assert explicit.auto_selected is False
    assert automatic.provider is None


def test_environment_can_choose_voice_without_code_change():
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "codex", "DAEDALUS_IKARUS_TIMEOUT_S": "44"},
        status_probe=lambda _: {"available": False},
    )
    selection = client.resolve(None)
    assert selection.provider == "codex_cli"
    assert selection.timeout_s == 44
    assert selection.auto_selected is True


def test_complete_retries_only_when_operator_opted_in():
    calls = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude", "DAEDALUS_IKARUS_RETRIES": "1"},
        status_probe=lambda _: {"available": True},
    )
    def invoke(provider, request, timeout):
        calls.append((provider, timeout))
        if len(calls) == 1:
            return None
        return LLMResponse("ok", provider, "model")
    response = client.complete(LLMRequest("hello"), invoke)
    assert response.text == "ok"
    assert response.attempts == 2
    assert len(calls) == 2


def test_tool_shapes_are_data_not_implicit_execution():
    request = LLMRequest("plan", tools=({"name": "queue_task"},))
    called = []
    client = IkarusLLMClient(environ={"DAEDALUS_IKARUS_PROVIDER": "claude"})
    response = client.complete(request, lambda provider, req, timeout: called.append(req.tools) or "proposal")
    assert response.text == "proposal"
    assert called == [({"name": "queue_task"},)]
'''

INTEGRATION_TESTS = r'''from __future__ import annotations

from daedalus import ikarus_os
from daedalus.llm_client import LLMSelection


class _FakeClient:
    def __init__(self, provider="claude_code_cli"):
        self.provider = provider
    def resolve(self, requested=None):
        return LLMSelection(self.provider, "auto", True, 33.0, 1, "test")


def test_chat_auto_route_uses_llm_client_and_records_resolved_provider(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient())
    seen = {}
    def fake_llm(provider, message, model=None, effort=None, project=None, conversation_id=None, timeout_s=None):
        seen.update(provider=provider, conversation_id=conversation_id, timeout_s=timeout_s)
        return "hello from model", "claude-test", ikarus_os._EMPTY_CTX
    monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
    out = ikarus_os._chat("project", "hello", None, conversation_id="conv_test")
    assert out["assistant"] == "hello from model"
    assert out["provider_used"] == "claude_code_cli"
    assert out["model_used"] == "claude-test"
    assert seen == {"provider": "claude_code_cli", "conversation_id": "conv_test", "timeout_s": 33.0}


def test_chat_without_available_llm_is_loud_not_fake_deterministic(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient(provider=None))
    out = ikarus_os._chat("project", "hello", None)
    assert out["intent"] == "error"
    assert out["provider_used"] == "unavailable"
    assert "LLM" in out["assistant"]
'''

DOC = r'''# Ikarus conversational LLM client — 2026-08-30

**Iron Plan: ALIGNED. Iron Gate: Gate 1.** This change implements the vendor-neutral runtime direction already required by `IKARUS_ARIADNE_MASTER_PLAN.md` §7; it does not amend the plan.

## Decision

Free-form Ikarus chat now resolves through `daedalus.llm_client.IkarusLLMClient`. `auto` means **an available language model**, not the deterministic help layer. The default preference order is Claude Code CLI → Ollama HTTP → Codex CLI → Ollama CLI → DeepSeek and is configurable with `DAEDALUS_IKARUS_PROVIDER_ORDER`; `DAEDALUS_IKARUS_PROVIDER` pins a default. The local deterministic index remains explicitly selectable and continues to own measured `status`, `distill`, and other deterministic routes.

The client owns provider normalization, automatic selection, model-call timeout (`DAEDALUS_IKARUS_TIMEOUT_S`, 150 s default), and bounded retry policy (`DAEDALUS_IKARUS_RETRIES`, zero by default, maximum two retries). It also defines provider-neutral request/response/tool-call shapes. Voice tool calls are **descriptions only**: Ikarus Voice is still text-only, while effectful work remains on the Hand/supervisor path behind policy, confirmation, budget, and evidence boundaries.

## Why the transport stays in `ikarus_os.py`

The repository already has a canonical `ikarus_os.provider_call` effect boundary around Ollama/DeepSeek sockets and Claude/Codex process spawning. Moving transport into a second client implementation would either duplicate that boundary or bypass it. The LLM client therefore supplies policy to the existing guarded adapters. This is consolidation rather than a second execution subsystem.

## Conversation behavior

A durable `conversation_id` now feeds the bounded recent transcript (`conversation.recent_turns_context`) into subsequent model calls, in addition to the existing gated project slice. This makes follow-up questions contextual while preserving the master-plan rule that chat is an interface, not orchestration state. Conversation rows remain facts on the canonical spine; no new chat database is introduced.

## Frontend contract

The cockpit renders model Markdown as React nodes (never injected HTML), including fenced code blocks, lists, headings, quotes, links, inline code and emphasis. Code blocks and completed model responses have copy actions. Empty streaming turns show an explicit thinking state. The runtime picker describes automatic model selection instead of presenting the deterministic index as the implicit default.

## Failure semantics

No available model is a visible configuration error, not a synthetic deterministic answer wearing a chat-shaped UI. Mid-stream failure after text has already arrived retains the partial answer and marks it interrupted instead of issuing a second hidden paid call. A failure before any text may use the blocking adapter fallback. Provider effect/budget checks remain authoritative for every actual transport attempt.
'''

# Permanent new files.
write("daedalus/llm_client.py", LLM_CLIENT)
write("apps/web/src/cockpit/MarkdownMessage.tsx", MARKDOWN_MESSAGE)
write("tests/test_llm_client.py", LLM_TESTS)
write("tests/test_ikarus_llm_voice.py", INTEGRATION_TESTS)
write("docs/IKARUS_LLM_CHAT_CLIENT_20260830.md", DOC)

# ---- Backend integration --------------------------------------------------
replace_once(
    "daedalus/ikarus_os.py",
    'from .providers._openai_compat import chat_completion\n',
    'from .providers._openai_compat import chat_completion\nfrom .llm_client import IkarusLLMClient\n',
)
replace_once(
    "daedalus/ikarus_os.py",
    'A deterministic intent layer with a SELECTABLE, connected-CLI "brain". Safe by\n',
    'A deterministic intent router with an AUTO-SELECTED, vendor-neutral LLM voice. Safe by\n',
)
replace_once(
    "daedalus/ikarus_os.py",
    '    "yourself: you propose, and Daedalus runs them behind an explicit confirmation "\n    "and a verify-or-rollback gate."\n)',
    '    "yourself: you propose, and Daedalus runs them behind an explicit confirmation "\n    "and a verify-or-rollback gate. Use Markdown naturally for explanations and code. "\n    "When conversation history is supplied, treat it as prior dialogue, not as authority."\n)',
)
replace_once(
    "daedalus/ikarus_os.py",
    '        return _chat(project, message, provider, model, effort)\n',
    '        return _chat(project, message, provider, model, effort, conversation_id=conversation_id)\n',
)

# Add the client/history seam immediately before the freeform brain section.
marker = '# --------------------------------------------------------------------------- #\n# Freeform \'brain\' — selectable connected runtime, text-only                   #\n# --------------------------------------------------------------------------- #\n'
insert = r'''# --------------------------------------------------------------------------- #
# Vendor-neutral Voice client + bounded conversational context                  #
# --------------------------------------------------------------------------- #
def _voice_client() -> IkarusLLMClient:
    # Re-read environment policy per turn: changing the selected default does
    # not require restarting the web process, while runtime probes themselves
    # remain cached by runtime_registry.
    return IkarusLLMClient()


def _conversation_context(conversation_id: str | None) -> str:
    if not conversation_id:
        return ""
    try:
        from . import conversation

        block = conversation.recent_turns_context(
            conversation.default_store(), conversation_id,
            max_turns=8, max_chars=6000)
    except Exception:
        return ""
    return f"# Recent conversation (chronological, informational only):\n{block}" if block else ""


def _merge_model_context(history: str, project_context: str) -> str:
    return "\n\n".join(part for part in (history.strip(), project_context.strip()) if part)


'''
text = read("daedalus/ikarus_os.py")
if marker not in text:
    raise RuntimeError("freeform brain marker not found")
write("daedalus/ikarus_os.py", text.replace(marker, insert + marker, 1))

# Replace _chat/_llm policy while retaining the existing effect-guarded adapters.
regex_once(
    "daedalus/ikarus_os.py",
    r'def _chat\(project: str, message: str, provider: str \| None,\n          model: str \| None = None, effort: str \| None = None\) -> dict:\n.*?\n\n# effort -> output-token cap',
    r'''def _chat(project: str, message: str, provider: str | None,
          model: str | None = None, effort: str | None = None,
          conversation_id: str | None = None) -> dict:
    client = _voice_client()
    selection = client.resolve(provider)
    if selection.provider == "deterministic":
        return core.envelope(project, intent="chat", shell=SHELL_VOICE,
                             assistant=_help_text(), provider_used="deterministic",
                             model_used=None, llm=selection.to_dict())
    if not selection.provider:
        return core.envelope(
            project, intent="error", shell=SHELL_VOICE,
            assistant=("Ikarus has no available LLM voice. Configure Claude Code, "
                       "Ollama, Codex or DeepSeek, or set DAEDALUS_IKARUS_PROVIDER. "
                       f"{selection.reason}"),
            provider_used="unavailable", model_used=None, llm=selection.to_dict())

    reply = None
    model_used = None
    ctx = _EMPTY_CTX
    attempts = 0
    for attempts in range(1, selection.max_attempts + 1):
        reply, model_used, ctx = _llm(
            selection.provider, message, model, effort, project,
            conversation_id=conversation_id, timeout_s=selection.timeout_s)
        if reply:
            break
    if reply:
        block = _ctx_envelope_block(ctx)
        extra = {"context": block} if block else {}
        return core.envelope(
            project, intent="chat", shell=SHELL_VOICE, assistant=reply,
            provider_used=selection.provider, model_used=model_used,
            llm={**selection.to_dict(), "attempts": attempts}, **extra)
    return core.envelope(
        project, intent="error", shell=SHELL_VOICE,
        assistant=(f"{selection.provider} did not return a usable answer after "
                   f"{attempts} attempt(s). Nothing was silently replaced with a "
                   "deterministic chat answer."),
        provider_used=selection.provider, model_used=model_used,
        llm={**selection.to_dict(), "attempts": attempts})


# effort -> output-token cap''',
    flags=re.S,
)
replace_once(
    "daedalus/ikarus_os.py",
    '_EFFORT_CAP = {"low": 300, "medium": 700, "high": 1400}\n',
    '_EFFORT_CAP = {"low": 700, "medium": 1400, "high": 2800}\n',
)
replace_once(
    "daedalus/ikarus_os.py",
    'def _llm(provider: str | None, message: str, model: str | None = None,\n         effort: str | None = None,\n         project: str | None = None) -> tuple[str | None, str | None, _Ctx]:',
    'def _llm(provider: str | None, message: str, model: str | None = None,\n         effort: str | None = None,\n         project: str | None = None, *, conversation_id: str | None = None,\n         timeout_s: float = 150.0) -> tuple[str | None, str | None, _Ctx]:',
)
# Inject history merging in each provider branch by replacing the transport calls.
replace_once("daedalus/ikarus_os.py",
             '        return _ollama(message, mdl, effort, ctx.text), mdl, ctx\n',
             '        context = _merge_model_context(_conversation_context(conversation_id), ctx.text)\n        return _ollama(message, mdl, effort, context, timeout_s=timeout_s), mdl, ctx\n')
replace_once("daedalus/ikarus_os.py",
             '        return _claude(message, effort, model, ctx.text), (model or "claude"), ctx\n',
             '        context = _merge_model_context(_conversation_context(conversation_id), ctx.text)\n        return _claude(message, effort, model, context, timeout_s=timeout_s), (model or "claude"), ctx\n')
replace_once("daedalus/ikarus_os.py",
             '        return _deepseek(message, mdl, effort, ctx.text), mdl, ctx\n',
             '        context = _merge_model_context(_conversation_context(conversation_id), ctx.text)\n        return _deepseek(message, mdl, effort, context, timeout_s=timeout_s), mdl, ctx\n')
replace_once("daedalus/ikarus_os.py",
             '        return _codex(message, effort, mdl, ctx.text), (mdl or "codex"), ctx\n',
             '        context = _merge_model_context(_conversation_context(conversation_id), ctx.text)\n        return _codex(message, effort, mdl, context, timeout_s=timeout_s), (mdl or "codex"), ctx\n')

# Configurable transport timeout, without moving any effect boundary.
replace_once("daedalus/ikarus_os.py",
             'def _ollama(message: str, model: str, effort: str | None,\n            context: str = "") -> str | None:',
             'def _ollama(message: str, model: str, effort: str | None,\n            context: str = "", *, timeout_s: float = 150.0) -> str | None:')
replace_once("daedalus/ikarus_os.py", '            timeout_s=120, extra={"max_tokens": _effort_cap(effort)},\n', '            timeout_s=timeout_s, extra={"max_tokens": _effort_cap(effort)},\n')
replace_once("daedalus/ikarus_os.py",
             'def _deepseek(message: str, model: str, effort: str | None,\n              context: str = "") -> str | None:',
             'def _deepseek(message: str, model: str, effort: str | None,\n              context: str = "", *, timeout_s: float = 150.0) -> str | None:')
# second blocking timeout=120 occurrence (DeepSeek)
text = read("daedalus/ikarus_os.py")
old = '            timeout_s=120, extra={"max_tokens": _effort_cap(effort)},\n'
if text.count(old) != 1:
    raise RuntimeError(f"deepseek timeout occurrence count {text.count(old)}")
write("daedalus/ikarus_os.py", text.replace(old, '            timeout_s=timeout_s, extra={"max_tokens": _effort_cap(effort)},\n', 1))
replace_once("daedalus/ikarus_os.py",
             'def _claude(message: str, effort: str | None = None, model: str | None = None,\n            context: str = "") -> str | None:',
             'def _claude(message: str, effort: str | None = None, model: str | None = None,\n            context: str = "", *, timeout_s: float = 150.0) -> str | None:')
replace_once("daedalus/ikarus_os.py", '            encoding="utf-8", errors="replace", timeout=150,\n', '            encoding="utf-8", errors="replace", timeout=timeout_s,\n')
replace_once("daedalus/ikarus_os.py",
             'def _codex(message: str, effort: str | None = None, model: str | None = None,\n           context: str = "") -> str | None:',
             'def _codex(message: str, effort: str | None = None, model: str | None = None,\n           context: str = "", *, timeout_s: float = 150.0) -> str | None:')
replace_once("daedalus/ikarus_os.py", '                errors="replace", timeout=150, stdin=subprocess.DEVNULL, check=False,\n', '                errors="replace", timeout=timeout_s, stdin=subprocess.DEVNULL, check=False,\n')

# Streaming: resolve automatic voice once, share timeout and history.
replace_once(
    "daedalus/ikarus_os.py",
    '    p = (provider or "").lower()\n    streamer = None\n    model_used = None\n    ctx = _EMPTY_CTX\n',
    '    selection = _voice_client().resolve(provider)\n    p = selection.provider or ""\n    streamer = None\n    model_used = None\n    ctx = _EMPTY_CTX\n    history = _conversation_context(conversation_id)\n',
)
replace_once("daedalus/ikarus_os.py",
             '        streamer = _ollama_stream(message, model_used, effort, ctx.text)\n',
             '        streamer = _ollama_stream(message, model_used, effort, _merge_model_context(history, ctx.text), timeout_s=selection.timeout_s)\n')
replace_once("daedalus/ikarus_os.py",
             '        streamer = _claude_stream(message, effort, model, ctx.text)\n',
             '        streamer = _claude_stream(message, effort, model, _merge_model_context(history, ctx.text), timeout_s=selection.timeout_s)\n')
replace_once("daedalus/ikarus_os.py",
             '        streamer = _deepseek_stream(message, model_used, effort, ctx.text)\n',
             '        streamer = _deepseek_stream(message, model_used, effort, _merge_model_context(history, ctx.text), timeout_s=selection.timeout_s)\n')
replace_once(
    "daedalus/ikarus_os.py",
    '    yield "start", {"intent": "chat",\n                    "shell": SHELL_VOICE,\n                    "provider_used": p or "deterministic",\n                    "model_used": model_used}\n',
    '    yield "start", {"intent": "chat",\n                    "shell": SHELL_VOICE,\n                    "provider_used": p or "unavailable",\n                    "model_used": model_used,\n                    "auto_selected": selection.auto_selected}\n',
)
replace_once(
    "daedalus/ikarus_os.py",
    '        # No streaming brain selected (deterministic/auto, or an unwired slot\n        # like codex/gemini) — identical outcome to ask().\n        yield "final", _reconcile_final(\n            route, ask(project, message, provider, model, effort,\n                       intent=intent, act=act))\n        return\n',
    '        # Codex currently has no verified token-frame parser; use the same\n        # resolved voice through the blocking adapter. This stays inside the\n        # already-authorised streaming turn and preserves conversation context.\n        yield "final", _reconcile_final(\n            route, _chat(project, message, p or provider, model, effort,\n                         conversation_id=conversation_id))\n        return\n',
)
# Preserve partial output on mid-stream failure; do not silently issue a second paid call.
replace_once(
    "daedalus/ikarus_os.py",
    '    if failed or not text:\n        # Nothing usable streamed -> blocking fallback keeps the chat alive.\n        yield "final", _reconcile_final(\n            route, ask(project, message, provider, model, effort,\n                       intent=intent, act=act))\n        return\n\n    block = _ctx_envelope_block(ctx)\n',
    '    if failed and text:\n        block = _ctx_envelope_block(ctx)\n        extra = {"context": block} if block else {}\n        yield "final", _reconcile_final(route, core.envelope(\n            project, intent="chat", shell=SHELL_VOICE, assistant=text,\n            provider_used=p, model_used=model_used, stream_interrupted=True, **extra))\n        return\n    if not text:\n        yield "final", _reconcile_final(\n            route, _chat(project, message, p or provider, model, effort,\n                         conversation_id=conversation_id))\n        return\n\n    block = _ctx_envelope_block(ctx)\n',
)
replace_once("daedalus/ikarus_os.py",
             'def _ollama_stream(message: str, model: str, effort: str | None, context: str = ""):',
             'def _ollama_stream(message: str, model: str, effort: str | None, context: str = "", *, timeout_s: float = 150.0):')
replace_once("daedalus/ikarus_os.py", '        timeout_s=120, extra={"max_tokens": _effort_cap(effort)},\n', '        timeout_s=timeout_s, extra={"max_tokens": _effort_cap(effort)},\n')
replace_once("daedalus/ikarus_os.py",
             'def _deepseek_stream(message: str, model: str, effort: str | None, context: str = ""):',
             'def _deepseek_stream(message: str, model: str, effort: str | None, context: str = "", *, timeout_s: float = 150.0):')
replace_once("daedalus/ikarus_os.py", '        api_key=api_key, temperature=0.3, timeout_s=120,\n', '        api_key=api_key, temperature=0.3, timeout_s=timeout_s,\n')
replace_once("daedalus/ikarus_os.py",
             'def _claude_stream(message: str, effort: str | None = None, model: str | None = None,\n                   context: str = ""):',
             'def _claude_stream(message: str, effort: str | None = None, model: str | None = None,\n                   context: str = "", *, timeout_s: float = 150.0):')
replace_once("daedalus/ikarus_os.py", '        deadline = _time.time() + 150\n', '        deadline = _time.time() + timeout_s\n')
replace_once("daedalus/ikarus_os.py",
             '            "Choose a runtime to give me a language brain (local Ollama is free)."\n',
             '            "Automatic chat selects an available language model; the local index remains available for measured answers."\n')

# ---- Frontend -------------------------------------------------------------
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "import { ContextPlan } from './ContextPlan';\n",
    "import { ContextPlan } from './ContextPlan';\nimport { MarkdownMessage } from './MarkdownMessage';\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "    ? `zuletzt ${labelOf(lastRoute) || lastRoute}`\n    : 'Ikarus entscheidet';\n",
    "    ? `zuletzt ${labelOf(lastRoute) || lastRoute}`\n    : 'wählt ein verfügbares Modell';\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "  const [error, setError] = useState('');\n",
    "  const [error, setError] = useState('');\n  const [copiedTurn, setCopiedTurn] = useState<number | null>(null);\n",
)
# Modern renderer replaces the deliberately-minimal inline parser at render time.
old_render = r'''              {t.role === 'you' ? (
                <p className="turn-text">{t.text}</p>
              ) : (
                <div className="turn-text">
                  {t.text.split(/\n{2,}/).map((para, p, all) => (
                    <p key={p}>
                      {piecesIn(para).map((piece, k) => {
                        const body =
                          piece.kind === 'code' ? <code>{piece.value}</code> : <span>{piece.value}</span>;
                        return <span key={k}>{piece.strong ? <b>{body}</b> : body}</span>;
                      })}
                      {t.streaming && p === all.length - 1 && <span className="caret" aria-hidden="true" />}
                    </p>
                  ))}
                </div>
              )}
'''
new_render = r'''              {t.role === 'you' ? (
                <p className="turn-text">{t.text}</p>
              ) : (
                <MarkdownMessage text={t.text} streaming={t.streaming} />
              )}

              {t.role === 'ikarus' && !t.streaming && t.text && (
                <div className="turn-actions" aria-label="Antwortaktionen">
                  <button
                    type="button"
                    onClick={() => {
                      void navigator.clipboard.writeText(t.text).then(() => {
                        setCopiedTurn(i);
                        window.setTimeout(() => setCopiedTurn((current) => (current === i ? null : current)), 1200);
                      });
                    }}
                  >
                    {copiedTurn === i ? 'Kopiert' : 'Antwort kopieren'}
                  </button>
                </div>
              )}
'''
replace_once("apps/web/src/cockpit/Conversation.tsx", old_render, new_render)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    '            <p className="convo-open-note">\n              Antworten aus dem lokalen Index tragen den Stempel GEMESSEN, Antworten eines Modells dessen Namen.\n            </p>\n',
    '            <p className="convo-open-note">\n              Ikarus wählt automatisch ein verfügbares LLM. Gemessene lokale Antworten bleiben klar von Modellantworten getrennt.\n            </p>\n            <div className="convo-suggestions" aria-label="Vorschläge">\n              {[\'Erklär mir die Architektur dieses Projekts.\', \'Wo würdest du als Nächstes refactoren?\', \'Fass den aktuellen Projektzustand zusammen.\'].map((suggestion) => (\n                <button key={suggestion} type="button" onClick={() => setDraft(suggestion)}>{suggestion}</button>\n              ))}\n            </div>\n',
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "          placeholder={busy ? 'Ikarus antwortet …' : 'Frag Ikarus … (Enter sendet, Shift+Enter bricht die Zeile)'}\n",
    "          placeholder={busy ? 'Du kannst schon weiterschreiben …' : 'Nachricht an Ikarus …'}\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    '<div className={empty ? \'convo-scroll empty\' : \'convo-scroll\'} ref={scroller} onScroll={onScroll}>',
    '<div className={empty ? \'convo-scroll empty\' : \'convo-scroll\'} ref={scroller} onScroll={onScroll} role="log" aria-live="polite" aria-busy={busy}>',
)

# Update API contract documentation so frontend/backend agree on omitted provider.
replace_once(
    "apps/web/src/api.ts",
    ' * `claude_code_cli`) or `deterministic`/omitted for the no-LLM default. BYOK —\n',
    ' * `claude_code_cli`) or `deterministic`; omitted means automatic LLM selection. BYOK —\n',
)

CSS = r'''

/* ------------------------------------------------ conversational Markdown */
/* Added 2026-08-30: model output is structured prose, not a pre-wrapped blob. */
.turn.ikarus .markdown { white-space: normal; width: min(100%, 74ch); }
.turn.ikarus .markdown > p { margin: 0; white-space: pre-wrap; }
.turn.ikarus .markdown > p + p,
.turn.ikarus .markdown > * + p { margin-top: 0.85em; }
.turn.ikarus .markdown h2,
.turn.ikarus .markdown h3,
.turn.ikarus .markdown h4,
.turn.ikarus .markdown h5 { margin: 1.15em 0 0.45em; line-height: 1.25; font-family: var(--font-display); }
.turn.ikarus .markdown ul,
.turn.ikarus .markdown ol { margin: 0.65em 0; padding-left: 1.4em; display: grid; gap: 0.35em; }
.turn.ikarus .markdown blockquote { margin: 0.85em 0; padding-left: var(--u3); border-left: 2px solid var(--line); color: var(--ink2); }
.turn.ikarus .markdown blockquote p { margin: 0; }
.turn.ikarus .markdown a { color: var(--accent); text-underline-offset: 0.18em; }
.md-codeblock { width: min(100%, 78ch); margin: 0.9em 0; overflow: hidden; border: 1px solid var(--line); border-radius: max(8px, calc(var(--u2) * 1.25)); background: color-mix(in srgb, var(--ink) 4%, transparent); }
.md-codebar { display: flex; align-items: center; justify-content: space-between; gap: var(--u3); padding: var(--u2) var(--u3); border-bottom: 1px solid var(--line); color: var(--ink3); font-family: var(--font-mono); font-size: var(--fs-xs); }
.md-codebar button,
.turn-actions button,
.convo-suggestions button { border: 0; background: transparent; color: var(--ink2); font: inherit; cursor: pointer; }
.md-codebar button:hover,
.turn-actions button:hover,
.convo-suggestions button:hover { color: var(--ink); }
.md-codeblock pre { margin: 0; padding: var(--u3); overflow: auto; max-width: 100%; white-space: pre; }
.md-codeblock pre code { color: var(--ink); font-size: var(--fs-sm); line-height: 1.55; }
.turn-actions { min-height: 1.5rem; display: flex; align-items: center; gap: var(--u2); opacity: 0.72; }
.turn-actions button { padding: 0; font-size: var(--fs-xs); }
.convo-suggestions { display: flex; flex-wrap: wrap; gap: var(--u2); max-width: 62ch; }
.convo-suggestions button { text-align: left; padding: var(--u2) var(--u3); border: 1px solid var(--line); border-radius: 999px; color: var(--ink2); background: color-mix(in srgb, var(--surface) 72%, transparent); }
.thinking { display: inline-flex; align-items: center; gap: 0.28em; color: var(--ink3) !important; }
.thinking i { width: 0.3em; height: 0.3em; border-radius: 50%; background: currentColor; animation: ikarus-thinking 1.1s ease-in-out infinite; opacity: 0.35; }
.thinking i:nth-of-type(2) { animation-delay: 0.14s; }
.thinking i:nth-of-type(3) { animation-delay: 0.28s; }
@keyframes ikarus-thinking { 50% { transform: translateY(-0.18em); opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .thinking i { animation: none; opacity: 0.7; } }
@media (max-width: 760px) {
  .convo { padding: var(--u2); }
  .convo-bar { gap: var(--u2); }
  .convo-thread code { display: none; }
  .convo-suggestions { display: grid; width: 100%; }
  .convo-suggestions button { border-radius: max(8px, var(--u2)); }
  .md-codeblock { max-width: calc(100vw - 2 * var(--u4)); }
  .brain-menu { max-width: calc(100vw - 2 * var(--u3)); }
}
'''
css_path = "apps/web/src/cockpit/conversation.css"
css = read(css_path)
if "/* ------------------------------------------------ conversational Markdown */" not in css:
    write(css_path, css.rstrip() + CSS + "\n")

print("Ikarus LLM/chat frontend patch applied")
