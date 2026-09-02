"""Tests for the prose preservation tripwire.

Every guard here is tested in BOTH directions: the damaging rewrite that must
fire, and the legitimate rewrite that must stay silent. A refusal test with no
control proves nothing -- a checker that flags everything is a checker people
switch off, and a switched-off checker protects nothing.

The ``test_blindspot_*`` cases are deliberate: they assert the checker is
SILENT on damage it structurally cannot see. They exist so the holes are
recorded in the suite instead of discovered later by someone who trusted a
green run. If one of them ever starts failing, that is good news and the
module docstring's BLIND SPOTS section needs updating.
"""

from __future__ import annotations

import pytest

from daedalus.preservation import (
    BLOCKING, DEMOTED, LOST, RECASED, REDUCED, SECTION, STRUCTURE,
    check_preservation, is_prose_path, project,
)
from test_preservation_fixtures import (
    AFTER_LEGIT, AFTER_LIVE, AFTER_REGRESSION, BEFORE,
)


def _arts(result, severity=None, kind=None):
    return {
        f.artefact for f in result.findings
        if (severity is None or f.severity == severity)
        and (kind is None or f.kind == kind)
    }


# ==========================================================================
# 1. The MEASURED regressions -- qwen2.5-coder:7b on docs/LOCAL_MODELS.md
# ==========================================================================


def test_measured_regression_fails_the_gate():
    """The real rewrite must not be accepted."""
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    assert result.ok is False
    assert result.lost, "a deleted cross-reference must produce a LOST finding"


def test_measured_regression_deleted_cross_reference_is_lost():
    """Regression 2: ``Per `docs/IMPROVEMENTS_RESEARCH.md`,`` deleted entirely.

    This is the blocking one: the path appears nowhere else in the document,
    so its disappearance is unambiguous.
    """
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    assert "docs/IMPROVEMENTS_RESEARCH.md" in _arts(result, LOST)
    assert any(f.blocking for f in result.findings)


def test_measured_regression_deleted_endpoint_fact_is_reported():
    """Regression 1: "pointed at an OpenAI-compatible endpoint via three env
    vars" -> "configured via three environment variables".

    Reported as REDUCED, not LOST, and that is the honest verdict: the term
    genuinely survives in the Option B paragraph, so claiming the document no
    longer says the endpoint is OpenAI-compatible would be false. The finding
    still names the exact token and the exact count drop.
    """
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    hit = [f for f in result.findings if f.artefact == "OpenAI-compatible"]
    assert hit, "the deleted technical term must be reported"
    assert hit[0].severity == REDUCED
    assert (hit[0].before, hit[0].after) == (2, 1)


def test_measured_regression_stripped_backticks_are_demoted_not_lost():
    """Regression 3: `` `daedalus` `` -> plain daedalus. The word survives, so
    this is degradation, not deletion -- reported, never blocking."""
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    assert "daedalus" in _arts(result, DEMOTED)
    assert "daedalus" not in _arts(result, LOST)


def test_measured_regression_heading_recase_is_churn_not_loss():
    """Regression 4: "Recommended models" -> "Recommended Models"."""
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    assert "Recommended models (2026)" in _arts(result, RECASED, kind="heading")


def test_measured_regression_reports_every_one_of_the_four():
    """All four MEASURED edits are visible; none is silently swallowed."""
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    got = {(f.kind, f.severity, f.artefact) for f in result.findings}
    assert ("code", LOST, "docs/IMPROVEMENTS_RESEARCH.md") in got
    assert ("term", REDUCED, "OpenAI-compatible") in got
    assert ("code", DEMOTED, "daedalus") in got
    assert ("heading", RECASED, "Recommended models (2026)") in got


# ==========================================================================
# 2. The control -- legitimate rewrites must be SILENT
# ==========================================================================


