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


THREE SHELLS, SPLIT BY CAPABILITY
---------------------------------
One classifier, three executors. What separates them is not which model is
behind them but WHAT THEY ARE ALLOWED TO DO:

  ``deterministic``  status / distill / design. Computed here, locally. No
                     spend, no egress, no model.
  ``hand``           the tool-bearing shell. Reached only for work the SEPARATE
                     capability predicate (:mod:`daedalus.ikarus_act`) cleared.
                     Inside this module the Hand shell only ever PROPOSES a
                     confirm-gated task -- the executor itself runs later,
                     asynchronously, via the bridge into
                     ``providers/ollama.py``. Nothing here calls a tool.
                     A CONFIRMED route additionally requires the executor to be
                     MEASURED ``working`` (see :func:`_enqueue`): confirming is
                     the moment the system commits work to the Hand, and it
                     refuses in words rather than committing on "I don't know".
                     An unconfirmed proposal commits nothing, so it proposes
                     regardless -- reporting the executor's state when it
                     happens to know it, and claiming nothing when it does not.
  ``voice``          conversational, NO tools, text out and nothing else. Every
                     branch of :func:`_llm` lives here.

Every ``start`` event, every envelope, and every persisted turn carries the
shell that answered, so "which one of the three spoke" is a recorded fact and
not an inference from the provider name.


THE PROVIDER FENCE — chat is the client's choice of voice, action is the
system's choice of hand
-----------------------------------------------------------------------
For ``chat`` intents the client-supplied ``provider`` parameter REMAINS
honored, exactly as before. It is a live capability -- local Ollama, the user's
Claude CLI, DeepSeek, Codex -- and which voice answers you is a preference,
paid for by the person expressing it. Removing that is a product decision this
code is not entitled to make on its own.

For any intent the capability predicate clears for tools, THE EXECUTOR IS
CHOSEN BY THE SYSTEM. ``provider`` is not consulted, not defaulted from, and
not echoed into the proposed action: :func:`_enqueue` does not take it as an
argument, so a client cannot name its way onto the tool-bearing path. The lane
is fixed at ``local_only`` here and re-derived downstream by the router, which
owns the lane decision; naming "claude" in a chat request must never become a
way to select who executes.

The fence exists because the two parameters look alike and are not: one selects
who TALKS TO YOU, the other selects who TOUCHES YOUR FILES.


CLASSIFY ONCE
-------------
:func:`classify` runs exactly once per request. Both entry points derive
``(intent, act)`` at the top and thread the labels down; nothing below
re-derives them. :func:`_route` folds the intent answer and the capability
answer into ONE effective label, which is what the streaming ``start`` event
announces and what every ``final`` is built from -- so a client that has
already committed to an affordance (or, later, to speech) cannot be handed a
``final`` that contradicts it. :func:`_reconcile_final` is the tripwire for the
case that should now be unreachable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time as _time
from collections import namedtuple
from pathlib import Path

from . import core, ikarus_act
from .ikarus_act import ActDecision
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

# Runtimes that can currently power the freeform 'brain'. A provider string not
# in any of these sets still falls back to the deterministic layer -- cleanly,
# via _llm()'s final `return None, None, _EMPTY_CTX` -- rather than crashing or
# guessing at a different brain.
_LOCAL = {"ollama", "ollama_http", "ollama_cli"}
_CLAUDE = {"claude", "claude_cli", "claude_code_cli"}
# CODEX and DEEPSEEK are EXTERNAL, NOT-trusted-with-IP lanes (see
# daedalus/providers/__init__.py _PROVIDERS: trusted_with_ip=False for both) --
# _llm() below deliberately builds their brain context with lane="untrusted",
# never "trusted" like Ollama/Claude get.
_CODEX = {"codex", "codex_cli"}
_DEEPSEEK = {"deepseek"}

# --------------------------------------------------------------------------- #
# Project-aware brain context (GATED distilled slice)                          #
# --------------------------------------------------------------------------- #
# A distilled slice of the file the user referenced, injected as brain context.
# It REPLACES in-repo context (Claude still runs from _neutral_cwd()), so it is
# capped: a focus file larger than the budget stays whole (never truncated), but
# its neighbour skeletons are shed by semantic_slice(max_tokens=) so a big file
# can't blow the chat prompt.
#
# Sizing (measured on agent_env, uncontended [M]): focus files of the core
# modules run 5.4k-8.2k tokens EACH, and a focus is never truncated -- so the cap
# only governs how many NEIGHBOURS ride along, and any cap below the focus size
# just evicts the whole neighbourhood while still paying for the big focus (the
# worst of both). Full focus+neighbourhood slices measure 817-15,773 tok,
# clustered ~10k for core files -- all under the 25,666-tok whole-repo baseline
# that in-repo cwd used to pay every message. 12k keeps the FULL neighbourhood
# for essentially every core file (only the 23-neighbour index.py outlier trims),
# stays < half the whole-repo cost, and the honest "capability for +slice_tokens
# per message" trade holds. The degrade path is exercised by a tiny-cap unit test
# regardless of this value.
_CONTEXT_MAX_TOKENS = 12000

# Framing so the model knows the injected block is a distilled slice, not the
# whole file — anti-hallucination: it should treat withheld/trimmed gaps as gaps.
_CONTEXT_FRAMING = "# Project context (distilled slice of the file you referenced):"

# Metadata carried up to the chat envelope so the USER sees their context was
# gated / trimmed / incomplete — not just the model. text="" means "no context
# injected" (no file token, ambiguous filename, or a build hiccup) and the prompt
# stays byte-identical to the pre-BOOTSTRAP neutral prompt.
_Ctx = namedtuple(
    "_Ctx", "text withheld_count focus_file included_count trimmed_count ambiguous")
_EMPTY_CTX = _Ctx("", 0, None, 0, 0, False)


# --------------------------------------------------------------------------- #
# The three shells (capability, not vendor)                                    #
# --------------------------------------------------------------------------- #
SHELL_DETERMINISTIC = "deterministic"
SHELL_HAND = "hand"
SHELL_VOICE = "voice"

#: Which shell answers which effective route. One table, so the ``start`` event
#: and the envelope cannot label the same turn differently.
_SHELL_BY_ROUTE = {
    "status": SHELL_DETERMINISTIC,
    "distill": SHELL_DETERMINISTIC,
    "design": SHELL_DETERMINISTIC,
    "enqueue": SHELL_HAND,
    "chat": SHELL_VOICE,
    "error": SHELL_DETERMINISTIC,
}


def _shell_for(route: str) -> str:
    return _SHELL_BY_ROUTE.get(route, SHELL_DETERMINISTIC)


