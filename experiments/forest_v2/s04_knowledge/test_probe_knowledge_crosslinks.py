"""Tests for the s04 knowledge-crosslink probe.

Every case builds a synthetic corpus in a tmp dir, so the resolution rules are
pinned independently of whatever the real repository currently contains.
Run directly: ``python -m pytest experiments/forest_v2/s04_knowledge -q``
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_knowledge_crosslinks import (  # noqa: E402
    mask_inline_code,
    probe,
    slugify,
    strip_fences,
)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- unit rules ---------------------------------------------------------


def test_slugify_matches_github_style_anchor():
    assert slugify("## 5. Wall-clock measurements") == "5-wall-clock-measurements"
    assert slugify("§5 Budgets & Limits") == "5-budgets--limits"
    assert slugify("`code` in a heading") == "code-in-a-heading"


def test_strip_fences_preserves_line_numbers_and_counts_removal():
    text = "a\n```\nsecret-looking noise\n```\nb"
    masked, removed = strip_fences(text)
    assert masked.splitlines() == ["a", "", "", "", "b"]
    assert removed == 3


def test_strip_fences_handles_tilde_and_unclosed_fence():
    masked, removed = strip_fences("a\n~~~\nx\n~~~\nb")
    assert masked.splitlines() == ["a", "", "", "", "b"]
    assert removed == 3
    # Unclosed fence: everything after it stays masked to end of file.  The
    # join/splitlines round-trip drops the trailing empty line, so assert the
    # property that matters (content masked, count correct), not the artifact.
    masked_open, removed_open = strip_fences("a\n```\nx\ny")
    assert masked_open.splitlines()[:2] == ["a", ""]
    assert "x" not in masked_open and "y" not in masked_open
    assert removed_open == 3


def test_mask_inline_code_preserves_length():
    text = "see `picker.py:12` here"
    assert len(mask_inline_code(text)) == len(text)
    assert "picker.py" not in mask_inline_code(text)


# --- link resolution ----------------------------------------------------


def test_link_path_resolved_and_dead_are_separated(tmp_path):
    write(tmp_path, "docs/a.md", "[live](b.md) and [gone](missing.md)\n")
    write(tmp_path, "docs/b.md", "# B\n")
    totals = probe(tmp_path)["totals"]
    assert totals["link_path_resolved"] == 1
    assert totals["link_path_dead"] == 1


def test_external_links_are_excluded_not_counted_resolved(tmp_path):
    write(tmp_path, "a.md", "[x](https://example.invalid/page) [y](mailto:a@b.c)\n")
    result = probe(tmp_path)
    assert result["totals"]["link_external"] == 2
    # external links must not inflate the resolved ratio
    assert result["rates"]["link_checkable"] == 0


def test_same_file_anchor_resolution(tmp_path):
    write(tmp_path, "a.md", "## 5. Wall-clock measurements\n\n[go](#5-wall-clock-measurements) [bad](#nope)\n")
    totals = probe(tmp_path)["totals"]
    assert totals["link_anchor_resolved"] == 1
    assert totals["link_anchor_dead"] == 1


def test_cross_file_anchor_is_checked_against_target_headings(tmp_path):
    write(tmp_path, "a.md", "[ok](b.md#topic) [bad](b.md#ghost)\n")
    write(tmp_path, "b.md", "# Topic\n")
    totals = probe(tmp_path)["totals"]
    assert totals["link_anchor_resolved"] == 1
    assert totals["link_anchor_dead"] == 1


def test_reference_style_definitions_are_extracted(tmp_path):
    write(tmp_path, "a.md", "text [label]\n\n[label]: b.md\n")
    write(tmp_path, "b.md", "# B\n")
    assert probe(tmp_path)["totals"]["link_path_resolved"] == 1


# --- code refs ----------------------------------------------------------


def test_code_ref_line_out_of_range_is_dead_not_resolved(tmp_path):
    write(tmp_path, "mod.py", "one\ntwo\nthree\n")
    write(tmp_path, "a.md", "see `mod.py:2` and `mod.py:900`\n")
    totals = probe(tmp_path)["totals"]
    assert totals["code_ref_total"] == 2
    assert totals["code_ref_resolved"] == 1
    assert totals["code_ref_line_out_of_range"] == 1


def test_code_ref_missing_file_is_dead_path(tmp_path):
    write(tmp_path, "a.md", "see `nowhere.py:3`\n")
    totals = probe(tmp_path)["totals"]
    assert totals["code_ref_dead_path"] == 1
    assert totals["code_ref_resolved"] == 0


def test_bare_basename_resolves_only_when_unique(tmp_path):
    write(tmp_path, "pkg/one/report.py", "x\n" * 50)
    write(tmp_path, "pkg/two/report.py", "x\n" * 50)
    write(tmp_path, "pkg/solo.py", "x\n" * 50)
    write(tmp_path, "a.md", "`report.py:10` and `solo.py:10`\n")
    totals = probe(tmp_path)["totals"]
    assert totals["code_ref_ambiguous"] == 1
    assert totals["code_ref_resolved"] == 1


def test_repo_relative_code_ref_resolves(tmp_path):
    write(tmp_path, "pkg/spine/picker.py", "x\n" * 900)
    write(tmp_path, "a.md", "`pkg/spine/picker.py:827`\n")
    assert probe(tmp_path)["totals"]["code_ref_resolved"] == 1


def test_package_relative_ref_resolves_by_suffix_into_its_own_bucket(tmp_path):
    """"spine/attempt.py:5" means "pkg/spine/attempt.py" — a real edge, but a
    weaker claim than an exact path, so it must not inflate the strict rate."""
    write(tmp_path, "pkg/spine/attempt.py", "x\n" * 40)
    write(tmp_path, "a.md", "`spine/attempt.py:5`\n")
    result = probe(tmp_path)
    assert result["totals"]["code_ref_suffix_resolved"] == 1
    assert result["totals"]["code_ref_resolved"] == 0
    assert result["totals"]["code_ref_dead_path"] == 0
    assert result["rates"]["code_ref_resolved_strict_pct"] == 0.0
    assert result["rates"]["code_ref_incl_inferred_pct"] == 100.0
    # and in the waterfall it is a proposal, never a verification
    assert result["waterfall"]["strictly_verified"] == 0
    assert result["waterfall"]["inferred_proposal"] == 1


def test_suffix_match_still_obeys_the_line_range_check(tmp_path):
    write(tmp_path, "pkg/spine/attempt.py", "x\n" * 10)
    write(tmp_path, "a.md", "`spine/attempt.py:999`\n")
    totals = probe(tmp_path)["totals"]
    assert totals["code_ref_line_out_of_range"] == 1
    assert totals["code_ref_suffix_resolved"] == 0


def test_ambiguous_suffix_is_not_resolved(tmp_path):
    write(tmp_path, "one/spine/attempt.py", "x\n" * 40)
    write(tmp_path, "two/spine/attempt.py", "x\n" * 40)
    write(tmp_path, "a.md", "`spine/attempt.py:5`\n")
    totals = probe(tmp_path)["totals"]
    assert totals["code_ref_ambiguous"] == 1
    assert totals["code_ref_suffix_resolved"] == 0


def test_typed_code_wikilink_resolves_against_files_not_note_stems(tmp_path):
    write(tmp_path, "pkg/vault.py", "x\n")
    write(tmp_path, "a.md", "[[code:pkg/vault.py]] and [[code:pkg/ghost.py]]\n")
    totals = probe(tmp_path)["totals"]
    assert totals["wiki_code_target_total"] == 2
    assert totals["wiki_code_target_resolved"] == 1
    assert totals["wiki_code_target_dead"] == 1
    # must not be judged as a prose note link
    assert totals["wiki_total"] == 0


def test_ambiguous_refs_leave_the_checkable_denominator(tmp_path):
    write(tmp_path, "one/dup.py", "x\n" * 20)
    write(tmp_path, "two/dup.py", "x\n" * 20)
    write(tmp_path, "a.md", "`dup.py:5`\n")
    rates = probe(tmp_path)["rates"]
    assert rates["code_ref_checkable"] == 0


# --- precision filter ---------------------------------------------------


def test_fenced_examples_do_not_become_edges(tmp_path):
    write(
        tmp_path,
        "a.md",
        "real [x](b.md)\n\n```\n[[Note]] and [fake](totally-missing.md)\n```\n",
    )
    write(tmp_path, "b.md", "# B\n")
    result = probe(tmp_path)
    assert result["totals"]["link_path_dead"] == 0
    assert result["totals"]["wiki_total"] == 0
    assert result["totals"]["refs_dropped_by_fence_filter"] == 2


def test_inline_code_link_is_not_counted_as_edge(tmp_path):
    write(tmp_path, "a.md", "the syntax `[x](y.md)` is documented\n")
    assert probe(tmp_path)["totals"]["link_total"] == 0


def test_wiki_link_resolution_against_stems(tmp_path):
    write(tmp_path, "notes/Alpha.md", "# Alpha\n")
    write(tmp_path, "a.md", "[[Alpha]] and [[Ghost]]\n")
    totals = probe(tmp_path)["totals"]
    assert totals["wiki_resolved"] == 1
    assert totals["wiki_dead"] == 1


# --- contract / hygiene -------------------------------------------------


def test_probe_is_read_only_on_the_corpus(tmp_path):
    write(tmp_path, "a.md", "[x](b.md) `b.md:1`\n")
    write(tmp_path, "b.md", "# B\n")
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    probe(tmp_path)
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after, "probe must not write to the corpus"


def test_output_is_json_serialisable_with_declared_schema(tmp_path):
    write(tmp_path, "a.md", "# H\n")
    result = probe(tmp_path)
    assert result["schema"] == "forest-v2-knowledge-crosslink-probe/2"
    assert result["read_only"] is True
    json.dumps(result)  # must not raise


def test_skipped_dirs_are_not_walked(tmp_path):
    write(tmp_path, "keep.md", "# K\n")
    write(tmp_path, "node_modules/pkg/readme.md", "[x](nope.md)\n")
    assert probe(tmp_path)["totals"]["markdown_files"] == 1


def test_cli_emits_one_json_object(tmp_path):
    write(tmp_path, "a.md", "[x](b.md)\n")
    write(tmp_path, "b.md", "# B\n")
    script = Path(__file__).resolve().parent / "probe_knowledge_crosslinks.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["totals"]["link_path_resolved"] == 1
