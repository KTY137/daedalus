"""embeddings.py -- the Embeddings Gate-3 baseline arm (plan §11 Gate 3, C6).

THE POINT OF THIS ARM: measure retrieval-by-vector-similarity against the SAME
retrieval-unit universe BM25 (arm C5) uses -- ``daedalus.eval.harness._repo_chunks``
-- so the two arms differ only in ranking formula, never in what corpus they saw.
Reusing the corpus function is not a style preference: docs/GATE2_FOREST_V2_TRIAGE.md
line 106 records a prior slice whose headline moved +0.056 MRR purely because its
corpus filter differed from its comparator's, while the ranking formula itself was
correct. The corpus is where that kind of dishonesty hides, so this arm imports
``_repo_chunks`` and ``count_tokens`` rather than re-deriving either (packet
G3-BASE-01 §2, "extend, never duplicate"). Tokenization for the default vectorizer
also reuses ``daedalus.eval.harness._bm25_tokenize`` -- one tokenizer, not two.

WHAT THIS ARM IS NOT, STATED PLAINLY (the packet exists to prevent exactly the
kind of inflated claim a silent default would make):

    The default embedder in this module is a DETERMINISTIC, OFFLINE, LEXICAL
    hashing-trick bag-of-words vectorizer (feature hashing + sign, L2-normalized,
    scored by cosine similarity). It is NOT a semantic neural embedding model. It
    has no notion of synonymy, paraphrase, or meaning beyond shared surface tokens.
    A result produced against the default embedder measures "does cosine similarity
    over hashed lexical features outperform BM25's TF/IDF formula on the same
    corpus" -- a real and useful comparison for isolating the ranking formula from
    the retrieval unit -- but it does NOT measure semantic retrieval, and no
    report may describe it as such.

Existing repository asset checked before writing this module: ``daedalus/memory/
embeddings.py`` (``EventVectorStore`` / ``OllamaEmbeddingBackend``) is a real,
already-egress-governed embedding layer. It was NOT reused directly here because
its responsibility is a different one -- versioned, content-addressed, append-only
projections of the AGENT EVENT JOURNAL through a network-backed Ollama endpoint,
with SQLite index tables, identity-anchor drift detection, and host-binding
enforcement (plan §4 invariant 8: egress is a policy boundary, not a baseline
concern). Importing that machinery into a stateless, in-memory, per-trial
retrieval arm would mean either paying its journal/SQLite/egress-policy cost for
every trial or partially reimplementing it badly -- both worse than a small,
honestly-labelled hashing vectorizer that needs neither a journal nor a network
socket. What IS reused from it is the *shape* of the idea: an ``EmbeddingBackend``
that turns texts into vectors is a legitimate seam, so the optional real-embedder
opt-in below (``real_embedder``) accepts anything satisfying that same
``Sequence[str] -> Sequence[Sequence[float]]`` shape (a bound
``OllamaEmbeddingBackend.embed`` closure fits it), without importing the module's
network/journal/index dependencies into the default, offline path (plan §9.2:
buy-versus-build behind an adapter seam, not a forked second implementation).

DEFAULT PATH IS NETWORK-FREE BY CONSTRUCTION, NOT BY A DISABLED FLAG: the default
vectorizer calls only ``hashlib`` and pure arithmetic. No import in this module's
default path touches ``urllib``, ``socket``, or any provider client, so there is
no code path to silently re-enable.

REAL-EMBEDDER OPT-IN, EXPLICIT FAILURE, NO SILENT FALLBACK: passing
``real_embedder=`` opts a trial into calling that callable instead of the
hashing vectorizer. If it raises, this arm returns ``ArmOutcome(error=...)`` --
it does NOT silently fall back to the hashing vectorizer, because a report that
mixed "asked for a real embedder, got the lexical stand-in instead" into one
number would misrepresent what was actually measured. This mirrors this
repository's existing posture for provider-gated arms (C3): unavailable means an
honest, explicit non-result, never a quiet substitution.

DETERMINISM: the hashing vectorizer uses ``hashlib.blake2b`` exclusively for both
the bucket index and the sign of each feature. It never calls Python's built-in
string hashing function, whose per-process salt (``PYTHONHASHSEED``) would make
two otherwise-identical runs disagree. Ranking ties are broken on chunk label
(same convention as ``daedalus.eval.harness._bm25_context``), not on insertion
or dict/set iteration order, so retrieval order is stable regardless of process
hash-seed state.

BUDGET: mirrors ``_bm25_context``'s anti-starvation rule exactly (packet §3,
rule R1 -- full budget, never split; rule R5 -- an arm that runs over is a
reported finding, not something to hide). Chunks are taken whole, ranked by
cosine similarity, and picked greedily until the next chunk would exceed
``budget.max_tokens``; the single top-ranked chunk is always included even if it
alone exceeds budget, because an empty context is a strictly worse baseline than
a slightly-over one.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Sequence

from daedalus.eval.harness import _bm25_tokenize, _repo_chunks
# count_tokens is reached through the module rather than imported by name:
# harness does not DEFINE it -- it imports it from daedalus.structcore.tokens
# inside a try/except with a chars/4 fallback, so a from-import re-exports
# another module's name. tests/test_deepseek_substitution_guard.py refuses
# that, and the sibling arms (bm25, separate_indices) already use this form.
from daedalus.eval import harness as _harness

from ..contracts import ArmBudget
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Feature-hashing bucket count for the default vectorizer. Not a claim about
#: semantic capacity -- purely how many hash buckets a lexical feature can land
#: in before collisions start blending unrelated tokens together.
DEFAULT_DIMENSION = 1024

#: This repository's recall convention (``daedalus.eval.harness._recall``):
#: 1.0 means every gold label was found. Adopted here rather than a second scale,
#: matching ``best_of_n.py``'s SUCCESS_SCORE.
SUCCESS_SCORE = 1.0

#: Same block format ``_bm25_context`` uses, so a rendered context is
#: byte-for-byte comparable between the two retrieval arms modulo chunk order.
_BLOCK_FORMAT = "# ===== {label} =====\n{text}\n"

#: Shape an opt-in real embedder must satisfy: a batch of texts in, one vector
#: per text out, same order, same length. Deliberately NOT typed against
#: ``daedalus.memory.embeddings.EmbeddingBackend`` -- that protocol carries a
#: ``model=`` keyword and provider identity this arm has no use for; a caller
#: wanting to use ``OllamaEmbeddingBackend`` here binds one with a closure,
#: e.g. ``lambda texts: backend.embed(texts, model="nomic-embed-text")``.
RealEmbedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def _hash_feature(token: str, dimension: int) -> tuple[int, float]:
    """Deterministic (bucket, sign) for one token via the hashing trick.

    ``hashlib.blake2b`` only -- never Python's built-in string hashing, whose
    per-process salt would make this non-reproducible across processes/seeds.
    Eight digest bytes are plenty of entropy for a bucket count this small; the
    index consumes the first four, the sign one bit of a fifth so index and
    sign are independent draws from one digest rather than correlated.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    index = int.from_bytes(digest[:4], "big") % dimension
    sign = 1.0 if (digest[4] & 1) else -1.0
    return index, sign


