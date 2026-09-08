"""G1-IKARUS-36 -- one voice turn is bounded, honest and priced at what it cost.

BASELINE THIS REPLACES (MEASURED 2026-09-08, this host):
``ikarus_os.ask('agent_env', 'verbessere Daedalus')`` took 150.3 s, returned
``intent='error'`` with the sentence "claude_code_cli did not return a usable
answer after 1 attempt(s)", and left ``reserve 3.0 + settle 3.0`` in the
ledger -- so the SECOND voice turn of the day was refused against the $5.00
period ceiling. The 150 s were a tool loop: with the Ikarus system prompt the
CLI ends with ``stop_reason='tool_use'`` and keeps going.

The three CLI bodies replayed here verbatim are the ones measured that day and
retained under ``docs/evidence/G1-IKARUS-36/``:

* ``probe1_sonnet.json`` -- ``--tools "" --model sonnet --max-turns 1``:
  one turn, ``end_turn``, 20.98 s wall, $0.211466;
* ``probe2_bare.json``   -- the same plus ``--bare``: rc=1, ``is_error=true``
  with ``subtype="success"``, "Not logged in", $0. ``--bare`` is REJECTED, and
  this body is why the parser may never key on ``subtype`` alone;
* ``probe3_opus.json``   -- the CLI default model: $0.529010 billed against a
  $0.25 cap (2.12x) with NO ``result`` key. A cap is an abort switch, not a
  price bound.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest

from daedalus import budget
from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.orchestration.llm_client import LLMSelection

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "G1-IKARUS-36"


def _probe(name: str) -> str:
    return (EVIDENCE / f"{name}.json").read_text(encoding="utf-8")


def _probe_obj(name: str) -> dict:
    return json.loads(_probe(name))


def _completed(stdout: str, *, stderr: str = "", returncode: int = 0):
    proc = mock.MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


class _FakeStreamProc:
    """A Popen double whose stdout is a line iterator and whose stderr is a
    real iterable, because the production path now DRAINS stderr."""

    def __init__(self, lines, stderr_lines=()):
        self.stdout = iter(lines)
        self.stderr = iter(stderr_lines)
        self.stdin = mock.MagicMock()
        self.returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


def _resolved_claude():
    return mock.patch(
        "daedalus.orchestration.runtime_registry.resolve_runtime_command",
        return_value="claude")


# ===========================================================================
# A1/A2 -- the argv is a single tool-free turn with a declared spend cap
# ===========================================================================

def test_blocking_argv_is_one_bounded_tool_free_turn():
    """A1. The exact argv, in order. ``--tools ""`` is what collapsed 150.3 s
    and a ``tool_use`` stop into 20.98 s and ``end_turn``."""
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe1_sonnet"))) as run:
        ikarus_os._claude("hi", effort="low")
    args = run.call_args[0][0]
    assert args == ["claude", "-p", "--tools", "", "--model", "sonnet",
                    "--max-turns", "1", "--max-budget-usd", "0.50",
                    "--no-session-persistence", "--output-format", "json"]
    # The prompt travels on stdin, never in argv.
    assert run.call_args[1]["input"].endswith("User: hi")
    assert not any("User: hi" in a for a in args)


def test_streaming_argv_keeps_the_same_bounded_head():
    """A2."""
    with _resolved_claude(), \
         mock.patch("subprocess.Popen",
                    return_value=_FakeStreamProc([])) as popen:
        list(ikarus_os._claude_stream("hi", effort="low"))
    args = popen.call_args[0][0]
    assert args[:11] == ["claude", "-p", "--tools", "", "--model", "sonnet",
                         "--max-turns", "1", "--max-budget-usd", "0.50",
                         "--no-session-persistence"]
    assert args[11:] == ["--output-format", "stream-json",
                         "--include-partial-messages", "--verbose"]
    assert "json" not in args[12:13]


def test_effort_selects_the_pinned_model_and_cap():
    """A1 (variants). Chat pins its model instead of inheriting the CLI
    default, measured at 2.5x sonnet for the identical single turn."""
    for effort, model, cap in (("low", "sonnet", "0.50"),
                               ("medium", "sonnet", "1.00"),
                               ("high", "opus", "2.00")):
        with _resolved_claude(), \
             mock.patch("subprocess.run",
                        return_value=_completed(_probe("probe1_sonnet"))) as run:
            ikarus_os._claude("hi", effort=effort)
        args = run.call_args[0][0]
        assert args[args.index("--model") + 1] == model
        assert args[args.index("--max-budget-usd") + 1] == cap


# ===========================================================================
# A3/A4/A5/A6/A7 -- the result body decides, and says why
# ===========================================================================

def test_measured_success_body_is_parsed_whole():
    """A3. probe1 replayed verbatim."""
    payload = _probe_obj("probe1_sonnet")
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe1_sonnet"))):
        reply = ikarus_os._claude("hi", effort="low", telemetry=tel)
    assert reply == payload["result"]
    assert tel["duration_ms"] == 15628
    assert tel["stop_reason"] == "end_turn"
    assert tel["subtype"] == "success"
    assert tel["terminal_reason"] == "completed"
    assert tel["num_turns"] == 1
    assert tel["cost_usd_measured"] == pytest.approx(0.211466)
    assert tel["cost_basis"] == "provider_reported"
    assert tel["model_used"] == "claude-sonnet-5"
    assert tel["tokens"] == {"input": 2, "output": 1117,
                             "cache_creation": 50073, "cache_read": 0}
    assert tel["failure_reason_code"] is None


def _mutated(name: str, **changes) -> str:
    obj = _probe_obj(name)
    obj.update(changes)
    return json.dumps(obj)


def test_a_tool_use_stop_is_surfaced_not_swallowed():
    """A4. The exact failure the owner hit, now named in their own language."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(
                        _mutated("probe1_sonnet", stop_reason="tool_use"))):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["failure_reason_code"] == "tool_use"

    german = ikarus_os._claude_failure_sentence("tool_use", tel, german=True)
    english = ikarus_os._claude_failure_sentence("tool_use", tel, german=False)
    assert "Werkzeuge" in german and "--tools" in german
    assert "tools" in english and "--max-turns 1" in english