# --------------------------------------------------------------------------- #
# Intent classification (deterministic, keyword rules)                         #
# --------------------------------------------------------------------------- #
def classify(message: str) -> str:
    """WHICH INTENT IS THIS -- for UI affordances. Nothing else.

    This answers the same question with the same substring table it always has,
    and its answer is deliberately NOT a capability decision. The capability
    question ("may this message reach a tool-bearing executor") is answered by
    :func:`daedalus.ikarus_act.may_act`, which is a different function with a
    different return type, a different error budget and its own test suite.
    See that module's docstring for why the two must never be merged, and for
    the worked divergences (e.g. "fix the clone detector" lands here in
    ``distill`` while may_act would clear the sentence).

    Two answers, and a message needs BOTH before a Hand ever sees it.
    """
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
        model: str | None = None, effort: str | None = None,
        conversation_id: str | None = None, *,
        intent: str | None = None, act: ActDecision | None = None) -> dict:
    """Route one chat turn. Always returns a chat-shaped envelope; never raises
    up to the caller for an expected failure. ``effort`` (low/medium/high,
    default low) + ``model`` tune the freeform brain — it's an interface chatbot,
    so keep it cheap by default.

    ``conversation_id`` is OPT-IN and purely additive: omitted (the default),
    this is byte-for-byte the old stateless call. Passed, the turn is appended
    durably via :mod:`daedalus.conversation` (a conversation has an id; turns
    survive a restart) AFTER the reply is computed, so a store hiccup can never
    turn a good reply into a failed one — see :func:`_persist_turn`, which
    records its own failure on the envelope instead of raising.

    ``intent`` / ``act`` are the ALREADY-DERIVED labels, threaded in by a caller
    that has classified this exact message once (the streaming path does). Both
    are keyword-only and default to None, so every existing call site is
    unchanged; passing them is what makes "classify exactly once per request"
    true rather than merely likely. A caller that passes them is asserting they
    describe THIS message — never a cached label from a different one.

    THE BOUNDARY COMES FIRST — above classification, above provider selection,
    above the conversation lookup, exactly as ``daedalus/loop.py`` (72b5af82)
    and ``daedalus/token_monitor.py`` (c67fd116) do it, and for the same
    reason: no branch below can reach a socket or a vendor spawn without having
    passed it. ``process_guard_boundary_decision`` really installs the
    process-wide spend net and returns the decision naming what is now
    interposed, so the receipt cannot cite a guard that never ran, and
    ``begin_effect`` refuses the start unless the ``ikarus_os.ask`` row, the
    declared effects and that decision agree. A refusal returns a refusal
    envelope rather than raising: this function's contract is that it always
    answers, and fail-closed here means the turn stops at the door, not that
    the caller gets an exception it has never had to handle.
    """
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    try:
        begin_effect(ASK_ENTRYPOINT_ID,
                     REGISTRY_BY_ID[ASK_ENTRYPOINT_ID].effects,
                     (process_guard_boundary_decision(),))
    # Deliberately wider than EffectBoundaryError: a deleted row (KeyError), a
    # spend net that cannot install, an import that fails -- every one of them
    # means the door did not open, and the door not opening must stop the turn
    # rather than raise into a caller whose contract says this never raises.
    except Exception as exc:  # noqa: BLE001 - fail closed, then say so
        return _refusal_envelope(project, _deny_receipt(
            ASK_ENTRYPOINT_ID, contract="budget.process_guard", endpoint=None,
            lane="n/a", provider="", reason=str(exc)))

    envelope = _ask_inner(project, message, provider, model, effort,
                          intent=intent, act=act, conversation_id=conversation_id)
    if conversation_id:
        _persist_turn(conversation_id, project, message, provider, envelope)
    return envelope


def _prior_turn(conversation_id: str | None):
    """The last persisted turn of this conversation, or None.

    Best-effort and never raises: :func:`may_act` degrades to its stateless
    rules when the store is unavailable, and that degrade can only make it MORE
    restrictive (a bare confirmation stops clearing anything), never less. The
    fail direction is the whole reason this is allowed to be best-effort.

    CHAT CONTEXT, NOT ORCHESTRATION STATE. What this reads back is "what did the
    user just say, and what did we offer", so that a bare "ja" can be resolved
    against the offer it answers. No policy, budget, promotion or dispatch
    decision is read out of a turn; the capability answer is recomputed from the
    message every time, and the row only supplies the sentence it refers to.
    """
    if not conversation_id:
        return None
    try:
        from . import conversation

        return conversation.default_store().last_turn(conversation_id)
    except Exception:
        return None


def _decide(message: str, intent: str, conversation_id: str | None) -> ActDecision:
    """Ask the CAPABILITY question, once, fail-closed.

    A predicate that raises must not become a predicate that permits, so the
    exception path returns a refusal rather than propagating.
    """
    try:
        return ikarus_act.may_act(message, intent, _prior_turn(conversation_id))
    except Exception as exc:
        return ActDecision(False, f"the capability check failed: {exc}", intent=intent)


def _route(intent: str, act: ActDecision) -> str:
    """Fold the INTENT answer and the CAPABILITY answer into one effective label.

    Called exactly once per request, by whoever derived the two answers, and
    then threaded. This is what makes a ``start``/``final`` disagreement
    structurally impossible instead of merely unobserved: both are built from
    the value this returns.

    The capability answer WINS DOWNWARD only. It can pull a message off the
    tool-bearing route ("does that make sense" classifies as ``enqueue``
    because of a substring, and is refused here), and it can put a confirmed
    offer back ON it — but a confirmation is itself a cleared act decision, so
    nothing reaches ``enqueue`` that ``may_act`` did not allow.
    """
    if act.allowed and act.confirmation_of:
        return "enqueue"
    if intent == "enqueue" and not act.allowed:
        return "chat"
    return intent


def _ask_inner(project: str, message: str, provider: str | None = None,
               model: str | None = None, effort: str | None = None, *,
               intent: str | None = None, act: ActDecision | None = None,
               conversation_id: str | None = None) -> dict:
    """The stateless routing body of :func:`ask`.

    ``conversation_id`` is read-only here: it is used to look up the previous
    turn for :func:`_decide` and nothing else. Persistence stays in
    :func:`ask` / :func:`ask_stream`, so there is still exactly one place a
    turn is written.
    """
    message = (message or "").strip()
    if not message:
        return core.envelope(project, intent="chat", shell=SHELL_DETERMINISTIC, assistant="Say the word — I can report status, distill code, propose a task, or design an agent network.", provider_used="deterministic")
    try:
        if intent is None:
            intent = classify(message)
        if act is None:
            act = _decide(message, intent, conversation_id)
        route = _route(intent, act)

        if route == "status":
            return _status(project, message)
        if route == "distill":
            return _distill(project, message)
        if route == "design":
            return _design(project, message)
        if route == "enqueue":
            # THE ONLY DOOR TO THE HAND SHELL, and `act.allowed` is true on
            # every path that reaches it (see _route). `provider` is not passed:
            # the executor is the system's choice, not the request's.
            return _enqueue(project, act.objective or message, act=act)
        if act.suspected:
            # The Voice REPORTING what may_act said, not the Voice judging.
            return _act_offer(project, message, act)
        return _chat(project, message, provider, model, effort)
    except ProviderStartRefused as exc:
        # A REFUSAL IS NOT A SNAG. Caught above the generic handler so the
        # deny receipt reaches the envelope intact instead of being flattened
        # into "I hit a snag": the host, the lane and the contract that said no
        # are the only things that make the refusal actionable.
        return _refusal_envelope(project, exc.receipt)
    except Exception as exc:  # never 500 the chat on an internal hiccup
        return core.envelope(project, intent="error", shell=SHELL_DETERMINISTIC, assistant=f"I hit a snag: {exc}", provider_used="deterministic")


# --------------------------------------------------------------------------- #
# Durable conversation state (opt-in) -- see daedalus/conversation.py, which   #
# owns no store: every turn is a ``conversation.turn`` intent on the single     #
# canonical event spine (daedalus/spine/ledger.py).                            #
# --------------------------------------------------------------------------- #
def _turn_status(envelope: dict):
    """Map a chat envelope's ``intent`` to conversation.py's closed turn-status
    vocabulary. A separate, tiny function so the mapping is one place and is
    unit-testable without a real store."""
    from . import conversation

    intent = envelope.get("intent")
    if intent == "error":
        return conversation.STATUS_ERROR
    # "proposed" means an action is sitting there waiting for a confirmation.
    # An enqueue turn that REFUSED to propose (the Hand is absent) has nothing
    # to confirm, so recording it as proposed would leave a phantom pending
    # action in the conversation's history. The envelope's own `action` key is
    # the ground truth for that, not the intent label.
    if intent == "enqueue" and envelope.get("action"):
        return conversation.STATUS_PROPOSED
    return conversation.STATUS_ANSWERED


