# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tests for the council's GitHub-PR bridge.

NO NETWORK, NO gh. Every test injects a fake runner and asserts on exactly what
that runner received -- which is the only way to prove the egress gate ran BEFORE
the call rather than after it.
"""
from __future__ import annotations

import json

import pytest

from daedalus.council.publish import (
    DEGRADED_QUORUM_MARKER,
    PUBLISH_STATUSES,
    READ_STATUSES,
    STATUS_BAD_PAYLOAD,
    STATUS_DRY_RUN,
    STATUS_GH_ERROR,
    STATUS_GH_MISSING,
    STATUS_GH_UNAUTHENTICATED,
    STATUS_PR_NOT_FOUND,
    STATUS_PUBLISHED,
    STATUS_RATE_LIMITED,
    STATUS_READ_OK,
    STATUS_REFUSED_SECRET,
    PublishResult,
    RunResult,
    ThreadResult,
    publish_to_pr,
    read_pr_thread,
    render_markdown,
)


# --------------------------------------------------------------------------- #
# fakes                                                                        #
# --------------------------------------------------------------------------- #
class FakeRunner:
    """Records every (argv, stdin_text) it was handed and replays a canned
    RunResult. The recording IS the assertion surface for the egress gate."""

    def __init__(self, result: RunResult | None = None):
        self.result = result or RunResult(0, "https://github.com/o/r/pull/7#issuecomment-1\n")
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, argv, stdin_text=None):
        self.calls.append((list(argv), stdin_text))
        return self.result

    def seen_text(self) -> str:
        """Everything that would have crossed the process boundary: argv AND
        stdin, for every call. A secret hiding in either is a leak."""
        chunks = []
        for argv, stdin_text in self.calls:
            chunks.extend(argv)
            if stdin_text:
                chunks.append(stdin_text)
        return "\n".join(chunks)


def _verdict(**over):
    v = {
        "council_id": "c-0001",
        "question": "Does this patch break the offload slice contract?",
        "outcome": "no-blocking-objection",
        "advisory": True,
        "convergence": "The patch preserves the slice contract; the added guard "
                       "is redundant but harmless.",
        "vendors_requested": ["claude", "codex", "agy", "ollama"],
        "vendors_answered": ["claude", "codex", "agy", "ollama"],
        "dissents": [
            {"author": "codex", "model": "gpt-5",
             "text": "DISSENT: the guard is not redundant. Line 88 can be reached "
                     "with paths=[] and the guard is the only thing stopping a "
                     "None deref."},
            {"author": "ollama", "model": "qwen2.5-coder:7b",
             "text": "DISSENT: no test covers the empty-paths branch at all."},
        ],
        "evidence": [
            {"label": "patch.diff", "sha256": "a" * 64},
            {"label": "daedalus/offload.py", "sha256": "b" * 64},
        ],
        "vendor_stats": [
            {"vendor": "claude", "model": "opus", "cost_usd": 0.41, "latency_s": 12.2},
            {"vendor": "codex", "model": "gpt-5", "cost_usd": 0.18, "latency_s": 30.9},
            {"vendor": "agy", "model": "gemini", "cost_usd": 0.0, "latency_s": 44.1},
            {"vendor": "ollama", "model": "qwen2.5-coder:7b", "cost_usd": 0.0,
             "latency_s": 61.7},
        ],
    }
    v.update(over)
    return v


def _transcript(**over):
    t = {
        "bus_path": "runs/council/c-0001.jsonl",
        "chain_head": "f" * 64,
        "turns": [
            {"author": "claude", "ts": "2026-07-28T10:00:00+00:00",
             "entry_sha": "1" * 64, "text": "Opening read of the patch."},
            {"author": "codex", "ts": "2026-07-28T10:01:00+00:00",
             "entry_sha": "2" * 64, "text": "I object; see line 88."},
        ],
    }
    t.update(over)
    return t


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #
def test_rendering_carries_verdict_every_dissent_with_author_and_chain_head():
    md = render_markdown(_verdict(), _transcript())

    # the verdict itself
    assert "no-blocking-objection" in md
    assert "The patch preserves the slice contract" in md

    # EVERY dissent, verbatim, with its author
    assert "codex" in md
    assert "Line 88 can be reached" in md
    assert "ollama" in md
    assert "no test covers the empty-paths branch at all" in md
    assert md.count("### Dissent -- ") == 2

    # the chain head + bus path, so a reader can verify offline
    assert "f" * 64 in md
    assert "runs/council/c-0001.jsonl" in md

    # advisory doctrine, stated not implied
    assert "ADVISORY ONLY" in md
    assert "THE GATE DECIDES, NOT A MODEL" in md


def test_degraded_quorum_is_prominent_not_buried():
    md = render_markdown(
        _verdict(vendors_answered=["claude", "ollama"],
                 dissents=[{"author": "ollama", "text": "DISSENT: unclear."}]),
        _transcript())
    lines = md.splitlines()
    idx = next(i for i, ln in enumerate(lines) if DEGRADED_QUORUM_MARKER in ln)

    # near the TOP: inside the first dozen lines, and ahead of everything
    # substantive -- majority, dissents, evidence, and the footer.
    assert idx < 12, f"degraded-quorum banner buried at line {idx}"
    assert idx < lines.index("## Where the vendors converged")
    assert idx < next(i for i, ln in enumerate(lines) if ln.startswith("## Dissents"))

    # and it says what was actually missing, by name
    assert "2 of 4" in md
    assert "codex" in md and "agy" in md


def test_dissent_is_not_subordinate_to_convergence():
    # The dissent is the only content that could not have come from asking one
    # model twice. If it renders BELOW the agreement it reads as a footnote to
    # the least informative half of the document.
    lines = render_markdown(_verdict(), _transcript()).splitlines()
    dissents_at = next(i for i, ln in enumerate(lines) if ln.startswith("## Dissents"))
    converged_at = lines.index("## Where the vendors converged")
    assert dissents_at < converged_at


def test_rendering_never_reintroduces_a_majority_field():
    # The council package carries no approve/reject/score/majority/consensus
    # field: ABSENCE of the field is the control. A rendering that says
    # "majority" structurally reintroduces the thing that gets read as a verdict.
    md = render_markdown(_verdict(), _transcript())
    lowered = md.lower()
    for banned in ("majority", "consensus", "approved", "rejected"):
        assert banned not in lowered, f"rendering reintroduced {banned!r}"


def test_legacy_majority_payload_still_renders_under_the_new_heading():
    v = _verdict()
    del v["convergence"]
    v["majority"] = "older shape, still has to render"
    md = render_markdown(v, _transcript())
    assert "older shape, still has to render" in md
    assert "## Where the vendors converged" in md


def test_full_quorum_renders_no_degraded_banner():
    md = render_markdown(_verdict(), _transcript())
    assert DEGRADED_QUORUM_MARKER not in md
    assert "4 of 4" in md


def test_dissent_containing_a_code_fence_is_not_truncated():
    md = render_markdown(
        _verdict(dissents=[{"author": "agy",
                            "text": "DISSENT:\n```python\nx = 1\n```\nthat is wrong"}]),
        _transcript())
    assert "x = 1" in md
    assert "that is wrong" in md


def test_real_bus_turn_shape_renders_author_and_content():
    # The field names bus.py actually writes (actor/vendor/content/status),
    # not the aliases the renderer also tolerates.
    md = render_markdown(_verdict(), {
        "bus_path": "runs/council/c-0001.jsonl",
        "chain_head": "f" * 64,
        "turns": [{
            "record": "turn", "council_id": "c-0001", "round": 1,
            "actor": "council.openai.gpt-5", "vendor": "openai", "model": "gpt-5",
            "role": "participant", "status": "spoke",
            "content": "The empty-paths branch is unreachable.",
            "ts": "2026-07-28T10:00:00+00:00", "entry_sha": "3" * 64,
        }],
    })
    assert "openai" in md
    assert "The empty-paths branch is unreachable." in md


def test_a_turn_that_did_not_speak_is_shown_not_dropped():
    md = render_markdown(_verdict(), {
        "turns": [
            {"vendor": "agy", "status": "unavailable",
             "reason": "agy has never been signed in on the bench", "content": ""},
            {"vendor": "claude", "status": "spoke", "content": "looks fine"},
        ],
    })
    assert "unavailable" in md
    assert "never been signed in on the bench" in md


def test_withheld_evidence_is_named_on_the_turn_that_lost_it():
    md = render_markdown(_verdict(), {
        "turns": [{"vendor": "codex", "status": "spoke", "content": "no objection",
                   "withheld": ["deploy/secrets.env"]}],
    })
    assert "deploy/secrets.env" in md
    assert "less evidence than the others" in md


def test_missing_advisory_marker_is_rendered_loudly_not_honoured():
    md = render_markdown(_verdict(advisory=False), _transcript())
    assert "ADVISORY ONLY" in md
    assert "advisory=False" in md


# --------------------------------------------------------------------------- #
# egress gate                                                                  #
# --------------------------------------------------------------------------- #
def test_planted_secret_in_transcript_is_refused_and_never_reaches_the_runner():
    secret = "AKIAIOSFODNN7EXAMPLE"
    runner = FakeRunner()
    res = publish_to_pr(
        _verdict(),
        _transcript(turns=[{"author": "codex", "ts": "2026-07-28T10:01:00+00:00",
                            "entry_sha": "2" * 64,
                            "text": f"the failing config had {secret} in it"}]),
        pr="7", repo="KTY137/daedalus", runner=runner)

    assert res.status == STATUS_REFUSED_SECRET
    assert runner.calls == [], "gh was invoked despite a secret-floor refusal"
    assert secret not in runner.seen_text()
    # the refusal names the rule, never the matched text
    assert "AWS access key id" in res.detail
    assert secret not in res.detail
    # and the refused body is withheld, so a caller cannot log it back out
    assert res.markdown == ""


def test_planted_secret_in_a_dissent_is_refused():
    secret = 'password = "hunter2-not-a-real-one"'
    runner = FakeRunner()
    res = publish_to_pr(
        _verdict(dissents=[{"author": "ollama", "text": f"DISSENT: {secret}"}]),
        _transcript(), pr="7", runner=runner)
    assert res.status == STATUS_REFUSED_SECRET
    assert runner.calls == []
    assert "hunter2" not in runner.seen_text()


def test_secret_bearing_evidence_path_is_refused_by_the_path_floor():
    runner = FakeRunner()
    res = publish_to_pr(
        _verdict(evidence=[{"label": "deploy/id_rsa", "sha256": "c" * 64}]),
        _transcript(), pr="7", runner=runner)
    assert res.status == STATUS_REFUSED_SECRET
    assert "id_rsa" in res.detail
    assert runner.calls == []


def test_clean_transcript_is_published_and_the_body_travels_on_stdin():
    runner = FakeRunner()
    res = publish_to_pr(_verdict(), _transcript(), pr="7",
                        repo="KTY137/daedalus", runner=runner)
    assert res.status == STATUS_PUBLISHED
    assert len(runner.calls) == 1
    argv, stdin_text = runner.calls[0]
    assert argv[:4] == ["gh", "pr", "comment", "7"]
    assert "--body-file" in argv and "-" in argv
    assert argv[-2:] == ["--repo", "KTY137/daedalus"]
    assert stdin_text is not None and "ADVISORY ONLY" in stdin_text
    assert res.comment_url.startswith("https://github.com/")


# --------------------------------------------------------------------------- #
# dry run                                                                      #
# --------------------------------------------------------------------------- #
def test_dry_run_calls_the_runner_zero_times_and_returns_the_markdown():
    runner = FakeRunner()
    res = publish_to_pr(_verdict(), _transcript(), pr="7", repo="KTY137/daedalus",
                        runner=runner, dry_run=True)
    assert res.status == STATUS_DRY_RUN
    assert runner.calls == []
    assert "# Council verdict" in res.markdown
    assert "THE GATE DECIDES, NOT A MODEL" in res.markdown


def test_dry_run_still_runs_the_gate_so_a_preview_cannot_bypass_it():
    runner = FakeRunner()
    res = publish_to_pr(
        _verdict(),
        _transcript(turns=[{"author": "codex", "text": "key AKIAIOSFODNN7EXAMPLE"}]),
        pr="7", runner=runner, dry_run=True)
    assert res.status == STATUS_REFUSED_SECRET
    assert runner.calls == []


# --------------------------------------------------------------------------- #
# gh failure modes -> explicit statuses, never exceptions                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("result,expected", [
    (RunResult(127, "", "gh: command not found"), STATUS_GH_MISSING),
    (RunResult(127, "", "gh could not be launched: [WinError 2] The system cannot "
                        "find the file specified"), STATUS_GH_MISSING),
    (RunResult(4, "", "gh: To get started with GitHub CLI, please run: gh auth login"),
     STATUS_GH_UNAUTHENTICATED),
    (RunResult(1, "", "HTTP 401: Bad credentials"), STATUS_GH_UNAUTHENTICATED),
    (RunResult(1, "", "GraphQL: Could not resolve to a PullRequest with the number "
                      "of 99999."), STATUS_PR_NOT_FOUND),
    (RunResult(1, "", "no pull requests found for branch"), STATUS_PR_NOT_FOUND),
    (RunResult(1, "", "HTTP 403: API rate limit exceeded for user ID 1."),
     STATUS_RATE_LIMITED),
    (RunResult(1, "", "You have exceeded a secondary rate limit"), STATUS_RATE_LIMITED),
    (RunResult(1, "", "unexpected end of JSON input"), STATUS_GH_ERROR),
])
def test_gh_failures_map_to_explicit_statuses_without_raising(result, expected):
    runner = FakeRunner(result)
    res = publish_to_pr(_verdict(), _transcript(), pr="7", runner=runner)
    assert isinstance(res, PublishResult)
    assert res.status == expected
    assert res.status in PUBLISH_STATUSES
    assert res.detail, "a failure status must carry an operator-readable detail"


def test_auth_failure_wins_over_not_found_for_a_private_repo():
    # GitHub answers 404 -- not 403 -- for a private repo an unauthenticated CLI
    # cannot see. Reporting that as pr_not_found sends the operator hunting for a
    # PR that exists.
    runner = FakeRunner(RunResult(1, "", "HTTP 404: Not Found. Try: gh auth login"))
    res = publish_to_pr(_verdict(), _transcript(), pr="7", runner=runner)
    assert res.status == STATUS_GH_UNAUTHENTICATED


def test_missing_pr_reference_is_a_status_not_a_call():
    runner = FakeRunner()
    res = publish_to_pr(_verdict(), _transcript(), pr="", runner=runner)
    assert res.status == STATUS_PR_NOT_FOUND
    assert runner.calls == []


def test_status_vocabulary_is_closed():
    assert PUBLISH_STATUSES == {
        STATUS_PUBLISHED, STATUS_DRY_RUN, STATUS_REFUSED_SECRET,
        STATUS_GH_MISSING, STATUS_GH_UNAUTHENTICATED, STATUS_PR_NOT_FOUND,
        STATUS_RATE_LIMITED, STATUS_GH_ERROR,
    }
    assert READ_STATUSES == {
        STATUS_READ_OK, STATUS_REFUSED_SECRET, STATUS_GH_MISSING,
        STATUS_GH_UNAUTHENTICATED, STATUS_PR_NOT_FOUND, STATUS_RATE_LIMITED,
        STATUS_BAD_PAYLOAD, STATUS_GH_ERROR,
    }


# --------------------------------------------------------------------------- #
# read_pr_thread -- the async channel                                          #
# --------------------------------------------------------------------------- #
_GH_PAYLOAD = json.dumps({
    "comments": [
        {"author": {"login": "kty137"}, "createdAt": "2026-07-28T11:00:00Z",
         "body": "The council missed that offload.py already guards this.",
         "url": "https://github.com/o/r/pull/7#issuecomment-1"},
        {"author": {"login": "some-agent[bot]"}, "createdAt": "2026-07-28T11:05:00Z",
         "body": "Re-running with the guard in evidence.",
         "url": "https://github.com/o/r/pull/7#issuecomment-2"},
    ]
})


def test_read_pr_thread_parses_gh_json_into_structured_turns():
    runner = FakeRunner(RunResult(0, _GH_PAYLOAD))
    res = read_pr_thread(pr="7", repo="KTY137/daedalus", runner=runner)

    assert isinstance(res, ThreadResult)
    assert res.status == STATUS_READ_OK
    assert len(res.turns) == 2

    first, second = res.turns
    assert first.author == "kty137"
    assert first.created_at == "2026-07-28T11:00:00Z"
    assert "offload.py already guards this" in first.body
    assert first.url.endswith("issuecomment-1")
    assert second.author == "some-agent[bot]"

    argv, stdin_text = runner.calls[0]
    assert argv[:4] == ["gh", "pr", "view", "7"]
    assert "--json" in argv and "comments" in argv
    assert stdin_text is None


def test_read_pr_thread_tolerates_the_rest_author_shape():
    payload = json.dumps({"comments": [
        {"user": {"login": "octocat"}, "created_at": "2026-07-28T12:00:00Z",
         "body": "ack"}]})
    res = read_pr_thread(pr="7", runner=FakeRunner(RunResult(0, payload)))
    assert res.status == STATUS_READ_OK
    assert res.turns[0].author == "octocat"
    assert res.turns[0].created_at == "2026-07-28T12:00:00Z"


def test_read_pr_thread_maps_gh_failures_to_statuses():
    for result, expected in (
        (RunResult(127, "", "gh: command not found"), STATUS_GH_MISSING),
        (RunResult(4, "", "please run: gh auth login"), STATUS_GH_UNAUTHENTICATED),
        (RunResult(1, "", "Could not resolve to a PullRequest"), STATUS_PR_NOT_FOUND),
        (RunResult(1, "", "API rate limit exceeded"), STATUS_RATE_LIMITED),
    ):
        res = read_pr_thread(pr="7", runner=FakeRunner(result))
        assert res.status == expected
        assert res.turns == ()


def test_read_pr_thread_flags_unparseable_json_instead_of_raising():
    res = read_pr_thread(pr="7", runner=FakeRunner(RunResult(0, "not json at all")))
    assert res.status == STATUS_BAD_PAYLOAD
    assert res.turns == ()


def test_read_pr_thread_gates_its_own_arguments():
    runner = FakeRunner(RunResult(0, _GH_PAYLOAD))
    res = read_pr_thread(pr="ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                         runner=runner)
    assert res.status == STATUS_REFUSED_SECRET
    assert runner.calls == []
    assert "ghp_" not in runner.seen_text()
