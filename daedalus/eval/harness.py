"""harness.py -- run the distillation eval over a task set.

Tier 1 (deterministic, no LLM, the rigorous core):
    For each task, take the distilled ``semantic_slice`` and measure
      * recall     = fraction of ``must_include`` found in the slice text,
      * compression = 1 - slice_tokens / whole_repo_tokens.
    Aggregated PER LABEL-PROVENANCE TIER (see ``daedalus.eval.tasks`` docstring)
    -- never blended into one number, because "hand_reachable" labels were
    picked by reading the code and verified reachable by the very slicer being
    graded (circular), while "independent_diff"/"temporal_churn" labels are
    not. Blending would re-hide exactly the circularity this module exists to
    expose. ``tier == "quarantine"`` tasks are excluded from every headline and
    reported separately (see ``run_tier1``). Any task with recall < 1.0 is a
    *slice-recall miss*; we surface exactly which symbols were dropped -- that
    is the feedback signal the structcore team uses to sharpen slices.

Arms A/B/C (deterministic, no LLM -- same honesty rules as Tier 1):
    A/B/C is a three-way, model-free comparison of the distilled slice (A)
    against a naive whole-repo concat (B) and a BM25 top-k retrieval baseline
    (C), scored on BOTH recall (via ``_recall``) and true token cost. See
    ``run_arms``. This is the "does distillation actually beat dumb retrieval"
    question -- if C ties or beats A on some task, that is reported loudly,
    not smoothed over.

Tier 2 (opt-in, needs a runtime):
    Ask each task's question against context A (the distilled slice) and context
    B (whole-repo concat), score with ``answer_contains``, and compare
    success/tokens. Gated: if no provider is reachable it is skipped cleanly with
    a message -- Tier 2 NEVER crashes Tier 1 and NEVER makes a network call
    unless explicitly enabled.

Gate (advisory, local-only):
    ``run_gate`` replays the corpus against a stored ``baseline.json`` and
    flags PRIMARY-tier tasks whose recall decreased -- see its docstring for
    the exact workflow. ADVISORY ONLY: never wired to block an autonomous
    action; there is no CI in this repo, this is a developer-run local check.

Isolated: imports only structcore's stable public API.
"""
from __future__ import annotations

import json
import math
import os
import re

from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units
from daedalus.structcore.slice import semantic_slice

try:  # optional tiktoken-backed counter; degrades to chars/4 on its own
    from daedalus.structcore.tokens import count_tokens, tokenizer_name
except Exception:  # pragma: no cover - structcore is a hard dep, but be safe
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def tokenizer_name() -> str:
        return "chars/4 (heuristic)"

from .mint import load_minted_tasks
from .tasks import TASKS, resolve_task_repo, task_project_label

# Directories the whole-repo concat (context B) skips -- mirrors structcore.
_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
}


def all_tasks() -> list[dict]:
    """The hardcoded ``TASKS`` plus every task persisted in the mint store
    (``daedalus.eval.mint.load_minted_tasks``) -- the load path that closes
    the mint -> quarantine -> confirm -> primary flywheel described in
    ``daedalus.eval.tasks``'s module docstring. Byte-identical to ``TASKS``
    alone until something has actually been minted AND persisted: no store
    file -> ``load_minted_tasks`` returns ``[]`` -> this is exactly ``TASKS``,
    same order, same content. This is the default every ``run_*``/``*_baseline``
    function below uses in place of ``TASKS`` -- additive, not a behavior
    change for any caller who has never run a mint."""
    return TASKS + load_minted_tasks()


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _is_primary_tier(label_tier: object) -> bool:
    """Fail-closed: only the EXACT string "primary" counts. A missing, typo'd,
    or otherwise unrecognized tier is treated as quarantine (excluded from any
    go/no-go number) rather than silently trusted -- same "never under-escalate"
    posture the rest of this repo uses for safety classification."""
    return label_tier == "primary"


