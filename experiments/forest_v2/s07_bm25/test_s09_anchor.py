"""EXPERIMENT s07: self-tests for the s09 anchoring bridge.

Three things have to hold or the anchored numbers mean nothing:

* the frozen task set is really frozen -- an edited copy must fail loudly
  instead of scoring;
* the metric definitions match the ones s09 states, including the bit where a
  gold file outside the measured window scores 0 and not a tail value;
* the token-count fast path (twenty overlapping historical trees, each blob
  tokenised once) produces the *same ranking* as the plain text path, or the
  speed-up would have bought a different experiment.

Run:  python -m pytest experiments/forest_v2/s07_bm25/test_s09_anchor.py -q
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bm25_index import BM25Index, IndexConfig, token_counts  # noqa: E402
from contamination import ADOPTED_RULE  # noqa: E402
from measure_bm25 import (  # noqa: E402
    LEGACY_QUERY_CARRIERS,
    QUERY_SET,
    _blanket_map,
    _legacy_under_evidence_map,
)
from s09_anchor import (  # noqa: E402
    TASKSET_PATH,
    AnchorError,
    _eligible,
    aggregate,
    load_taskset,
    score_case,
)

# sha256 over the newline-NORMALISED text of the task set s09 froze at 4000f77a.
# This is the digest of the committed blob (LF); see the test below for why a
# raw-byte pin was a property of the checkout rather than of the file.
S09_FROZEN_CONTENT_SHA256 = "e1f850b79189e157abcd65da878b22747968a27a43db36e3029902990d08c0e6"

CORPUS = {
    "daedalus/budget.py": "the ledger enforces a hard ceiling on spend before any call",
    "daedalus/storage.py": "content addressed artifact store with a watermark",
    "runs/receipt.md": "receipt: walked daedalus/budget.py and the ledger",
    "notes/spend.md": "a note about ceiling and ledger and spend",
}


# ---- the fast path may not change a ranking ----------------------------


def test_counted_documents_match_from_documents():
    config = IndexConfig(path_weight=3)
    plain = BM25Index.from_documents(CORPUS, config)
    counted = BM25Index.from_counted_documents(
        {path: token_counts(text) for path, text in CORPUS.items()}, config
    )
    assert counted.paths == plain.paths
    assert counted.doc_len == plain.doc_len
    assert counted.postings == plain.postings
    for query in ("hard ceiling ledger", "artifact store watermark", "receipt"):
        assert [h.as_dict() for h in counted.search(query, k=5)] == [
            h.as_dict() for h in plain.search(query, k=5)
        ]


def test_counted_documents_still_apply_the_path_boost():
    counted = BM25Index.from_counted_documents(
        {"daedalus/budget.py": Counter({"ledger": 1})}, IndexConfig(path_weight=3)
    )
    assert counted.search("budget", k=1)[0].path == "daedalus/budget.py"


# ---- the frozen task set is frozen -------------------------------------


def test_the_copied_taskset_verifies_against_its_own_digest():
    record = load_taskset()
    assert record["schema"] == "forest_v2.s09.taskset/1"
    assert len(record["cases"]) == 20
    assert sum(len(case["gold"]) for case in record["cases"]) == 35


def test_the_copy_is_content_identical_to_what_s09_froze():
    """The self-consistent digest is necessary but NOT sufficient.

    ``load_taskset`` recomputes the digest from ``record["cases"]`` alone, so it
    catches an edit that forgets to re-stamp the digest -- but an editor who
    recomputes both walks straight through, and that rule never covers the
    non-case fields at all (``universe_rule``, ``selection``, ``anchor_commit``,
    ``strata_actual``).  Those are exactly the fields this module reads the
    universe rule out of instead of re-typing it, so they need a pin of their
    own.  This one covers the whole file s09 committed at 4000f77a ("the task
    set freezes before a single retriever exists").

    The digest is taken over the newline-NORMALISED text, not over the raw
    bytes, and that is the whole point.  A raw-byte digest pins the checkout,
    not the file: under ``core.autocrlf=true`` this path lands as CRLF and
    hashes to fe05b1c1..., while the blob s09 committed is LF and hashes to
    the value above, and no repository line-ending attribute is set for this
    path to make the two agree.  The previous pin held the CRLF value while
    its docstring claimed to pin the committed bytes -- so the drift guard
    passed only by accident of a local git setting, and failed on the very
    bytes it named.  Normalising first makes the assert checkout-independent
    and makes the pinned constant the one s09 really froze.
    """
    normalised = TASKSET_PATH.read_text(encoding="utf-8")
    actual = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    assert actual == S09_FROZEN_CONTENT_SHA256


def test_an_edited_taskset_is_refused(tmp_path):
    record = json.loads(TASKSET_PATH.read_text(encoding="utf-8"))
    record["cases"][0]["gold"] = ["daedalus/budget.py"]
    edited = tmp_path / "taskset.json"
    edited.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AnchorError, match="digest mismatch"):
        load_taskset(edited)


def test_eligibility_reproduces_the_two_edges_that_were_wrong_first_time():
    """Empty files are out; the suffix match is case-insensitive.

    Getting either wrong put 33 extra documents into every universe and the
    run said so.  Pinned here so the next reader does not rediscover it.
    """
    suffixes = frozenset({".py", ".md"})
    assert _eligible("a/b.py", 10, suffixes, 200000)
    assert not _eligible("a/empty.py", 0, suffixes, 200000)
    assert not _eligible("a/huge.py", 200001, suffixes, 200000)
    assert _eligible("a/README.MD", 10, suffixes, 200000)
    assert not _eligible("a/binary.png", 10, suffixes, 200000)


def test_every_case_carries_a_parent_and_a_nonempty_query():
    for case in load_taskset()["cases"]:
        assert len(case["parent"]) == 40
        assert case["query_raw"].strip()
        assert case["gold"]


# ---- the metric is s09's metric ----------------------------------------


def test_score_case_counts_gold_inside_each_cutoff():
    score = score_case(["a", "b", "c"], ["c", "z"], [1, 5, 10, 20])
    assert score["gold_total"] == 2
    assert score["hits_at"] == {1: 0, 5: 1, 10: 1, 20: 1}
    assert score["first_hit_rank"] == 3
    assert score["reciprocal_rank"] == pytest.approx(1 / 3)


def test_a_gold_outside_the_window_scores_zero_not_a_tail_value():
    ranking = [f"f{i}" for i in range(30)] + ["gold"]
    score = score_case(ranking, ["gold"], [1, 5, 10, 20])
    assert score["first_hit_rank"] == 31
    assert score["reciprocal_rank"] == 0.0


def test_macro_and_micro_recall_answer_different_questions():
    one_of_five = score_case(["g1"], [f"g{i}" for i in range(1, 6)], [1])
    one_of_one = score_case(["h1"], ["h1"], [1])
    agg = aggregate([one_of_five, one_of_one], [1])
    # the aggregate rounds to four places, as the report does
    assert agg["macro_recall_at"][1] == pytest.approx(round((0.2 + 1.0) / 2, 4))
    assert agg["micro_recall_at"][1] == pytest.approx(round(2 / 6, 4))
    assert agg["cases_with_any_hit"] == 2


# ---- the evidence rule behaves on s09-shaped cases ---------------------


def test_the_over_exclusion_arm_is_a_subset_of_both_rules_it_sits_between():
    """The decomposition arm must be bounded by the two arms it separates.

    ``blanket_postfilter`` withholds all three legacy documents from all twelve
    queries; this arm withholds them only where C1 fires.  If it ever withheld
    a pair the blanket did not, the subtraction ``blanket - this`` would stop
    meaning "what the over-exclusion bought" and the reported
    ``over_exclusion_alone`` would be uninterpretable.
    """
    quote_only = {query: frozenset(gold and ()) for query, gold in QUERY_SET}
    quote_only[QUERY_SET[0][0]] = frozenset(LEGACY_QUERY_CARRIERS) | {"some/other.py"}

    arm = _legacy_under_evidence_map(quote_only)
    blanket = _blanket_map(sorted(LEGACY_QUERY_CARRIERS))

    assert set(arm) == {query for query, _ in QUERY_SET}
    for query, _ in QUERY_SET:
        assert arm[query] <= blanket[query], "arm withholds a pair the blanket did not"
        assert arm[query] <= frozenset(quote_only[query]), "arm withholds a pair C1 did not"
        assert arm[query] <= LEGACY_QUERY_CARRIERS
    # the one query whose C1 set covers the carriers withholds exactly them,
    # and the unrelated path is not dragged in
    assert arm[QUERY_SET[0][0]] == LEGACY_QUERY_CARRIERS
    assert all(not arm[query] for query, _ in QUERY_SET[1:])


def test_a_receipt_citing_the_gold_is_withheld_only_from_that_case():
    """Same corpus, two cases: the citation is evidence for one of them only."""
    case_a = ("make the ledger fail closed", ["daedalus/budget.py"])
    case_b = ("watermark the artifact store", ["daedalus/storage.py"])
    doc = CORPUS["runs/receipt.md"]
    assert ADOPTED_RULE.reasons(
        query=case_a[0], gold=case_a[1], doc_path="runs/receipt.md", doc_text=doc
    )
    assert (
        ADOPTED_RULE.reasons(
            query=case_b[0], gold=case_b[1], doc_path="runs/receipt.md", doc_text=doc
        )
        == ()
    )
