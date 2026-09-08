"""diversity.py -- the D7 measure (plan §11 Gate 3, sentence 3: "diversity").

Packet §8, expected failure #4 (recorded before this module was built):

    "Diversity (D7) is underdetermined by the plan. Expect one declared
    definition with its limitations stated."

The plan never operationalizes "diversity." An undefined metric is
unfalsifiable, and `AGENTS.md`'s review rules class an unverifiable claim as a
release-blocking defect. This module makes ONE declared, falsifiable choice --
``DIVERSITY_DEFINITION`` -- rather than leaving the word to mean whatever a
later report wants it to mean. It is a LEXICAL metric over candidate strings.
It is deliberately not a semantic/behavioral one; see
``DIVERSITY_DEFINITION["does_not_capture"]`` for exactly what that gives up.

WHY LEXICAL AND NOT SEMANTIC: this packet is stdlib-only (no numpy, no
embedding model -- see the binding constraints in G3-BASE-01). An embedding-
based notion of diversity is a legitimate, probably stronger, alternative, but
it would require exactly the model dependency this harness's deterministic,
offline arms are built to avoid (`daedalus.eval.gate3.arms.embeddings` already
carries that cost for its own arm; duplicating it here for a measure that
every other arm's trials also flow through would make every deterministic arm
secretly depend on an embedder). Declaring the metric lexical and stating its
blind spots is the honest trade; calling a token-overlap number "semantic
diversity" would be the exact inflation this packet exists to prevent.

THE DEFINITION, precisely:
* distance(a, b) = 1 - Jaccard(tokens(a), tokens(b)), where tokens(x) is the
  set of whitespace-split, casefolded substrings of x (``x.casefold().split()``
  ). Two candidates with identical token sets have distance 0.0 regardless of
  token order or repetition; two candidates with disjoint non-empty token sets
  have distance 1.0; two candidates that are both empty-token have distance
  0.0 (both contribute nothing, so they are indistinguishable, not "maximally
  different").
* the headline ``value`` is the MEAN of that distance over every unordered
  pair of candidates.
* ``normalised_entropy`` is a second, complementary view: cluster candidates
  by EXACT string equality, take the Shannon entropy (base 2) of the cluster-
  size distribution, and divide by log2(n) -- the entropy of n singleton
  clusters, i.e. the maximum any partition of n items can reach. This gives a
  bounded [0, 1] view of "how spread out are the exact-duplicate clusters"
  that is independent of the token-level distance above (two candidates can
  be exact-string-distinct yet token-set-identical, e.g. word order swaps).
* ``n_distinct`` is the plain count of exact-string-distinct candidates.

DETERMINISM: every function here sorts its candidate list before doing any
pairwise or clustering arithmetic, so the result is identical for any
permutation of the same multiset of candidates -- summation order stops being
an accident of input order or of ``PYTHONHASHSEED``-dependent set/dict
iteration. Set/dict operations below are used only for their CARDINALITY
(``len(a & b)``, ``len(set(...))``, ``Counter(...).values()`` iterated over an
already-sorted input), never for an order-dependent numeric result, and
Python's built-in ``hash()`` of a string is never read directly.

REFUSALS: a single candidate has no partner to differ from. Reporting 0.0 for
that case would make "measured one candidate, found no diversity" and "did not
measure diversity at all" the same number -- exactly the structurally
guaranteed, unmeasured counter this repository's own triage document names as
a defect (``docs/GATE2_FOREST_V2_TRIAGE.md``, the s06 Node Cards row: "die
beiden Null-Zaehler sind strukturell garantiert, nicht gemessen"). So
``diversity()`` REFUSES (raises ``FreezeError``) for n < 2, both for n == 0
(no data at all) and n == 1 (one candidate, no comparison possible); it never
returns 0.0 for either.

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. This module is
Gate-3 prework; a value it produces is not Gate-3 baseline evidence until an
owner seals the harness (``daedalus.eval.gate3.contracts.RunManifest.sealed``).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Mapping, Sequence

from .contracts import FreezeError, TrialResult, partition_trials

#: The one declared diversity definition (packet rule: one metric, not a
#: family of undeclared candidates). Machine-readable so a report renderer can
#: quote it instead of re-describing the metric in prose each time. Every
#: value is a plain str/tuple so this constant itself is trivially JSON-
#: serializable and, being a ``MappingProxyType`` over a ``tuple``-valued
#: ``does_not_capture``, cannot be mutated by an importer.
DIVERSITY_DEFINITION: Mapping[str, object] = MappingProxyType({
    "metric": (
        "mean pairwise token-Jaccard distance over candidate strings, plus "
        "distinct-candidate count and normalised exact-string-cluster entropy"
    ),
    "distance": (
        "1 - |tokens(a) & tokens(b)| / |tokens(a) | tokens(b)|, where "
        "tokens(x) = set(x.casefold().split()); both-empty token sets => "
        "distance 0.0 (indistinguishable, not maximal); exactly one empty "
        "=> distance 1.0"
    ),
    "normalisation": (
        "normalised_entropy = ShannonEntropy_base2(exact-string cluster "
        "sizes / n) / log2(n); log2(n) is the entropy of n singleton "
        "clusters, the maximum any partition of n candidates can reach, so "
        "the result is bounded to [0, 1] independent of n"
    ),
    "does_not_capture": (
        "lexically different but semantically identical candidates "
        "(paraphrases, renamed identifiers, reworded sentences) score as "
        "maximally diverse: there is no embedding or meaning model behind "
        "this metric, only surface tokens",

        "token-SET distance is blind to order and structure: two candidates "
        "built from the same tokens in a different sequence (swapped clauses, "
        "reordered arguments, transposed lines) have distance exactly 0.0, "
        "even though they may be structurally very different candidates",

        "token-set distance is also blind to multiplicity: it operates on "
        "sets, not multisets, so 'a a a b' and 'a b' are distance 0.0 apart",

        "whitespace-plus-casefold tokenization means punctuation, exact "
        "formatting, and case are the only sub-token distinctions collapsed; "
        "two candidates differing only in insignificant formatting can "
        "register as different tokens if punctuation is not separated",

        "exact-string-cluster entropy and n_distinct measure lexical "
        "duplication, not behavioral or functional coverage: two candidates "
        "that are byte-for-byte distinct (e.g. a cosmetic rename or an added "
        "comment) count as fully distinct even if they behave identically, "
        "and this metric cannot tell 'diverse text' from 'diverse behavior'",

        "this is not the archive/MAP-Elites notion of diversity (behavioural "
        "cell coverage over a declared descriptor space, see "
        "daedalus.eval.gate3.arms.map_elites) and does not replace or "
        "approximate it; a search-space-coverage claim needs that measure, "
        "not this one",
    ),
})


def _tokens(candidate: str) -> frozenset[str]:
    return frozenset(candidate.casefold().split())


def _jaccard_distance(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0  # unreachable given the guard above; kept for safety
    intersection = a & b
    return 1.0 - (len(intersection) / len(union))


@dataclass(frozen=True)
class DiversityResult:
    """D7 for one set of candidate strings. Never a bare float (packet
    instruction): the headline ``value`` is meaningless without ``n_candidates``
    next to it, and ``definition`` pins exactly which metric produced it so a
    reader never has to guess or trust an unstated convention.

    ``value`` is the mean pairwise token-Jaccard distance (see module
    docstring). ``n_distinct`` and ``normalised_entropy`` are the two
    complementary views ``DIVERSITY_DEFINITION["metric"]`` declares.
    """

    value: float
    n_candidates: int
    n_distinct: int
    normalised_entropy: float
    definition: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.n_candidates < 2:
            raise FreezeError(
                f"DiversityResult.n_candidates must be >= 2, got "
                f"{self.n_candidates}; a diversity value with fewer than two "
                "candidates cannot exist (see diversity()'s refusal rule)")
        if not (0.0 <= self.value <= 1.0):
            raise FreezeError(
                f"DiversityResult.value {self.value!r} is outside [0, 1] -- "
                "a Jaccard distance is always in that range; something "
                "upstream is not this module's distance function")
        if not (0.0 <= self.normalised_entropy <= 1.0 + 1e-12):
            raise FreezeError(
                f"DiversityResult.normalised_entropy {self.normalised_entropy!r} "
                "is outside [0, 1]")
        if not (1 <= self.n_distinct <= self.n_candidates):
            raise FreezeError(
                f"DiversityResult.n_distinct ({self.n_distinct}) must be "
                f"between 1 and n_candidates ({self.n_candidates})")


def diversity(candidates: Sequence[str]) -> DiversityResult:
    """The D7 measure over a flat sequence of candidate strings.

    REFUSES (raises ``FreezeError``), rather than returning 0.0, when there
    are fewer than two candidates:

    * zero candidates -- nothing was measured, there is no value to report;
    * exactly one candidate -- diversity is a relationship between candidates,
      and a single candidate has no partner to differ from. Reporting 0.0
      here would collapse "one candidate, trivially no diversity" and "did
      not measure diversity" into the same number, which is precisely the
      structurally-guaranteed-counter defect this module's docstring cites.

    Deterministic and independent of input order (see module docstring): the
    candidates are sorted before any pairwise or clustering arithmetic runs.
    """
    n = len(candidates)
    if n == 0:
        raise FreezeError(
            "diversity() over zero candidates is undefined -- pass at least "
            "two candidate strings, or report 'no candidates' explicitly "
            "rather than calling this with an empty sequence")
    if n == 1:
        raise FreezeError(
            "diversity() of exactly one candidate is UNDEFINED, not 0.0: a "
            "single candidate has no partner to differ from. Returning 0.0 "
            "would make 'no diversity' and 'not measurable' indistinguishable "
            "(docs/GATE2_FOREST_V2_TRIAGE.md, the s06 Node Cards finding: a "
            "counter that cannot be non-zero is not a measurement).")

    ordered = sorted(candidates)
    token_sets = [_tokens(c) for c in ordered]
    pairs = list(combinations(range(n), 2))
    distances = [_jaccard_distance(token_sets[i], token_sets[j]) for i, j in pairs]
    mean_distance = sum(distances) / len(distances)

    clusters = Counter(ordered)
    n_distinct = len(clusters)
    if n_distinct == 1:
        entropy = 0.0
    else:
        entropy = -sum(
            (count / n) * math.log2(count / n) for count in clusters.values()
        )
    max_entropy = math.log2(n)  # n >= 2 here, so max_entropy > 0
    normalised_entropy = entropy / max_entropy

    return DiversityResult(
        value=mean_distance,
        n_candidates=n,
        n_distinct=n_distinct,
        normalised_entropy=normalised_entropy,
        definition=DIVERSITY_DEFINITION,
    )


@dataclass(frozen=True)
class TrialDiversity:
    """D7 applied to one arm's trials, with the trial-level bookkeeping
    ``diversity()`` alone cannot see: how many trials were measured, how many
    errored (and were therefore excluded), and how many measured trials had
    no extractable candidate string at all (see ``diversity_of_trials``'s
    docstring for why that last count exists and is not silently zero).
    """

    diversity: DiversityResult
    n_measured: int
    n_errored: int
    n_without_candidate: int

    def __post_init__(self) -> None:
        for f_name in ("n_measured", "n_errored", "n_without_candidate"):
            if getattr(self, f_name) < 0:
                raise FreezeError(f"TrialDiversity.{f_name} cannot be negative")
        if self.n_without_candidate > self.n_measured:
            raise FreezeError(
                f"TrialDiversity.n_without_candidate ({self.n_without_candidate}) "
                f"cannot exceed n_measured ({self.n_measured})")


def diversity_of_trials(trials: Sequence[TrialResult],
                         candidate_key: str = "candidate") -> TrialDiversity:
    """D7 over one arm's candidate outputs.

    KNOWN LIMITATION, stated up front rather than silently worked around:
    ``daedalus.eval.gate3.contracts.TrialResult`` has no dedicated candidate-
    text field -- ``protocols.run_trial`` does not carry ``ArmOutcome.candidate``
    forward into the ``TrialResult`` it builds. That is existing, out-of-scope
    contract shape this module does not own or edit (G3-BASE-01 forbids
    touching ``contracts.py``/``protocols.py`` from this file). So this
    function reads the candidate text from ``trial.notes[candidate_key]``
    (default key ``"candidate"``) when an arm happens to have recorded one
    there as a convention (as ``arms/evaluator_only.py`` does), rather than
    from a field the contract guarantees.

    A measured trial (``partition_trials`` excludes errored ones first) whose
    ``notes`` has no usable string under ``candidate_key`` is EXCLUDED from
    the diversity computation and counted in ``TrialDiversity.n_without_candidate``
    -- never silently treated as an empty-string candidate, which would
    fabricate data the trial never actually reported, and never silently
    dropped without a visible count, which would understate how much of the
    arm's output this measurement actually covers.

    Refuses (via ``diversity()``) when fewer than two trials yield a usable
    candidate string, naming exactly how many measured trials were unusable
    and why.
    """
    measured, errored = partition_trials(trials)
    candidates: list[str] = []
    n_without_candidate = 0
    for trial in measured:
        # RESOLVED 2026-09-06: TrialResult now carries `candidate` as a real
        # field, and protocols.run_trial forwards ArmOutcome.candidate into it.
        # The notes-key fallback is kept for arms that recorded a candidate
        # under a custom key, but the contract field is authoritative.
        value = getattr(trial, "candidate", None)
        if not isinstance(value, str):
            notes = trial.notes
            value = notes.get(candidate_key) if isinstance(notes, Mapping) else None
        if isinstance(value, str):
            candidates.append(value)
        else:
            n_without_candidate += 1

    if len(candidates) < 2:
        raise FreezeError(
            f"diversity_of_trials needs >= 2 measured trials carrying a "
            f"string {candidate_key!r} note; got {len(candidates)} usable "
            f"candidate(s) out of {len(measured)} measured trial(s) "
            f"({len(errored)} errored, excluded; {n_without_candidate} "
            f"measured trial(s) had no usable {candidate_key!r} note). "
            "TrialResult has no dedicated candidate field, so this reads an "
            "arm-supplied convention note rather than a guaranteed contract "
            "field -- see diversity_of_trials's docstring.")

    result = diversity(candidates)
    return TrialDiversity(
        diversity=result,
        n_measured=len(measured),
        n_errored=len(errored),
        n_without_candidate=n_without_candidate,
    )