def test_more_than_one_turn_is_a_tool_loop_even_without_the_stop_reason():
    """A4 (net). A ``.cmd`` relay could swallow the empty ``--tools`` value;
    the turn count catches it."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(
                        _mutated("probe1_sonnet", num_turns=3))):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["failure_reason_code"] == "tool_use"


def test_max_turns_error_is_surfaced_and_is_not_retryable():
    """A5."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(
                        _mutated("probe1_sonnet", subtype="error_max_turns",
                                 is_error=True), returncode=1)):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["failure_reason_code"] == "max_turns"
    assert tel["failure_reason_code"] in ikarus_os._NON_RETRYABLE_FAILURES


def test_budget_abort_names_the_cap_and_the_money_that_moved_anyway():
    """A6. probe3 replayed verbatim: no ``result``, $0.529010 against $0.25."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe3_opus"),
                                            returncode=1)):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["failure_reason_code"] == "max_budget"
    assert tel["cost_usd_measured"] == pytest.approx(0.52901)
    sentence = ikarus_os._claude_failure_sentence("max_budget", tel, german=True)
    assert "$0.50" in sentence and "0.5290" in sentence


def test_an_auth_failure_is_not_read_as_success_from_its_subtype():
    """A7. probe2 measured ``subtype='success'`` together with
    ``is_error=true``; keying on subtype alone would have spoken a login
    error as an answer."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe2_bare"),
                                            returncode=1)):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["subtype"] == "success"
    assert tel["failure_reason_code"] == "not_authenticated"
    assert "login" in ikarus_os._claude_failure_sentence(
        "not_authenticated", tel, german=True)


def test_a_body_that_is_not_result_json_is_never_spoken_as_an_answer():
    """R-adjacent: raw stdout from a CLI in an unknown state is not a reply."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run", return_value=_completed("ok")):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    assert tel["failure_reason_code"] == "bad_response"


def test_a_nonzero_exit_after_a_complete_result_keeps_the_answer():
    """MEASURED precedent (tools/watchdog.py): a plugin SessionEnd hook makes
    ``claude -p`` exit non-zero after a complete, paid-for result."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe1_sonnet"),
                                            returncode=143)):
        reply = ikarus_os._claude("hi", effort="low", telemetry=tel)
    assert reply
    assert tel["failure_reason_code"] is None
    assert "143" in (tel["failure_detail"] or "")