def test_legitimate_rewrite_is_completely_silent():
    """Rewrapped paragraphs and tightened sentences, every fact kept.

    Zero findings, not merely ok=True. This is the assertion that keeps the
    checker usable.
    """
    result = check_preservation(BEFORE, AFTER_LEGIT)
    assert result.ok is True
    assert result.findings == [], [f.describe() for f in result.findings]


def test_live_model_rewrite_passes_with_style_churn_only():
    """UNEDITED qwen2.5-coder:7b output, captured from the local Ollama lane.

    That run happened to keep every fact while re-casing nearly every heading
    into Title Case. The checker must accept it and report the churn as churn:
    no LOST, no REDUCED, only RECASED.
    """
    result = check_preservation(BEFORE, AFTER_LIVE)
    assert result.ok is True
    assert result.of(LOST) == []
    assert result.of(REDUCED) == []
    assert result.of(RECASED), "the Title Case churn should still be visible"


def test_identity_rewrite_is_silent():
    assert check_preservation(BEFORE, BEFORE).findings == []


def test_pure_rewrapping_is_silent():
    before = (
        "The lane is pointed at an OpenAI-compatible endpoint via\n"
        "three env vars, documented in `docs/LOCAL_MODELS.md`.\n"
    )
    after = (
        "The lane is pointed at an OpenAI-compatible\n"
        "endpoint via three env vars, documented\n"
        "in `docs/LOCAL_MODELS.md`.\n"
    )
    assert check_preservation(before, after).findings == []


def test_prose_table_cell_may_be_reworded():
    """Calibration MEASURED against the live run: an earlier version admitted
    any cell containing "/", so "the coder that reads/writes" -> "The coder for
    reading/writing" fired as LOST. That is a legitimate rewording of prose and
    was a BLOCKING false positive."""
    before = "| env var | used for |\n|---|---|\n| `OLLAMA_MODEL` | the coder that reads/writes |\n"
    after = "| env var | used for |\n|---|---|\n| `OLLAMA_MODEL` | The coder for reading/writing |\n"
    result = check_preservation(before, after)
    assert result.ok is True
    assert result.findings == [], [f.describe() for f in result.findings]


def test_tone_emphasis_may_be_dropped():
    """``**and**`` is emphasis for rhythm, not a fact. Dropping it is fine;
    the fact-marker filter is what keeps this class quiet."""
    before = "A single server serves the coder **and** the embedder.\n"
    after = "A single server serves both the coder and the embedder.\n"
    assert check_preservation(before, after).findings == []


# ==========================================================================
# 3. Per-class block/allow pairs
# ==========================================================================


def test_inline_code_deleted_blocks_but_reworded_prose_does_not():
    before = "Point `OLLAMA_HOST` at the server; see `configs/llama-swap.example.yaml`.\n"
    blocked = check_preservation(before, "Point OLLAMA_HOST at the server.\n")
    assert blocked.ok is False
    assert "configs/llama-swap.example.yaml" in _arts(blocked, LOST)

    allowed = check_preservation(
        before,
        "Aim `OLLAMA_HOST` at your server. A starter config lives at "
        "`configs/llama-swap.example.yaml`.\n",
    )
    assert allowed.ok is True
    assert allowed.of(LOST) == []


def test_fence_line_deleted_blocks_but_reindented_fence_does_not():
    before = "```sh\nollama pull qwen2.5-coder:7b\nollama pull nomic-embed-text\n```\n"
    blocked = check_preservation(before, "```sh\nollama pull qwen2.5-coder:7b\n```\n")
    assert blocked.ok is False
    assert "ollama pull nomic-embed-text" in _arts(blocked, LOST)

    allowed = check_preservation(
        before,
        "```bash\n  ollama pull qwen2.5-coder:7b\n  ollama pull nomic-embed-text\n```\n",
    )
    assert allowed.findings == []


def test_whole_fence_removed_is_reported_as_structure():
    before = "Run it:\n\n```sh\nollama serve\n```\n"
    result = check_preservation(before, "Run it.\n")
    assert result.ok is False
    assert "code fences" in _arts(result, STRUCTURE)


