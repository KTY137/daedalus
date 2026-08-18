"""EXPERIMENT s07: the per-(query, document) contamination evidence rule.

WHY THIS FILE REPLACED A FILE LIST
----------------------------------
The first version of this slice excluded three whole files -- the measurement
script, its self-test and the slice README -- from *every* scored query, on the
grounds that they "quote the queries and the gold paths verbatim".  That is true
of the script and the self-test, which contain the entire frozen query set.  It
is **not** true of the README, which quotes some queries and some gold paths and
not others; an independent review put it at 1 of 12 queries, and the mechanical
scan in this module settles the real number.

The damage was not bookkeeping.  Dropping a whole document from every query
removes a *competing document* from eleven queries it never contaminated, and
that raises the score.  Measured on this tree the blanket rule was worth
+0.056 MRR and +1 h@1 over the rule below.  A baseline lifted by an after-the-fact
corpus filter is not a floor -- and every later graph-conditioned retriever is
supposed to be measured against this floor, so a floor set too low makes the
whole comparison flatter the hypothesis.

THE RULE
--------
Contamination is a property of a *pair*, never of a file:

    a document D is withheld from query Q  iff
        (C1) D's text contains Q's query string verbatim, or
        (C2) D's text contains one of Q's gold paths verbatim
    unless D *is* one of Q's gold documents.

Both classes are decided mechanically by substring containment on a normalised
form; no file is ever named by hand.  D stays in the corpus for every other
query, so a document that leaks the answer to Q still competes for R.

WHAT THE NORMALISATION DOES AND WHY IT STOPS THERE
--------------------------------------------------
``normalise`` casefolds, turns ``\\`` into ``/`` and collapses runs of
whitespace to one space.  Whitespace collapsing is load-bearing: a Markdown
document that quotes a query across a line break is quoting it, and a rule that
missed that would be trivially evadable by reflowing a paragraph.

The normalisation deliberately stops there.  It does **not** strip punctuation
and it does **not** tokenise, because a looser match reintroduces the very
defect it is fixing.  Two concrete cases decided the shape:

* ``from daedalus.budget import Ledger`` must NOT count as citing
  ``daedalus/budget.py``.  That is an ordinary import, i.e. real corpus
  structure and exactly the signal retrieval is supposed to find.  Under
  punctuation-stripping normalisation ("daedalus budget py" vs "daedalus
  budget") it would have matched, and the rule would have deleted the
  repository's own call graph from the corpus.
* a document that merely shares words with the query is a competitor, not a
  carrier.  Only the query *as issued* counts.

C2 is the aggressive half and it is reported separately for that reason: a
receipt that names the gold path knows the answer, but it is also legitimate
repository content.  ``measure_bm25.py`` therefore scores C1-only and C1+C2 side
by side, and never quotes one without the other.

Read-only, stdlib only, no repository imports, no writes, no network, no
subprocess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

REASON_QUERY_QUOTE = "query_quote"
REASON_GOLD_PATH_CITATION = "gold_path_citation"
ALL_REASONS: tuple[str, ...] = (REASON_QUERY_QUOTE, REASON_GOLD_PATH_CITATION)

_WS_RE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Casefold, unify path separators, collapse whitespace runs to one space."""
    return _WS_RE.sub(" ", text.replace("\\", "/").casefold())