def _persist_turn(conversation_id: str, project: str, message: str,
                  provider: str | None, envelope: dict) -> None:
    """Best-effort durable append of one turn. NEVER raises into the caller:
    conversation state is purely additive to the chat response, so a store
    hiccup (disk full, locked file, WAL error) must not turn a good reply into
    a 500 -- the same fail-open ethos this module already applies to context
    building (see ``_project_context``). Unlike that silent degrade, failure
    HERE is recorded on the envelope (``conversation_persisted=False`` +
    ``conversation_error``) rather than swallowed, because a caller that asked
    for durable state has a right to know it didn't get it this turn.
    """
    try:
        from . import conversation

        turn = conversation.default_store().append_turn(
            conversation_id,
            user_message=message,
            intent=str(envelope.get("intent") or "chat"),
            status=_turn_status(envelope),
            assistant_text=envelope.get("assistant"),
            provider_used=envelope.get("provider_used") or provider,
            model_used=envelope.get("model_used"),
            project=project,
            proposed_action=envelope.get("action"),
            envelope=envelope,
        )
        envelope["conversation_id"] = conversation_id
        envelope["turn_id"] = turn.id
        envelope["turn_seq"] = turn.seq
        envelope["conversation_persisted"] = True
    except Exception as exc:
        envelope["conversation_id"] = conversation_id
        envelope["conversation_persisted"] = False
        envelope["conversation_error"] = str(exc)


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
    return core.envelope(project, intent="status", shell=SHELL_DETERMINISTIC, assistant=reply, status=st, provider_used="deterministic")


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
        return core.envelope(project, intent="distill", shell=SHELL_DETERMINISTIC, assistant=reply, distill=res, provider_used="deterministic")

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
    return core.envelope(project, intent="distill", shell=SHELL_DETERMINISTIC, assistant=reply, structure=summ, provider_used="deterministic")


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


def _resolve_target(message: str, idx: dict) -> tuple[str | None, bool]:
    """Ambiguity-aware target resolution, used ONLY on the brain-context path.

    ``_extract_target`` silently returns ``hits[0]`` when a bare filename matches
    several modules — harmless for the local distill *report*, but here that pick
    decides which SOURCE FILE leaves the machine as injected context. So we (a)
    match on a PATH-SEGMENT boundary (``m == tok`` or ``.../tok``) rather than the
    looser ``endswith(tok)`` — "slice.py" then resolves to ``.../slice.py`` and
    does NOT also snag ``test_..._slice.py`` — and (b) when a token still matches
    >1 module (a real same-basename collision) we REFUSE to guess: return
    ``(None, True)`` so the caller injects no slice and the model answers
    context-free rather than egressing a guessed file.

    Returns ``(target, ambiguous)``. ``_extract_target`` / ``_distill`` are left
    untouched (their pick never egresses source)."""
    modules = idx.get("modules", {})
    for tok in re.findall(r"[\w./\\-]+\.\w+", message):
        tok = tok.replace("\\", "/")
        if tok in modules:
            return tok, False  # exact path — unambiguous
        hits = [m for m in modules if m == tok or m.endswith("/" + tok)]
        if len(hits) == 1:
            return hits[0], False
        if len(hits) > 1:
            return None, True  # same-basename collision — do not guess what to egress
    return None, False


# --------------------------------------------------------------------------- #
# The Hand's liveness — ONE predicate, borrowed, never a second one            #
# --------------------------------------------------------------------------- #
#: Seconds a liveness answer is reused. A chat turn must not pay a network
#: round trip per keystroke-sized request, and the Hand's state does not
#: meaningfully change inside one exchange. Short enough that "I just started
#: Ollama" is true again almost immediately.
_HAND_TTL_S = 5.0
_HAND_CACHE: dict[str, tuple[float, object]] = {}


def _hand_state(probe: bool = True):
    """Is the tool-bearing executor there? In the five-word vocabulary.

    Delegates to :func:`daedalus.health.hand_state`, which is composed from the
    SAME ``_ollama_alive`` the bench probes use. Deliberately not reimplemented
    here: this repo's recurring disease is two predicates for one question, and
    a chat path that disagrees with the health surface about whether the bench
    is up is exactly that disease.

    Fails to ``unknown`` if health itself cannot be consulted — never to
    ``working``, because uncertainty about liveness must not read as health.

    ``probe=False`` answers FROM THE CACHE ONLY and returns ``None`` rather than
    making a network call. MEASURED 2026-07-29 on this box: a local port with
    nothing listening does not refuse, it TIMES OUT -- 2.0s for 127.0.0.1:11435,
    :49999 and :1 alike -- so a liveness check on every turn would tax exactly
    the machines that have no executor to show for it. The advisory paths (a
    proposal, which commits nothing) therefore look but do not knock, and say
    nothing at all when they do not know; only the paths where the answer
    CHANGES THE OUTCOME pay for it. Returning None is the honest shape: this
    module does not get to report a state it did not measure.
    """
    now = _time.monotonic()
    hit = _HAND_CACHE.get("hand")
    if hit and (now - hit[0]) < _HAND_TTL_S:
        return hit[1]
    if not probe:
        return None
    try:
        from . import health

        # Shorter than health's own default: a chat turn must never hang on a
        # liveness question. A host that has not answered in 2s is `unknown`,
        # which is honest -- and `unknown` is not clearance (see _enqueue).
        state = health.hand_state(timeout_s=2.0)
    except Exception as exc:
        from collections import namedtuple as _nt

        state = _nt("HandState", "state detail host")(
            "unknown", f"the liveness check could not run: {exc}", "")
    _HAND_CACHE["hand"] = (now, state)
    return state


def _hand_block(state) -> dict:
    return {"state": state.state, "detail": state.detail, "host": state.host}