def test_link_target_deleted_blocks_but_relabelled_link_does_not():
    before = "See [the research](docs/IMPROVEMENTS_RESEARCH.md) for detail.\n"
    blocked = check_preservation(before, "See the research for detail.\n")
    assert blocked.ok is False
    assert "docs/IMPROVEMENTS_RESEARCH.md" in _arts(blocked, LOST)

    allowed = check_preservation(
        before, "See [the research notes](docs/IMPROVEMENTS_RESEARCH.md).\n")
    assert allowed.ok is True


def test_bare_path_reference_deleted_blocks():
    before = "The backstop is daedalus/orchestration/verifier.py, which runs the gate.\n"
    blocked = check_preservation(before, "The backstop is the gate.\n")
    assert blocked.ok is False
    assert "daedalus/orchestration/verifier.py" in _arts(blocked, LOST)

    allowed = check_preservation(
        before, "daedalus/orchestration/verifier.py runs the gate and is the backstop.\n")
    assert allowed.findings == []


def test_number_with_unit_deleted_blocks_but_unit_spacing_does_not():
    before = "A modest step up, same Apache-2.0 family, ~12-16 GB VRAM.\n"
    blocked = check_preservation(before, "A modest step up, same Apache-2.0 family.\n")
    assert blocked.ok is False
    assert "16gb" in _arts(blocked, LOST, kind="number")

    # spacing, approx marker and unit casing must NOT be treated as deletions
    allowed = check_preservation(
        before, "A modest step up in the same Apache-2.0 family; needs 12-16GB of VRAM.\n")
    assert allowed.ok is True
    assert allowed.of(LOST) == []


def test_table_row_deleted_blocks_but_recased_header_does_not():
    before = (
        "| env var | default |\n|---|---|\n"
        "| `OLLAMA_HOST` | `http://localhost:11434` |\n"
        "| `OLLAMA_MODEL` | `qwen2.5-coder:7b` |\n"
    )
    blocked = check_preservation(
        before, "| env var | default |\n|---|---|\n| `OLLAMA_HOST` | `http://localhost:11434` |\n")
    assert blocked.ok is False
    assert "OLLAMA_MODEL" in _arts(blocked, LOST)
    assert "table rows" in _arts(blocked, STRUCTURE)

    allowed = check_preservation(
        before,
        "| Env Var | Default |\n|---|---|\n"
        "| `OLLAMA_HOST` | `http://localhost:11434` |\n"
        "| `OLLAMA_MODEL` | `qwen2.5-coder:7b` |\n",
    )
    assert allowed.ok is True
    assert allowed.of(LOST) == []


def test_acronym_deleted_blocks_but_sentence_initial_words_are_ignored():
    before = "`llama-swap` (MIT, single Go binary) needs VRAM.\n"
    blocked = check_preservation(before, "`llama-swap` is a single Go binary that needs VRAM.\n")
    assert blocked.ok is False
    assert "MIT" in _arts(blocked, LOST)

    # "Best"/"Per"/"Re-benchmark" are sentence-initial, not technical terms:
    # rewriting around them must stay silent.
    allowed = check_preservation(
        "Best pick if VRAM allows. Per the notes, re-benchmark first.\n",
        "If VRAM allows this is the pick; the notes say to benchmark again.\n",
    )
    assert allowed.findings == []


def test_removed_heading_is_reported_but_does_not_block():
    before = "# Title\n\n## Running the bench\n\ntext\n"
    result = check_preservation(before, "# Title\n\ntext\n")
    assert result.ok is True, "a renamed/removed section is a human call, not a block"
    assert "Running the bench" in _arts(result, SECTION)


def test_emptied_document_blocks_loudly():
    result = check_preservation(BEFORE, "# Local models for the Ikarus bench\n")
    assert result.ok is False
    assert len(result.lost) > 10


# ==========================================================================
# 4. Policy surface -- what blocks is a decision, not a knob
# ==========================================================================


