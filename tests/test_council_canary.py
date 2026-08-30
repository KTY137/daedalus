# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the vendor canary.

NO network, NO Ollama, NO vendor CLI, NO CLI entry point: every lane is a fake
callable that returns a ``VendorReply``. The properties under test are the ones
the two real incidents (a truncated codex prompt, an anchoring Ollama reply)
would have needed:

  * a truncated reply is ``wrong_answer``, never ``ok``;
  * an anchoring copy is DETECTED and reported as a QUALITY signal, not as a
    liveness failure;
  * ``unavailable`` and ``wrong_answer` are distinct and the summary never
    merges them;
  * a hung lane hits the cap and the other lanes still complete;
  * history append/compare survives the first-ever run and a corrupt line;
  * ``--dry-run`` calls nothing.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from daedalus.council import canary as C
from daedalus.council.vendors import VendorReply


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


def _reply(content: str = "", *, status: str = "ok", model: str = "fake-1",
           reason: str = "", stderr: str = "") -> VendorReply:
    return VendorReply(vendor="fake", actor="canary.fake.fake-1", model=model,
                       status=status, content=content, reason=reason,
                       stderr=stderr)


def _lane(vendor: str, ask, *, model: str = "fake-1", local: bool = False) -> C.Lane:
    return C.Lane(vendor=vendor, model=model, endpoint=f"fake:{vendor}",
                  ask=ask, local=local)


class PerfectLane:
    """Answers every probe correctly, by reading the nonce back out of the prompt."""

    def __init__(self, *, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls = 0

    def __call__(self, prompt: str, timeout_s: float) -> VendorReply:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return _reply(_correct_answer(prompt))


def _nonce_of(prompt: str) -> str:
    """Recover the nonce a probe body was built with (test-only convenience)."""
    for pat in (r"NONCE-([A-Z0-9]{8})", r"OK-([A-Z0-9]{8})"):
        import re
        m = re.search(pat, prompt)
        if m:
            return m.group(1)
    return ""


def _correct_answer(prompt: str) -> str:
    """A deterministic 'good model': works out the right answer from the body."""
    import re
    nonce = _nonce_of(prompt)
    if prompt.startswith("NONCE-"):
        tail = prompt.rsplit("TAILWORD: ", 1)[-1].strip()
        return f"NONCE-{nonce} {tail}"
    if prompt.startswith("Reply with exactly OK-"):
        return f"OK-{nonce}"
    if "NEW QUESTION" in prompt:
        block = prompt.split("NEW QUESTION")[1]
        items = re.search(r"Of \[([^\]]+)\], which is the (\w+)\?", block)
        words = [w.strip() for w in items.group(1).split(",")]
        return words[C._ORDINALS.index(items.group(2))]
    if "one-line file summaries" in prompt:
        for line in prompt.splitlines():
            if "roll" in line.lower() and line[:1].isdigit():
                return line[0]
    return "?"


# --------------------------------------------------------------------------
# probe checkers: accept the right answer, reject the wrong one
# --------------------------------------------------------------------------

NONCE = "KDEADBEE"


@pytest.mark.parametrize("probe", C.PROBES, ids=[p.name for p in C.PROBES])
def test_checker_accepts_the_correct_answer(probe):
    body = probe.build(NONCE)
    passed, failed = probe.check(_correct_answer(body), NONCE)
    assert passed, f"{probe.name} rejected its own correct answer ({failed})"
    assert failed == ""


@pytest.mark.parametrize("probe", C.PROBES, ids=[p.name for p in C.PROBES])
def test_checker_rejects_a_wrong_answer(probe):
    passed, failed = probe.check("banana split, obviously", NONCE)
    assert not passed
    assert failed, "a rejection must name WHICH check failed"


@pytest.mark.parametrize("probe", C.PROBES, ids=[p.name for p in C.PROBES])
def test_checker_rejects_an_empty_reply(probe):
    passed, failed = probe.check("", NONCE)
    assert not passed and failed


def test_expected_matches_the_checkers_notion_of_correct():
    for probe in C.PROBES:
        assert probe.check(probe.expect(NONCE), NONCE)[0], probe.name


def test_probe_bodies_are_synthetic_and_carry_no_repo_source():
    """A canary is not a place to ship repo source off the machine."""
    for probe in C.PROBES:
        body = probe.build(NONCE)
        for marker in ("daedalus", "import ", "def ", "c:\\", "/home/", "diff --git"):
            assert marker not in body.lower(), (probe.name, marker)


# --------------------------------------------------------------------------
# THE TRUNCATION CLASS -- the codex .cmd bug and the Ollama head-truncation
# --------------------------------------------------------------------------


def test_head_truncated_reply_is_wrong_answer_not_ok():
    """Ollama eats the HEAD of an over-budget prompt: the nonce is gone."""
    body = C.build_arrival(NONCE)
    tail = body.rsplit("TAILWORD: ", 1)[-1].strip()
    # The model saw the tail (so it knows the word) but never saw the nonce.
    passed, failed = C.check_arrival(f"I only received part of it, but: {tail}", NONCE)
    assert not passed
    assert failed == "nonce_absent"


def test_tail_truncated_reply_is_wrong_answer_not_ok():
    """The .cmd shim cut the argv at the first newline: the instruction is gone.

    The model echoes the one line it got -- the nonce -- and complains. That
    reply contains the nonce, so a naive contains-the-nonce check would call it
    healthy. Requiring the tail word too is what rejects it.
    """
    passed, failed = C.check_arrival(
        f"NONCE-{NONCE}\n\nIt looks like your message was cut off. "
        "Could you resend it?", NONCE)
    assert not passed
    assert failed == "tailword_absent"


def test_arrival_truncation_grades_as_wrong_answer_through_the_runner():
    def truncated(prompt: str, timeout_s: float) -> VendorReply:
        return _reply("your message was cut off")

    run = C.run_canary([_lane("openai", truncated)],
                       C.probes_for(quick=True), wall_clock_s=5.0)
    (result,) = run.results
    assert result.status == "wrong_answer"
    assert result.status != "ok"
    assert result.failed_check == "both_absent"
    assert result.severity == "liveness"


def test_a_totally_silent_ok_reply_is_not_ok():
    run = C.run_canary([_lane("openai", lambda prompt, timeout_s: _reply(""))],
                       C.probes_for(quick=True), wall_clock_s=5.0)
    assert run.results[0].status == "wrong_answer"


# --------------------------------------------------------------------------
# ANCHORING -- detected, and reported as QUALITY not liveness
# --------------------------------------------------------------------------


def test_anchoring_copy_is_detected():
    body, decoy, correct = C._anchor_pair(NONCE)
    assert decoy != correct
    passed, failed = C.check_anchoring(decoy, NONCE)
    assert not passed
    assert failed == "anchored_on_decoy"


def test_anchoring_decoy_wins_even_when_the_correct_word_also_appears():
    """Quoting the transcript back is not answering, even if the answer is in it."""
    _, decoy, correct = C._anchor_pair(NONCE)
    passed, failed = C.check_anchoring(f"{decoy} and maybe {correct}", NONCE)
    assert not passed and failed == "anchored_on_decoy"


def test_anchoring_failure_is_a_quality_signal_not_a_liveness_failure():
    def anchored(prompt: str, timeout_s: float) -> VendorReply:
        if "NEW QUESTION" in prompt:
            # What the real failure looked like: the model reads the prior
            # turn's answer straight off the transcript and repeats it. The
            # anchoring body deliberately carries no nonce, so this fake has to
            # copy the decoy exactly the way a wedged model does.
            import re
            return _reply(re.search(r"^  A: (\w+)$", prompt, re.M).group(1))
        return _reply(_correct_answer(prompt))

    run = C.run_canary([_lane("local", anchored, local=True)], C.PROBES,
                       wall_clock_s=10.0)
    anchoring = [r for r in run.results if r.probe == "anchoring"][0]
    assert anchoring.status == "wrong_answer"
    assert anchoring.severity == "quality"
    assert anchoring.failed_check == "anchored_on_decoy"

    s = run.summary()
    assert s["quality_failures"] == 1
    assert s["liveness_failures"] == 0
    # A lane can be alive and still be the wrong shape for a job.
    assert [r.status for r in run.results if r.severity == "liveness"] == ["ok", "ok"]


def test_quality_regression_does_not_trip_the_exit_code():
    _, decoy, _ = C._anchor_pair(NONCE)
    result = C.ProbeResult(vendor="local", model="qwen", endpoint="e",
                           probe="anchoring", severity="quality",
                           status="wrong_answer", failed_check="anchored_on_decoy")
    history = [{"schema": C.SCHEMA_VERSION, "vendor": "local", "model": "qwen",
                "probe": "anchoring", "status": "ok", "latency_s": 1.0}]
    comparison = C.compare_to_history(result, history)
    assert comparison.regressed is True
    run = C.CanaryRun(run_id="r", ts="t", results=(result,), comparisons=(comparison,))
    assert run.regressions("quality") == (comparison,)
    assert run.exit_code() == 0, "a quality regression must not page anyone"
    assert run.summary()["quality_regressions"] == 1


# --------------------------------------------------------------------------
# unavailable != wrong_answer, and the summary never merges them
# --------------------------------------------------------------------------


def test_unavailable_and_wrong_answer_are_distinct_statuses():
    def missing(prompt: str, timeout_s: float) -> VendorReply:
        return _reply(status="unavailable", reason="not_authenticated")

    def wrong(prompt: str, timeout_s: float) -> VendorReply:
        return _reply("nope")

    run = C.run_canary(
        [_lane("google", missing), _lane("openai", wrong)],
        C.probes_for(quick=True), wall_clock_s=5.0)
    by_vendor = {r.vendor: r for r in run.results}
    assert by_vendor["google"].status == "unavailable"
    assert by_vendor["openai"].status == "wrong_answer"
    assert by_vendor["google"].status != by_vendor["openai"].status

    s = run.summary()
    assert s["by_status"]["unavailable"] == 1
    assert s["by_status"]["wrong_answer"] == 1
    assert s["asked"] == 1 and s["could_not_ask"] == 1
    # "we could not ask" is never counted as a failure of any kind.
    assert s["liveness_failures"] == 1
    assert "failures" not in s, "a single merged failure count is how the two get conflated"


def test_unavailable_never_runs_the_checker_and_is_never_a_regression():
    result = C.ProbeResult(vendor="google", model="agy", endpoint="ssh:x",
                           probe="arrival", severity="liveness",
                           status="unavailable", reason="not_authenticated")
    assert result.asked is False
    assert result.failed_check == ""
    history = [{"schema": C.SCHEMA_VERSION, "vendor": "google", "model": "agy",
                "probe": "arrival", "status": "ok", "latency_s": 3.0}]
    comparison = C.compare_to_history(result, history)
    assert comparison.previously_passed is True
    assert comparison.regressed is False, "the bench asleep is not the bench broken"


def test_status_vocabulary_is_closed():
    with pytest.raises(ValueError):
        C.ProbeResult(vendor="v", model="m", endpoint="e", probe="arrival",
                      severity="liveness", status="degraded")
    with pytest.raises(ValueError):
        C.ProbeResult(vendor="v", model="m", endpoint="e", probe="arrival",
                      severity="vibes", status="ok")
    assert "unavailable" not in C.FAILING_STATUSES


def test_transport_failures_map_onto_the_closed_vocabulary():
    cases = {
        "unavailable": "unavailable",
        "timeout": "timeout",
        "error": "error",
        "refused_by_floor": "error",
    }
    for transport, expected in cases.items():
        lane = _lane("x", lambda prompt, timeout_s, t=transport: _reply(
            status=t, reason="r"))
        run = C.run_canary([lane], C.probes_for(quick=True), wall_clock_s=5.0)
        assert run.results[0].status == expected, transport


def test_a_raising_lane_becomes_error_not_a_traceback():
    def boom(prompt: str, timeout_s: float) -> VendorReply:
        raise RuntimeError("socket exploded")

    run = C.run_canary([_lane("local", boom)], C.probes_for(quick=True),
                       wall_clock_s=5.0)
    assert run.results[0].status == "error"
    assert "socket exploded" in run.results[0].reply


# --------------------------------------------------------------------------
# budget: a hung lane must not block the others
# --------------------------------------------------------------------------


def test_hung_lane_times_out_and_the_other_lanes_still_complete():
    release = threading.Event()

    def hung(prompt: str, timeout_s: float) -> VendorReply:
        release.wait(30)                     # never set: this lane is wedged
        return _reply("too late")

    healthy = PerfectLane()
    started = time.monotonic()
    try:
        run = C.run_canary(
            [_lane("openai", hung), _lane("anthropic", healthy),
             _lane("local", PerfectLane(), local=True)],
            C.probes_for(quick=True),
            per_probe_timeout_s=30.0, wall_clock_s=1.5, max_parallel=4)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 10.0, "one hung vendor blocked the whole canary"
    by_vendor = {r.vendor: r for r in run.results}
    assert by_vendor["openai"].status == "timeout"
    assert by_vendor["openai"].reason == "wall_clock"
    assert by_vendor["anthropic"].status == "ok"
    assert by_vendor["local"].status == "ok"
    assert len(run.results) == 3, "an abandoned probe must still be reported"


def test_every_scheduled_probe_is_reported_even_when_abandoned():
    def hung(prompt: str, timeout_s: float) -> VendorReply:
        time.sleep(20)
        return _reply("late")

    run = C.run_canary([_lane("openai", hung)], C.PROBES, wall_clock_s=0.5)
    assert len(run.results) == len(C.PROBES)
    assert {r.status for r in run.results} == {"timeout"}


def test_probes_within_one_lane_run_sequentially():
    """Four concurrent calls to one vendor is a load test, not a health check."""
    concurrent = []
    lock = threading.Lock()
    live = {"n": 0}

    def counting(prompt: str, timeout_s: float) -> VendorReply:
        with lock:
            live["n"] += 1
            concurrent.append(live["n"])
        time.sleep(0.02)
        with lock:
            live["n"] -= 1
        return _reply(_correct_answer(prompt))

    C.run_canary([_lane("local", counting, local=True)], C.PROBES, wall_clock_s=10.0)
    assert max(concurrent) == 1


def test_max_parallel_bounds_lanes_in_flight():
    lock = threading.Lock()
    live = {"n": 0}
    peak = {"n": 0}

    def counting(prompt: str, timeout_s: float) -> VendorReply:
        with lock:
            live["n"] += 1
            peak["n"] = max(peak["n"], live["n"])
        time.sleep(0.05)
        with lock:
            live["n"] -= 1
        return _reply(_correct_answer(prompt))

    lanes = [_lane(f"v{i}", counting) for i in range(6)]
    C.run_canary(lanes, C.probes_for(quick=True), wall_clock_s=20.0, max_parallel=2)
    assert peak["n"] <= 2


# --------------------------------------------------------------------------
# history: append / compare, first-ever run, corrupt line
# --------------------------------------------------------------------------


def _run_with(status: str, latency: float, *, probe: str = "arrival",
              severity: str = "liveness", run_id: str = "r1") -> C.CanaryRun:
    result = C.ProbeResult(vendor="local", model="qwen2.5-coder:7b",
                           endpoint="http://127.0.0.1:11434", probe=probe,
                           severity=severity, status=status, latency_s=latency,
                           local=True)
    return C.CanaryRun(run_id=run_id, ts="2026-07-28T00:00:00Z", results=(result,))


def test_history_roundtrip_append_and_load(tmp_path: Path):
    path = tmp_path / "canary" / "history.jsonl"
    assert C.append_history(_run_with("ok", 1.0), path) == 1
    assert C.append_history(_run_with("ok", 1.5, run_id="r2"), path) == 1
    assert path.exists(), "parents must be created"
    records = C.load_history(path)
    assert len(records) == 2
    assert [r["run_id"] for r in records] == ["r1", "r2"]
    assert records[0]["schema"] == C.SCHEMA_VERSION
    # Append-only: the first line is byte-identical after the second write.
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["latency_s"] == 1.0


def test_first_ever_run_has_no_median_and_is_not_a_regression(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    assert C.load_history(path) == [], "a missing history file is not an error"
    result = _run_with("wrong_answer", 2.0).results[0]
    comparison = C.compare_to_history(result, C.load_history(path))
    assert comparison.first_ever is True
    assert comparison.samples == 0
    assert comparison.median_latency_s is None
    assert comparison.delta_s is None
    assert comparison.prior_pass_rate is None
    assert comparison.previously_passed is False
    assert comparison.regressed is False, "a lane that never passed cannot regress"
    run = C.CanaryRun(run_id="r", ts="t", results=(result,), comparisons=(comparison,))
    assert run.exit_code() == 0
    assert "first" in C.render_table(run)


def test_corrupt_line_is_skipped_not_fatal(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    C.append_history(_run_with("ok", 1.0), path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"schema": "dcanary/1", "vendor": "local", "prob\n')   # torn write
        fh.write("not json at all\n")
        fh.write("\n")
        fh.write('["a", "list", "not", "a", "record"]\n')
        fh.write('{"schema": "other/9", "status": "ok"}\n')              # foreign
        fh.write('{"schema": "dcanary/1", "status": "invented"}\n')      # bad status
    C.append_history(_run_with("ok", 2.0, run_id="r2"), path)

    records = C.load_history(path)
    assert len(records) == 2, "good records survive a corrupt neighbour"
    assert [r["run_id"] for r in records] == ["r1", "r2"]


def test_regression_is_previously_passing_now_failing(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    for i in range(3):
        C.append_history(_run_with("ok", 1.0, run_id=f"r{i}"), path)
    history = C.load_history(path)

    now_broken = _run_with("wrong_answer", 1.2).results[0]
    comparison = C.compare_to_history(now_broken, history)
    assert comparison.samples == 3
    assert comparison.median_latency_s == 1.0
    assert comparison.prior_pass_rate == 1.0
    assert comparison.previously_passed is True
    assert comparison.regressed is True

    run = C.CanaryRun(run_id="r", ts="t", results=(now_broken,),
                      comparisons=(comparison,))
    assert run.exit_code() == 1
    assert run.summary()["liveness_regressions"] == 1
    assert "REGRESSION" in C.render_table(run)


def test_never_passing_lane_is_reported_but_does_not_trip_the_exit_code(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    C.append_history(_run_with("wrong_answer", 1.0), path)
    result = _run_with("wrong_answer", 1.0, run_id="r2").results[0]
    comparison = C.compare_to_history(result, C.load_history(path))
    assert comparison.samples == 1
    assert comparison.previously_passed is False
    assert comparison.regressed is False
    run = C.CanaryRun(run_id="r2", ts="t", results=(result,), comparisons=(comparison,))
    assert run.exit_code() == 0
    assert "WRONG" in C.render_table(run)


def test_latency_delta_and_slower_flag(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    for i, lat in enumerate((1.0, 1.0, 1.2)):
        C.append_history(_run_with("ok", lat, run_id=f"r{i}"), path)
    history = C.load_history(path)

    steady = C.compare_to_history(_run_with("ok", 1.1).results[0], history)
    assert steady.median_latency_s == 1.0
    assert steady.delta_s == pytest.approx(0.1)
    assert steady.slower is False, "a 0.1s wobble is not a regression"

    crawling = C.compare_to_history(_run_with("ok", 9.0).results[0], history)
    assert crawling.delta_s == pytest.approx(8.0)
    assert crawling.slower is True
    assert crawling.regressed is False, "slow is not the same as broken"


def test_slower_needs_both_a_ratio_and_an_absolute_jump(tmp_path: Path):
    history = [{"schema": C.SCHEMA_VERSION, "vendor": "local",
                "model": "qwen2.5-coder:7b", "probe": "arrival",
                "status": "ok", "latency_s": 0.2}]
    tripled = C.compare_to_history(_run_with("ok", 0.6).results[0], history)
    assert tripled.delta_s == pytest.approx(0.4)
    assert tripled.slower is False, "3x on a 0.2s baseline is noise, not news"


def test_history_is_keyed_on_vendor_model_and_probe(tmp_path: Path):
    """A model swap must not inherit the previous model's baseline."""
    history = [{"schema": C.SCHEMA_VERSION, "vendor": "local", "model": "qwen-7b",
                "probe": "arrival", "status": "ok", "latency_s": 1.0}]
    other_model = C.ProbeResult(vendor="local", model="qwen-32b", endpoint="e",
                                probe="arrival", severity="liveness",
                                status="wrong_answer")
    assert C.compare_to_history(other_model, history).regressed is False
    other_probe = C.ProbeResult(vendor="local", model="qwen-7b", endpoint="e",
                                probe="instruction", severity="liveness",
                                status="wrong_answer")
    assert C.compare_to_history(other_probe, history).regressed is False


def test_trailing_window_bounds_the_comparison():
    history = [{"schema": C.SCHEMA_VERSION, "vendor": "local",
                "model": "qwen2.5-coder:7b", "probe": "arrival",
                "status": "ok", "latency_s": 100.0}] * 5
    history += [{"schema": C.SCHEMA_VERSION, "vendor": "local",
                 "model": "qwen2.5-coder:7b", "probe": "arrival",
                 "status": "ok", "latency_s": 1.0}] * 3
    comparison = C.compare_to_history(_run_with("ok", 1.0).results[0], history,
                                      window=3)
    assert comparison.samples == 3
    assert comparison.median_latency_s == 1.0


def test_history_record_carries_which_check_failed(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    result = C.ProbeResult(vendor="openai", model="codex", endpoint="cli:codex",
                           probe="arrival", severity="liveness",
                           status="wrong_answer", failed_check="tailword_absent",
                           reply="x" * 5000)
    run = C.CanaryRun(run_id="r", ts="t", results=(result,))
    C.append_history(run, path)
    record = C.load_history(path)[0]
    assert record["failed_check"] == "tailword_absent"
    assert record["severity"] == "liveness"
    assert len(record["reply"]) == C.REPLY_TRIM, "a reply is trimmed, not stored whole"


# --------------------------------------------------------------------------
# dry run: calls nothing
# --------------------------------------------------------------------------


def test_dry_run_calls_nothing():
    def must_not_be_called(prompt: str, timeout_s: float) -> VendorReply:
        raise AssertionError("--dry-run called a vendor")

    lanes = [_lane("anthropic", must_not_be_called),
             _lane("local", must_not_be_called, local=True)]
    plan = C.dry_run_plan(lanes, C.PROBES)
    assert plan["dry_run"] is True
    assert plan["calls"] == 2 * len(C.PROBES)
    assert [l["vendor"] for l in plan["lanes"]] == ["anthropic", "local"]
    assert [p["name"] for p in plan["probes"]] == [p.name for p in C.PROBES]
    assert all(p["prompt_chars"] > 0 for p in plan["probes"])


def test_dry_run_names_the_egress_of_every_lane():
    plan = C.dry_run_plan(
        [_lane("local", lambda *a, **k: _reply(), local=True),
         _lane("local", lambda *a, **k: _reply(), local=False)],
        C.probes_for(quick=True))
    assert plan["lanes"][0]["egress"] == "none (loopback)"
    assert plan["lanes"][1]["egress"] == "LEAVES THIS MACHINE"


# --------------------------------------------------------------------------
# egress rules
# --------------------------------------------------------------------------


def test_only_loopback_counts_as_local():
    assert C._is_local_http("http://127.0.0.1:11434") is True
    assert C._is_local_http("http://localhost:11434") is True
    assert C._is_local_http("http://100.119.126.9:11434") is False, (
        "the bench is another machine; bytes sent there have left this one")


def test_default_lanes_never_touch_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://evil.example:11434")
    lanes = C.default_lanes(["local"], ollama_host="http://127.0.0.1:11434")
    assert lanes[0].endpoint == "http://127.0.0.1:11434"
    assert lanes[0].local is True
    # And the variable is left exactly as it was found.
    import os
    assert os.environ["OLLAMA_HOST"] == "http://evil.example:11434"


def test_bench_lane_is_untrusted_and_not_local():
    lanes = C.default_lanes(["local"], ollama_host=C.DEFAULT_BENCH_OLLAMA_HOST)
    assert lanes[0].local is False


def test_unknown_vendor_is_refused():
    with pytest.raises(ValueError):
        C.default_lanes(["deepmind"])


# --------------------------------------------------------------------------
# probe selection
# --------------------------------------------------------------------------


def test_quick_is_the_truncation_probe():
    assert [p.name for p in C.probes_for(quick=True)] == ["arrival"]


def test_probes_for_rejects_an_unknown_name():
    with pytest.raises(ValueError):
        C.probes_for(["telepathy"])


def test_nonces_are_fresh_per_probe():
    seen = {C.new_nonce() for _ in range(200)}
    assert len(seen) == 200


def test_prompt_bodies_differ_between_runs():
    a = C.build_arrival("KAAAAAAA")
    b = C.build_arrival("KBBBBBBB")
    assert a != b, "a probe a model has memorised measures nothing"