def _enqueue(project: str, message: str, act: ActDecision | None = None) -> dict:
    """Propose a confirm-gated task on the Hand's lane.

    Takes NO ``provider``: see the module docstring's provider fence. The
    executor for act-cleared work is the system's choice, and there is no
    argument here through which a request could express one.
    """
    objective = message.strip()
    confirmed = bool(act is not None and act.confirmation_of)
    # Only the confirmed route knocks: see _hand_state's MEASURED note on cost.
    hand = _hand_state(probe=confirmed)

    if confirmed and (hand is None or hand.state != "working"):
        # THE REFUSAL, IN WORDS. The user has confirmed; this is the moment the
        # system would otherwise commit work to something that is not there.
        # Saying "queued!" here, or letting the Voice answer as though it had
        # done the work, is the failure mode this branch exists to prevent.
        #
        # It refuses on ANYTHING BUT `working`, not only on `absent`. That is a
        # deliberate widening, forced by measurement rather than by taste: on
        # Windows a local port with nothing listening TIMES OUT instead of
        # refusing, so `absent` is nearly unreachable here and a guard keyed to
        # it would have been a guard in name only. The vocabulary is unchanged
        # -- `unknown` still is not `absent`, and the wording below says which
        # of the two we got -- but neither is CLEARANCE. Committing confirmed
        # work on "I could not find out" is the Voice pretending, one level up.
        state = "unknown" if hand is None else hand.state
        detail = "the liveness check did not run" if hand is None else hand.detail
        head = ("the local executor is unreachable" if state == "absent"
                else "I could not confirm the local executor is up")
        return core.envelope(
            project, intent="enqueue", shell=SHELL_HAND,
            assistant=(f"I can't route that: {head}: {detail}"
                       f"{f' (host {hand.host})' if hand is not None and hand.host else ''}. "
                       "Nothing was queued and nothing ran. Start the local bench "
                       "and confirm again."),
            hand={"state": state, "detail": detail,
                  "host": hand.host if hand is not None else ""},
            act=act.to_dict(), provider_used="deterministic")

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
    extra = {"act": act.to_dict()} if act is not None else {}
    if hand is not None:
        extra["hand"] = _hand_block(hand)
        if hand.state != "working":
            # Loud, but not a refusal: nothing has been committed yet, and the
            # bench may well be up by the time the user confirms. What is not
            # allowed is proposing into the void SILENTLY.
            reply += (f" Note: the local executor is {hand.state} right now "
                      f"({hand.detail}) — it will need to be up before this can run.")
    return core.envelope(project, intent="enqueue", shell=SHELL_HAND, assistant=reply,
                         action=action, provider_used="deterministic", **extra)


def _act_offer(project: str, message: str, act: ActDecision) -> dict:
    """The Voice REPORTING a refusal it did not make.

    A message that reads like an act request but does not meet the allow rule
    (the German "kannst du das mal bauen" carries no English keyword, so
    ``classify`` says chat and ``may_act`` refuses it) must not be answered as
    if nothing had been asked. This says what happened, in words, and offers
    the confirm path — whose confirmation re-enters :func:`may_act` and then
    the ordinary enqueue path, never a path around either.

    Deterministic on purpose: it must read the same whether or not a brain is
    configured, and it must cost nothing.
    """
    objective = (act.objective or message).strip()
    reply = (
        "That reads like a request to build something, but I can't queue it from "
        f"here: {act.reason} ({act.signal}). Say “yes” and I'll route it the normal "
        "way — a confirm-gated task on the free local bench (lane local_only, "
        "verify-or-rollback, zero spend)."
    )
    return core.envelope(
        project, intent="chat", shell=SHELL_VOICE, assistant=reply,
        provider_used="deterministic", model_used=None,
        act=act.to_dict(),
        # Read back by ikarus_act.pending_offer on the NEXT turn. This is the
        # only thing that lets a bare "yes" mean anything, and it names the
        # objective explicitly so the confirmation can never clear something
        # other than what was offered.
        act_offer={"objective": objective, "reason": act.reason, "signal": act.signal})


def _design(project: str, message: str) -> dict:
    from . import ikarus_chat

    res = ikarus_chat.chat(project, message, apply=False)
    res["intent"] = "design"
    res.setdefault("shell", SHELL_DETERMINISTIC)
    res.setdefault("provider_used", "deterministic")
    return res


# --------------------------------------------------------------------------- #
# Freeform 'brain' — selectable connected runtime, text-only                   #
# --------------------------------------------------------------------------- #
def _project_context(project: str, message: str, lane: str = "trusted") -> _Ctx:
    """Build a GATED distilled slice of the file ``message`` references, for
    injection as brain context. The ONLY content source is the already-gated
    ``semantic_slice`` (its SECRET FLOOR runs on every lane) — we NEVER read the
    target file ourselves, which would bypass the egress gate.

    Returns ``_EMPTY_CTX`` (text="") — reproducing today's neutral, context-free
    behaviour — when there is no file token, when the filename is ambiguous (we
    won't guess which file to egress), or on any build hiccup. The caller picks
    the lane. Claude is TRUSTED (``lane="trusted"`` -- floor on, default-deny
    off, recall preserved). DeepSeek and Codex CLI are EXTERNAL and NOT trusted
    with IP, so ``_llm()`` calls this with ``lane="untrusted"`` (floor on,
    default-deny ALSO on).

    Ollama is trusted ONLY WHEN ITS RESOLVED HOST IS THIS MACHINE, which is why
    the local branches call :func:`_local_lane` instead of naming a lane. This
    sentence used to read "Claude and local Ollama are TRUSTED", and that word
    "local" was doing security work no code performed: ``OLLAMA_HOST`` is an
    environment variable, so pointing it at the RTX bench kept the trusted lane
    while sending distilled source off-machine."""
    # Cheap guard: no path/file-shaped token -> no context, WITHOUT indexing the
    # repo. Keeps every non-file chat turn as fast and inert as before BOOTSTRAP.
    if not re.search(r"[\w./\\-]+\.\w+", message):
        return _EMPTY_CTX
    try:
        from .structcore.index import cached_index
        from .structcore.slice import semantic_slice

        repo_root = resolve_repo_root(None, project)
        idx = cached_index(repo_root)
        target, ambiguous = _resolve_target(message, idx)
        if ambiguous:
            return _Ctx("", 0, None, 0, 0, True)
        if not target:
            return _EMPTY_CTX
        res = semantic_slice(repo_root, target, idx=idx, lane=lane,
                             max_tokens=_CONTEXT_MAX_TOKENS)
        slice_text = (res.get("slice_text") or "").strip()
        if not slice_text:
            return _EMPTY_CTX
        return _Ctx(
            text=f"{_CONTEXT_FRAMING}\n{slice_text}",
            withheld_count=int(res.get("withheld_count", 0)),
            focus_file=res.get("focus_file"),
            included_count=int(res.get("n_included", 0)),
            trimmed_count=int(res.get("trimmed_count", 0)),
            ambiguous=False,
        )
    except Exception:
        # Never break the chat on a context-build hiccup: degrade to no context.
        return _EMPTY_CTX


def _ctx_envelope_block(ctx: _Ctx) -> dict | None:
    """The context metadata carried to the USER in the chat envelope, or None
    when there is nothing to report (no file referenced) — so a plain chat turn's
    envelope is unchanged."""
    if not (ctx.focus_file or ctx.ambiguous):
        return None
    return {
        "focus_file": ctx.focus_file,
        "included": ctx.included_count,
        "withheld_count": ctx.withheld_count,
        "trimmed": ctx.trimmed_count,
        "ambiguous": ctx.ambiguous,
    }


def _with_context(message: str, context: str) -> str:
    """Prepend gated project context to the user turn (empty context -> the
    message unchanged). Used for the Ollama system/user split."""
    return f"{context}\n\n{message}" if context else message


def _claude_prompt(message: str, effort: str | None, context: str = "") -> str:
    """Assemble the single-string Claude CLI prompt. With no context this is
    byte-identical to the pre-BOOTSTRAP prompt; with context the distilled slice
    is injected between the system framing and the user turn."""
    concise = "\nBe concise." if (effort or "low").lower() == "low" else ""
    if context:
        return f"{SYSTEM}{concise}\n\n{context}\n\nUser: {message}"
    return f"{SYSTEM}{concise}\n\nUser: {message}"


def _chat(project: str, message: str, provider: str | None,
          model: str | None = None, effort: str | None = None) -> dict:
    reply, model_used, ctx = _llm(provider, message, model, effort, project)
    if reply:
        block = _ctx_envelope_block(ctx)
        extra = {"context": block} if block else {}
        return core.envelope(project, intent="chat", shell=SHELL_VOICE, assistant=reply,
                             provider_used=(provider or "").lower(),
                             model_used=model_used, **extra)
    return core.envelope(project, intent="chat", shell=SHELL_VOICE, assistant=_help_text(),
                         provider_used="deterministic", model_used=None)