def _group_rows_by_provenance(rows: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """{provenance: {"primary": [...], "quarantine": [...]}} for every
    provenance actually present in ``rows``. Both tier buckets always exist
    (possibly empty) so a report renders a stable shape even when a task set
    happens to have zero quarantine (or zero primary) rows for a provenance."""
    out: dict[str, dict[str, list[dict]]] = {}
    for prov in sorted({r["label_provenance"] for r in rows}):
        out[prov] = {"primary": [], "quarantine": []}
    for r in rows:
        tier = "primary" if _is_primary_tier(r["label_tier"]) else "quarantine"
        out[r["label_provenance"]][tier].append(r)
    return out


def _by_provenance(rows: list[dict], aggregate_fn) -> dict:
    """Apply ``aggregate_fn`` within each (provenance, tier) bucket. This is
    the ONLY aggregation path Tier 1 and the arms comparison use -- there is
    deliberately no top-level blended mean anywhere in this module."""
    grouped = _group_rows_by_provenance(rows)
    return {prov: {tier: aggregate_fn(items) for tier, items in tiers.items()}
            for prov, tiers in grouped.items()}


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
        # Defaulted so pre-provenance task dicts (e.g. ad-hoc test fixtures
        # that predate this schema) still group as "hand_reachable"/"primary"
        # -- additive, byte-identical aggregation for callers who never
        # adopted the new fields.
        "label_provenance": task.get("label_provenance", "hand_reachable"),
        "label_tier": task.get("tier", "primary"),
    }


def _tier1_aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    misses = [r for r in rows if r["recall"] < 1.0]
    return {
        "n_tasks": n,
        "mean_recall": _mean([r["recall"] for r in rows]),
        "mean_compression": _mean([r["compression"] for r in rows]),
        "n_slice_recall_misses": len(misses),
        "missed_ids": sorted(r["id"] for r in misses),
    }


def run_tier1(tasks: list[dict] | None = None) -> dict:
    """Run Tier 1 over ``tasks`` (default: the built-in TASKS). Indexes are built
    once per repo and reused across that repo's tasks.

    No top-level blended recall/compression: see ``by_provenance`` for the
    honest, per-provenance-tier numbers. ``tier == "quarantine"`` tasks are
    counted in ``n_quarantine_tasks`` and reported inside ``by_provenance``,
    but never inside a go/no-go figure.
    """
    tasks = all_tasks() if tasks is None else tasks
    idx_cache: dict[str, dict] = {}
    per_task: list[dict] = []
    for task in tasks:
        repo = resolve_task_repo(task["repo"])
        if repo not in idx_cache:
            idx_cache[repo] = cached_index(repo)
        per_task.append(eval_task_tier1(task, idx=idx_cache[repo]))

    n = len(per_task)
    n_primary = sum(1 for t in per_task if _is_primary_tier(t["label_tier"]))
    return {
        "tier": 1,
        "n_tasks": n,
        "n_primary_tasks": n_primary,
        "n_quarantine_tasks": n - n_primary,
        "tokenizer": tokenizer_name(),
        "per_task": per_task,
        "by_provenance": _by_provenance(per_task, _tier1_aggregate),
    }


# --------------------------------------------------------------------------- #
# Arms A/B/C -- deterministic, model-free: slice vs whole-repo vs BM25        #
# --------------------------------------------------------------------------- #
def _whole_repo_text(root: str, cap_chars: int | None = None) -> tuple[str, bool]:
    """Naive whole-repo concatenation (Repomix/Gitingest style): every source
    file under ``root`` glued together with a header. ``cap_chars=None`` (the
    new default) walks the ENTIRE repo untruncated -- the TRUE size of the
    baseline. Pass an int to cap it (what Tier 2 actually hands a model).
    Returns (text, truncated); ``truncated`` is always False when uncapped.
    """
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
            if cap_chars is not None and total + len(block) > cap_chars:
                block = block[: max(0, cap_chars - total)]
                parts.append(block)
                truncated = True
                return "".join(parts), truncated
            parts.append(block)
            total += len(block)
    return "".join(parts), truncated


