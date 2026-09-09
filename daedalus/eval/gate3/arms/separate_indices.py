"""separate_indices.py -- Gate-3 baseline (h): four separate per-plane indices,
built and queried WITHOUT any cross-plane scoring or fusion.

Packet G3-BASE-01, acceptance test C8 (``test_arm_separate_indices_each_full_budget``).

THE DEFECT THIS MODULE EXISTS TO NOT REPEAT
--------------------------------------------------------------------------
``docs/GATE2_FOREST_V2_TRIAGE.md:109-131`` records the worst measurement this
repository has produced. Slice s08 concluded "four separate indices are
strictly inferior to cross-plane fusion (432 vs 491)" by splitting ONE shared
hit budget round-robin across four per-plane indices. Every gold label in that
comparison was a code document, so only the code index could ever hold the
answer -- and round-robin gave it effectively ranks 1, 5, 9, i.e. top-3 instead
of top-10. Given each index its OWN full budget, the identical baseline scored
491: exactly the pure code index, a null result, not a strict loss. The
"strict inferiority" was an artifact of the budget split, and the README
booked it as evidence FOR the four-plane hypothesis anyway.

Two binding rules follow directly (packet §3):

* R1 -- OWN BUDGET. Each of the four per-plane indices in this arm receives
  the FULL ``ArmBudget`` handed to the arm, independently. ``ArmBudget.split``
  is never called; it is refused by construction (see ``contracts.py``) and
  this module does not attempt to work around that refusal by re-implementing
  a division by hand. A consequence, stated plainly rather than hidden: this
  arm's real aggregate resource use across its four indices can exceed the
  single-arm budget number when several planes are present. That is the
  honest cost of maintaining four full-budget indices instead of one, and it
  is reported (``ArmOutcome.tokens_used`` is the sum across present planes),
  never clipped to look budget-equal with a single-index arm (packet test B4).
* R3 -- NO SILENT CROSS-PLANE VERDICT. This module never fuses per-plane
  results into a ranked list, and ``cross_plane_verdict`` below refuses to
  compare this arm against a fusion baseline when the task set's gold labels
  live in only one plane (``FrozenTaskSet.require_cross_plane``). That refusal
  is the s08 defect made mechanical: a structurally impossible comparison must
  not be run and reported as a finding.

WHAT "FOUR SEPARATE INDICES, NO FUSION" MEANS OPERATIONALLY
--------------------------------------------------------------------------
The arm builds one independent BM25 index per plane that has documents in the
task's repository. ``Task.label_plane`` (a public field the arm may read --
unlike gold answer text, which lives only behind ``SealedEvaluator``, plan §4
invariant 3) names which plane a real system would have to consult to find
this task's answer. Because there is no fusion, the arm's reported candidate
for scoring is exactly that one plane's retrieval -- never a blend, rerank, or
concatenation across planes. If the label plane has no documents in this
repository, the honest result is an ordinary miss (``success=False``,
``score=0.0``), not an error and not a borrowed answer from a different plane.

PLANE CLASSIFICATION -- reuse where a canonical classifier exists, declare a
proxy where it does not:

* ``code``      -- ``daedalus.structcore.languages.spec_for`` (the SAME claim
  ``daedalus.eval.harness._repo_chunks`` already uses for arm C's corpus).
* ``knowledge`` -- ``daedalus.structcore.languages.doc_spec_for`` (markdown;
  the same registry ``eval/harness`` and ``structcore.index`` already read).
* ``type`` / ``data`` -- NO canonical Gate-2 classifier exists yet
  (``daedalus/twin/`` and ``experiments/forest_v2/`` are both off-limits to
  this packet, see the packet's forbidden-paths list). This module declares a
  minimal, explicit extension-based proxy for these two planes and states so
  here rather than silently inventing authority: a `.pyi`/`.proto`/`.graphql`/
  `.fbs`/`.d.ts` file is treated as ``type``; a `.csv`/`.json`/`.yaml`/`.yml`/
  `.sql`/`.tsv`/`.parquet` file is treated as ``data``. This mirrors the
  packet's own expected failure #2: "only the code index is substantially
  built" -- ``type``/``data`` are frequently reported ABSENT for an ordinary
  repository, and that absence is surfaced, never hidden (packet §3, and see
  ``plane_documents``/``ArmOutcome.notes["per_plane"]`` below).

BM25 REUSE: every ranking decision here calls ``daedalus.eval.harness``'s
existing ``_bm25_context`` / ``_bm25_scores`` (Okapi BM25, k1=1.2, b=0.75,
deterministic tie-break). This module contains no scoring formula of its own
(packet §2: "a second BM25 implementation" is a named, forbidden defect).

DETERMINISM: ``stochastic = False``. Four independent BM25 rankings over a
fixed corpus and fixed query are byte-identical on every call; ``seed`` is
accepted only to satisfy the ``Arm`` protocol.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from daedalus.eval import harness
from daedalus.structcore.languages import doc_spec_for, spec_for

from ..contracts import ArmBudget, FreezeError, FrozenTaskSet, PLANES
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Recall/score value that counts as a fully successful retrieval. Matches
#: ``daedalus.eval.gate3.arms.bm25``'s convention, which itself matches
#: ``daedalus.eval.harness``'s "perfect ``_recall`` is exactly 1.0".
_SUCCESS_THRESHOLD = 1.0

#: Declared proxy extensions for the two planes with no canonical Gate-2
#: classifier available to this packet (see module docstring). Extension
#: sets are deliberately small and literal -- no glob, no content sniffing --
#: so the classification is auditable from this one place.
_TYPE_EXTENSIONS = {".pyi", ".proto", ".graphql", ".fbs", ".thrift"}
_DATA_EXTENSIONS = {".csv", ".json", ".yaml", ".yml", ".sql", ".tsv", ".parquet"}


def classify_plane(rel_path: str) -> str | None:
    """Classify one repo-relative path into exactly one plane, or ``None``.

    Precedence is deliberate and non-overlapping, following the same
    "answers non-None to exactly one of them, or to neither" discipline
    ``daedalus.structcore.languages`` documents for ``spec_for``/``doc_spec_for``:
    a file ``spec_for`` already claims as code (e.g. ``types.py``) is reported
    as ``code``, never re-claimed by the ``type`` proxy below -- one file, one
    plane, no double counting.
    """
    if spec_for(rel_path) is not None:
        return "code"
    if doc_spec_for(rel_path) is not None:
        return "knowledge"
    fn = rel_path.rsplit("/", 1)[-1]
    if fn.endswith(".d.ts"):
        return "type"
    ext = os.path.splitext(fn)[1].lower()
    if ext in _TYPE_EXTENSIONS:
        return "type"
    if ext in _DATA_EXTENSIONS:
        return "data"
    return None


def plane_documents(root: str) -> dict[str, list[tuple[str, str]]]:
    """Walk ``root`` and bucket every classifiable file into its plane.

    Mirrors ``daedalus.eval.harness._repo_chunks``'s ignore-dir list and
    sorted walk exactly (``harness._IGNORE_DIRS``, sorted dirnames/filenames)
    so this arm's corpus universe is directly comparable to arm C's and to the
    ``bm25`` Gate-3 arm's, rather than silently differing by an ad-hoc filter
    of its own (packet §2: "Extend, never duplicate").

    Returns all four ``PLANES`` as keys always, even when a plane's list is
    empty -- an absent plane is an empty list, never a missing key, so a
    caller cannot "forget" to report it (packet §3, s06 lesson: a counter that
    cannot be non-zero, or a category that can silently vanish, is not a
    measurement).
    """
    docs: dict[str, list[tuple[str, str]]] = {p: [] for p in PLANES}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in harness._IGNORE_DIRS and not d.startswith(".")
        )
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            plane = classify_plane(rel)
            if plane is None:
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            docs[plane].append((rel, text))
    return docs


@dataclass
class SeparateIndicesArm:
    """Gate-3 baseline (h): four independent per-plane BM25 indices, no fusion.

    See the module docstring for the full defect history (s08), the R1/R3
    rules this class exists to satisfy, and the plane classification sources.
    """

    name: str = "separate_indices"
    stochastic: bool = False

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        del seed  # deterministic arm; accepted only to satisfy the Arm protocol
        try:
            docs_by_plane = plane_documents(task.repo_root)
            query = (task.question or "").strip() or harness._target_query(task.target)
        except FreezeError:
            raise  # contract violation: never swallowed (protocols.Arm docstring)
        except Exception as exc:  # ordinary failure -> an errored outcome
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

        # R1: budget_tokens below is the SAME full budget for every plane --
        # never budget.split(n) and never budget.max_tokens // len(PLANES).
        budget_tokens = budget.max_tokens if budget.max_tokens is not None else math.inf

        per_plane_notes: dict[str, object] = {}
        retrieval_by_plane: dict[str, dict] = {}
        for plane in PLANES:
            chunks = docs_by_plane.get(plane, [])
            if not chunks:
                # Absent, reported -- not dropped from the denominator (packet
                # §3 / s06 lesson: a category that silently disappears is how
                # a rate gets inflated without anyone changing a formula).
                per_plane_notes[plane] = {"present": False, "n_documents": 0}
                continue
            try:
                retrieval = harness._bm25_context(chunks, query, budget_tokens=budget_tokens)
            except FreezeError:
                raise
            except Exception as exc:
                return ArmOutcome(
                    error=f"{type(exc).__name__}: {exc}",
                    notes={"failed_plane": plane},
                )
            retrieval_by_plane[plane] = retrieval
            per_plane_notes[plane] = {
                "present": True,
                "n_documents": len(chunks),
                "n_chunks_used": retrieval["n_chunks_used"],
                "truncated": retrieval["truncated"],
                "tokens": retrieval["tokens"],
            }

        notes: dict[str, object] = {
            "budget_arrangement": (
                "each of the four per-plane indices received the FULL declared "
                "arm budget independently (max_tokens="
                f"{budget.max_tokens!r}); no shared budget was split or divided "
                "across planes (G3-BASE-01 rule R1; see the s08 finding in "
                "docs/GATE2_FOREST_V2_TRIAGE.md)."
            ),
            "budget_digest": budget.digest,
            "per_plane": per_plane_notes,
            "fusion": "none -- each plane's retrieval is scored independently; "
                      "no cross-plane rank merge or blend occurs in this arm",
            "query": query,
            "label_plane": task.label_plane,
        }

        label_plane = task.label_plane
        if label_plane not in PLANES:
            return ArmOutcome(
                error=f"task {task.task_id!r} declares unknown label_plane {label_plane!r} "
                      f"(known planes: {list(PLANES)})",
                notes=notes,
            )

        if label_plane not in retrieval_by_plane:
            # Honest null result: the plane holding this task's answer has no
            # documents in this repository, so a fusion-free arm could never
            # retrieve it. Reported as an ordinary miss, never silently scored
            # against a different plane's content (that would be an implicit
            # fusion, exactly what R3 forbids).
            return ArmOutcome(
                candidate="", score=0.0, success=False, tokens_used=0, notes=notes,
            )

        candidate = retrieval_by_plane[label_plane]["text"]
        try:
            score = evaluator.score(candidate, task)
        except FreezeError:
            raise
        except Exception as exc:
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}", notes=notes)

        # Sum across every PRESENT plane, not just the reported plane: this
        # arm really did build/query every one of those indices at full
        # budget, and that aggregate cost is the honest number R1 wants
        # visible (see module docstring; packet test B4 -- overrun is
        # reported, never clipped to flatter a budget-equality comparison).
        total_tokens = sum(r["tokens"] for r in retrieval_by_plane.values())

        return ArmOutcome(
            candidate=candidate,
            score=score,
            success=score >= _SUCCESS_THRESHOLD,
            tokens_used=total_tokens,
            notes=notes,
        )


def cross_plane_verdict(task_set: FrozenTaskSet, separate_score: float,
                         fusion_score: float, *,
                         separate_label: str = "separate_indices",
                         fusion_label: str = "fusion") -> str:
    """Compare this arm's aggregate score against a fusion baseline's -- but
    ONLY when ``task_set`` can honestly support a cross-plane comparison.

    This is the s08 defect made mechanical at the REPORTING layer, not just
    the budget layer: ``docs/GATE2_FOREST_V2_TRIAGE.md:109-131`` records that
    "four separate indices are strictly inferior to fusion" was reported
    against a task set whose gold labels were 100% code documents -- a
    comparison no cross-plane method could structurally win, because the
    answer was never anywhere fusion could find it that the code index could
    not. ``task_set.require_cross_plane()`` (packet rule R3) raises
    ``FreezeError`` for exactly that shape. This function calls it and lets it
    raise rather than catching it and printing a verdict anyway -- a caller
    cannot reproduce the original defect through this function, because there
    is no code path here that returns a "loses"/"beats" string for a
    single-plane task set.
    """
    task_set.require_cross_plane()
    if separate_score > fusion_score:
        return f"{separate_label} ({separate_score}) beats {fusion_label} ({fusion_score})"
    if separate_score < fusion_score:
        return f"{separate_label} ({separate_score}) loses to {fusion_label} ({fusion_score})"
    return f"{separate_label} ({separate_score}) ties {fusion_label} ({fusion_score})"