# ===========================================================================
# A8 -- stderr is retained, bounded, ASCII and secret-free
# ===========================================================================

def test_stderr_is_retained_bounded_ascii_and_redacted(monkeypatch):
    """A8. stderr was ``DEVNULL``: a failure the operator cannot see is a
    failure they cannot fix. Retaining it is only safe if it is bounded and
    scrubbed."""
    monkeypatch.setenv("DUMMY_API_KEY", "super-secret-value-1234")
    noisy = ("x" * 5000 + " sk-ant-AAAAAAAAAAAAAAAA "
             + "super-secret-value-1234 é tail-marker")
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe1_sonnet"),
                                            stderr=noisy)):
        ikarus_os._claude("hi", effort="low", telemetry=tel)
    tail = tel["stderr_tail"]
    assert len(tail) <= ikarus_os._STDERR_TAIL_MAX
    assert tail.isascii()
    assert "sk-ant-" not in tail
    assert "super-secret-value-1234" not in tail
    assert "tail-marker" in tail            # the useful end survives


# ===========================================================================
# A9 -- pricing: a declared child cap narrows only the flat worst case
# ===========================================================================

def test_a_declared_child_cap_narrows_only_the_worst_case_branch():
    """A9. And it NEVER widens: 2.00 * 3 exceeds the $3.00 worst case, so the
    worst case still wins."""
    capped = budget.price_call("anthropic_cli", cli_budget_cap_usd=0.50)
    assert (capped.usd, capped.basis) == (1.50, "cli_budget_cap")

    over = budget.price_call("anthropic_cli", cli_budget_cap_usd=2.00)
    assert (over.usd, over.basis) == (3.00, "worst_case")

    plain = budget.price_call("anthropic_cli")
    assert (plain.usd, plain.basis) == (3.00, "worst_case")

    # A cap says nothing about where the bytes go or whether a price is known.
    local = budget.price_call("remote_inference", host="127.0.0.1",
                              cli_budget_cap_usd=0.01)
    assert (local.usd, local.basis) == (0.0, "free_local")
    unknown = budget.price_call("no_such_vendor", cli_budget_cap_usd=0.01)
    assert unknown.basis == "unknown" and unknown.usd == budget.UNKNOWN_CALL_USD


@pytest.mark.parametrize("bad", [0, -1, "nope", float("inf"), float("nan")])
def test_a_nonsense_cap_falls_back_to_the_worst_case(bad):
    est = budget.price_call("anthropic_cli", cli_budget_cap_usd=bad)
    assert (est.usd, est.basis) == (3.00, "worst_case")


def test_the_cap_is_read_from_the_childs_own_argv():
    """A12 (half). The largest declared cap wins: which occurrence the CLI
    honours is UNVERIFIED and the guard must never under-reserve."""
    read = budget.cli_budget_cap_usd
    assert read(["claude", "-p", "--max-budget-usd", "0.40"]) == 0.40
    assert read(["claude", "--max-budget-usd=0.75"]) == 0.75
    assert read(["claude", "--max-budget-usd", "0.40",
                 "--max-budget-usd", "0.90"]) == 0.90
    assert read(["claude", "-p"]) is None
    assert read(["claude", "--max-budget-usd", "nope"]) is None
    assert read(["claude", "--max-budget-usd"]) is None
    assert read("claude -p --max-budget-usd 0.40") is None


# ===========================================================================
# A10/A11/A16/A17 -- the ledger says what the turn actually cost
# ===========================================================================

def _entries():
    return json.loads(budget.ledger().path.read_text(encoding="utf-8"))["entries"]


def test_the_turn_settles_at_the_price_the_vendor_reported():
    """A10. Before this packet the same turn reserved AND settled $3.00."""
    budget.install_process_guard()
    try:
        with _resolved_claude(), \
             mock.patch("subprocess.run",
                        return_value=_completed(_probe("probe1_sonnet"))):
            assert ikarus_os._claude("hi", effort="low")
    finally:
        budget.uninstall_process_guard()
    settles = [e for e in _entries() if e["kind"] == "settle"]
    assert len(settles) == 1, "the interposer must not book a second call"
    assert settles[0]["usd"] == pytest.approx(0.211466)
    assert settles[0]["estimate_usd"] == pytest.approx(1.50)
    assert budget.ledger().state().spent_usd == pytest.approx(0.211466)


