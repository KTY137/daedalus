from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def replace_section(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"{path}: start marker missing: {start!r}")
    b = text.find(end, a + len(start))
    if b < 0:
        raise RuntimeError(f"{path}: end marker missing: {end!r}")
    write(path, text[:a] + replacement + text[b:])


# ---------------------------------------------------------------------------
# Ikarus: thread the canonical exact cancellation signal into existing
# cancellable HTTP transports. No new policy, ledger, or provider authority.
# ---------------------------------------------------------------------------
replace_once(
    "daedalus/ikarus_os.py",
    "from . import core, ikarus_act\nfrom .ikarus_act import ActDecision\nfrom .projects import resolve_repo_root\nfrom .providers._openai_compat import chat_completion\nfrom .llm_client import IkarusLLMClient\n",
    "from . import core, ikarus_act\nfrom .ikarus_act import ActDecision\nfrom .ikarus_cancellation import CancellationSignal\nfrom .llm_client import IkarusLLMClient\nfrom .projects import resolve_repo_root\nfrom .providers._openai_compat import ProviderCancelled, chat_completion\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "def ask_stream(project: str, message: str, provider: str | None = None,\n"
    "               model: str | None = None, effort: str | None = None,\n"
    "               conversation_id: str | None = None):\n",
    "def ask_stream(project: str, message: str, provider: str | None = None,\n"
    "               model: str | None = None, effort: str | None = None,\n"
    "               conversation_id: str | None = None, *,\n"
    "               cancellation: CancellationSignal | None = None):\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "    for event, payload in _ask_stream_inner(project, message, provider, model, effort,\n"
    "                                            conversation_id=conversation_id):\n",
    "    for event, payload in _ask_stream_inner(\n"
    "            project, message, provider, model, effort,\n"
    "            conversation_id=conversation_id, cancellation=cancellation):\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "def _ask_stream_inner(project: str, message: str, provider: str | None = None,\n"
    "                      model: str | None = None, effort: str | None = None, *,\n"
    "                      conversation_id: str | None = None):\n",
    "def _ask_stream_inner(project: str, message: str, provider: str | None = None,\n"
    "                      model: str | None = None, effort: str | None = None, *,\n"
    "                      conversation_id: str | None = None,\n"
    "                      cancellation: CancellationSignal | None = None):\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "    from .budget import process_guard_boundary_decision\n"
    "    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect\n",
    "    # Exact type at the outer runtime boundary: a duck-typed cancellation\n"
    "    # object is executable code (its `cancelled` attribute can run anything).\n"
    "    # Reject it before provider selection, context construction, or effects.\n"
    "    if cancellation is not None and type(cancellation) is not CancellationSignal:\n"
    "        raise TypeError(\"cancellation must be an exact CancellationSignal\")\n\n"
    "    from .budget import process_guard_boundary_decision\n"
    "    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect\n",
)

cancel_helper = '''def _cancelled_stream_final(
    project: str,
    provider: str,
    model_used: str | None,
    ctx: _Ctx,
    chunks: list[str],
    cancellation: CancellationSignal | None,
) -> dict:
    """One known-stop final: terminal, non-replayed, and honest about evidence.

    This says only that the canonical live request signal was cancelled. Owner
    release is proven later by ``CancellationRegistry.cancel_and_wait`` and OS
    child termination needs its own subprocess receipt; neither is invented here.
    """
    block = _ctx_envelope_block(ctx)
    extra = {"context": block} if block else {}
    request_id = cancellation.request_id if cancellation is not None else None
    return core.envelope(
        project,
        intent="chat",
        shell=SHELL_VOICE,
        assistant=("".join(chunks).strip() or
                   "Stopped by request. The turn was not automatically retried."),
        provider_used=provider,
        model_used=model_used,
        cancelled=True,
        cancellation_request_id=request_id,
        **extra,
    )


'''
replace_once(
    "daedalus/ikarus_os.py",
    "def _ask_stream_inner(project: str, message: str, provider: str | None = None,\n",
    cancel_helper + "def _ask_stream_inner(project: str, message: str, provider: str | None = None,\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "        streamer = _ollama_stream(message, model_used, effort, _merge_model_context(history, ctx.text), timeout_s=selection.timeout_s)\n",
    "        streamer = _ollama_stream(\n"
    "            message, model_used, effort, _merge_model_context(history, ctx.text),\n"
    "            timeout_s=selection.timeout_s, cancellation=cancellation)\n",
)
replace_once(
    "daedalus/ikarus_os.py",
    "        streamer = _deepseek_stream(message, model_used, effort, _merge_model_context(history, ctx.text), timeout_s=selection.timeout_s)\n",
    "        streamer = _deepseek_stream(\n"
    "            message, model_used, effort, _merge_model_context(history, ctx.text),\n"
    "            timeout_s=selection.timeout_s, cancellation=cancellation)\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "    if streamer is None:\n"
    "        # Codex currently has no verified token-frame parser; use the same\n",
    "    if cancellation is not None and cancellation.cancelled():\n"
    "        yield \"final\", _reconcile_final(\n"
    "            route, _cancelled_stream_final(\n"
    "                project, p or \"unavailable\", model_used, ctx, [], cancellation))\n"
    "        return\n\n"
    "    if streamer is None:\n"
    "        # Codex currently has no verified token-frame parser; use the same\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "    except ProviderStartRefused as exc:\n"
    "        # The transport boundary refused on the generator's FIRST step, before\n",
    "    except ProviderCancelled:\n"
    "        # A known stop is neither a provider failure nor an uncertain stream.\n"
    "        # Never replay it through the blocking path.\n"
    "        yield \"final\", _reconcile_final(\n"
    "            route, _cancelled_stream_final(\n"
    "                project, p, model_used, ctx, chunks, cancellation))\n"
    "        return\n"
    "    except ProviderStartRefused as exc:\n"
    "        # The transport boundary refused on the generator's FIRST step, before\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "    text = \"\".join(chunks).strip()\n"
    "    if failed and text:\n",
    "    if cancellation is not None and cancellation.cancelled():\n"
    "        yield \"final\", _reconcile_final(\n"
    "            route, _cancelled_stream_final(\n"
    "                project, p, model_used, ctx, chunks, cancellation))\n"
    "        return\n\n"
    "    text = \"\".join(chunks).strip()\n"
    "    if failed and text:\n",
)

replace_once(
    "daedalus/ikarus_os.py",
    "def _ollama_stream(message: str, model: str, effort: str | None, context: str = \"\", *, timeout_s: float = 150.0):\n",
    "def _ollama_stream(message: str, model: str, effort: str | None, context: str = \"\", *,\n"
    "                   timeout_s: float = 150.0,\n"
    "                   cancellation: CancellationSignal | None = None):\n",
)
replace_once(
    "daedalus/ikarus_os.py",
    "    host = os.environ.get(\"OLLAMA_HOST\", DEFAULT_HOST)\n"
    "    _provider_start(\"ollama\", endpoint=host, model=model)\n",
    "    host = os.environ.get(\"OLLAMA_HOST\", DEFAULT_HOST)\n"
    "    if cancellation is not None and cancellation.cancelled():\n"
    "        raise ProviderCancelled(\"cancelled before Ikarus opened the Ollama stream\")\n"
    "    _provider_start(\"ollama\", endpoint=host, model=model)\n",
)
replace_once(
    "daedalus/ikarus_os.py",
    "        temperature=0.3, timeout_s=timeout_s,\n"
    "    )\n\n\ndef _deepseek_stream",
    "        temperature=0.3, timeout_s=timeout_s,\n"
    "        cancelled=(cancellation.cancelled if cancellation is not None else None),\n"
    "    )\n\n\ndef _deepseek_stream",
)
replace_once(
    "daedalus/ikarus_os.py",
    "def _deepseek_stream(message: str, model: str, effort: str | None, context: str = \"\", *, timeout_s: float = 150.0):\n",
    "def _deepseek_stream(message: str, model: str, effort: str | None, context: str = \"\", *,\n"
    "                     timeout_s: float = 150.0,\n"
    "                     cancellation: CancellationSignal | None = None):\n",
)
replace_once(
    "daedalus/ikarus_os.py",
    "    api_key = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")\n"
    "    base_url = os.environ.get(\"DEEPSEEK_BASE_URL\", DEFAULT_BASE_URL)\n"
    "    _provider_start(\"deepseek\", endpoint=base_url, model=model)\n",
    "    api_key = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")\n"
    "    base_url = os.environ.get(\"DEEPSEEK_BASE_URL\", DEFAULT_BASE_URL)\n"
    "    if cancellation is not None and cancellation.cancelled():\n"
    "        raise ProviderCancelled(\"cancelled before Ikarus opened the DeepSeek stream\")\n"
    "    _provider_start(\"deepseek\", endpoint=base_url, model=model)\n",
)
replace_once(
    "daedalus/ikarus_os.py",
    "        api_key=api_key, temperature=0.3, timeout_s=timeout_s,\n"
    "        extra={\"max_tokens\": _effort_cap(effort)},\n"
    "    )\n\n\n# Claude CLI stream-json",
    "        api_key=api_key, temperature=0.3, timeout_s=timeout_s,\n"
    "        extra={\"max_tokens\": _effort_cap(effort)},\n"
    "        cancelled=(cancellation.cancelled if cancellation is not None else None),\n"
    "    )\n\n\n# Claude CLI stream-json",
)

# ---------------------------------------------------------------------------
# HTTP owner: one live request id, one registry signal, one cancel mutation.
# ---------------------------------------------------------------------------
replace_once("daedalus/web_api.py", "import re\n", "import re\nimport secrets\n")
replace_once(
    "daedalus/web_api.py",
    "from . import core, ikarus_chat, ikarus_os\n",
    "from . import core, ikarus_cancellation, ikarus_chat, ikarus_os\n",
)

new_stream_handler = '''    def _handle_ikarus_stream(self, qs: dict) -> None:
        """Serve one cancellable Ikarus turn over one-shot SSE.

        ``request_id`` is the correlation identity shared by the browser,
        process-local cancellation registry, Ikarus router and provider probe.
        Older callers that omit it receive a server-minted id in ``start``;
        shipping Cockpit callers mint it first so their Stop mutation can name
        the exact live owner. A duplicate active id fails before SSE headers.

        Disconnect is not terminal evidence, but it is a stop signal: once a
        write proves the client is gone, the exact signal is cancelled and the
        generator is closed before owner release. Normal completion releases the
        same signal without fabricating cancellation.
        """
        project = (qs.get("project") or [""])[0]
        message = (qs.get("message") or [""])[0].strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        provider = (qs.get("provider") or [""])[0] or None
        model = (qs.get("model") or [""])[0] or None
        effort = (qs.get("effort") or [""])[0] or None
        conversation_id = (qs.get("conversation_id") or [""])[0] or None
        request_id = ((qs.get("request_id") or [""])[0].strip()
                      or f"ikarus:{secrets.token_hex(16)}")

        registry = ikarus_cancellation.default_registry()
        try:
            registry.validate_request_id(request_id)
        except ikarus_cancellation.CancellationRegistrationError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        try:
            cancellation = registry.open(request_id)
        except ikarus_cancellation.CancellationRegistrationError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return

        stream = None
        try:
            unit_id: str | None = None
            try:
                from . import progress as progress_mod

                unit_id = progress_mod.open_unit(
                    source="web_api.ikarus_stream",
                    detail={"project": project, "message_chars": len(message),
                            "request_id": request_id})
            except Exception:
                unit_id = None  # progress tracking is best-effort; chat is not

            self.close_connection = True
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
            except OSError:
                return

            def emit(event: str, data: Any) -> None:
                msg = f"event: {event}\\ndata: {json.dumps(data, default=str)}\\n\\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()

            try:
                stream = ikarus_os.ask_stream(
                    project, message, provider=provider, model=model, effort=effort,
                    conversation_id=conversation_id, cancellation=cancellation,
                )
                if unit_id:
                    from . import progress_sources

                    stream = progress_sources.watch_stream(
                        unit_id, stream, source="web_api.ikarus_stream")
                for event, payload in stream:
                    if event == "start":
                        payload = {**payload, "request_id": request_id}
                        if unit_id:
                            payload["progress_unit_id"] = unit_id
                    emit(event, payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                # This is evidence only that the observer disappeared. Request
                # stop, then let provider/owner evidence say what actually ended.
                cancellation.cancel()
                return
            except Exception as exc:
                try:
                    emit("final", core.envelope(
                        project, intent="error",
                        assistant=f"I hit a snag: {exc}",
                        provider_used="deterministic",
                        cancellation_request_id=request_id,
                    ))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    cancellation.cancel()
                    return
        finally:
            if stream is not None:
                try:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    pass
            registry.release(cancellation)

'''
replace_section(
    "daedalus/web_api.py",
    "    def _handle_ikarus_stream(self, qs: dict) -> None:\n",
    "    def _handle_task_events(self, task_id: str) -> None:\n",
    new_stream_handler,
)

cancel_endpoint = '''        if path == "/api/ikarus/cancel":
            request_id = str(body.get("request_id") or "").strip()
            if not request_id:
                self._send_json({"ok": False, "error": "request_id is required"}, status=400)
                return
            try:
                # 250 ms is an observation budget, not a work deadline. The
                # receipt stays request_finished=false when owner release is not
                # observed in that window instead of rounding "requested" up to
                # "stopped".
                receipt = ikarus_cancellation.default_registry().cancel_and_wait(
                    request_id, timeout_s=0.25)
            except (ikarus_cancellation.CancellationRegistrationError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json(core.envelope(None, cancellation=receipt.to_dict()))
            return
'''
replace_once(
    "daedalus/web_api.py",
    "        if path == \"/api/ikarus/chat\":\n",
    cancel_endpoint + "        if path == \"/api/ikarus/chat\":\n",
)

# ---------------------------------------------------------------------------
# Browser API: mint the id before opening SSE; cancellation POST starts before
# observation is closed and is idempotent per stream handle.
# ---------------------------------------------------------------------------
api_contract = '''export interface IkarusCancellationReceipt {
  request_id: string;
  active: boolean;
  newly_cancelled: boolean;
  /** Exact owner release observed within the backend's bounded stop window. */
  request_finished: boolean;
}

export interface IkarusCancellationPayload extends ApiEnvelope {
  cancellation: IkarusCancellationReceipt;
}

export interface IkarusStreamHandle {
  requestId: string;
  /** Observation-only close, used after a terminal frame. */
  close: () => void;
  /** Request backend cancellation, then close browser observation. */
  cancel: () => Promise<IkarusCancellationPayload>;
}

function newIkarusRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `ikarus:${uuid}`;
  // Correlation identity, not an auth token. A duplicate is still rejected by
  // the server's exact live-owner registry.
  return `ikarus:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 14)}`;
}

export function cancelIkarus(requestId: string) {
  return request<IkarusCancellationPayload>('/api/ikarus/cancel', {
    method: 'POST',
    body: JSON.stringify({ request_id: requestId })
  }, 3_000);
}

'''
replace_once(
    "apps/web/src/api.ts",
    "/**\n * Streaming twin of `askIkarus` — renders text as it is produced instead of\n",
    api_contract + "/**\n * Streaming twin of `askIkarus` — renders text as it is produced instead of\n",
)
replace_once(
    "apps/web/src/api.ts",
    "    onStart?: (data: { intent?: string; provider_used?: string }) => void;\n",
    "    onStart?: (data: { intent?: string; provider_used?: string; request_id?: string }) => void;\n",
)
replace_once(
    "apps/web/src/api.ts",
    "): { close: () => void } {\n  const qs = new URLSearchParams({ project, message });\n",
    "): IkarusStreamHandle {\n  const requestId = newIkarusRequestId();\n  const qs = new URLSearchParams({ project, message, request_id: requestId });\n",
)
replace_once(
    "apps/web/src/api.ts",
    "  let done = false;\n  let streamedText = '';\n",
    "  let done = false;\n  let cancelPromise: Promise<IkarusCancellationPayload> | null = null;\n  let streamedText = '';\n",
)
replace_once(
    "apps/web/src/api.ts",
    "      const data = JSON.parse((event as MessageEvent).data) as { intent?: string; provider_used?: string };\n",
    "      const data = JSON.parse((event as MessageEvent).data) as { intent?: string; provider_used?: string; request_id?: string };\n",
)
replace_once(
    "apps/web/src/api.ts",
    "  return { close: () => settle() };\n}\n",
    "  return {\n"
    "    requestId,\n"
    "    close: () => settle(),\n"
    "    cancel: () => {\n"
    "      // Start the mutation before closing EventSource. Closing observation\n"
    "      // is not itself a backend stop signal. Repeated calls share one POST.\n"
    "      if (!cancelPromise) cancelPromise = cancelIkarus(requestId);\n"
    "      settle();\n"
    "      return cancelPromise;\n"
    "    }\n"
    "  };\n}\n",
)

replace_once(
    "apps/web/src/types.ts",
    "  /** True means the text may be partial and no action affordance is safe. */\n"
    "  stream_interrupted: boolean;\n",
    "  /** True means the text may be partial and no action affordance is safe. */\n"
    "  stream_interrupted: boolean;\n"
    "  /** Known cancellation is distinct from an uncertain transport failure. */\n"
    "  cancelled?: boolean;\n"
    "  /** Opaque correlation id for the exact live cancellation owner. */\n"
    "  cancellation_request_id?: string;\n",
)

# ---------------------------------------------------------------------------
# Cockpit UX: Stop means "request stop" immediately, and the receipt upgrades
# the label only when exact owner release was positively observed.
# ---------------------------------------------------------------------------
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "import { getConversation, getRuntimeStatus, newConversation, queueTask, streamIkarus } from '../api';\n",
    "import { getConversation, getRuntimeStatus, newConversation, queueTask, streamIkarus, type IkarusStreamHandle } from '../api';\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "  /** the reader stopped this turn before the backend reported anything */\n  halted?: boolean;\n",
    "  /** the reader requested stop before the backend reported a terminal frame */\n"
    "  halted?: boolean;\n"
    "  /** Stop-request evidence: requested != exact-owner release. */\n"
    "  stopState?: 'requested' | 'finished' | 'unproven';\n"
    "  /** Correlates an asynchronous stop receipt to this exact visible turn. */\n"
    "  stopRequestId?: string;\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "  const stream = useRef<{ close: () => void } | null>(null);\n",
    "  const stream = useRef<IkarusStreamHandle | null>(null);\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "  useEffect(() => () => stream.current?.close(), []);\n",
    "  useEffect(() => () => {\n"
    "    const active = stream.current;\n"
    "    stream.current = null;\n"
    "    if (active) void active.cancel().catch(() => undefined);\n"
    "  }, []);\n",
)