def test_only_lost_is_blocking():
    assert BLOCKING == frozenset({LOST})
    for severity in (REDUCED, DEMOTED, SECTION, RECASED, STRUCTURE):
        assert severity not in BLOCKING


def test_ok_is_exactly_the_absence_of_lost():
    result = check_preservation(BEFORE, AFTER_REGRESSION)
    assert result.ok == (not result.lost)
    assert result.blocking == result.lost


def test_summary_is_one_line_and_leads_with_the_blocking_finding():
    summary = check_preservation(BEFORE, AFTER_REGRESSION).summary()
    assert "\n" not in summary
    assert "lost=1" in summary
    assert "docs/IMPROVEMENTS_RESEARCH.md" in summary


def test_clean_summary_says_so():
    assert check_preservation(BEFORE, AFTER_LEGIT).summary() == (
        "all fact-bearing artefacts preserved")


def test_as_dict_is_json_safe():
    import json
    payload = check_preservation(BEFORE, AFTER_REGRESSION).as_dict()
    assert json.loads(json.dumps(payload))["ok"] is False


@pytest.mark.parametrize("rel,expected", [
    ("docs/LOCAL_MODELS.md", True),
    ("README.md", True),
    ("docs/notes.MD", True),
    ("docs/guide.rst", True),
    ("daedalus/orchestration/verifier.py", False),
    ("package.json", False),
])
def test_is_prose_path(rel, expected):
    assert is_prose_path(rel) is expected


def test_projection_erases_markup_and_wrapping_only():
    assert project("a **b** `c`\n  d") == "a b c d"
    assert project("[label](docs/X.md)") == "label docs/X.md"


def test_checker_is_pure_and_does_no_io(monkeypatch):
    """It must be safe to call inside a gate: no file reads, no subprocesses."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned a process"))
    monkeypatch.setattr("builtins.open", lambda *a, **k: pytest.fail("touched the filesystem"))
    assert check_preservation(BEFORE, AFTER_LEGIT).ok is True


# ==========================================================================
# 5. BLIND SPOTS -- damage this structurally CANNOT see.
#    These assert SILENCE on purpose. They are the honest part of the file.
# ==========================================================================


def test_blindspot_negation_flip_is_invisible():
    """"only if you are *not* on Ollama" -> "if you are on Ollama" reverses the
    instruction and deletes no protected token."""
    before = "Use it only if you are *not* on Ollama.\n"
    after = "Use it if you are on Ollama.\n"
    assert check_preservation(before, after).findings == []


def test_blindspot_spelled_out_number_is_invisible():
    """"three env vars" -> "env vars" loses a count and leaves no digit."""
    before = "The lane is configured by three env vars.\n"
    after = "The lane is configured by env vars.\n"
    assert check_preservation(before, after).findings == []


def test_blindspot_invented_facts_pass_clean():
    """One-directional by construction: it never asks what APPEARED."""
    before = "Set `OLLAMA_HOST` to point at the server.\n"
    after = "Set `OLLAMA_HOST` and `OLLAMA_TIMEOUT` to point at the server.\n"
    assert check_preservation(before, after).findings == []


def test_blindspot_false_prose_around_intact_artefacts_passes_clean():
    """The actual bound: replace every true sentence with a false one while
    keeping the code spans, and the checker reports nothing. ``ok is True``
    means "no fact-bearing token vanished", never "the rewrite is good"."""
    before = "`OLLAMA_HOST` must point at a running server or the lane fails.\n"
    after = "`OLLAMA_HOST` is optional and the lane works fine without a server.\n"
    result = check_preservation(before, after)
    assert result.ok is True
    assert result.findings == []


def test_blindspot_reordering_under_the_wrong_heading_is_invisible():
    before = "## Option A\n\nUse `ollama serve`.\n\n## Option B\n\nUse `llama-swap`.\n"
    after = "## Option A\n\nUse `llama-swap`.\n\n## Option B\n\nUse `ollama serve`.\n"
    assert check_preservation(before, after).findings == []