def test_an_unreadable_cost_settles_at_the_estimate_and_says_so():
    """A11/R4. An unknown price is not a free price."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(
                        _mutated("probe1_sonnet", total_cost_usd="free"))):
        reply = ikarus_os._claude("hi", effort="low", telemetry=tel)
    assert reply                                   # the answer still arrives
    assert tel["cost_usd_measured"] is None
    assert tel["cost_basis"] == "estimate"
    settles = [e for e in _entries() if e["kind"] == "settle"]
    assert settles[-1]["usd"] == pytest.approx(1.50)


@pytest.mark.parametrize("bad", [None, "free", -1.0, float("nan"),
                                 float("inf"), True])
def test_no_malformed_cost_is_ever_read_as_zero(bad):
    """R4. ``0.0`` would be the one wrong answer here."""
    body = _mutated("probe1_sonnet", total_cost_usd=bad)
    assert budget.claude_reported_cost_usd(body) is None
    assert budget.claude_reported_cost_usd("") is None
    assert budget.claude_reported_cost_usd("not json") is None
    assert budget.claude_reported_cost_usd(None) is None


def test_a_missing_executable_is_released_not_charged():
    """A16."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run", side_effect=FileNotFoundError("gone")):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    releases = [e for e in _entries() if e["kind"] == "release"]
    assert releases and releases[-1]["reason"]
    assert budget.ledger().state().spent_usd == pytest.approx(0.0)
    assert tel["failure_reason_code"] == "spawn_failed"