def _target_query(target: str) -> str:
    """BM25 query fallback when a task has no ``question``: the target symbol
    name, or the file's stem for a file-level target."""
    if "::" in target:
        return target.split("::", 1)[1]
    stem = target.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0] if "." in stem else stem


def _repo_chunks(root: str) -> list[tuple[str, str]]:
    """Retrieval units for arm C: one chunk per extractable unit (function or
    class), else the whole file when nothing is extractable -- "the repo's
    files/units" the BM25 baseline retrieves over. Same source-file universe as
    ``_whole_repo_text``. Unlike ``_whole_repo_text``, dirnames ARE sorted here:
    this is new code with no prior byte-order contract to preserve, and BM25
    tie-breaking needs a deterministic candidate order (see ``_bm25_context``).
    """
    chunks: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            spec = spec_for(fn)
            if spec is None:
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(p, root).replace("\\", "/")
            units = extract_units(rel, text, spec)
            if units:
                for u in units:
                    chunks.append((f"{rel}::{u.name}", u.source))
            else:
                chunks.append((rel, text))
    return chunks


_BM25_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _bm25_tokenize(text: str) -> list[str]:
    return [w.lower() for w in _BM25_TOKEN_RE.findall(text)]


def _bm25_scores(query_tokens: list[str], doc_tokens: list[list[str]],
                  k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Okapi BM25 over pre-tokenized docs -- no new dependency, no network.
    Standard k1=1.2 / b=0.75. Ties are broken by the CALLER (chunk label, not
    insertion order) so retrieval order stays deterministic regardless of
    dict/set iteration order (PYTHONHASHSEED)."""
    n = len(doc_tokens)
    if n == 0 or not query_tokens:
        return [0.0] * n
    lens = [len(d) for d in doc_tokens]
    avgdl = sum(lens) / n
    df: dict[str, int] = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    scores: list[float] = []
    for toks, dl in zip(doc_tokens, lens):
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        len_norm = k1 * (1 - b + b * (dl / avgdl if avgdl else 1.0))
        s = 0.0
        for q in query_tokens:
            f = tf.get(q, 0)
            if not f:
                continue
            s += idf.get(q, 0.0) * (f * (k1 + 1)) / (f + len_norm)
        scores.append(s)
    return scores


def _bm25_context(chunks: list[tuple[str, str]], query: str, budget_tokens: int) -> dict:
    """Top-k BM25 retrieval up to ``budget_tokens`` -- arm C. Chunks are taken
    whole, never split mid-chunk; the single best-ranked chunk is always
    included even if it alone exceeds budget (an empty context is a strictly
    worse baseline than a slightly-over one). ``truncated`` is True iff a
    lower-ranked chunk existed that did not fit the remaining budget."""
    if not chunks or not (query or "").strip():
        return {"text": "", "n_chunks_total": len(chunks), "n_chunks_used": 0,
                "truncated": False, "tokens": 0}
    q_tokens = _bm25_tokenize(query)
    doc_tokens = [_bm25_tokenize(t) for _, t in chunks]
    scores = _bm25_scores(q_tokens, doc_tokens)
    order = sorted(range(len(chunks)), key=lambda i: (-scores[i], chunks[i][0]))
    picked: list[int] = []
    total = 0
    truncated = False
    for i in order:
        label, text = chunks[i]
        block = f"# ===== {label} =====\n{text}\n"
        t = count_tokens(block)
        if picked and total + t > budget_tokens:
            truncated = True
            break
        picked.append(i)
        total += t
    combined = "".join(f"# ===== {chunks[i][0]} =====\n{chunks[i][1]}\n" for i in picked)
    return {
        "text": combined,
        "n_chunks_total": len(chunks),
        "n_chunks_used": len(picked),
        "truncated": truncated,
        "tokens": count_tokens(combined),
    }


# What a Tier-2 run would actually hand a model when B is capped -- mirrors
# run_tier2's own default so the "if this ran against an LLM" figure is real.
_DEFAULT_MODEL_CAP_TOKENS = 120_000


def eval_task_arms(task: dict, idx: dict | None = None,
                    chunks: list[tuple[str, str]] | None = None) -> dict:
    """Deterministic A/B/C comparison for one task: recall (model-free, via
    ``_recall``) AND true token cost, side by side, for every arm. No LLM.

      A = the distilled semantic slice (today's product).
      B = naive whole-repo concat. Recall is measured against the TRUE, FULL,
          UNTRUNCATED text (``tokens_B``) -- beating a baseline you truncated
          is not a win. ``tokens_B_capped_at_default``/``b_truncated_at_cap``
          additionally report what Tier 2 would actually hand a model (capped
          at ``_DEFAULT_MODEL_CAP_TOKENS``), so that weakening is visible, not
          hidden inside a smaller B that looks stronger than it is.
      C = BM25 top-k retrieval, budgeted to the SAME token count as A
          (``token_budget_C == tokens_A``) -- the "dumb retrieval" baseline
          that matters commercially. ``c_beats_a`` is TIE-INCLUSIVE
          (``recall_C >= recall_A``, matching the report's "C>=A" column and
          this module's own docstring promise that a tie is "reported loudly,
          not smoothed over") and reported plainly either way; nothing here is
          tuned to make A win.
    """
    repo = resolve_task_repo(task["repo"])
    idx = idx if idx is not None else cached_index(repo)
    chunks = chunks if chunks is not None else _repo_chunks(repo)
    must_include = task.get("must_include", [])

    res = semantic_slice(repo, task["target"], idx=idx)
    text_a = res["slice_text"]
    tokens_a = res["slice_tokens"]
    recall_a, missed_a = _recall(text_a, must_include)

    text_b_full, _ = _whole_repo_text(repo, cap_chars=None)
    tokens_b = count_tokens(text_b_full)
    recall_b, missed_b = _recall(text_b_full, must_include)
    text_b_capped, b_truncated_at_cap = _whole_repo_text(
        repo, cap_chars=_DEFAULT_MODEL_CAP_TOKENS * 4)
    tokens_b_capped = count_tokens(text_b_capped)

    query = task.get("question") or _target_query(task["target"])
    budget_c = max(tokens_a, 1)
    bm25 = _bm25_context(chunks, query, budget_tokens=budget_c)
    recall_c, missed_c = _recall(bm25["text"], must_include)

    return {
        "id": task["id"],
        "project": task_project_label(task),
        "target": task["target"],
        "label_provenance": task.get("label_provenance", "hand_reachable"),
        "label_tier": task.get("tier", "primary"),
        "recall_A": recall_a, "tokens_A": tokens_a, "missed_A": missed_a,
        "recall_B": recall_b, "tokens_B": tokens_b, "missed_B": missed_b,
        "tokens_B_capped_at_default": tokens_b_capped,
        "b_truncated_at_cap": b_truncated_at_cap,
        "recall_C": recall_c, "tokens_C": bm25["tokens"], "missed_C": missed_c,
        "c_chunks_used": bm25["n_chunks_used"], "c_chunks_total": bm25["n_chunks_total"],
        "c_truncated_at_budget": bm25["truncated"],
        "token_budget_C": budget_c,
        # Tie-inclusive on purpose: a strict '>' here silently counted a BM25
        # tie as an A win, contradicting the "C>=A" column header (report.py)
        # and this function's own docstring ("if C ties or beats A ... that is
        # reported loudly, not smoothed over"). recall_A==1.0 on every current
        # hand_reachable task makes a strict C win impossible, so with '>' the
        # tie case -- dumb retrieval matching the product at equal cost, the
        # commercially damning one -- was the ONLY case that could ever fire
        # and it was being absorbed into "no".
        "c_beats_a": recall_c >= recall_a,
    }


def _arms_aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "n_tasks": n,
        "mean_recall_A": _mean([r["recall_A"] for r in rows]),
        "mean_recall_B": _mean([r["recall_B"] for r in rows]),
        "mean_recall_C": _mean([r["recall_C"] for r in rows]),
        "mean_tokens_A": _mean([r["tokens_A"] for r in rows]),
        "mean_tokens_B": _mean([r["tokens_B"] for r in rows]),
        "mean_tokens_C": _mean([r["tokens_C"] for r in rows]),
        "n_c_beats_a": sum(1 for r in rows if r["c_beats_a"]),
        "c_beats_a_ids": sorted(r["id"] for r in rows if r["c_beats_a"]),
        "n_b_truncated_at_cap": sum(1 for r in rows if r["b_truncated_at_cap"]),
    }


def run_arms(tasks: list[dict] | None = None) -> dict:
    """Run the deterministic A/B/C comparison over ``tasks`` (default TASKS).
    Model-free (recall via ``_recall``), offline, no LLM -- safe to run
    alongside Tier 1. See ``eval_task_arms`` for what each arm measures and
    ``by_provenance`` for the (never-blended) per-provenance-tier breakdown.
    """
    tasks = all_tasks() if tasks is None else tasks
    idx_cache: dict[str, dict] = {}
    chunks_cache: dict[str, list[tuple[str, str]]] = {}
    per_task: list[dict] = []
    for task in tasks:
        repo = resolve_task_repo(task["repo"])
        if repo not in idx_cache:
            idx_cache[repo] = cached_index(repo)
        if repo not in chunks_cache:
            chunks_cache[repo] = _repo_chunks(repo)
        per_task.append(eval_task_arms(task, idx=idx_cache[repo], chunks=chunks_cache[repo]))
    return {
        "tier": "arms",
        "n_tasks": len(per_task),
        "tokenizer": tokenizer_name(),
        "per_task": per_task,
        "by_provenance": _by_provenance(per_task, _arms_aggregate),
    }


# --------------------------------------------------------------------------- #
# Tier 2 -- opt-in LLM task-success: distilled slice (A) vs whole concat (B)   #
# --------------------------------------------------------------------------- #
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
    success + tokens. Cleanly skipped (never crashes) when no provider is up.

    B's tokens were ALREADY measured with the real tokenizer before this
    change (``count_tokens`` is exact whenever tiktoken is installed) -- that
    part was honest. What was NOT honest: B is capped at ``cap_tokens * 4``
    chars before being measured, so ``tokens_B`` silently reflected a
    TRUNCATED text, not the real whole-repo size. ``tokens_B_true`` (added
    here) is the untruncated whole-repo token count, so a truncated B can
    never be mistaken for the real baseline.
    """
    tasks = all_tasks() if tasks is None else tasks
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
    whole_true_tokens_cache: dict[str, int] = {}
    per_task: list[dict] = []
    for task in tasks:
        if not task.get("question"):
            continue
        repo = resolve_task_repo(task["repo"])
        if repo not in idx_cache:
            idx_cache[repo] = cached_index(repo)
        if repo not in whole_cache:
            whole_cache[repo] = _whole_repo_text(repo, cap_chars)
        if repo not in whole_true_tokens_cache:
            full_text, _ = _whole_repo_text(repo, cap_chars=None)
            whole_true_tokens_cache[repo] = count_tokens(full_text)
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
            "tokens_B_true": whole_true_tokens_cache[repo],
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
        "tokens_B_true": sum(t["tokens_B_true"] for t in per_task),
        "b_truncated_any": any(t["b_truncated"] for t in per_task),
        "per_task": per_task,
    }
    return agg


# --------------------------------------------------------------------------- #
# Gate -- advisory counterfactual regression ratchet                          #
# --------------------------------------------------------------------------- #
DEFAULT_BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def load_baseline(path: str | None = None) -> dict:
    """Read baseline.json, or an empty baseline if it does not exist yet (a
    fresh repo checkout before the first ``--update-baseline`` run)."""
    p = path or DEFAULT_BASELINE_PATH
    if not os.path.exists(p):
        return {"schema": 1, "tasks": {}}
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def snapshot_baseline(tasks: list[dict] | None = None) -> dict:
    """Pure: build the baseline structure for the CURRENT recall of ``tasks``
    (default TASKS). Does not touch disk -- see ``write_baseline``. Every task
    is snapshotted (including quarantine ones) so quarantine promotion is
    still comparable later; only PRIMARY tasks are ever gated (see ``run_gate``).
    """
    tasks = all_tasks() if tasks is None else tasks
    result = run_tier1(tasks)
    snap = {
        t["id"]: {
            "recall": t["recall"],
            "label_provenance": t["label_provenance"],
            "tier": t["label_tier"],
        }
        for t in result["per_task"]
    }
    return {
        "schema": 1,
        "note": "Advisory regression baseline for daedalus.eval.harness.run_gate. "
                "Never auto-updates -- only 'python -m daedalus.eval --update-baseline' "
                "(an explicit, human-invoked action) writes this file.",
        "tasks": snap,
    }


def write_baseline(tasks: list[dict] | None = None, path: str | None = None) -> str:
    """EXPLICIT-ONLY baseline write. Never call this from an automatic code
    path -- a baseline that updates itself is not a ratchet, it is a no-op.
    Only the '--update-baseline' CLI flag (a human decision) should reach this.
    Returns the path written. Deterministic formatting (sorted keys) so the
    diff is meaningful in review."""
    p = path or DEFAULT_BASELINE_PATH
    snap = snapshot_baseline(tasks)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return p


def run_gate(tasks: list[dict] | None = None, baseline_path: str | None = None) -> dict:
    """ADVISORY regression ratchet. Replays ``tasks`` (default TASKS) against a
    stored baseline.json and flags any PRIMARY-tier task whose recall
    DECREASED. Compares PER TASK, never on a mean -- a mean hides one task
    collapsing while another improves (see tests/test_eval_oracle.py for the
    mean-preserving-swap test that proves this).

    Workflow before shipping a slice-heuristic change:
        python -m daedalus.eval --gate
    Expect PASS. A FAIL means either a real regression (fix the slicer) or an
    intentional, reviewed label change -- in which case update the baseline
    EXPLICITLY (never automatically):
        python -m daedalus.eval --update-baseline

    GUARDRAIL: this gate is ADVISORY ONLY. It is a local developer command plus
    a unit test (there is no CI in this repo -- verified: no .github/workflows).
    It must never be wired to block an autonomous action.
    """
    tasks = all_tasks() if tasks is None else tasks
    p = baseline_path or DEFAULT_BASELINE_PATH
    baseline = load_baseline(p)
    baseline_tasks = baseline.get("tasks", {})

    result = run_tier1(tasks)
    regressions: list[dict] = []
    improved: list[dict] = []
    new_tasks: list[str] = []
    checked: list[str] = []
    current_ids: set[str] = set()

    for t in result["per_task"]:
        current_ids.add(t["id"])
        if not _is_primary_tier(t["label_tier"]):
            continue  # quarantine is never gated, see module docstring
        base = baseline_tasks.get(t["id"])
        if base is None:
            new_tasks.append(t["id"])
            continue
        checked.append(t["id"])
        base_recall = base["recall"]
        cur_recall = t["recall"]
        if cur_recall < base_recall:
            regressions.append({
                "id": t["id"], "baseline_recall": base_recall,
                "current_recall": cur_recall, "delta": cur_recall - base_recall,
                "missed": t["missed"],
            })
        elif cur_recall > base_recall:
            improved.append({
                "id": t["id"], "baseline_recall": base_recall,
                "current_recall": cur_recall, "delta": cur_recall - base_recall,
            })

    missing_tasks = sorted(set(baseline_tasks) - current_ids)
    return {
        "passed": len(regressions) == 0,
        "advisory": True,
        "baseline_path": p,
        "n_checked": len(checked),
        "regressions": sorted(regressions, key=lambda r: r["id"]),
        "improved": sorted(improved, key=lambda r: r["id"]),
        "new_tasks": sorted(new_tasks),
        "missing_tasks": missing_tasks,
    }
