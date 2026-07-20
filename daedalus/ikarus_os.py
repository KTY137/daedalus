"""ikarus_os — talk to your Agent OS.

A deterministic intent layer with a SELECTABLE, connected-CLI "brain". Safe by
construction:

  * STATUS / DISTILL answers are computed locally — no spend, no egress.
  * ENQUEUE only PROPOSES a confirm-gated task; nothing runs until the UI posts
    the confirmation to /api/queue (which funnels through process_bridge_payload).
  * the LLM brain (whichever runtime you pick — local Ollama, your Claude CLI,
    …) only ever produces TEXT. It never executes an action. BYOK: it uses the
    runtime's own auth; the platform holds no key.

So "hooking Ikarus onto a CLI" adds language understanding without moving the
safety rails: the model advises, Daedalus acts (behind confirmation + the
verify-or-rollback gate).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time as _time
from pathlib import Path

from . import core
from .projects import resolve_repo_root
from .providers._openai_compat import chat_completion

SYSTEM = (
    "You are Ikarus, the assistant inside the Daedalus Agent OS — a local, "
    "bring-your-own-key code-intelligence cockpit that maps a codebase, distills "
    "exactly the relevant slice, and orchestrates the user's own AI coding agents "
    "to work on it. Be concise, concrete and honest. You do NOT execute actions "
    "yourself: you propose, and Daedalus runs them behind an explicit confirmation "
    "and a verify-or-rollback gate."
)

# Runtimes that can currently power the freeform 'brain'. Others (codex, gemini)
# appear in the picker but fall back to the deterministic layer until wired.
_LOCAL = {"ollama", "ollama_http", "ollama_cli"}
_CLAUDE = {"claude", "claude_cli", "claude_code_cli"}


# --------------------------------------------------------------------------- #
# Intent classification (deterministic, keyword rules)                         #
# --------------------------------------------------------------------------- #
def classify(message: str) -> str:
    t = message.lower()
    if any(k in t for k in ("agent network", "squad", "add agent", "team roster", "roles network")):
        return "design"
    if any(k in t for k in ("distill", "duplicat", "clone", "hotspot", "dead code",
                            "tech debt", "complexit", "refactor target", "code health")):
        return "distill"
    if any(k in t for k in ("what's running", "whats running", "status", "queue",
                            "watcher", "health check", "alive", "pending", "in flight")):
        return "status"
    if any(k in t for k in ("build ", "add ", "fix ", "implement", "create ",
                            "write ", "refactor ", "make ", "generate ")):
        return "enqueue"
    return "chat"


def ask(project: str, message: str, provider: str | None = None,
        model: str | None = None, effort: str | None = None) -> dict:
    """Route one chat turn. Always returns a chat-shaped envelope; never raises
    up to the caller for an expected failure. ``effort`` (low/medium/high,
    default low) + ``model`` tune the freeform brain — it's an interface chatbot,
    so keep it cheap by default."""
    message = (message or "").strip()
    if not message:
        return core.envelope(project, intent="chat", assistant="Say the word — I can report status, distill code, propose a task, or design an agent network.", provider_used="deterministic")
    try:
        intent = classify(message)
        if intent == "status":
            return _status(project, message)
        if intent == "distill":
            return _distill(project, message)
        if intent == "design":
            return _design(project, message)
        if intent == "enqueue":
            return _enqueue(project, message)
        return _chat(project, message, provider, model, effort)
    except Exception as exc:  # never 500 the chat on an internal hiccup
        return core.envelope(project, intent="error", assistant=f"I hit a snag: {exc}", provider_used="deterministic")


# --------------------------------------------------------------------------- #
# Deterministic intents (no spend, no egress)                                  #
# --------------------------------------------------------------------------- #
def _status(project: str, message: str) -> dict:
    from .file_bridge import bridge_status

    st = bridge_status(project)
    watcher = (st.get("watcher") or {}).get("state", "unknown")
    reply = (
        f"Queue: {st.get('queue_depth', 0)} pending, {st.get('in_flight', 0)} in flight. "
        f"Watcher: {watcher}. {st.get('unread_count', 0)} unread reports, "
        f"{st.get('reports_total', 0)} total."
    )
    return core.envelope(project, intent="status", assistant=reply, status=st, provider_used="deterministic")


def _distill(project: str, message: str) -> dict:
    from .structcore.index import cached_index
    from .structcore.report import structure_summary
    from .structcore.slice import semantic_slice

    repo_root = resolve_repo_root(None, project)
    idx = cached_index(repo_root)
    target = _extract_target(message, idx)
    if target:
        res = semantic_slice(repo_root, target, idx=idx)
        reply = (
            f"Distilling {res['focus_file']}: {res['reduction_pct']}% smaller — "
            f"{res['slice_tokens']:,} tokens vs {res['whole_repo_tokens']:,} to dump the whole repo. "
            f"Included {res['n_included']} files (the focus plus its dependency/caller neighborhood)."
        )
        res.pop("slice_text", None)
        return core.envelope(project, intent="distill", assistant=reply, distill=res, provider_used="deterministic")

    summ = structure_summary(idx)
    top = summ["clones"][:5]
    fenced = summ["totals"]["safety_fenced"]
    if top:
        lines = ", ".join(f"{c['name']} x{c['count']}" for c in top)
        reply = (
            f"{summ['totals']['unit_clusters']} clone clusters across {len(summ['languages'])} languages "
            f"({fenced} safety-fenced). Top: {lines}. "
            "Name a file (e.g. \"distill gui/motor_panel.py\") and I'll show the token saving."
        )
    else:
        reply = "No clone clusters detected yet. Point me at a file to distill and I'll show the token saving."
    return core.envelope(project, intent="distill", assistant=reply, structure=summ, provider_used="deterministic")


def _extract_target(message: str, idx: dict) -> str | None:
    modules = idx.get("modules", {})
    # a token that looks like a path/file with a known extension
    for tok in re.findall(r"[\w./\\-]+\.\w+", message):
        tok = tok.replace("\\", "/")
        if tok in modules:
            return tok
        hits = [m for m in modules if m.endswith(tok) or m.endswith("/" + tok)]
        if hits:
            return hits[0]
    return None


def _enqueue(project: str, message: str) -> dict:
    objective = message.strip()
    action = {
        "kind": "queue_task",
        "args": {"project": project, "objective": objective, "lane": "local_only"},
        "requires_confirmation": True,
    }
    reply = (
        f"I can queue this on the free local bench (lane local_only — verify-or-rollback, "
        f"zero spend): “{objective[:140]}”. Confirm to run, or tell me to route it to a "
        "frontier lane."
    )
    return core.envelope(project, intent="enqueue", assistant=reply, action=action, provider_used="deterministic")


def _design(project: str, message: str) -> dict:
    from . import ikarus_chat

    res = ikarus_chat.chat(project, message, apply=False)
    res["intent"] = "design"
    res.setdefault("provider_used", "deterministic")
    return res


# --------------------------------------------------------------------------- #
# Freeform 'brain' — selectable connected runtime, text-only                   #
# --------------------------------------------------------------------------- #
def _chat(project: str, message: str, provider: str | None,
          model: str | None = None, effort: str | None = None) -> dict:
    reply, model_used = _llm(provider, message, model, effort)
    if reply:
        return core.envelope(project, intent="chat", assistant=reply,
                             provider_used=(provider or "").lower(), model_used=model_used)
    return core.envelope(project, intent="chat", assistant=_help_text(),
                         provider_used="deterministic", model_used=None)


# effort -> output-token cap (it's an interface chatbot; low keeps it snappy/cheap)
_EFFORT_CAP = {"low": 300, "medium": 700, "high": 1400}


def _effort_cap(effort: str | None) -> int:
    return _EFFORT_CAP.get((effort or "low").lower(), 300)


def _llm(provider: str | None, message: str, model: str | None = None,
         effort: str | None = None) -> tuple[str | None, str | None]:
    """Return (reply_text, model_used); (None, None) -> caller falls back to help."""
    p = (provider or "").lower()
    if p in ("", "auto", "none", "deterministic"):
        return None, None
    if p in _LOCAL:
        from .providers.ollama import DEFAULT_MODEL

        mdl = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        return _ollama(message, mdl, effort), mdl
    if p in _CLAUDE:
        return _claude(message, effort, model), (model or "claude")
    return None, None  # codex / gemini / api slots: picker-visible, not wired yet


def _ollama(message: str, model: str, effort: str | None) -> str | None:
    from .providers.ollama import DEFAULT_HOST, warm_model_async

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    # Refresh VRAM residency off-thread. Purely a side effect: the reply text and
    # envelope are byte-for-byte what they were, but the NEXT turn skips the
    # ~44s cold reload instead of paying it after 5 idle minutes.
    warm_model_async(host, model)
    try:
        txt = chat_completion(
            base_url=host.rstrip("/") + "/v1", model=model,
            system=system, user=message, force_json=False, temperature=0.3,
            timeout_s=120, extra={"max_tokens": _effort_cap(effort)},
        )
        return (txt or "").strip() or None
    except Exception:
        return None


def _neutral_cwd() -> str:
    """An empty directory to run the Claude CLI from.

    WHY: ``subprocess.run`` inherits the SERVER's cwd, and the Claude CLI walks
    up from wherever it starts to load CLAUDE.md, memory and skills. Running it
    inside this repo meant every chat message -- including "hi" -- re-sent
    agent_env's whole project context: measured at 25,666 cache-creation tokens
    and $0.28 per message.

    Measured effect of this fix, same prompt, only cwd differing:
        repo cwd  5.3s / 5.9s      neutral cwd  3.8s / 4.1s     (~30% faster)

    Latency is the smaller half of the win; the token cost is the point. Note
    ~4s is the CLI's own startup floor, so this does NOT make chat feel instant
    -- streaming (``ask_stream``) is what fixes perceived speed.

    Deliberately NOT tempfile.mkdtemp(): a stable path keeps the CLI's own
    caches warm across messages instead of looking new every time.
    """
    d = Path(tempfile.gettempdir()) / "daedalus_neutral_cwd"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return tempfile.gettempdir()
    return str(d)


def _claude(message: str, effort: str | None = None, model: str | None = None) -> str | None:
    path = shutil.which("claude")
    if not path:
        return None
    concise = "\nBe concise." if (effort or "low").lower() == "low" else ""
    prompt = f"{SYSTEM}{concise}\n\nUser: {message}"
    args = [path, "-p"]
    if model:
        args += ["--model", model]
    try:
        proc = subprocess.run(
            args, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=150,
            cwd=_neutral_cwd(),
        )
        return (proc.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- #
# Streaming brain — same routing as ask(), tokens pushed as they are produced   #
# --------------------------------------------------------------------------- #
def ask_stream(project: str, message: str, provider: str | None = None,
               model: str | None = None, effort: str | None = None):
    """Streaming twin of :func:`ask`. Yields ``(event, payload)`` tuples:

      ``("start", {...})``  once, before any text
      ``("delta", {"text": ...})``  zero or more, as tokens arrive
      ``("final", <envelope>)``  exactly once, the same shape ``ask()`` returns

    ``ask()`` itself is untouched — this is purely additive. Deterministic
    intents (status/distill/design/enqueue) are computed locally and fast, so
    they emit start+final with no deltas; only the freeform brain streams. That
    keeps ONE endpoint correct for every message the UI sends.

    Fail-closed: any streaming failure (unsupported flag, dead runtime, mid-
    stream error) degrades to the blocking path rather than erroring the chat.
    """
    message = (message or "").strip()
    if not message:
        yield "start", {"intent": "chat", "provider_used": "deterministic"}
        yield "final", ask(project, message, provider, model, effort)
        return

    try:
        intent = classify(message)
    except Exception:
        intent = "chat"

    # Deterministic lanes: no token stream to give, just compute and finish.
    if intent != "chat":
        yield "start", {"intent": intent, "provider_used": "deterministic"}
        yield "final", ask(project, message, provider, model, effort)
        return

    p = (provider or "").lower()
    streamer = None
    model_used = None
    if p in _LOCAL:
        from .providers.ollama import DEFAULT_MODEL

        model_used = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        streamer = _ollama_stream(message, model_used, effort)
    elif p in _CLAUDE:
        model_used = model or "claude"
        streamer = _claude_stream(message, effort, model)

    yield "start", {"intent": "chat",
                    "provider_used": p or "deterministic",
                    "model_used": model_used}

    if streamer is None:
        # No streaming brain selected (deterministic/auto, or an unwired slot
        # like codex/gemini) — identical outcome to ask().
        yield "final", ask(project, message, provider, model, effort)
        return

    chunks: list[str] = []
    failed = False
    try:
        for piece in streamer:
            if piece:
                chunks.append(piece)
                yield "delta", {"text": piece}
    except Exception:
        failed = True  # fall through to the blocking path

    text = "".join(chunks).strip()
    if failed or not text:
        # Nothing usable streamed -> blocking fallback keeps the chat alive.
        yield "final", ask(project, message, provider, model, effort)
        return

    yield "final", core.envelope(project, intent="chat", assistant=text,
                                 provider_used=p, model_used=model_used)


def _ollama_stream(message: str, model: str, effort: str | None):
    """Yield text deltas from the local Ollama runtime, and refresh the VRAM
    residency TTL in the background so the NEXT turn skips the ~44s reload."""
    from .providers._openai_compat import chat_stream
    from .providers.ollama import DEFAULT_HOST, warm_model_async

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    warm_model_async(host, model)  # non-blocking: never delays this reply
    yield from chat_stream(
        base_url=host.rstrip("/") + "/v1", model=model,
        system=system, user=message, temperature=0.3,
        timeout_s=120, extra={"max_tokens": _effort_cap(effort)},
    )


# Claude CLI stream-json frames we care about (verified against 2.1.201):
#   {"type":"stream_event","event":{"type":"content_block_delta",
#    "delta":{"type":"text_delta","text":"..."}}}
def _claude_stream(message: str, effort: str | None = None, model: str | None = None):
    """Yield text deltas from `claude -p --output-format stream-json
    --include-partial-messages`.

    Both flags are verified present on the installed CLI (2.1.201);
    ``--verbose`` is required alongside stream-json in --print mode. If the
    process dies or emits no deltas the generator simply ends, and the caller
    falls back to the blocking path.
    """
    path = shutil.which("claude")
    if not path:
        return
    concise = "\nBe concise." if (effort or "low").lower() == "low" else ""
    prompt = f"{SYSTEM}{concise}\n\nUser: {message}"
    args = [path, "-p", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose"]
    if model:
        args += ["--model", model]

    proc = None
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
            # Same neutral cwd as the blocking path -- see _neutral_cwd(). This
            # one matters MORE: it is the path that fixes perceived latency, so
            # leaving it to reload the repo's CLAUDE.md on every turn would pay
            # the whole context cost precisely where it is most visible.
            cwd=_neutral_cwd(),
        )
        proc.stdin.write(prompt)
        proc.stdin.close()
        deadline = _time.time() + 150
        for line in proc.stdout:
            if _time.time() > deadline:
                break
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "stream_event":
                continue
            ev = obj.get("event") or {}
            if ev.get("type") != "content_block_delta":
                continue
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield delta["text"]
    except (OSError, subprocess.SubprocessError, ValueError):
        return
    finally:
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


def _help_text() -> str:
    return (
        "I'm Ikarus — the assistant for your Agent OS. I can:\n"
        "- report status (\"what's running?\")\n"
        "- distill code (\"distill gui/motor_panel.py\", \"show duplicate clones\")\n"
        "- propose a task (\"build a settings dialog\") — you confirm before it runs\n"
        "- design an agent network (\"build an agent network with UI, API, QA roles\")\n"
        "Pick a model in the header to give me a language brain (local Ollama is free)."
    )