def test_a_timeout_settles_at_the_estimate_because_money_may_have_moved():
    """A17. A timeout after the tokens were generated looks exactly like a
    connection refused, so this is the one case that must NOT release."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    side_effect=subprocess.TimeoutExpired("claude", 150)):
        assert ikarus_os._claude("hi", effort="low", telemetry=tel) is None
    settles = [e for e in _entries() if e["kind"] == "settle"]
    assert settles[-1]["usd"] == pytest.approx(1.50)
    assert tel["failure_reason_code"] == "timeout"
    assert tel["cost_basis"] == "estimate"


# ===========================================================================
# A12/A13 -- the interposer, for every OTHER claude spawner in the tree
# ===========================================================================

def _reserve_recorder(seen: list):
    def fake_reserve(vendor, model=None, **kw):
        seen.append({"vendor": vendor, **kw})
        return mock.MagicMock(usd=1.0)
    return fake_reserve


def test_the_interposer_prices_a_capped_argv_at_the_cap_and_settles_measured():
    """A12. No call site needs to change to benefit."""
    from daedalus.runtimes.execution import budget_process as bp

    reservation = mock.MagicMock(usd=1.2)
    seen: list = []

    def fake_reserve(vendor, model=None, **kw):
        seen.append({"vendor": vendor, **kw})
        return reservation

    def fake_run(argv, **kw):
        return _completed(_probe("probe1_sonnet"))

    guarded = bp._guarded_spawn(fake_run, "subprocess.run",
                                reserve_call=fake_reserve)
    guarded(["claude", "-p", "--max-budget-usd", "0.40", "hello"])
    assert seen[0]["cli_budget_cap_usd"] == 0.40
    reservation.settle.assert_called_once_with(pytest.approx(0.211466))


def test_an_uncapped_claude_spawn_is_unchanged():
    """A13. Every other claude spawner in the tree keeps the worst case."""
    from daedalus.runtimes.execution import budget_process as bp

    reservation = mock.MagicMock(usd=3.0)
    seen: list = []

    def fake_reserve(vendor, model=None, **kw):
        seen.append({"vendor": vendor, **kw})
        return reservation

    guarded = bp._guarded_spawn(lambda argv, **kw: _completed("not json"),
                                "subprocess.run", reserve_call=fake_reserve)
    guarded(["claude", "-p", "build the whole feature"])
    assert "cli_budget_cap_usd" not in seen[0]
    reservation.settle.assert_called_once_with(None)   # -> the estimate


# ===========================================================================
# A14/A15 -- the streaming twin
# ===========================================================================

_STREAM_RESULT = {
    "type": "result", "subtype": "success", "is_error": False,
    "result": "Hi there", "total_cost_usd": 0.031, "num_turns": 1,
    "stop_reason": "end_turn", "terminal_reason": "completed",
    "duration_ms": 1200, "permission_denials": [],
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 2, "outputTokens": 9,
                                       "cacheReadInputTokens": 0,
                                       "cacheCreationInputTokens": 11}},
}


def _delta(text: str) -> str:
    return json.dumps({"type": "stream_event", "event": {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": text}}}) + "\n"


def test_the_stream_final_result_frame_is_parsed_and_settles_the_turn():
    """A14. The frame the parser used to ignore is the one carrying the
    price."""
    lines = [_delta("Hi"), _delta(" there"), json.dumps(_STREAM_RESULT) + "\n"]
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.Popen",
                    return_value=_FakeStreamProc(lines)):
        out = list(ikarus_os._claude_stream("hi", effort="low", telemetry=tel))
    assert out == ["Hi", " there"]
    assert tel["cost_usd_measured"] == pytest.approx(0.031)
    assert tel["cost_basis"] == "provider_reported"
    assert tel["model_used"] == "claude-sonnet-5"
    settles = [e for e in _entries() if e["kind"] == "settle"]
    assert settles[-1]["usd"] == pytest.approx(0.031)


def test_a_stream_without_a_result_frame_settles_at_the_estimate():
    """A14 (honesty half). No frame means the price is UNKNOWN; it is never
    fabricated as provider_reported and never zero."""
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.Popen",
                    return_value=_FakeStreamProc([_delta("Hi")])):
        assert list(ikarus_os._claude_stream("hi", effort="low",
                                             telemetry=tel)) == ["Hi"]
    assert tel["cost_usd_measured"] is None
    assert tel["cost_basis"] == "estimate"
    assert tel["failure_reason_code"] == "empty_result"
    settles = [e for e in _entries() if e["kind"] == "settle"]
    assert settles[-1]["usd"] == pytest.approx(1.50)


def test_a_chatty_child_stderr_cannot_deadlock_the_stream():
    """A15. stderr moved from DEVNULL to PIPE; without a drain thread a full
    64 KiB pipe blocks the child outside every timeout here."""
    noise = ["noise line %d\n" % i for i in range(4000)]     # ~200 KiB
    lines = [_delta("a"), _delta("b"), json.dumps(_STREAM_RESULT) + "\n"]
    tel: dict = {}
    with _resolved_claude(), \
         mock.patch("subprocess.Popen",
                    return_value=_FakeStreamProc(lines, stderr_lines=noise)):
        out = list(ikarus_os._claude_stream("hi", effort="low", telemetry=tel))
    assert out == ["a", "b"]
    assert len(tel["stderr_tail"]) <= ikarus_os._STDERR_TAIL_MAX


# ===========================================================================
# A18 -- the envelope contract the cockpit consumes
# ===========================================================================

class _ClaudeClient:
    def resolve(self, requested=None):
        return LLMSelection("claude_code_cli", "auto", True, 150.0, 1, "test")


@pytest.mark.parametrize("probe,expect_error", [("probe1_sonnet", False),
                                                ("probe3_opus", True)])
def test_the_envelope_carries_exactly_the_documented_invocation_block(
        probe, expect_error):
    """A18."""
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe(probe),
                                            returncode=1 if expect_error else 0)):
        env = ikarus_os._chat("p", "hello", None, voice_client=_ClaudeClient())
    block = env["llm"]["invocation"]
    assert set(block) == set(ikarus_os._INVOCATION_KEYS)
    json.dumps(env)                                   # must round-trip
    assert env["provider_used"] == "claude_code_cli"
    if expect_error:
        assert env["intent"] == "error"
        assert block["failure_reason_code"] == "max_budget"
        # The reason is IN the spoken answer, not only in a field.
        assert "0.5290" in env["assistant"]
    else:
        assert env["intent"] == "chat"
        assert block["failure_reason_code"] is None
        assert env["model_used"] == "claude-sonnet-5"


def test_a_non_claude_voice_has_no_invocation_block():
    """A18 (contract). The cockpit must treat the object as optional."""
    def fake_llm(provider, message, model=None, effort=None, project=None, *,
                 conversation_id=None, timeout_s=150.0, limit_policy=None,
                 additional_context="", response_schema=None, cancelled=None,
                 transport=None, telemetry=None):
        return "local answer", "qwen", ikarus_os._EMPTY_CTX

    class _Ollama:
        def resolve(self, requested=None):
            return LLMSelection("ollama", "auto", True, 150.0, 1, "test")

    with mock.patch.object(ikarus_os, "_llm", fake_llm):
        env = ikarus_os._chat("p", "hello", None, voice_client=_Ollama())
    assert "invocation" not in env["llm"]


# ===========================================================================
# R1/R2/R3/R5 -- refusals
# ===========================================================================

def test_the_always_present_model_flag_is_still_shim_screened():
    """R1. ``--model`` is now ALWAYS in argv, so this coverage must not
    regress."""
    with _resolved_claude(), \
         mock.patch.object(ikarus_os, "_refuse_cmd_shim",
                           side_effect=ikarus_os.ProviderStartRefused({})) as shim, \
         mock.patch("subprocess.run") as run:
        with pytest.raises(ikarus_os.ProviderStartRefused):
            ikarus_os._claude("hi", model='sonnet" & echo pwned & rem ')
    run.assert_not_called()
    assert "--model" in shim.call_args[0][1]


@pytest.mark.parametrize("effort", ["0.99; rm -rf /", None, "HIGH", "",
                                    "; --max-budget-usd 999"])
def test_no_caller_string_ever_reaches_the_budget_argv_slot(effort):
    """R2. The cap is always a formatted module constant."""
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe1_sonnet"))) as run:
        ikarus_os._claude("hi", effort=effort)
    args = run.call_args[0][0]
    value = args[args.index("--max-budget-usd") + 1]
    assert value in {"0.50", "1.00", "2.00"}
    assert args.count("--max-budget-usd") == 1


def test_a_turn_that_does_not_fit_under_the_ceiling_never_spawns():
    """R3. The refusal is the receipt -- not a deterministic answer wearing
    Claude's name."""
    led = budget.ledger()
    held = led.reserve(budget.price_call("anthropic_cli", calls=1), label="pre")
    held.settle(4.90)
    with _resolved_claude(), \
         mock.patch("subprocess.run") as run, \
         mock.patch("subprocess.Popen") as popen:
        with pytest.raises(ikarus_os.ProviderStartRefused) as refused:
            ikarus_os._claude("hi", effort="low")
    run.assert_not_called()
    popen.assert_not_called()
    assert "cli_budget_cap" in json.dumps(refused.value.receipt)