# effort -> output-token cap (it's an interface chatbot; low keeps it snappy/cheap)
_EFFORT_CAP = {"low": 300, "medium": 700, "high": 1400}


def _effort_cap(effort: str | None) -> int:
    return _EFFORT_CAP.get((effort or "low").lower(), 300)


def _unconfigured_reply(brain: str, remedy: str) -> str:
    """A clear, honest 'this brain is not set up' answer -- never a crash, and
    never a silent switch to a different provider's answer wearing this one's
    name. Used for the fast pre-flight checks in ``_llm`` (missing key /
    missing CLI, checked before any egress or subprocess spawn); a runtime
    failure AFTER that check still falls through to the existing
    ``return None`` -> deterministic-help-text path, same as Ollama/Claude."""
    return (f"{brain} isn't set up yet -- {remedy}. Pick a different brain in "
            "the header, or fix that and try again.")


def _llm(provider: str | None, message: str, model: str | None = None,
         effort: str | None = None,
         project: str | None = None) -> tuple[str | None, str | None, _Ctx]:
    """Return (reply_text, model_used, ctx). (None, None, _EMPTY_CTX) -> caller
    falls back to help. ``ctx`` carries the gated-slice metadata for the envelope.

    Context is built HERE (where the chosen lane is known) so its metadata reaches
    the envelope, then passed as TEXT into the runtime functions — keeping their
    signatures clean and never re-reading source outside the gate."""
    p = (provider or "").lower()
    if p in ("", "auto", "none", "deterministic"):
        return None, None, _EMPTY_CTX
    if p in _LOCAL:
        from .providers.ollama import DEFAULT_MODEL

        mdl = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        ctx = _project_context(project, message, lane=_local_lane())
        return _ollama(message, mdl, effort, ctx.text), mdl, ctx
    if p in _CLAUDE:
        ctx = _project_context(project, message, lane="trusted")
        return _claude(message, effort, model, ctx.text), (model or "claude"), ctx
    if p in _DEEPSEEK:
        from .providers.deepseek import DEFAULT_MODEL

        if not os.environ.get("DEEPSEEK_API_KEY"):
            return _unconfigured_reply(
                "DeepSeek", "set the DEEPSEEK_API_KEY environment variable"), None, _EMPTY_CTX
        mdl = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        ctx = _project_context(project, message, lane="untrusted")
        return _deepseek(message, mdl, effort, ctx.text), mdl, ctx
    if p in _CODEX:
        if not shutil.which("codex"):
            return _unconfigured_reply(
                "Codex CLI", "install the Codex CLI and run `codex login`"), None, _EMPTY_CTX
        mdl = model or os.environ.get("CODEX_MODEL", "")
        ctx = _project_context(project, message, lane="untrusted")
        return _codex(message, effort, mdl, ctx.text), (mdl or "codex"), ctx
    return None, None, _EMPTY_CTX  # gemini / api slots: not wired yet


def _local_lane() -> str:
    """The lane for the LOCAL branch, derived from the endpoint that will
    actually be called -- never from the fact that the provider is named
    "ollama".

    ``_ollama``/``_ollama_stream`` resolve their host from ``OLLAMA_HOST``, an
    environment variable. Hardcoding ``lane="trusted"`` here meant that pointing
    that variable at the RTX bench silently turned this chat path's distilled
    context into a NETWORK EGRESS lane: default-deny off, only the secret floor
    left, source shipped off-machine, and nothing in the code or the transcript
    saying so. See :func:`daedalus.sensitivity.lane_for_host`.
    """
    from .providers.ollama import DEFAULT_HOST
    from .sensitivity import lane_for_host

    return lane_for_host(os.environ.get("OLLAMA_HOST", DEFAULT_HOST))


# --------------------------------------------------------------------------- #
# THE EFFECT BOUNDARY for this module                                          #
#                                                                              #
# daedalus/budget.py has named ikarus_os.py as one of the four independent      #
# vendor-spend origins since the ceiling was written, and until now this file   #
# had no canonical start at all: a chat turn could spend money and open a       #
# socket without one row in the registry. Two levels, matching the two          #
# questions:                                                                    #
#                                                                               #
#   THE DOOR (``ask`` / ``_ask_stream_inner``) authorises the TURN. It runs     #
#   before classification and before provider selection, and its guard          #
#   decision really installs the process-wide spend net, so every later         #
#   urlopen/spawn in this process -- including ones this module does not know   #
#   about -- is priced against the ceiling.                                     #
#                                                                               #
#   THE TRANSPORT (``_provider_start``) authorises ONE call to ONE endpoint.    #
#   It cannot live at the door: the endpoint is not known there, and a status   #
#   turn must not be refused for an egress it never performs.                   #
#                                                                               #
# Neither is a sandbox. The door is a chokepoint for the paths that go through  #
# it, and the registry anchors make deleting either one a conformance blocker   #
# rather than a silent regression.                                              #
# --------------------------------------------------------------------------- #
ASK_ENTRYPOINT_ID = "ikarus_os.ask"
ASK_STREAM_ENTRYPOINT_ID = "ikarus_os.ask_stream"
PROVIDER_ENTRYPOINT_ID = "ikarus_os.provider_call"

#: What each provider branch actually does, requested per branch rather than as
#: the row's union: ollama over loopback spends nothing, and a CLI spawn opens
#: no socket in THIS process. Asking for an effect you do not perform is how a
#: registry stops meaning anything.
_PROVIDER_EFFECTS: dict[str, tuple[str, ...]] = {
    "ollama": ("network_egress",),
    "deepseek": ("network_egress", "spend", "secrets"),
    "claude": ("process_spawn", "spend"),
    "codex": ("process_spawn", "spend"),
}

#: The budget vendor key per branch -- the same names ``classify_argv`` /
#: ``classify_url`` give the interposer, so the pre-flight and the net cannot
#: disagree about what a call costs.
_PROVIDER_VENDORS: dict[str, str] = {
    "ollama": "local_inference",
    "deepseek": "deepseek",
    "claude": "anthropic_cli",
    "codex": "openai_cli",
}


class ProviderStartRefused(RuntimeError):
    """One provider transport was refused BEFORE it existed.

    Carries the content-addressed deny receipt as ``.receipt``. Raised out of
    the sink functions and caught once, in :func:`_ask_inner`, which turns it
    into an ordinary refusal envelope -- :func:`ask` still never raises.
    """

    def __init__(self, receipt: dict):
        super().__init__(str(receipt.get("reason") or "provider start refused"))
        self.receipt = receipt


def _deny_receipt(entrypoint_id: str, *, contract: str, endpoint: str | None,
                  lane: str, reason: str, provider: str = "") -> dict:
    """A content-addressed record of a refusal, shaped like the embedding
    backend's (daedalus/memory/embeddings.py) so both egress refusals in this
    repo read the same. ``connected`` is a claim about control flow: the
    decision is taken before the request object or the argv exists."""
    receipt = {
        "entrypoint_id": entrypoint_id,
        "verdict": "deny",
        "contract": contract,
        "provider": provider,
        "host": endpoint,
        "lane": lane,
        "reason": reason,
        "connected": False,
        "spawned": False,
        "security_boundary_claimed": False,
        "at": core.now_iso(),
    }
    try:
        from .spine.effect_boundary import registry_sha256

        receipt["registry_sha256"] = registry_sha256()
    except Exception:  # a registry that cannot be hashed still refuses
        receipt["registry_sha256"] = ""
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in receipt.items() if k != "at"},
                   sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return receipt