old_stop = '''  const stop = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    setBusy(false);
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === 'ikarus' && last.streaming) {
        next[next.length - 1] = {
          ...last,
          streaming: false,
          halted: true,
          text: last.text || 'Abgebrochen, bevor eine Antwort kam.'
        };
      }
      return next;
    });
  }, []);
'''
new_stop = '''  const stop = useCallback(() => {
    const active = stream.current;
    stream.current = null;
    setBusy(false);
    if (!active) return;

    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === 'ikarus' && last.streaming) {
        next[next.length - 1] = {
          ...last,
          streaming: false,
          halted: true,
          stopState: 'requested',
          stopRequestId: active.requestId,
          text: last.text || 'Stop angefordert, bevor eine Antwort kam.'
        };
      }
      return next;
    });

    void active.cancel().then((payload) => {
      const finished = Boolean(payload.cancellation?.active && payload.cancellation?.request_finished);
      setTurns((prev) => prev.map((turn) =>
        turn.stopRequestId === active.requestId
          ? { ...turn, stopState: finished ? 'finished' : 'unproven' }
          : turn
      ));
    }).catch(() => {
      // Transport failure is not evidence that backend cancellation failed OR
      // succeeded. Keep that uncertainty visible instead of saying stopped.
      setTurns((prev) => prev.map((turn) =>
        turn.stopRequestId === active.requestId
          ? { ...turn, stopState: 'unproven' }
          : turn
      ));
    });
  }, []);
'''
replace_once("apps/web/src/cockpit/Conversation.tsx", old_stop, new_stop)

replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "        onFinal: (payload) => settle(payload, threadId),\n",
    "        onFinal: (payload) => {\n"
    "          stream.current = null;\n"
    "          settle(payload, threadId);\n"
    "        },\n",
)
replace_once(
    "apps/web/src/cockpit/Conversation.tsx",
    "        const stamp: Stamp | undefined = t.halted\n"
    "          ? { word: 'ABGEBROCHEN', kind: 'failed' }\n"
    "          : t.origin\n",
    "        const stamp: Stamp | undefined = t.halted\n"
    "          ? {\n"
    "              word: t.stopState === 'finished'\n"
    "                ? 'ABGEBROCHEN'\n"
    "                : t.stopState === 'unproven'\n"
    "                  ? 'STOP UNBESTÄTIGT'\n"
    "                  : 'STOP ANGEFORDERT',\n"
    "              kind: 'failed'\n"
    "            }\n"
    "          : t.origin\n",
)

# ---------------------------------------------------------------------------
# Python regression evidence.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_ikarus_stream.py",
    "from daedalus import ikarus_os\n",
    "from daedalus import ikarus_os\nfrom daedalus.ikarus_cancellation import CancellationSignal\n",
)
replace_once(
    "tests/test_ikarus_stream.py",
    "from daedalus.providers._openai_compat import ProviderHTTPError, chat_stream\n",
    "from daedalus.providers._openai_compat import ProviderCancelled, ProviderHTTPError, chat_stream\n",
)

