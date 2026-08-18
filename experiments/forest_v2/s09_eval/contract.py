"""The adapter contract every measured retriever implements.

Two properties matter more than convenience here and are enforced
structurally, not by prose:

1. **The retriever cannot see its answer key.**  ``rank()`` receives a
   :class:`QueryView` and a candidate universe.  Neither carries the gold
   set; the gold lives only in the frozen task set the harness holds.  This
   mirrors the plan's evidence boundary (invariant 3/4): the thing being
   graded has no path to its grader.
2. **Every retriever gets the identical budget.**  The same candidate
   universe object, the same per-file content cap, the same cutoffs.  A
   retriever that reads more bytes than the declared cap simply cannot --
   :meth:`Candidate.text` truncates at the budget the harness set.

A retriever is any object with a ``name`` attribute and a ``rank`` method.
Slices s07/s08 and any later fusion plug in through
``module:factory`` dotted paths (see ``harness.load_retriever``); this
package never imports them, so the dependency arrow only ever points at the
harness.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Protocol, Sequence, Tuple, runtime_checkable


class ContractViolation(RuntimeError):
    """A retriever returned a ranking the harness refuses to score."""


@dataclass(frozen=True)
class Candidate:
    """One searchable file in the pre-image tree of a case.

    ``raw`` holds the bytes as stored; ``text`` decodes and truncates to the
    budget so no retriever can quietly buy accuracy with more input.
    """

    path: str
    blob: str
    size: int
    raw: bytes = field(repr=False, default=b"")
    content_budget: int = 65536

    def text(self) -> str:
        return self.raw[: self.content_budget].decode("utf-8", "replace")


@dataclass(frozen=True)
class QueryView:
    """What a retriever is allowed to know about a case.

    Deliberately gold-free.  ``variant`` says which frozen query text this
    is (``raw`` or ``scrubbed``) so a retriever may adapt, but it can never
    learn which files the commit touched.

    ``revision`` is the pre-image commit -- the tree the universe was taken
    from -- so a retriever may use history-derived priors.  It is the *only*
    revision a retriever may consult: reading anything committed after it is
    reading the answer.  That rule is a stated norm, not a sandbox; this
    package cannot stop a retriever with repository access from walking
    forward, and the plan is explicit that a prompt is not a boundary.
    """

    case_id: str
    text: str
    variant: str
    revision: str = ""


@runtime_checkable
class Retriever(Protocol):
    """Rank candidate paths for a query, best first."""

    name: str

    def rank(
        self, query: QueryView, universe: Sequence[Candidate]
    ) -> Sequence[str]:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class Budget:
    """The measurement budget, identical for every retriever in a run."""

    content_budget_bytes: int = 65536
    max_file_bytes: int = 200_000
    cutoffs: Tuple[int, ...] = (1, 5, 10, 20)
    text_suffixes: Tuple[str, ...] = (
        ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml",
        ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".csv",
        ".sh", ".cfg", ".ini", ".sql", ".rst",
    )

    @property
    def max_k(self) -> int:
        return max(self.cutoffs)

    def eligible(self, path: str, size: int) -> bool:
        if size <= 0 or size > self.max_file_bytes:
            return False
        lowered = path.lower()
        return any(lowered.endswith(sfx) for sfx in self.text_suffixes)

    def as_dict(self) -> Dict[str, object]:
        return {
            "content_budget_bytes": self.content_budget_bytes,
            "max_file_bytes": self.max_file_bytes,
            "cutoffs": list(self.cutoffs),
            "text_suffixes": list(self.text_suffixes),
        }


def validate_ranking(
    name: str, ranking: Sequence[str], universe: Sequence[Candidate], max_k: int
) -> List[str]:
    """Truncate and check a ranking before it is allowed to score.

    Rejects (loudly, never silently) a ranking that invents paths outside the
    universe or repeats one to buy extra draws.  A retriever that returns
    fewer than ``max_k`` paths is fine -- it just scores worse.
    """
    known = {cand.path for cand in universe}
    seen = set()
    out: List[str] = []
    for path in ranking:
        if path not in known:
            raise ContractViolation(
                f"retriever {name!r} returned {path!r}, which is not in the universe"
            )
        if path in seen:
            raise ContractViolation(
                f"retriever {name!r} returned duplicate path {path!r}"
            )
        seen.add(path)
        out.append(path)
        if len(out) >= max_k:
            break
    return out


def load_retriever(spec: str) -> Retriever:
    """Import a retriever from a ``module:attribute`` spec.

    The attribute may be the retriever itself or a zero-argument factory.
    This is the seam s07/s08/fusion attach to without this package taking a
    dependency on any of them.
    """
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise ContractViolation(f"retriever spec must be 'module:attribute', got {spec!r}")
    module = importlib.import_module(module_name)
    try:
        obj = getattr(module, attr)
    except AttributeError as exc:  # pragma: no cover - trivial
        raise ContractViolation(f"{module_name!r} has no attribute {attr!r}") from exc
    if isinstance(obj, type) or (callable(obj) and not hasattr(obj, "rank")):
        try:
            obj = obj()
        except TypeError as exc:
            raise ContractViolation(
                f"{spec!r} does not satisfy the retriever contract: "
                f"it is neither a retriever nor a zero-argument factory ({exc})"
            ) from exc
    if not hasattr(obj, "rank") or not hasattr(obj, "name"):
        raise ContractViolation(
            f"{spec!r} does not satisfy the retriever contract (needs .name and .rank)"
        )
    return obj  # type: ignore[return-value]