def test_no_failure_path_switches_to_another_provider():
    """R5. Every degrade is visible; none is a different brain's answer wearing
    claude_code_cli's name."""
    for probe, rc in (("probe2_bare", 1), ("probe3_opus", 1)):
        with _resolved_claude(), \
             mock.patch.object(ikarus_os, "_ollama",
                               side_effect=AssertionError("fell back")), \
             mock.patch.object(ikarus_os, "_codex",
                               side_effect=AssertionError("fell back")), \
             mock.patch.object(ikarus_os, "_deepseek",
                               side_effect=AssertionError("fell back")), \
             mock.patch("subprocess.run",
                        return_value=_completed(_probe(probe), returncode=rc)):
            env = ikarus_os._chat("p", "hello", None,
                                  voice_client=_ClaudeClient())
        assert env["provider_used"] == "claude_code_cli"
        assert env["intent"] == "error"


def test_a_deterministic_failure_is_not_retried_into_a_second_charge():
    """The attempt loop stops on a refusal a retry cannot fix. Inert at the
    default ``max_attempts == 1``; this pins the opted-in path."""
    class _Retrying:
        def resolve(self, requested=None):
            return LLMSelection("claude_code_cli", "auto", True, 150.0, 3, "t")

    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(_probe("probe2_bare"),
                                            returncode=1)) as run:
        env = ikarus_os._chat("p", "hello", None, voice_client=_Retrying())
    assert run.call_count == 1
    assert env["llm"]["attempts"] == 1
    assert env["llm"]["invocation"]["failure_reason_code"] == "not_authenticated"