stream_tests = '''

class IkarusCancellationWiringTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def test_exact_signal_reaches_native_ollama_transport(self):
        signal = CancellationSignal("request-ollama-probe-001")
        with mock.patch.object(ikarus_os, "_provider_start"), \\
             mock.patch("daedalus.providers._ollama_native.native_chat_stream",
                        return_value=iter([])) as transport:
            list(ikarus_os._ollama_stream(
                "hello", "m7", "low", cancellation=signal))
        probe = transport.call_args.kwargs["cancelled"]
        self.assertFalse(probe())
        signal.cancel()
        self.assertTrue(probe())

    def test_precancel_refuses_before_ollama_effect_start(self):
        signal = CancellationSignal("request-ollama-precancel-001")
        signal.cancel()
        with mock.patch.object(ikarus_os, "_provider_start") as start, \\
             mock.patch("daedalus.providers._ollama_native.native_chat_stream") as transport:
            events = list(ikarus_os.ask_stream(
                self.PROJECT, "hello there", provider="ollama", cancellation=signal))
        start.assert_not_called()
        transport.assert_not_called()
        final = events[-1][1]
        self.assertTrue(final["cancelled"])
        self.assertEqual(final["cancellation_request_id"], signal.request_id)
        self.assertNotIn("stream_interrupted", final)

    def test_provider_cancel_is_terminal_and_never_blocking_replayed(self):
        signal = CancellationSignal("request-midstream-cancel-001")

        def cancelled_stream():
            yield "partial"
            signal.cancel()
            raise ProviderCancelled("stop")

        with mock.patch.object(ikarus_os, "_ollama_stream",
                               return_value=cancelled_stream()), \\
             mock.patch.object(ikarus_os, "_chat") as blocking:
            events = list(ikarus_os.ask_stream(
                self.PROJECT, "hello there", provider="ollama", cancellation=signal))
        blocking.assert_not_called()
        final = events[-1][1]
        self.assertEqual(final["assistant"], "partial")
        self.assertTrue(final["cancelled"])
        self.assertEqual(final["cancellation_request_id"], signal.request_id)
        self.assertNotIn("stream_interrupted", final)

    def test_duck_typed_signal_is_refused_before_provider_selection(self):
        class DuckSignal:
            def cancelled(self):
                raise AssertionError("duck callback executed")

        with self.assertRaisesRegex(TypeError, "exact CancellationSignal"):
            list(ikarus_os.ask_stream(
                self.PROJECT, "hello there", provider="ollama",
                cancellation=DuckSignal()))
'''
text = read("tests/test_ikarus_stream.py")
if "class IkarusCancellationWiringTest" in text:
    raise RuntimeError("tests/test_ikarus_stream.py: cancellation wiring tests already present")
