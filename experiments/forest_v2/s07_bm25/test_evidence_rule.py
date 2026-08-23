"""EXPERIMENT s07: self-tests for the per-(query, document) contamination rule.

The property under test is the one the blanket file list did not have:

    a document that leaks the answer to query A is still a competitor for
    query B.

Everything else here exists to pin the edges where a looser or tighter rule
would quietly change the baseline -- and the mutation probe at the bottom
checks that these assertions actually bite, by weakening the rule on purpose
and demanding that something fails.

Run:  python -m pytest experiments/forest_v2/s07_bm25/test_evidence_rule.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contamination import (  # noqa: E402
    ADOPTED_RULE,
    QUERY_QUOTE_ONLY,
    REASON_GOLD_PATH_CITATION,
    REASON_QUERY_QUOTE,
    EvidenceRule,
    normalise,
    scan,
)

QUERY_A = "hard ceiling on money ledger backed fail closed"
GOLD_A = ("daedalus/budget.py",)
QUERY_B = "content addressed artifact store and storage watermark"
GOLD_B = ("daedalus/storage.py",)
QUERY_SET = ((QUERY_A, GOLD_A), (QUERY_B, GOLD_B))


def reasons(rule: EvidenceRule, query, gold, path, text):
    return rule.reasons(
        query=query, gold=gold, doc_path=path, doc_text=text, all_queries=QUERY_SET
    )


# ---- the property the blanket list did not have ------------------------


def test_a_carrier_for_one_query_stays_in_the_corpus_for_another():
    """THE point of the rewrite: contamination is per pair, not per file."""
    carrier = f'QUERY = "{QUERY_A}"\nsome other prose about storage and artifacts\n'
    assert reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "eval/sheet.py", carrier)
    assert reasons(ADOPTED_RULE, QUERY_B, GOLD_B, "eval/sheet.py", carrier) == ()


def test_scan_withholds_the_carrier_from_exactly_one_query():
    carrier = f'QUERY = "{QUERY_A}"\n'
    corpus = [("eval/sheet.py", carrier), ("daedalus/storage.py", "watermark of the store")]
    result = scan(corpus, QUERY_SET)
    assert result.documents_scanned == 2
    assert result.excluded_for(QUERY_A) == frozenset({"eval/sheet.py"})
    assert result.excluded_for(QUERY_B) == frozenset()
    assert result.pair_count == 1
    assert result.reason_counts()[REASON_QUERY_QUOTE] == 1


# ---- the gold document is not its own contaminant ----------------------


def test_gold_document_is_never_withheld_from_its_own_query():
    """Withholding the gold would make the query unanswerable, not clean."""
    self_quoting_gold = f"# {QUERY_A}\n# see daedalus/budget.py\n"
    assert reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "daedalus/budget.py", self_quoting_gold) == ()


def test_the_gold_exemption_does_not_leak_to_another_query():
    """Being gold for A buys nothing for B."""
    text = f"quotes {QUERY_B} verbatim"
    assert reasons(ADOPTED_RULE, QUERY_B, GOLD_B, "daedalus/budget.py", text)


# ---- what counts as a quote --------------------------------------------


def _wrapped(query: str) -> str:
    """The query as a Markdown paragraph would carry it: broken at a space."""
    words = query.split(" ")
    half = len(words) // 2
    return "the frozen query is\n  " + " ".join(words[:half]) + "\n  " + " ".join(words[half:]) + "\n"


def test_a_line_wrapped_quote_still_counts():
    """Reflowing a paragraph must not launder a leak."""
    assert REASON_QUERY_QUOTE in reasons(
        ADOPTED_RULE, QUERY_A, GOLD_A, "readme.md", _wrapped(QUERY_A)
    )


def test_a_break_inside_a_word_is_not_the_same_string():
    """Whitespace collapsing joins words, it does not glue a broken one back."""
    broken = f"{QUERY_A[:20]}\n{QUERY_A[20:]}"
    assert REASON_QUERY_QUOTE not in reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "readme.md", broken)


def test_case_differences_do_not_launder_a_leak():
    assert REASON_QUERY_QUOTE in reasons(
        ADOPTED_RULE, QUERY_A, GOLD_A, "readme.md", QUERY_A.upper()
    )


def test_merely_sharing_words_with_the_query_is_not_contamination():
    """A competitor is not a carrier -- this is where over-broad rules die."""
    competitor = "the ledger enforces a hard ceiling, and money never leaves without it"
    assert reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "daedalus/ledger_notes.md", competitor) == ()


# ---- what counts as citing the answer ----------------------------------


def test_a_verbatim_gold_path_is_a_citation():
    doc = "the receipt scanner walks daedalus/budget.py before every run"
    assert reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "runs/receipt.md", doc) == (
        REASON_GOLD_PATH_CITATION,
    )


def test_a_windows_separator_citation_counts_the_same():
    doc = r"walked daedalus\budget.py on windows"
    assert REASON_GOLD_PATH_CITATION in reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "runs/r.md", doc)


def test_an_import_of_the_gold_module_is_not_a_citation():
    """`from daedalus.budget import ...` is the call graph, not the answer key.

    A punctuation-stripping normalisation would match it and delete the
    repository's own structure from the corpus.  Pinned so nobody loosens
    `normalise` without seeing this fail.
    """
    doc = "from daedalus.budget import Ledger\nledger = Ledger()\n"
    assert reasons(ADOPTED_RULE, QUERY_A, GOLD_A, "daedalus/kernel.py", doc) == ()


def test_query_quote_only_rule_ignores_citations():
    """The conservative half is genuinely narrower, so the pair is informative."""
    doc = "the receipt scanner walks daedalus/budget.py before every run"
    assert reasons(QUERY_QUOTE_ONLY, QUERY_A, GOLD_A, "runs/receipt.md", doc) == ()
    assert reasons(QUERY_QUOTE_ONLY, QUERY_A, GOLD_A, "runs/r.md", QUERY_A) == (
        REASON_QUERY_QUOTE,
    )


def test_normalise_is_the_documented_transformation():
    assert normalise("A\\B\n  c\td") == "a/b c d"


# ---- mutation probe ----------------------------------------------------
#
# Each entry weakens the rule in a way a hurried edit plausibly would, and the
# probe demands that at least one assertion above notices.  A mutant nobody
# kills means the corresponding assertion is decoration.

CORE_ASSERTIONS = {
    "per_query_isolation": lambda rule: reasons(
        rule, QUERY_B, GOLD_B, "eval/sheet.py", f'QUERY = "{QUERY_A}"\n'
    )
    == (),
    "gold_survives": lambda rule: reasons(
        rule, QUERY_A, GOLD_A, "daedalus/budget.py", f"# {QUERY_A}\n"
    )
    == (),
    "competitor_survives": lambda rule: reasons(
        rule,
        QUERY_A,
        GOLD_A,
        "daedalus/ledger_notes.md",
        "the ledger enforces a hard ceiling, and money never leaves without it",
    )
    == (),
    "import_survives": lambda rule: reasons(
        rule, QUERY_A, GOLD_A, "daedalus/kernel.py", "from daedalus.budget import Ledger\n"
    )
    == (),
    "wrapped_quote_caught": lambda rule: bool(
        reasons(rule, QUERY_A, GOLD_A, "readme.md", _wrapped(QUERY_A))
    ),
    "citation_caught": lambda rule: bool(
        reasons(rule, QUERY_A, GOLD_A, "runs/receipt.md", "walks daedalus/budget.py here")
    ),
}

MUTANTS = {
    "blanket_filter_again": EvidenceRule(query_independent=True),
    "match_single_query_tokens": EvidenceRule(token_level_query_match=True),
    "withhold_the_gold_too": EvidenceRule(exempt_gold=False),
    "no_whitespace_collapse": EvidenceRule(collapse_whitespace=False),
    "forget_path_citations": EvidenceRule(check_gold_path=False),
    "forget_query_quotes": EvidenceRule(check_query_quote=False),
}


def test_the_adopted_rule_satisfies_every_core_assertion():
    failed = [name for name, check in CORE_ASSERTIONS.items() if not check(ADOPTED_RULE)]
    assert failed == []


@pytest.mark.parametrize("mutant_name", sorted(MUTANTS))
def test_mutation_probe_every_weakened_rule_is_killed(mutant_name):
    mutant = MUTANTS[mutant_name]
    killed_by = [name for name, check in CORE_ASSERTIONS.items() if not check(mutant)]
    assert killed_by, f"mutant {mutant_name!r} survives every assertion"


# ---- the rule, applied to the tree it was written for ------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_on_the_real_tree_the_readme_is_withheld_selectively(tmp_path):
    """The concrete defect: the README was withheld from all 12 queries.

    Under the evidence rule it is withheld only from the queries it actually
    quotes or whose gold path it actually cites, and it competes in the rest.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import measure_bm25

    readme = "experiments/forest_v2/README.md"
    root = _repo_root()
    text = (root / readme).read_text(encoding="utf-8", errors="replace")
    query_set = measure_bm25.pair_query_set()

    withheld = [
        query
        for query, gold in query_set
        if ADOPTED_RULE.reasons(query=query, gold=gold, doc_path=readme, doc_text=text)
    ]
    assert withheld, "the README does carry some queries -- the rule must catch those"
    assert len(withheld) < len(query_set), (
        "the README was withheld from every query again -- that is the blanket rule"
    )
