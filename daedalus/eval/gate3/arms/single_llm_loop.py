"""single_llm_loop.py -- Gate-3 baseline (c): a single LLM iterating alone
(plan §11 Gate 3, C3).

THE POINT OF THIS ARM: this is the classic "just ask a model in a loop"
baseline every orchestration-heavy method must beat to justify its own
machinery. One model gets the task, proposes an answer, has that answer
scored, and is shown its own score to revise -- propose -> evaluate -> revise
-- until its budget is exhausted. No retrieval cleverness beyond a fair,
budget-equal context window; no population; no archive. Because the whole
"orchestration" here is a Python for-loop, any product path that ties or
beats this arm has not yet shown it does anything smarter than iterating.

THIS IS THE ONLY ARM ALLOWED TO MAKE A MODEL CALL among the eleven baselines
this packet builds (the others are deliberately model-free -- random_search,
best_of_n, bm25). It reuses the existing, already-provider-gated Tier-2 path
instead of opening a second one:

  * ``daedalus.eval.harness.detect_provider`` -- the ONE provider probe this
    repository has (a 2s local-Ollama ``/api/tags`` GET, no key, no egress
    beyond localhost). Returns ``None`` when nothing is reachable.
  * ``daedalus.eval.tier2._ask`` -- the ONE provider-call wrapper, itself
    delegating to ``daedalus.providers._openai_compat.chat_completion``.

Both are called through their MODULE (``harness.detect_provider(...)``,
``tier2._ask(...)``), never imported by bare name, so a test can monkeypatch
the exact seam ``bm25.py``'s sibling arms already rely on for the same reason
(see ``test_arm_bm25_delegates_to_harness``'s ``monkeypatch.setattr(harness,
...)`` precedent). Writing a second HTTP client here would be exactly the
"second BM25 formula" defect this packet's §2 forbids, just for provider
calls instead of retrieval.

PROVIDER GATING, NEVER A SILENT DOWNGRADE. When no provider is reachable this
arm returns ``ArmOutcome(error="no provider reachable: single_llm_loop
skipped")`` -- a clean, explicit, budget-free skip. It never falls back to a
deterministic imitation while still reporting itself as an LLM arm: plan §1
("no silent downgrade") and AGENTS.md ("unverifiable claims" as a
release-blocking defect) both name that exact failure mode.

CONTEXT, FAIRLY BUILT. The loop's context window is assembled by the SAME
BM25 top-k retrieval every other retrieval arm uses
(``harness._repo_chunks`` + ``harness._bm25_context``), bounded by
``budget.max_tokens`` -- not hand-picked, not the answer key. This keeps the
comparison a test of "does looping with a model help", not "did this arm get
better context than its rivals" (packet rule R2: a comparison must name and
use ONE comparator, not a friendlier one).

BUDGET DISCIPLINE (rule R1 -- full, undivided budget):
  * ``budget.max_calls`` bounds the number of propose/evaluate iterations.
    One iteration is exactly one provider call plus one
    ``evaluator.score`` call, so the SAME number bounds both, mirroring how
    ``best_of_n``'s ``max_calls`` bounds its evaluator-call count. An
    uncapped comparison still needs a finite, declared default
    (``DEFAULT_MAX_ITERATIONS_WHEN_UNCAPPED``), recorded in ``notes`` exactly
    like ``best_of_n``'s ``DEFAULT_N_WHEN_UNCAPPED``.
  * ``budget.max_wall_seconds`` is checked before every iteration; the loop
    stops rather than starting an iteration it cannot finish inside budget.
  * ``budget.split()`` is never called -- there is nothing to split; the
    model gets the full context budget on every iteration.

TOKEN ACCOUNTING IS HONEST, NOT SILENTLY ESTIMATED. This paragraph used to
say real usage was unavailable because ``tier2._ask`` reached
``_openai_compat.chat_completion``, whose return type is a bare ``str``. That
is no longer true: ``_ask`` calls ``chat_completion_receipt`` and returns a
receipt carrying the provider's own ``usage`` block (``input_tokens``,
``output_tokens``, ``total_tokens``, ``tokenizer``) plus a ``usage_status``.
G3-BASE-01 §F3 recorded the old shape and is superseded on this point.

So both numbers are now carried, and neither is substituted for the other:

  * ``notes["provider_tokens_reported"]`` -- summed from the provider's own
    usage over the calls that reported it;
  * ``notes["local_estimate_tokens"]`` -- this repository's ``count_tokens``
    over the exact context/question/answer text exchanged, as before;
  * ``notes["tokens_estimated"]`` -- now MEASURED: ``False`` only when every
    call made came back with usage, ``True`` the moment one did not, with
    ``provider_calls``/``provider_calls_with_usage``/``usage_status_counts``
    saying which and why.

Carrying both matters rather than picking one: the local estimator was
measured to over-count Python by 11.5% and under-count Markdown by 2.4%, an
error whose sign follows content type. Keeping the provider's number beside it
makes that difference visible per run instead of assumed away.

``ArmOutcome.notes["model_id"]`` carries the model id actually used, so a
``RunEnvironment.model_id`` populated from this arm's evidence is honest
(plan §4 invariant 9: declared models for any comparative claim).

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from daedalus.eval import harness, tier2

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: This repository's recall convention (``daedalus.eval.harness._recall``,
#: reused by ``best_of_n``/``bm25``): 1.0 means the gold labels were fully
#: satisfied. Reaching it early ends the loop -- there is no point spending
#: further iterations once the ceiling is hit.
SUCCESS_SCORE = 1.0

#: Applied only when the caller declares no ``max_calls`` at all. Mirrors
#: ``best_of_n.DEFAULT_N_WHEN_UNCAPPED``: an uncapped comparison is not this
#: packet's default posture, but the loop still needs a finite, declared,
#: non-hardcoded-per-run number of iterations to run under. Recorded in
#: ``ArmOutcome.notes`` whenever used.
DEFAULT_MAX_ITERATIONS_WHEN_UNCAPPED = 5

_REVISION_PROMPT_TEMPLATE = (
    "{question}\n\n"
    "Your previous answer scored {prior_score:.3f} out of 1.0 "
    "(1.0 = fully correct). Previous answer:\n{prior_candidate}\n\n"
    "Revise your answer to improve the score. Answer again in full."
)


@dataclass
class SingleLlmLoopArm:
    """Baseline (c): one model, propose -> evaluate -> revise, until budget runs out.

    ``name``/``stochastic`` satisfy the ``Arm`` protocol (``protocols.py``).
    ``stochastic = True``: an LLM call is not guaranteed reproducible even at
    temperature 0.0 (batching/hardware nondeterminism is a documented,
    measured real-world property of hosted and local inference), so this arm
    declares variance rather than a false determinism guarantee.
    """

    name: str = "single_llm_loop"
    stochastic: bool = True
    #: Repaired 2026-09-10 (G3-ARM-PLANE-01): this arm now requests
    #: ``planes=_RETRIEVABLE_PLANES`` instead of inheriting the code-only
    #: default, so it retrieves data and knowledge documents as well. Declared
    #: here so ``gate3.coverage`` can admit a cross-plane comparison, and
    #: checked against behaviour by
    #: ``test_real_arm_declarations_match_what_they_retrieve`` rather than
    #: trusted.
    retrieved_planes = ("code", "data", "knowledge")

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        try:
            return self._run(task, budget, evaluator, seed)
        except FreezeError:
            raise  # contract violation: never swallowed (protocols.Arm docstring)
        except Exception as exc:  # ordinary failure -> an errored outcome, not a crash
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

    def _run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
              seed: int) -> ArmOutcome:
        del seed  # accepted for the Arm protocol; the model call is the only
        # source of variance this arm has, and it is not seedable through the
        # reused provider seam.

        prov = harness.detect_provider()
        if prov is None:
            return ArmOutcome(
                error="no provider reachable: single_llm_loop skipped",
                notes={"skipped": True, "reason": "no_provider"},
            )

        try:
            chunks = harness._repo_chunks(task.repo_root, planes=harness._RETRIEVABLE_PLANES)
        except OSError as exc:
            return ArmOutcome(error=f"OSError reading {task.repo_root!r}: {exc}")
        if not chunks:
            return ArmOutcome(
                error=f"single_llm_loop: no repository chunks found under "
                      f"{task.repo_root!r}")

        query = (task.question or "").strip() or harness._target_query(task.target)
        budget_tokens = budget.max_tokens if budget.max_tokens is not None else math.inf
        retrieval = harness._bm25_context(chunks, query, budget_tokens=budget_tokens)
        context = retrieval["text"]

        used_default_iterations = budget.max_calls is None
        max_iterations = (budget.max_calls if budget.max_calls is not None
                          else DEFAULT_MAX_ITERATIONS_WHEN_UNCAPPED)

        deadline = (None if budget.max_wall_seconds is None
                    else time.perf_counter() + budget.max_wall_seconds)

        best_candidate: str | None = None
        best_score: float | None = None
        score_history: list[float] = []
        tokens_used = 0
        # Real provider-reported usage, accumulated separately from the local
        # estimate so the two can be compared rather than silently substituted.
        provider_tokens = 0
        calls_with_usage = 0
        calls_made = 0
        usage_statuses: dict[str, int] = {}
        iterations_run = 0
        provider_errors: list[str] = []
        prior_candidate: str | None = None
        prior_score: float | None = None

        for i in range(max_iterations):
            if deadline is not None and time.perf_counter() >= deadline:
                break

            if i == 0 or prior_candidate is None:
                question = task.question
            else:
                question = _REVISION_PROMPT_TEMPLATE.format(
                    question=task.question, prior_score=prior_score,
                    prior_candidate=prior_candidate)

            receipt = tier2._ask(prov, question, context)
            iterations_run += 1
            tokens_used += harness.count_tokens(context) + harness.count_tokens(question)

            # tier2._ask has returned a receipt carrying the provider's own
            # usage block since it moved to chat_completion_receipt. A call that
            # reports usage is counted from the provider; one that does not
            # leaves calls_with_usage behind calls_made, which is what makes
            # notes["tokens_estimated"] below true rather than assumed.
            calls_made += 1
            status = receipt.get("usage_status") or "absent"
            usage_statuses[status] = usage_statuses.get(status, 0) + 1
            usage = receipt.get("usage")
            if isinstance(usage, dict):
                total = usage.get("total_tokens")
                if total is None:
                    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
                    total = (inp or 0) + (out or 0) if (inp or out) else None
                if isinstance(total, int) and total > 0:
                    provider_tokens += total
                    calls_with_usage += 1

            if not receipt.get("ok"):
                provider_errors.append(receipt.get("error") or "unknown provider error")
                continue

            candidate = receipt.get("text") or ""
            tokens_used += harness.count_tokens(candidate)
            score = evaluator.score(candidate, task)
            score_history.append(score)

            if best_score is None or score > best_score:
                best_score, best_candidate = score, candidate
            prior_candidate, prior_score = candidate, score

            if best_score is not None and best_score >= SUCCESS_SCORE:
                break

        notes = {
            "model_id": prov.get("model"),
            "provider_kind": prov.get("kind"),
            "provider_host": prov.get("host"),
            "iterations_run": iterations_run,
            "max_iterations": max_iterations,
            "used_default_iterations": used_default_iterations,
            "score_history": score_history,
            # MEASURED, not assumed: false only when every call this arm made
            # came back with the provider's own usage. One silent call and the
            # whole run is an estimate again.
            "tokens_estimated": not (calls_made > 0 and calls_with_usage == calls_made),
            "tokenizer": getattr(harness, "tokenizer_name", lambda: "unknown")(),
            "provider_calls": calls_made,
            "provider_calls_with_usage": calls_with_usage,
            "usage_status_counts": dict(sorted(usage_statuses.items())),
            # Both numbers travel together on purpose. Substituting one for the
            # other would hide the estimator's error; carrying both makes it
            # measurable, which matters because chars/4 was measured to
            # over-count code by 11.5% and under-count prose by 2.4%.
            "provider_tokens_reported": provider_tokens,
            "local_estimate_tokens": tokens_used,
        }
        if provider_errors:
            notes["provider_errors"] = provider_errors

        if best_candidate is None:
            return ArmOutcome(
                error=(
                    "single_llm_loop: provider never returned a usable answer "
                    f"in {iterations_run} iteration(s): {provider_errors}"),
                tokens_used=tokens_used,
                notes=notes,
            )

        success = best_score is not None and best_score >= SUCCESS_SCORE
        return ArmOutcome(
            candidate=best_candidate,
            score=best_score,
            success=success,
            tokens_used=tokens_used,
            notes=notes,
        )