write("tests/test_ikarus_stream.py", text + stream_tests)

http_tests = '''from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest import mock

from daedalus import ikarus_cancellation, web_api


def _post_handler(body: dict, registry: ikarus_cancellation.CancellationRegistry):
    handler = SimpleNamespace(path="/api/ikarus/cancel", _send_json=mock.Mock())
    with mock.patch.object(web_api, "_read_body", return_value=body), \\
         mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry):
        web_api.DaedalusHandler._handle_post(handler)
    return handler._send_json


def test_cancel_endpoint_returns_positive_exact_owner_release_evidence() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-stop-001"
    entered = threading.Event()

    def owner() -> None:
        with registry.claim(request_id) as signal:
            entered.set()
            while not signal.cancelled():
                time.sleep(0.002)

    thread = threading.Thread(target=owner, daemon=True)
    thread.start()
    assert entered.wait(1.0)

    send = _post_handler({"request_id": request_id}, registry)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    payload = send.call_args.args[0]
    assert payload["cancellation"] == {
        "request_id": request_id,
        "active": True,
        "newly_cancelled": True,
        "request_finished": True,
    }


def test_cancel_endpoint_rejects_malformed_identity_without_owner_lookup() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    send = _post_handler({"request_id": "bad"}, registry)
    assert send.call_args.kwargs["status"] == 400
    assert "request_id" in send.call_args.args[0]["error"]
    assert registry.active_count() == 0


class _BrokenWriter:
    def write(self, _data: bytes) -> int:
        raise BrokenPipeError("client gone")

    def flush(self) -> None:
        return None


def test_sse_disconnect_cancels_and_releases_exact_live_signal() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-stream-001"
    captured: dict[str, object] = {}

    def fake_stream(*_args, cancellation=None, **_kwargs):
        captured["signal"] = cancellation
        yield "start", {"intent": "chat", "provider_used": "ollama_http"}
        yield "final", {"ok": True}

    handler = SimpleNamespace(
        close_connection=False,
        wfile=_BrokenWriter(),
        send_response=lambda *_a, **_k: None,
        send_header=lambda *_a, **_k: None,
        end_headers=lambda *_a, **_k: None,
        _send_json=mock.Mock(),
    )
    qs = {
        "project": ["fixture"],
        "message": ["hello"],
        "request_id": [request_id],
    }
    with mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry), \\
         mock.patch.object(web_api.ikarus_os, "ask_stream", side_effect=fake_stream), \\
         mock.patch("daedalus.progress.open_unit", side_effect=RuntimeError("skip progress")):
        web_api.DaedalusHandler._handle_ikarus_stream(handler, qs)

    signal = captured["signal"]
    assert type(signal) is ikarus_cancellation.CancellationSignal
    assert signal.request_id == request_id
    assert signal.cancelled()
    assert signal.finished()
    assert registry.active_count() == 0


def test_sse_start_frame_exposes_the_exact_request_identity() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-start-001"
    chunks: list[bytes] = []

    class Writer:
        def write(self, data: bytes) -> int:
            chunks.append(data)
            return len(data)
        def flush(self) -> None:
            return None

    def fake_stream(*_args, cancellation=None, **_kwargs):
        assert cancellation.request_id == request_id
        yield "start", {"intent": "chat", "provider_used": "ollama_http"}
        yield "final", {"ok": True, "intent": "chat", "assistant": "done",
                        "provider_used": "ollama_http"}

    handler = SimpleNamespace(
        close_connection=False,
        wfile=Writer(),
        send_response=lambda *_a, **_k: None,
        send_header=lambda *_a, **_k: None,
        end_headers=lambda *_a, **_k: None,
        _send_json=mock.Mock(),
    )
    qs = {"project": ["fixture"], "message": ["hello"], "request_id": [request_id]}
    with mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry), \\
         mock.patch.object(web_api.ikarus_os, "ask_stream", side_effect=fake_stream), \\
         mock.patch("daedalus.progress.open_unit", side_effect=RuntimeError("skip progress")):
        web_api.DaedalusHandler._handle_ikarus_stream(handler, qs)

    body = b"".join(chunks).decode("utf-8")
    start_data = body.split("event: start\\n", 1)[1].split("\\n\\n", 1)[0]
    payload = json.loads(start_data.removeprefix("data: "))
    assert payload["request_id"] == request_id
    assert registry.active_count() == 0
'''
write("tests/test_ikarus_http_cancellation.py", http_tests)

