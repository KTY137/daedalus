"""harness.py -- run the distillation eval over a task set.

Tier 1 (deterministic, no LLM, the rigorous core):
    For each task, take the distilled ``semantic_slice`` and measure
      * recall     = fraction of ``must_include`` found in the slice text,
      * compression = 1 - slice_tokens / whole_repo_tokens.
    Aggregate mean recall + mean compression. Any task with recall < 1.0 is a
    *slice-recall miss*; we surface exactly which symbols were dropped -- that is
    the feedback signal the structcore team uses to sharpen slices.

Tier 2 (opt-in, needs a runtime):
    Ask each task's question against context A (the distilled slice) and context
    B (whole-repo concat), score with ``answer_contains``, and compare
    success/tokens. Gated: if no provider is reachable it is skipped cleanly with
    a message -- Tier 2 NEVER crashes Tier 1 and NEVER makes a network call
    unless explicitly enabled.

Isolated: imports only structcore's stable public API.
"""
from __future__ import annotations

import json
import os

from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.slice import semantic_slice

try:  # optional tiktoken-backed counter; degrades to chars/4 on its own
    from daedalus.structcore.tokens import count_tokens, tokenizer_name
except Exception:  # pragma: no cover - structcore is a hard dep, but be safe
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def tokenizer_name() -> str:
        return "chars/4 (heuristic)"

from .tasks import TASKS, resolve_task_repo, task_project_label

# Directories the whole-repo concat (context B) skips -- mirrors structcore.
_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
}


# --------------------------------------------------------------------------- #
# Tier 1 -- deterministic slice recall + compression                          #
# --------------------------------------------------------------------------- #
def _recall(slice_text: str, must_include: list[str]) -> tuple[float, list[str]]:
    """Fraction of ``must_include`` found (substring) in ``slice_text``, plus the
    list of items that were missed. Empty label list -> recall 1.0 vacuously."""
    if not must_include:
        return 1.0, []
    missed = [m for m in must_include if m not in slice_text]
    found = len(must_include) - len(missed)
    return found / len(must_include), missed


def eval_task_tier1(task: dict, idx: dict | None = None) -> dict:
    """Deterministic Tier-1 result for a single task."""
    repo = resolve_task_repo(task["repo"])
    idx = idx if idx is not None else cached_index(repo)
    res = semantic_slice(repo, task["target"], idx=idx)
    slice_tokens = res["slice_tokens"]
    whole_tokens = res["whole_repo_tokens"]
    recall, missed = _recall(res["slice_text"], task.get("must_include", []))
    compression = 1.0 - (slice_tokens / whole_tokens) if whole_tokens else 0.0
    return {
        "id": task["id"],
        "project": task_project_label(task),
        "target": task["target"],
        "focus_file": res["focus_file"],
        "recall": recall,
        "compression": compression,
        "slice_tokens": slice_tokens,
        "whole_repo_tokens": whole_tokens,
        "n_included": res["n_included"],
        "must_include": list(task.get("must_include", [])),
        "missed": missed,
    }


def run_tier1(tasks: list[dict] | None = None) -> dict:
    """Run Tier 1 over ``tasks`` (default: the built-in TASKS). Indexes are built
    once per repo and reused across that repo's tasks."""
    tasks = TASKS if tasks is None else tasks
    idx_cache: dict[str, dict] = {}
    per_task: list[dict] = []
    for task in tasks:
        repo = resolve_task_repo(task["repo"])
        if repo not in idx_cache:
            idx_cache[repo] = cached_index(repo)
        per_task.append(eval_task_tier1(task, idx=idx_cache[repo]))

    n = len(per_task)
    mean_recall = sum(t["recall"] for t in per_task) / n if n else 0.0
    mean_compression = sum(t["compression"] for t in per_task) / n if n else 0.0
    misses = [t for t in per_task if t["recall"] < 1.0]
    return {
        "tier": 1,
        "n_tasks": n,
        "mean_recall": mean_recall,
        "mean_compression": mean_compression,
        "n_slice_recall_misses": len(misses),
        "tokenizer": tokenizer_name(),
        "per_task": per_task,
    }