@dataclass(frozen=True)
class EvidenceRule:
    """The contamination rule, with every knob it could plausibly be weakened by.

    The defaults ARE the rule.  The flags exist so the mutation probe in
    ``test_evidence_rule.py`` can build a weakened variant and check that the
    self-tests notice; a knob that no test kills is a knob that documents
    nothing.
    """

    #: C1 -- the document quotes the query as issued.
    check_query_quote: bool = True
    #: C2 -- the document cites one of the query's gold paths verbatim.
    check_gold_path: bool = True
    #: a gold document is never withheld from its own query (else the query is
    #: unanswerable and the metric silently measures a different question).
    exempt_gold: bool = True
    #: collapse whitespace before matching, so a line-wrapped quote still counts.
    collapse_whitespace: bool = True
    #: MUTANT ONLY: match single query tokens instead of the query as issued.
    #: This is the "too broad" failure mode -- it re-creates a blanket filter.
    token_level_query_match: bool = False
    #: MUTANT ONLY: ignore the query and withhold a carrier from every query.
    #: This is the exact defect being repaired; kept nameable so it is testable.
    query_independent: bool = False

    def _prepare(self, text: str) -> str:
        return normalise(text) if self.collapse_whitespace else text.replace("\\", "/").casefold()

    def reasons(
        self,
        *,
        query: str,
        gold: Sequence[str],
        doc_path: str,
        doc_text: str,
        all_queries: Sequence[tuple[str, Sequence[str]]] = (),
    ) -> tuple[str, ...]:
        """Why ``doc_path`` is withheld from ``query`` -- empty tuple means it stays.

        ``all_queries`` is only consulted by the ``query_independent`` mutant;
        the real rule never looks at another query's evidence.
        """
        if self.exempt_gold and doc_path in set(gold):
            return ()
        pairs: list[tuple[str, Sequence[str]]] = [(query, gold)]
        if self.query_independent:
            pairs = list(all_queries) or pairs
        haystack = self._prepare(doc_text)
        found: list[str] = []
        for one_query, one_gold in pairs:
            if self.check_query_quote:
                if self.token_level_query_match:
                    needles = [t for t in self._prepare(one_query).split(" ") if t]
                else:
                    needles = [self._prepare(one_query)]
                if any(needle and needle in haystack for needle in needles):
                    found.append(REASON_QUERY_QUOTE)
            if self.check_gold_path:
                if any(self._prepare(path) in haystack for path in one_gold):
                    found.append(REASON_GOLD_PATH_CITATION)
        return tuple(sorted(set(found)))


#: The rule as adopted.  Anything else in this module is a mutant.
ADOPTED_RULE = EvidenceRule()

#: C1 alone -- the conservative half, reported next to the full rule so the
#: cost of the aggressive half (C2) is a number instead of an argument.
QUERY_QUOTE_ONLY = EvidenceRule(check_gold_path=False)


@dataclass(frozen=True)
class ContaminationMap:
    """Which documents are withheld from which query, and why.

    ``withheld[query] -> {path: reasons}``.  Keyed by query string, so an arm
    that indexes a smaller corpus just intersects with its own path set; the
    scan runs once over the widest corpus and is reused by every arm.
    """

    rule_name: str
    withheld: Mapping[str, Mapping[str, tuple[str, ...]]]
    documents_scanned: int

    def excluded_for(self, query: str) -> frozenset[str]:
        return frozenset(self.withheld.get(query, {}))

    @property
    def pair_count(self) -> int:
        return sum(len(paths) for paths in self.withheld.values())

    def reason_counts(self) -> dict[str, int]:
        counts = {reason: 0 for reason in ALL_REASONS}
        for paths in self.withheld.values():
            for reasons in paths.values():
                for reason in reasons:
                    counts[reason] = counts.get(reason, 0) + 1
        return counts

    def as_dict(self) -> dict:
        """RAW: every withheld pair, with its reason, listed."""
        return {
            "rule": self.rule_name,
            "documents_scanned": self.documents_scanned,
            "pairs_withheld": self.pair_count,
            "reason_counts": self.reason_counts(),
            "per_query": {
                query: {
                    "withheld": len(paths),
                    "documents": {path: list(reasons) for path, reasons in sorted(paths.items())},
                }
                for query, paths in sorted(self.withheld.items())
            },
        }


def scan(
    documents: Iterable[tuple[str, str]],
    query_set: Sequence[tuple[str, Sequence[str]]],
    rule: EvidenceRule = ADOPTED_RULE,
    rule_name: str = "adopted",
) -> ContaminationMap:
    """Apply ``rule`` to every (query, document) pair of a corpus.

    ``documents`` is consumed once and streamed, so the caller can hand it
    ``bm25_index.iter_documents`` without materialising the tree in memory.
    """
    withheld: dict[str, dict[str, tuple[str, ...]]] = {query: {} for query, _ in query_set}
    scanned = 0
    for path, text in documents:
        scanned += 1
        for query, gold in query_set:
            reasons = rule.reasons(
                query=query,
                gold=gold,
                doc_path=path,
                doc_text=text,
                all_queries=query_set,
            )
            if reasons:
                withheld[query][path] = reasons
    return ContaminationMap(rule_name=rule_name, withheld=withheld, documents_scanned=scanned)