# ---------------------------------------------------------------------------
# Shipping-browser regression: one Stop -> one cancel mutation with the same id,
# and proof wording follows the backend receipt rather than the click itself.
# ---------------------------------------------------------------------------
browser_test = '''

test('shipping Stop cancels the exact SSE request and only claims completion from evidence', async ({ page }) => {
  const replay = { calls: 0 };
  let cancelBody: { request_id?: string } | undefined;

  await page.addInitScript(() => {
    (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls = [];
    class HeldEventSource {
      url: string;
      onerror: ((event: Event) => unknown) | null = null;
      constructor(url: string | URL) {
        this.url = String(url);
        (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls.push(this.url);
      }
      addEventListener() { /* intentionally held open until the UI cancels */ }
      close() { /* observation closed; the POST is the backend stop */ }
    }
    Object.defineProperty(window, 'EventSource', { value: HeldEventSource, configurable: true });
  });

  await page.route('**/api/ikarus/ask', blockUnexpectedReplay(replay));
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, conversation_id: 'conv_20260906T230000Z_stopbeef' })
    });
  });
  await page.route('**/api/runtimes/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, runtimes: [] }) });
  });
  await page.route('**/api/ikarus/cancel', async (route) => {
    cancelBody = route.request().postDataJSON() as { request_id?: string };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        generated_at: '2026-09-06T21:00:00Z',
        project: null,
        warnings: [],
        cancellation: {
          request_id: cancelBody.request_id,
          active: true,
          newly_cancelled: true,
          request_finished: true
        }
      })
    });
  });

  await openCockpit(page);
  await page.getByLabel('Nachricht an Ikarus').fill('keep working until I stop you');
  await page.getByRole('button', { name: 'Senden' }).click();
  const stop = page.getByRole('button', { name: 'Antwort stoppen' });
  await expect(stop).toBeVisible({ timeout: 10_000 });
  await stop.click();

  await expect.poll(() => cancelBody?.request_id || '').not.toBe('');
  const streamUrl = await page.evaluate(() => {
    const urls = (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls;
    return [...urls].reverse().find((url) => url.includes('/api/ikarus/stream?')) || '';
  });
  const streamedRequestId = new URL(streamUrl, 'http://localhost').searchParams.get('request_id');
  expect(streamedRequestId).toBeTruthy();
  expect(cancelBody?.request_id).toBe(streamedRequestId);

  await expect(page.getByText('ABGEBROCHEN', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('STOP ANGEFORDERT', { exact: true })).toHaveCount(0);
  await expect(page.getByText('STOP UNBESTÄTIGT', { exact: true })).toHaveCount(0);
  expect(replay.calls, 'Stop must never replay the turn through /api/ikarus/ask').toBe(0);
});
'''
text = read("apps/web/tests/cockpit-stream.spec.ts")
if "shipping Stop cancels the exact SSE request" in text:
    raise RuntimeError("cockpit stop test already present")