def _hashing_vector(tokens: Sequence[str], dimension: int) -> list[float]:
    """Bag-of-hashed-features vector, L2-normalized. A zero vector (no tokens,
    or every token's contributions cancelled) stays a zero vector -- ``_cosine``
    below treats that as similarity 0.0 rather than raising, since an
    all-punctuation chunk is a real, if unhelpful, retrieval unit."""
    vector = [0.0] * dimension
    for token in tokens:
        index, sign = _hash_feature(token, dimension)
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0.0:
        vector = [v / norm for v in vector]
    return vector


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity that tolerates non-normalized input (a real embedder's
    output is not guaranteed unit-length) and a zero vector on either side by
    reporting similarity 0.0 rather than dividing by zero."""
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _vectorize(
    texts: Sequence[str], dimension: int, real_embedder: RealEmbedder | None,
) -> list[list[float]]:
    """One vector per text, same order. Raises on a broken opt-in embedder --
    the caller (``EmbeddingsArm.run``) turns that into an explicit
    ``ArmOutcome(error=...)`` rather than swallowing it into a fallback."""
    if real_embedder is not None:
        vectors = list(real_embedder(texts))
        if len(vectors) != len(texts):
            raise ValueError(
                f"real embedder returned {len(vectors)} vectors for "
                f"{len(texts)} texts")
        return [list(v) for v in vectors]
    return [_hashing_vector(_bm25_tokenize(text), dimension) for text in texts]


@dataclass
class EmbeddingsArm:
    """Rank repository chunks by vector cosine similarity, keep the top-k that
    fit the budget.

    ``name``/``stochastic`` satisfy the ``Arm`` protocol (``protocols.py``).
    ``stochastic = False``: the default hashing vectorizer and the greedy,
    label-tie-broken selection are both fully deterministic, so this arm runs
    once rather than under the full ``SeedPolicy`` (plan §14; ``seed`` is
    accepted for protocol conformance and ignored). Stateless aside from its
    three configuration fields, so one instance may be reused across
    tasks/seeds safely.
    """

    name: str = "embeddings"
    stochastic: bool = False
    dimension: int = DEFAULT_DIMENSION
    #: ``None`` (default): use the offline deterministic hashing vectorizer.
    #: Set to opt in to a real embedder; see the module docstring for the
    #: explicit-failure contract this carries.
    real_embedder: RealEmbedder | None = None

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        try:
            chunks = _repo_chunks(task.repo_root)
        except OSError as exc:
            return ArmOutcome(error=f"OSError reading {task.repo_root!r}: {exc}")

        if not chunks:
            return ArmOutcome(
                error=f"no candidate chunks found under {task.repo_root!r}")

        embedder_label = "hashing-lexical-v1" if self.real_embedder is None \
            else "real-embedder-opt-in"

        texts = [task.question] + [text for _, text in chunks]
        try:
            vectors = _vectorize(texts, self.dimension, self.real_embedder)
        except Exception as exc:  # ordinary arm failure, never a silent fallback
            return ArmOutcome(
                error=f"{embedder_label} embedder unavailable: "
                      f"{type(exc).__name__}: {exc}")

        query_vector, *chunk_vectors = vectors
        scores = [_cosine(query_vector, v) for v in chunk_vectors]

        # Deterministic tie-break on chunk label, matching
        # ``_bm25_context`` -- retrieval order must not depend on dict/set
        # iteration order (PYTHONHASHSEED) or on insertion order.
        order = sorted(range(len(chunks)), key=lambda i: (-scores[i], chunks[i][0]))

        picked: list[int] = []
        total = 0
        truncated = False
        for i in order:
            label, text = chunks[i]
            block = _BLOCK_FORMAT.format(label=label, text=text)
            block_tokens = _harness.count_tokens(block)
            if picked and budget.max_tokens is not None \
                    and total + block_tokens > budget.max_tokens:
                truncated = True
                break
            picked.append(i)
            total += block_tokens

        combined = "".join(
            _BLOCK_FORMAT.format(label=chunks[i][0], text=chunks[i][1])
            for i in picked
        )
        candidate_score = evaluator.score(combined, task)
        tokens_used = _harness.count_tokens(combined) if combined else 0
        success = candidate_score >= SUCCESS_SCORE

        return ArmOutcome(
            candidate=combined,
            score=candidate_score,
            success=success,
            tokens_used=tokens_used,
            notes={
                "n_chunks_total": len(chunks),
                "n_chunks_used": len(picked),
                "truncated": truncated,
                "vector_dimension": len(query_vector),
                "embedder": embedder_label,
                "top_label": chunks[order[0]][0] if order else None,
                "top_score": scores[order[0]] if order else None,
            },
        )