def _spend_decision(vendor: str, model: str | None, *, host: str | None = None,
                    calls: int = 1):
    """The ``budget.process_guard`` decision for one about-to-happen call.

    It installs the net (that is what makes the receipt's evidence true) and
    then asks the ledger the SAME two questions ``Ledger.reserve`` asks -- does
    this dollar estimate cross the ceiling, does this call cross the call cap --
    as a READ. It deliberately does not reserve: the interposer reserves at the
    socket/spawn, so reserving here would count the same call twice. What this
    buys is that the refusal happens before the connection instead of inside
    it, and arrives as a named verdict instead of a swallowed exception.

    FAILS CLOSED. An unreadable ledger, an unpriceable vendor, or any other
    error is a denial, never a pass -- absence of a budget is not absence of a
    ceiling.
    """
    from .spine.effect_boundary import GuardDecision

    try:
        from . import budget

        installed = budget.process_guard_boundary_decision()
    except Exception as exc:
        return GuardDecision(
            "budget.process_guard", False,
            f"the process spend net could not be installed ({type(exc).__name__}: "
            f"{exc}), so no vendor call may start")
    if not installed.allowed:
        return installed
    try:
        est = budget.price_call(vendor, model, calls=calls, host=host)
        state = budget.ledger().state()
    except Exception as exc:
        return GuardDecision(
            "budget.process_guard", False,
            f"the budget ledger could not be read for vendor {vendor!r} "
            f"({type(exc).__name__}: {exc}); an unknown ceiling is not an "
            f"absent ceiling")
    over_dollars = (est.usd > 0
                    and state.committed_usd + est.usd > state.ceiling_usd)
    billable = est.basis != "free_local"
    over_calls = (billable
                  and state.calls + state.open_calls + calls > state.max_calls)
    if over_dollars or over_calls:
        crossed = "spend ceiling" if over_dollars else "call-count cap"
        return GuardDecision(
            "budget.process_guard", False,
            f"the {crossed} would be crossed by this {vendor} call: estimate "
            f"${est.usd:.4f} (basis={est.basis}), committed "
            f"${state.committed_usd:.4f} of ${state.ceiling_usd:.4f}, "
            f"{state.calls + state.open_calls} of {state.max_calls} calls used "
            f"in period {state.period_key}")
    return GuardDecision(
        "budget.process_guard", True,
        f"{installed.evidence}; ledger headroom checked before the call: "
        f"estimate ${est.usd:.4f} (basis={est.basis}) against "
        f"${state.ceiling_usd - state.committed_usd:.4f} remaining and "
        f"{state.max_calls - state.calls - state.open_calls} calls left")


def _egress_decision(provider_key: str, endpoint: str | None):
    """The ``provider.egress_policy`` decision, and the lane it found.

    For the Ollama transport this is NOT a second opinion: it delegates to
    :func:`daedalus.providers.ollama.ollama_endpoint_admission`, the one
    implementation of "may bytes reach this endpoint at all" (lane_for_host
    plus exact-endpoint operator consent), which the embedding backend also
    calls. Two copies of that answer would be free to drift.

    DeepSeek's endpoint is a declared vendor API, so the question there is
    credentials: no key means nothing may be sent. The two CLIs open no socket
    in this process -- the vendor binary carries its own transport and its own
    auth -- so the decision states exactly that and refuses when the binary
    did not resolve.
    """
    from .spine.effect_boundary import GuardDecision

    if provider_key == "ollama":
        from .providers.ollama import ollama_endpoint_admission

        allowed, lane, why = ollama_endpoint_admission(endpoint)
        return GuardDecision("provider.egress_policy", allowed, why), lane
    if provider_key == "deepseek":
        from .sensitivity import lane_for_host

        lane = lane_for_host(endpoint)
        keyed = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
        return GuardDecision(
            "provider.egress_policy", keyed,
            f"lane_for_host({endpoint!r}) == {lane!r}: the declared DeepSeek "
            f"API endpoint; DEEPSEEK_API_KEY is "
            + ("present, and the context slice for this turn was built on the "
               "untrusted lane (secret floor + default-deny)"
               if keyed else
               "absent, so this process holds no credential for that endpoint "
               "and may send nothing to it")), lane
    lane = "untrusted"
    return GuardDecision(
        "provider.egress_policy", bool(endpoint),
        f"vendor CLI {endpoint!r}: this process opens no socket for it and "
        f"reads no key for it -- the binary carries its own transport and "
        f"auth. It is spawned from a neutral cwd (never the project repo), so "
        f"what leaves with it is the prompt plus the gated context slice and "
        f"nothing the cwd would have added"
        if endpoint else
        "the vendor CLI did not resolve on PATH, so nothing can leave with it"
    ), lane


def _provider_start(provider_key: str, *, endpoint: str | None,
                    model: str | None = None, calls: int = 1):
    """Authorise ONE provider transport, or raise :class:`ProviderStartRefused`.

    Called as the first statement of every function in this module that reaches
    a socket or spawns a vendor -- before the request object, before the argv.
    That placement, not a mock, is what makes "a refused turn costs zero
    connections" true.

    The decisions are not taken here: ``ollama_endpoint_admission`` and the
    budget ledger own them, in the modules that already own them.
    ``begin_effect`` owns the start -- it re-checks the row, the requested
    effects and the contracts, and refuses a decision that says no. This
    function only carries the answers between them and shapes a refusal into
    something a reader can act on.
    """
    from .spine.effect_boundary import EffectBoundaryError, begin_effect

    vendor = _PROVIDER_VENDORS.get(provider_key, provider_key)
    effects = _PROVIDER_EFFECTS.get(provider_key)
    if effects is None:
        raise ProviderStartRefused(_deny_receipt(
            PROVIDER_ENTRYPOINT_ID, contract="provider.egress_policy",
            endpoint=endpoint, lane="unknown", provider=provider_key,
            reason=f"no declared effect set for provider {provider_key!r}"))
    egress, lane = _egress_decision(provider_key, endpoint)
    # The host is passed to the pricer for the HTTP lanes on purpose: the
    # question is never "which provider is this" but "where do the bytes go".
    spend = _spend_decision(
        vendor, model,
        host=endpoint if provider_key in ("ollama", "deepseek") else None,
        calls=calls)
    try:
        return begin_effect(PROVIDER_ENTRYPOINT_ID, effects, (spend, egress))
    except EffectBoundaryError as exc:
        denied = next((d for d in (egress, spend) if not d.allowed), None)
        raise ProviderStartRefused(_deny_receipt(
            PROVIDER_ENTRYPOINT_ID,
            contract=denied.contract if denied else "effect_boundary",
            endpoint=endpoint, lane=lane, provider=provider_key,
            reason=str(exc))) from exc


def _refusal_envelope(project: str, receipt: dict) -> dict:
    """A refused turn, spoken. The host/endpoint is named in the text as well as
    in the receipt: a withheld call nobody can attribute to an endpoint is a
    refusal nobody can fix."""
    where = receipt.get("host") or receipt.get("entrypoint_id")
    return core.envelope(
        project, intent="error", shell=SHELL_DETERMINISTIC,
        assistant=(f"I didn't make that call. The {receipt.get('contract')} "
                   f"contract refused it before anything left this machine "
                   f"(endpoint: {where}). Reason: {receipt.get('reason')}"),
        provider_used="deterministic", model_used=None, refusal=receipt)