write("apps/web/tests/cockpit-stream.spec.ts", text + browser_test)

# ---------------------------------------------------------------------------
# Canonical Gate 1 must own every new seam and test.
# ---------------------------------------------------------------------------
replace_once(
    ".github/workflows/g1-ikarus-unified-runtime-admission.yml",
    "      - \"tests/test_ikarus_stream.py\"\n      - \"tests/test_ikarus_stop_gate_paths.py\"\n",
    "      - \"tests/test_ikarus_stream.py\"\n      - \"tests/test_ikarus_http_cancellation.py\"\n      - \"tests/test_ikarus_stop_gate_paths.py\"\n",
)
replace_once(
    ".github/workflows/g1-ikarus-unified-runtime-admission.yml",
    "          tests/test_ikarus_stream.py\n          tests/test_ikarus_stop_gate_paths.py\n",
    "          tests/test_ikarus_stream.py\n          tests/test_ikarus_http_cancellation.py\n          tests/test_ikarus_stop_gate_paths.py\n",
)
# The same pair occurs once more in pytest after the compile replacement above.
replace_once(
    ".github/workflows/g1-ikarus-unified-runtime-admission.yml",
    "          tests/test_ikarus_stream.py\n          tests/test_ikarus_stop_gate_paths.py\n",
    "          tests/test_ikarus_stream.py\n          tests/test_ikarus_http_cancellation.py\n          tests/test_ikarus_stop_gate_paths.py\n",
)