# --------------------------------------------------------------------------- #
# Tier 2 -- opt-in LLM task-success: distilled slice (A) vs whole concat (B)   #
# --------------------------------------------------------------------------- #
def _whole_repo_text(root: str, cap_chars: int) -> tuple[str, bool]:
    """Naive whole-repo concatenation (Repomix/Gitingest style): every source
    file under ``root`` glued together with a header, capped at ``cap_chars``.
    Returns (text, truncated)."""
    parts: list[str] = []
    total = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fn in sorted(filenames):
            if spec_for(fn) is None:
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(p, root).replace("\\", "/")
            block = f"# ===== {rel} =====\n{text}\n"
            if total + len(block) > cap_chars:
                block = block[: max(0, cap_chars - total)]
                parts.append(block)
                truncated = True
                return "".join(parts), truncated
            parts.append(block)
            total += len(block)
    return "".join(parts), truncated


def _score(answer: str, answer_contains: list[str]) -> tuple[bool, float]:
    """Success = every expected substring appears (case-insensitive). Also return
    the fraction present for a softer signal."""
    if not answer or not answer_contains:
        return False, 0.0
    low = answer.lower()
    present = sum(1 for s in answer_contains if s.lower() in low)
    frac = present / len(answer_contains)
    return present == len(answer_contains), frac


def detect_provider(provider: str | None = None) -> dict | None:
    """Return a usable provider descriptor, or None if none is reachable.

    Only a local Ollama HTTP endpoint is probed (free, no key, no egress). The
    probe is a 2s GET to /api/tags -- it does nothing unless Tier 2 is requested.
    """
    p = (provider or "").lower()
    if p in ("none", "off", "deterministic"):
        return None
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        import urllib.request

        with urllib.request.urlopen(host + "/api/tags", timeout=2) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    if not models:
        return None
    want = os.environ.get("OLLAMA_MODEL")
    model = want if want in models else models[0]
    return {"kind": "ollama", "host": host, "model": model, "models": models}


def _ask(prov: dict, question: str, context: str) -> str:
    """Single text-only turn against the provider. Never raises to the caller."""
    system = (
        "You answer strictly from the provided CONTEXT. If the answer is not in "
        "the context, say you cannot tell. Be brief and concrete."
    )
    user = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
    try:
        from daedalus.providers._openai_compat import chat_completion

        txt = chat_completion(
            base_url=prov["host"] + "/v1", model=prov["model"],
            system=system, user=user, force_json=False, temperature=0.0, timeout_s=120,
        )
        return (txt or "").strip()
    except Exception:
        return ""


def run_tier2(tasks: list[dict] | None = None, provider: str | None = None,
              cap_tokens: int = 120_000) -> dict:
    """Opt-in Tier 2. Compares distilled-slice (A) vs whole-repo-concat (B) task
    success + tokens. Cleanly skipped (never crashes) when no provider is up."""
    tasks = TASKS if tasks is None else tasks
    prov = detect_provider(provider)
    if prov is None:
        return {
            "tier": 2,
            "skipped": True,
            "reason": "no provider/runtime available (set OLLAMA_HOST to a "
                      "running Ollama, or start one) -- Tier 1 is the deliverable.",
        }

    cap_chars = cap_tokens * 4
    idx_cache: dict[str, dict] = {}
    whole_cache: dict[str, tuple[str, bool]] = {}
    per_task: list[dict] = []
    for task in tasks:
        if not task.get("question"):
            continue
        repo = resolve_task_repo(task["repo"])
        if repo not in idx_cache:
            idx_cache[repo] = cached_index(repo)
        if repo not in whole_cache:
            whole_cache[repo] = _whole_repo_text(repo, cap_chars)
        res = semantic_slice(repo, task["target"], idx=idx_cache[repo])
        ctx_a = res["slice_text"]
        ctx_b, truncated = whole_cache[repo]

        ans_a = _ask(prov, task["question"], ctx_a)
        ans_b = _ask(prov, task["question"], ctx_b)
        ok_a, frac_a = _score(ans_a, task.get("answer_contains", []))
        ok_b, frac_b = _score(ans_b, task.get("answer_contains", []))
        per_task.append({
            "id": task["id"],
            "project": task_project_label(task),
            "question": task["question"],
            "success_A": ok_a, "frac_A": frac_a, "tokens_A": count_tokens(ctx_a),
            "success_B": ok_b, "frac_B": frac_b, "tokens_B": count_tokens(ctx_b),
            "b_truncated": truncated,
        })

    n = len(per_task)
    agg = {
        "tier": 2,
        "skipped": False,
        "provider": {"kind": prov["kind"], "model": prov["model"], "host": prov["host"]},
        "n_tasks": n,
        "success_A": sum(t["success_A"] for t in per_task),
        "success_B": sum(t["success_B"] for t in per_task),
        "tokens_A": sum(t["tokens_A"] for t in per_task),
        "tokens_B": sum(t["tokens_B"] for t in per_task),
        "per_task": per_task,
    }
    return agg