def _ollama(message: str, model: str, effort: str | None,
            context: str = "") -> str | None:
    from .providers.ollama import DEFAULT_HOST, warm_model_async

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    # BEFORE warm_model_async, which connects on a daemon thread, and before
    # the request is built. A repointed OLLAMA_HOST is refused here.
    _provider_start("ollama", endpoint=host, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    # Refresh VRAM residency off-thread. Purely a side effect: the reply text and
    # envelope are byte-for-byte what they were, but the NEXT turn skips the
    # ~44s cold reload instead of paying it after 5 idle minutes.
    warm_model_async(host, model)
    try:
        txt = chat_completion(
            base_url=host.rstrip("/") + "/v1", model=model,
            system=system, user=_with_context(message, context),
            force_json=False, temperature=0.3,
            timeout_s=120, extra={"max_tokens": _effort_cap(effort)},
        )
        return (txt or "").strip() or None
    except Exception:
        return None


def _deepseek(message: str, model: str, effort: str | None,
              context: str = "") -> str | None:
    """DeepSeek chat brain -- the SAME OpenAI-compatible client Ollama's chat
    brain uses (``providers._openai_compat.chat_completion``), just pointed at
    DeepSeek's base URL with the API key it requires. No new HTTP client.

    ``base_url`` is used AS-IS (no ``/v1`` suffix appended) -- matching
    ``DeepSeekProvider.run()`` in providers/deepseek.py exactly, since
    DeepSeek's REST root already serves ``/chat/completions`` directly."""
    from .providers.deepseek import DEFAULT_BASE_URL

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    # The paid lane, refused before the socket when the ledger has no room.
    _provider_start("deepseek", endpoint=base_url, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    try:
        txt = chat_completion(
            base_url=base_url, model=model, system=system, user=_with_context(message, context),
            api_key=api_key, force_json=False, temperature=0.3,
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


def _claude(message: str, effort: str | None = None, model: str | None = None,
            context: str = "") -> str | None:
    path = shutil.which("claude")
    if not path:
        return None
    # Before the argv exists: a refused start costs zero spawns.
    _provider_start("claude", endpoint=path, model=model)
    prompt = _claude_prompt(message, effort, context)
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


def _codex(message: str, effort: str | None = None, model: str | None = None,
           context: str = "") -> str | None:
    """Codex CLI chat brain -- the lightweight, read-only, non-agentic sibling
    of ``CodexCLIProvider`` (providers/codex_cli.py), which stays reserved for
    the agentic, write-capable offload/task path. Mirrors ``_claude`` above:
    a neutral cwd (never the project repo -- codex is agentic and would
    otherwise read whatever its cwd contains), ``--sandbox read-only`` so it
    can never write, and the SAME ``--output-last-message`` capture convention
    codex_cli.py already uses (no ``--output-schema`` here -- a freeform chat
    reply is plain text, not the agent_report_v1 json)."""
    path = shutil.which("codex")
    if not path:
        return None
    _provider_start("codex", endpoint=path, model=model)
    prompt = _claude_prompt(message, effort, context)  # model-agnostic SYSTEM+context+turn assembly
    try:
        with tempfile.TemporaryDirectory(prefix="daedalus-codex-chat-") as td:
            message_path = Path(td) / "last_message.txt"
            args = [
                path, "exec",
                "--cd", _neutral_cwd(),
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-last-message", str(message_path),
            ]
            if model:
                args += ["--model", model]
            args.append(prompt)
            subprocess.run(
                args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=150, stdin=subprocess.DEVNULL, check=False,
            )
            return (message_path.read_text(encoding="utf-8") or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- #
# Streaming brain — same routing as ask(), tokens pushed as they are produced   #
# --------------------------------------------------------------------------- #
def ask_stream(project: str, message: str, provider: str | None = None,
               model: str | None = None, effort: str | None = None,
               conversation_id: str | None = None):
    """Streaming twin of :func:`ask`, including its ``conversation_id`` opt-in.

    A thin tap around :func:`_ask_stream_inner`: every event is passed through
    unchanged, and the moment a ``"final"`` envelope is produced (there is
    exactly one, from whichever branch of the inner generator emitted it), the
    turn is persisted exactly like the blocking :func:`ask` does — one
    persistence code path for both entry points, via :func:`_persist_turn`.
    """
    for event, payload in _ask_stream_inner(project, message, provider, model, effort,
                                            conversation_id=conversation_id):
        if event == "final" and conversation_id:
            _persist_turn(conversation_id, project, message, provider, payload)
        yield event, payload


def _reconcile_final(started: str, envelope: dict) -> dict:
    """THE TRIPWIRE on ``start``/``final`` disagreement. Should be unreachable.

    ``start`` is a COMMITMENT. A client has already rendered an affordance from
    it, and a voice UI will already have begun speaking from it — there is no
    un-speaking. So a ``final`` whose intent contradicts it cannot be allowed to
    smuggle a capability past the announcement: the historic shape of this bug is
    a Confirm button rendered from a ``final`` whose ``start`` said "chat".

    Now that :func:`_route` is computed once and threaded, the only label that
    may legitimately supersede the announcement is ``error`` — a failure must
    always be able to speak. Anything else is a defect, and this handles it by
    FAILING CLOSED rather than by papering over it: the announced label stands,
    anything capability-bearing (``action``) is DROPPED, and the disagreement is
    recorded on the envelope so it is loud instead of silent. The worst outcome
    of a divergence is then a lost proposal, which the user recovers by asking
    again — never an unannounced Confirm button.
    """
    final_intent = str(envelope.get("intent") or "")
    if final_intent == started or final_intent == "error":
        return envelope
    dropped = envelope.pop("action", None)
    envelope["intent"] = started
    envelope["shell"] = _shell_for(started)
    envelope["intent_mismatch"] = {"start": started, "final": final_intent,
                                   "dropped_action": dropped is not None}
    return envelope


def _ask_stream_inner(project: str, message: str, provider: str | None = None,
                      model: str | None = None, effort: str | None = None, *,
                      conversation_id: str | None = None):
    """Streaming twin of :func:`_ask_inner`. Yields ``(event, payload)`` tuples:

      ``("start", {...})``  once, before any text
      ``("delta", {"text": ...})``  zero or more, as tokens arrive
      ``("final", <envelope>)``  exactly once, the same shape ``ask()`` returns

    ``ask()`` itself is untouched — this is purely additive. Deterministic
    intents (status/distill/design/enqueue) are computed locally and fast, so
    they emit start+final with no deltas; only the freeform brain streams. That
    keeps ONE endpoint correct for every message the UI sends.

    CLASSIFIES EXACTLY ONCE. ``(intent, act)`` are derived here, folded into one
    effective ``route``, and then THREADED into every ``ask()`` call below —
    which is why those calls pass ``intent=``/``act=``. This used to classify
    here and again inside ``ask()``, with the ``start`` event committing to the
    first answer and the ``final`` envelope built independently from the second.
    Both were pure and deterministic, so they always agreed; the moment either
    consulted conversation state (as ``act`` now does) they would not have, and
    the disagreement would have surfaced as a client rendering a Confirm button
    under a turn it had announced as chat.

    ``conversation_id`` is READ-ONLY here — it reaches :func:`_decide` so a
    confirmation can be recognised. Persistence stays in :func:`ask_stream`.

    Fail-closed: any streaming failure (unsupported flag, dead runtime, mid-
    stream error) degrades to the blocking path rather than erroring the chat.

    THE BOUNDARY COMES FIRST, here and not in :func:`ask_stream`. The tap
    around this generator only persists the final turn; THIS is the function
    that selects a provider and builds a streamer, so a caller that drives the
    inner generator directly must pass the same door. A refusal is spoken as
    start+final instead of raised, because a generator that raises on its first
    ``next()`` is not something the SSE surface can render.
    """
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    try:
        begin_effect(ASK_STREAM_ENTRYPOINT_ID,
                     REGISTRY_BY_ID[ASK_STREAM_ENTRYPOINT_ID].effects,
                     (process_guard_boundary_decision(),))
    except Exception as exc:  # noqa: BLE001 - see ask(): fail closed, then say so
        yield "start", {"intent": "error", "shell": SHELL_DETERMINISTIC,
                        "provider_used": "deterministic"}
        yield "final", _refusal_envelope(project, _deny_receipt(
            ASK_STREAM_ENTRYPOINT_ID, contract="budget.process_guard",
            endpoint=None, lane="n/a", provider="", reason=str(exc)))
        return

    message = (message or "").strip()
    if not message:
        yield "start", {"intent": "chat", "shell": SHELL_DETERMINISTIC,
                        "provider_used": "deterministic"}
        yield "final", _reconcile_final(
            "chat", ask(project, message, provider, model, effort))
        return

    try:
        intent = classify(message)
    except Exception:
        intent = "chat"
    act = _decide(message, intent, conversation_id)
    route = _route(intent, act)

    # Deterministic lanes: no token stream to give, just compute and finish.
    # ``route``, not ``intent`` — an enqueue-classified message the capability
    # predicate refused belongs to the Voice, and announcing "enqueue" here
    # would commit the client to an affordance the final will not carry.
    if route != "chat":
        yield "start", {"intent": route, "shell": _shell_for(route),
                        "provider_used": "deterministic"}
        yield "final", _reconcile_final(
            route, ask(project, message, provider, model, effort,
                       intent=intent, act=act))
        return

    # A suspected act request is answered deterministically (the Voice reporting
    # may_act's refusal + the confirm offer), so there is nothing to stream and
    # no brain to pay for — regardless of which provider the client named.
    if act.suspected:
        yield "start", {"intent": "chat", "shell": SHELL_VOICE,
                        "provider_used": "deterministic"}
        yield "final", _reconcile_final(
            "chat", ask(project, message, provider, model, effort,
                        intent=intent, act=act))
        return

    p = (provider or "").lower()
    streamer = None
    model_used = None
    ctx = _EMPTY_CTX
    if p in _LOCAL:
        from .providers.ollama import DEFAULT_MODEL

        model_used = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        ctx = _project_context(project, message, lane=_local_lane())
        streamer = _ollama_stream(message, model_used, effort, ctx.text)
    elif p in _CLAUDE:
        model_used = model or "claude"
        ctx = _project_context(project, message, lane="trusted")
        streamer = _claude_stream(message, effort, model, ctx.text)
    elif p in _DEEPSEEK and os.environ.get("DEEPSEEK_API_KEY"):
        from .providers.deepseek import DEFAULT_MODEL

        model_used = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        ctx = _project_context(project, message, lane="untrusted")
        streamer = _deepseek_stream(message, model_used, effort, ctx.text)
    # Codex CLI has no verified streaming JSON frame format (unlike Claude's,
    # confirmed against 2.1.201 -- see _claude_stream's comment), so an
    # unverified parser here risks yielding garbled deltas. It deliberately
    # stays on the blocking path via the `streamer is None` fallback below,
    # where `ask()` -> `_llm()` still answers it correctly, just without
    # per-token streaming. An unconfigured DeepSeek (missing key) falls
    # through the same way on purpose: the blocking call produces the clear
    # "not set up" reply via `_llm()`'s pre-flight check instead of this
    # function duplicating it.

    yield "start", {"intent": "chat",
                    "shell": SHELL_VOICE,
                    "provider_used": p or "deterministic",
                    "model_used": model_used}

    if streamer is None:
        # No streaming brain selected (deterministic/auto, or an unwired slot
        # like codex/gemini) — identical outcome to ask().
        yield "final", _reconcile_final(
            route, ask(project, message, provider, model, effort,
                       intent=intent, act=act))
        return

    chunks: list[str] = []
    failed = False
    try:
        for piece in streamer:
            if piece:
                chunks.append(piece)
                yield "delta", {"text": piece}
    except ProviderStartRefused as exc:
        # The transport boundary refused on the generator's FIRST step, before
        # any request object existed — so no delta was ever produced and there
        # is nothing to fall back to. Speak the refusal instead of degrading to
        # the blocking path, which would only reach the same verdict one
        # classification later.
        yield "final", _reconcile_final(route, _refusal_envelope(project, exc.receipt))
        return
    except Exception:
        failed = True  # fall through to the blocking path

    text = "".join(chunks).strip()
    if failed or not text:
        # Nothing usable streamed -> blocking fallback keeps the chat alive.
        yield "final", _reconcile_final(
            route, ask(project, message, provider, model, effort,
                       intent=intent, act=act))
        return

    block = _ctx_envelope_block(ctx)
    extra = {"context": block} if block else {}
    yield "final", _reconcile_final(route, core.envelope(
        project, intent="chat", shell=SHELL_VOICE, assistant=text,
        provider_used=p, model_used=model_used, **extra))


def _ollama_stream(message: str, model: str, effort: str | None, context: str = ""):
    """Yield text deltas from the local Ollama runtime, and refresh the VRAM
    residency TTL in the background so the NEXT turn skips the ~44s reload."""
    from .providers._openai_compat import chat_stream
    from .providers.ollama import DEFAULT_HOST, warm_model_async

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    # Before warm_model_async's daemon thread and before the stream request.
    _provider_start("ollama", endpoint=host, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    warm_model_async(host, model)  # non-blocking: never delays this reply
    yield from chat_stream(
        base_url=host.rstrip("/") + "/v1", model=model,
        system=system, user=_with_context(message, context), temperature=0.3,
        timeout_s=120, extra={"max_tokens": _effort_cap(effort)},
    )


def _deepseek_stream(message: str, model: str, effort: str | None, context: str = ""):
    """Yield text deltas from the DeepSeek API. Same OpenAI-compatible
    streaming client Ollama's stream uses (``chat_stream``); only
    base_url/api_key differ -- no new HTTP client."""
    from .providers._openai_compat import chat_stream
    from .providers.deepseek import DEFAULT_BASE_URL

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    _provider_start("deepseek", endpoint=base_url, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    yield from chat_stream(
        base_url=base_url, model=model, system=system, user=_with_context(message, context),
        api_key=api_key, temperature=0.3, timeout_s=120,
        extra={"max_tokens": _effort_cap(effort)},
    )


# Claude CLI stream-json frames we care about (verified against 2.1.201):
#   {"type":"stream_event","event":{"type":"content_block_delta",
#    "delta":{"type":"text_delta","text":"..."}}}
def _claude_stream(message: str, effort: str | None = None, model: str | None = None,
                   context: str = ""):
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
    _provider_start("claude", endpoint=path, model=model)
    prompt = _claude_prompt(message, effort, context)
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
        # Names the ACTION, not where the control is. This line used to say
        # "in the header"; the cockpit moved the runtime picker into the
        # composer on 2026-08-26 and the sentence became an instruction to
        # look somewhere nothing is -- and it is served to two surfaces that
        # put the control in different places. A help text that hard-codes a
        # location is a fake affordance waiting for the next redesign.
        "Choose a runtime to give me a language brain (local Ollama is free)."
    )