stop_gate = '''from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/g1-ikarus-unified-runtime-admission.yml")

# The JARVIS-style Stop path crosses UI ownership, the SSE transport boundary,
# Ikarus routing, canonical cancellation ownership, and both stream transports.
# A PR that edits any one of these must not be able to skip the canonical Gate 1
# workflow just because the path filter forgot that layer.
STOP_SEAM_PATHS = (
    "apps/web/src/api.ts",
    "apps/web/src/cockpit/Conversation.tsx",
    "apps/web/tests/cockpit-stream.spec.ts",
    "daedalus/web_api.py",
    "daedalus/ikarus_cancellation.py",
    "daedalus/ikarus_os.py",
    "daedalus/providers/_openai_compat.py",
    "daedalus/providers/_ollama_native.py",
    "tests/test_ikarus_cancellation.py",
    "tests/test_ikarus_stream.py",
    "tests/test_ikarus_http_cancellation.py",
    "tests/test_ikarus_stop_gate_paths.py",
)


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_stop_seam_paths_trigger_gate_one() -> None:
    text = _workflow_text()
    missing = [path for path in STOP_SEAM_PATHS if f'- "{path}"' not in text]
    assert not missing, f"Gate 1 path filter misses JARVIS Stop seam(s): {missing}"


def test_backend_stream_surface_is_compiled_in_focused_jobs() -> None:
    text = _workflow_text()
    compile_start = text.index("python -m py_compile")
    compile_end = text.index("- run: python -m json.tool", compile_start)
    compile_block = text[compile_start:compile_end]
    for path in (
        "daedalus/web_api.py",
        "daedalus/ikarus_cancellation.py",
        "tests/test_ikarus_cancellation.py",
        "tests/test_ikarus_http_cancellation.py",
        "tests/test_ikarus_stop_gate_paths.py",
    ):
        assert path in compile_block


def test_stop_contract_tests_run_in_focused_matrix() -> None:
    text = _workflow_text()
    pytest_start = text.index("python -m pytest -q -p no:cacheprovider")
    pytest_block = text[pytest_start:]
    for path in (
        "tests/test_ikarus_cancellation.py",
        "tests/test_ikarus_stream.py",
        "tests/test_ikarus_http_cancellation.py",
        "tests/test_ikarus_stop_gate_paths.py",
    ):
        assert path in pytest_block
'''
write("tests/test_ikarus_stop_gate_paths.py", stop_gate)

# The patch workflow is intentionally disposable authoring infrastructure. Once
# this script has applied the tested product delta, remove it in the same final
# commit so the canonical branch does not accumulate a second CI path.
tmp_workflow = ROOT / ".github/workflows/tmp-ikarus-stop-patch.yml"
if not tmp_workflow.exists():
    raise RuntimeError("temporary stop patch workflow unexpectedly missing")
tmp_workflow.unlink()