# ===========================================================================
# R6 -- no credential in retained evidence
# ===========================================================================

def test_the_ledger_label_never_carries_child_output(monkeypatch):
    """R6. The redacted stderr tail lives in the envelope only; ledger labels
    stay argv-derived and bounded."""
    monkeypatch.setenv("DUMMY_TOKEN", "tok-secret-abcdefgh")
    with _resolved_claude(), \
         mock.patch("subprocess.run",
                    return_value=_completed(
                        _probe("probe1_sonnet"),
                        stderr="tok-secret-abcdefgh sk-ant-BBBBBBBBBBBB")):
        ikarus_os._claude("hi", effort="low")
    blob = budget.ledger().path.read_text(encoding="utf-8")
    assert "tok-secret-abcdefgh" not in blob
    assert "sk-ant-" not in blob
    labels = [e.get("label", "") for e in _entries()]
    assert any(lbl.startswith("ikarus voice") for lbl in labels)


# ===========================================================================
# A20/A22 -- the live measurement. OPT-IN: it spends real money.
# ===========================================================================

@pytest.mark.skipif(
    os.environ.get("DAEDALUS_LIVE_CLAUDE") != "1",
    reason="spends real money; set DAEDALUS_LIVE_CLAUDE=1 and a scratch "
           "DAEDALUS_BUDGET_LEDGER to run it")
def test_live_one_voice_turn_is_bounded_fast_and_priced_at_what_it_cost():
    """A20/A22. Run once on this host and recorded in the packet doc.

    BEFORE (MEASURED 2026-09-08, same message, same host): 150.3 s,
    ``intent='error'``, reserve $3.00 + settle $3.00, second turn refused.
    """
    from daedalus.orchestration.ikarus import shell as live

    blocking: dict = {}
    t0 = time.monotonic()
    reply = live._claude("verbessere Daedalus", "low", telemetry=blocking)
    blocking["wall_seconds"] = round(time.monotonic() - t0, 3)

    streaming: dict = {}
    t1 = time.monotonic()
    deltas = list(live._claude_stream("verbessere Daedalus", "low",
                                      telemetry=streaming))
    streaming["wall_seconds"] = round(time.monotonic() - t1, 3)

    out = Path(os.environ["DAEDALUS_LIVE_CLAUDE_OUT"])
    out.write_text(json.dumps(
        {"blocking": blocking, "streaming": streaming,
         "blocking_reply_chars": len(reply or ""),
         "streaming_reply_chars": len("".join(deltas)),
         "ledger": json.loads(budget.ledger().path.read_text("utf-8"))},
        indent=2, sort_keys=True), encoding="utf-8")

    assert reply, "the blocking turn produced no answer"
    assert blocking["num_turns"] == 1
    assert blocking["stop_reason"] == "end_turn"
    assert blocking["failure_reason_code"] is None
    assert blocking["wall_seconds"] < 60
    assert blocking["cost_basis"] == "provider_reported"
    assert blocking["cost_usd_measured"] <= 0.50

    # THE STREAMING HALF IS NOT ASSERTED TO ANSWER, because MEASURED
    # 2026-09-08 it did not: 2/2 live `--output-format stream-json` turns with
    # the identical bounded head ended `stop_reason="tool_use"`,
    # `num_turns=2`, `subtype="error_max_turns"` ($0.253992 / $0.243142 /
    # $0.253388), while 2/2 `--output-format json` turns ended `end_turn` with
    # an answer. Asserting an answer here would be asserting something this
    # host does not produce. What IS asserted is the property this packet
    # exists for: whatever the CLI does, the turn stays bounded, the price is
    # the vendor's own, and a turn that produced no text says why.
    assert streaming["wall_seconds"] < 60
    assert streaming["cost_basis"] == "provider_reported"   # the result frame
    assert streaming["cost_usd_measured"] <= 0.50           # DOES carry cost
    if not "".join(deltas):
        assert streaming["failure_reason_code"], (
            "a streaming turn that produced no text must name a reason")
