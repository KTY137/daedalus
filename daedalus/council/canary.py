"""The vendor canary -- a cheap, repeatable health check for every model lane.

WHY THIS EXISTS (the incident, 2026-07-28)
------------------------------------------
Four vendor lanes were assumed healthy; two were silently broken, and both were
found by accident while doing real work that then had to be thrown away.

* ``codex`` received a TRUNCATED prompt, because a multi-line string does not
  survive an npm ``.cmd`` shim on Windows -- it arrives cut at the first
  newline. The model answered "your message was cut off", which reads as a
  model quirk rather than a transport bug.
* A local Ollama model answered the same 21 characters twice: it was anchoring
  on its own prior turn in the transcript instead of reasoning.

A liveness check that asserts "the process exited 0" or "HTTP 200" is GREEN
through both. That is the bar this module has to clear, so the rule here is:

    EVERY PROBE IS (prompt, checker) AND THE CHECKER IS DETERMINISTIC PYTHON.

No model judges another model's answer. A checker that needed an LLM would
have exactly the failure mode the canary is supposed to catch.

WE COULD NOT ASK  !=  WE ASKED AND THE ANSWER WAS WRONG
--------------------------------------------------------
Conflating those two is the main way a health check lies. ``unavailable`` (agy
not signed in, bench asleep, CLI not installed) is NOT a failure and never
trips the exit code; :data:`CANARY_STATUSES` is closed and
:meth:`CanaryRun.summary` reports the two groups separately, by construction.

LIVENESS vs QUALITY
-------------------
``arrival`` and ``instruction`` ask "did our bytes arrive intact and did the
lane answer in the shape it was told to" -- that is LIVENESS, and a regression
there is an alarm. ``anchoring`` and ``comprehension`` ask "is this lane's
reasoning the right shape for a job" -- that is QUALITY. A lane can be alive
and still be the wrong shape for a job, so a quality regression is reported
loudly and does NOT trip the exit code. Merging the two would either bury the
transport alarm or page a human because a 7b model failed a reading task.

EGRESS
------
``offload.py`` justifies running its local lane with the egress checks relaxed
on the grounds that "ollama is local, no bytes leave the machine" -- but its
host comes from ``OLLAMA_HOST``, an environment variable. So, here:

* every host is passed EXPLICITLY per call; this module never sets, mutates or
  exports ``OLLAMA_HOST`` into any process environment (the subprocess
  environment is :func:`vendors.council_env`, which strips it);
* only ``127.0.0.1``/``localhost`` counts as local. The bench is another box on
  the tailnet and a canary payload sent there HAS left this machine, which is
  why every probe body is synthetic -- generated filler, fruit names and
  invented one-line summaries. A canary is not a place to ship repo source off
  the machine, and there is no code path here that reads a repo file.

Transport is not reimplemented: :mod:`daedalus.council.vendors` already puts
the prompt on stdin, kills the whole process tree on timeout, strips
``OLLAMA_HOST`` and refuses an over-budget Ollama prompt rather than letting
the server head-truncate it. This module reuses those adapters and adds only
what a canary needs on top of them.

SPEND IS OPT-IN, AND THAT IS A CONTROL, NOT A COMMENT
-----------------------------------------------------
This module's own help text says the canary runs "a small REAL task" against
every vendor lane -- so a bare ``daedalus canary`` used to spawn ``claude`` and
``codex`` (MEASURED with a spawn sentinel on 2026-07-28: two real vendor
binaries launched, three records appended to disk) with nothing asking first.
``--dry-run`` was an OPT-OUT, and an opt-out is not a gate: it only protects the
operator who already knew to type it.

So the gate exists now, and it is the SAME gate as the council's:

* :func:`run_canary` takes ``live`` and it DEFAULTS TO FALSE.  Any lane still
  carrying a shipped vendor transport raises :class:`LiveCanaryRefused` before a
  thread is started, before a probe is built and before one byte is dispatched.
* The classification is :func:`session.live_egress_seats` -- IMPORTED, not
  re-implemented.  This repo has already been bitten by five copies of one "is
  this host local" predicate disagreeing with each other; a second, divergent
  spend classifier would be the same mistake with money attached.
  :func:`live_egress_lanes` only maps a :class:`Lane` back to the adapter(s)
  behind its ``ask`` callable and hands them to that one function.
* The operator's form is ``daedalus canary --live``.  Without it the CLI refuses
  and points at ``--dry-run``; ``--dry-run`` prints the plan, calls nothing, and
  NAMES THE SEATS ``--live`` would call, so the price is visible before it is
  paid.  ``--live --dry-run`` together is REFUSED as ambiguous rather than
  settled by a precedence rule nobody would remember at 2am.
"""

from __future__ import annotations

import json
import random
import re
import secrets
import shutil
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .session import LiveCouncilRefused, live_egress_seats
from .vendors import (
    DEFAULT_BENCH_OLLAMA_HOST,
    DEFAULT_LOCAL_OLLAMA_HOST,
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    CouncilAdapter,
    OllamaAdapter,
    VendorReply,
)

__all__ = [
    "CANARY_STATUSES",
    "SEVERITIES",
    "SCHEMA_VERSION",
    "DEFAULT_HISTORY_PATH",
    "DEFAULT_BENCH_OLLAMA_HOST",
    "DEFAULT_LOCAL_OLLAMA_HOST",
    "DEFAULT_PER_PROBE_TIMEOUT_S",
    "DEFAULT_WALL_CLOCK_S",
    "DEFAULT_MAX_PARALLEL",
    "DEFAULT_OLLAMA_MODEL",
    "VENDOR_KEYS",
    "ProbeSpec",
    "ProbeResult",
    "Comparison",
    "CanaryRun",
    "Lane",
    "PROBES",
    "QUICK_PROBE",
    "probes_for",
    "new_nonce",
    "build_arrival",
    "check_arrival",
    "build_instruction",
    "check_instruction",
    "build_anchoring",
    "check_anchoring",
    "build_comprehension",
    "check_comprehension",
    "default_lanes",
    "LiveCanaryRefused",
    "live_egress_lanes",
    "run_canary",
    "dry_run_plan",
    "append_history",
    "load_history",
    "compare_to_history",
    "render_table",
    "resolve_exe",
]


# --------------------------------------------------------------------------- #
# closed vocabularies                                                          #
# --------------------------------------------------------------------------- #

#: Outcome of one probe. CLOSED -- nothing may invent a sixth, and in
#: particular ``unavailable`` and ``wrong_answer`` are separate members because
#: a report that merges them is a report that lies.
#:
#:   ok           -- we asked, and the deterministic checker accepted the reply
#:   wrong_answer -- we asked, the bytes came back, the checker REJECTED them
#:   timeout      -- we asked and nothing came back inside the budget
#:   unavailable  -- WE COULD NOT ASK (not installed, not signed in, asleep)
#:   error        -- the transport itself failed (bad response, nonzero exit,
#:                   over-budget prompt, secret-floor refusal)
CANARY_STATUSES: tuple[str, ...] = (
    "ok",
    "wrong_answer",
    "timeout",
    "unavailable",
    "error",
)

#: A probe either measures whether the lane is ALIVE and the bytes arrived, or
#: whether the lane's reasoning is the right SHAPE. Only ``liveness`` trips the
#: exit code -- see the module docstring.
SEVERITIES: tuple[str, ...] = ("liveness", "quality")

#: Statuses that mean "we asked and it did not work". ``unavailable`` is
#: deliberately absent: we never asked, so there is nothing to have failed.
FAILING_STATUSES: frozenset[str] = frozenset({"wrong_answer", "timeout", "error"})

SCHEMA_VERSION = "dcanary/1"

#: Dumb, append-only, no database.
DEFAULT_HISTORY_PATH = Path("runs") / "canary" / "history.jsonl"

DEFAULT_PER_PROBE_TIMEOUT_S = 120.0
DEFAULT_WALL_CLOCK_S = 420.0
DEFAULT_MAX_PARALLEL = 4

#: Cheapest sensible local model. This runs often; the 32b is not a health
#: check, it is a bill.
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"

#: Vendor keys, spelled the way the operator types them (same set as
#: ``council.session.VENDOR_KEYS`` so ``--vendors`` means one thing repo-wide).
VENDOR_KEYS: tuple[str, ...] = ("anthropic", "openai", "google", "local")

#: How much of a reply is kept on the record. Enough to see what a lane
#: actually said, not enough to turn history.jsonl into a transcript store.
REPLY_TRIM = 400

#: Trailing window for the median comparison. Long enough to be a baseline,
#: short enough that a lane which legitimately got faster stops being compared
#: against last month.
TRAILING_WINDOW = 20

#: A lane counts as materially slower only if it is BOTH a large multiple of
#: its median AND absolutely slow enough for a human to care. Either test alone
#: cries wolf: a 0.2s -> 0.6s local hop is 3x and means nothing.
SLOWER_RATIO = 2.0
SLOWER_ABS_S = 2.0


# --------------------------------------------------------------------------- #
# nonce                                                                        #
# --------------------------------------------------------------------------- #

_NONCE_RE = re.compile(r"\bNONCE-([A-Z0-9]{8})\b")


def new_nonce() -> str:
    """A fresh probe nonce, e.g. ``K7F3A9C1``.

    Fresh PER PROBE PER LANE, not per run: a reused nonce cannot distinguish a
    lane that answered from a lane (or a cache, or a shared transcript) that
    echoed somebody else's answer -- which is the exact confusion the anchoring
    incident was made of.
    """
    return "K" + secrets.token_hex(4).upper()[:7]


def _rng(nonce: str) -> random.Random:
    """Deterministic per-nonce randomness, so ``build`` and ``check`` agree.

    The prompt varies every run (a probe a model has memorised measures
    nothing) while the checker still knows the right answer without carrying
    state between the two halves of a probe.
    """
    return random.Random(f"dcanary:{nonce}")


# --------------------------------------------------------------------------- #
# probe corpora -- SYNTHETIC ONLY, never repo source                           #
# --------------------------------------------------------------------------- #

_FILLER_WORDS = (
    "lantern", "meadow", "cobble", "thistle", "quarry", "bramble", "cinder",
    "gable", "harrow", "ivory", "kestrel", "linnet", "marrow", "nettle",
    "orchard", "pewter", "quiver", "rafter", "sorrel", "tallow", "umber",
    "verdant", "willow", "yarrow", "zephyr", "amber", "basalt", "clover",
)

#: Disjoint from :data:`_FILLER_WORDS` on purpose: the arrival tail token must
#: not be findable anywhere in the padding, or a reply could satisfy the tail
#: check by quoting the middle of the prompt.
_TAIL_WORDS = (
    "harbor", "beacon", "trellis", "compass", "anvil", "lattice", "mistral",
    "granite", "plumage", "saffron",
)

_ANCHOR_SETS = (
    ("apricot", "blueberry", "cranberry"),
    ("dandelion", "elderberry", "fig"),
    ("ginger", "hazelnut", "juniper"),
    ("kiwi", "lemon", "mango"),
    ("nectarine", "olive", "papaya"),
    ("quince", "rhubarb", "sultana"),
)

_ORDINALS = ("first", "second", "third")

#: Invented one-line summaries. None of these describes a real file in this
#: repo, and none of them may contain "roll"/"revert" -- the comprehension
#: probe's answer is defined by being the ONLY line that does.
_SUMMARY_DECOYS = (
    "parses a config file and reports unknown keys",
    "renders a progress bar for long downloads",
    "caches DNS lookups for the duration of a run",
    "converts timestamps between local time and UTC",
    "counts lines of code per language in a tree",
    "validates an email address against a pattern",
    "compresses log files older than seven days",
    "pretty-prints a nested dictionary as a tree",
)

_SUMMARY_TARGETS = (
    "restores the previous release when a deploy fails (rollback)",
    "performs a rollback of the database migration on error",
    "rolls the change back to the last known-good revision (rollback)",
)


def _filler(rng: random.Random, lines: int) -> str:
    return "\n".join(
        "padding %03d: %s" % (i, " ".join(rng.choice(_FILLER_WORDS) for _ in range(12)))
        for i in range(lines)
    )


# --------------------------------------------------------------------------- #
# probe 1 -- ARRIVAL (the one that would have caught both incidents)           #
# --------------------------------------------------------------------------- #

#: ~40 lines of filler is roughly 800 tokens: long enough that a transport
#: which truncates has something to truncate, and far enough under the Ollama
#: usable input window that the probe itself never provokes the failure it
#: measures.
ARRIVAL_PAD_LINES = 40


def build_arrival(nonce: str, pad_lines: int = ARRIVAL_PAD_LINES) -> str:
    """A long prompt with a token at the VERY START and a word at the VERY END.

    Both incidents were truncation, in OPPOSITE DIRECTIONS, so one token cannot
    catch both:

    * Ollama HEAD-truncates an over-budget prompt (it eats the system prompt
      first), so the HEAD token disappears;
    * the npm ``.cmd`` shim cut a multi-line argv at the first newline, so the
      TAIL -- including the instruction telling the model what to do --
      disappeared, and the model answered "your message was cut off".

    Requiring BOTH tokens back is what makes a single cheap probe cover both.
    It also closes the obvious false pass: a model that lost the tail may still
    echo the head token while complaining about the cut, and that reply is
    correctly rejected because it cannot contain a tail word it never received.
    """
    rng = _rng(nonce)
    tail = rng.choice(_TAIL_WORDS)
    return (
        f"NONCE-{nonce}\n"
        f"{_filler(rng, pad_lines)}\n"
        "The FIRST line of this message is a token of the form NONCE-XXXXXXXX, "
        "and the LAST line gives a single word after 'TAILWORD:'.\n"
        "Reply with the token, then one space, then that word. Nothing else.\n"
        f"TAILWORD: {tail}"
    )


def expect_arrival(nonce: str) -> str:
    return f"NONCE-{nonce} {_rng(nonce).choice(_TAIL_WORDS)}"


def check_arrival(reply: str, nonce: str) -> tuple[bool, str]:
    """Accept only if BOTH ends of the prompt demonstrably arrived."""
    tail = _rng(nonce).choice(_TAIL_WORDS)
    text = reply or ""
    head_ok = f"NONCE-{nonce}" in text
    tail_ok = re.search(rf"\b{re.escape(tail)}\b", text, re.IGNORECASE) is not None
    if head_ok and tail_ok:
        return True, ""
    if not head_ok and not tail_ok:
        return False, "both_absent"
    if not head_ok:
        # The tail came back but the head did not: the prompt was HEAD-truncated
        # (over-budget Ollama) or the lane never saw the opening bytes.
        return False, "nonce_absent"
    return False, "tailword_absent"


# --------------------------------------------------------------------------- #
# probe 2 -- INSTRUCTION                                                       #
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n?|\n?```$")


def build_instruction(nonce: str) -> str:
    return (
        f"Reply with exactly OK-{nonce}\n"
        "Nothing else: no preamble, no explanation, no trailing sentence."
    )


def expect_instruction(nonce: str) -> str:
    return f"OK-{nonce}"


def _normalise(reply: str) -> str:
    """Strip TRANSPORT artefacts only -- never content.

    Code fences, surrounding quotes and stray whitespace are things a CLI
    wrapper adds; removing them keeps the probe measuring instruction-following
    rather than punishing a lane for its own output framing. Anything the model
    actually chose to say survives this and is judged.
    """
    text = (reply or "").strip()
    text = _FENCE_RE.sub("", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        text = text[1:-1].strip()
    return text.rstrip(".")


def check_instruction(reply: str, nonce: str) -> tuple[bool, str]:
    want = f"OK-{nonce}"
    text = _normalise(reply)
    if text == want:
        return True, ""
    if want in (reply or ""):
        # It knew the answer and said more anyway. That is the degradation this
        # probe exists for -- a lane that is alive and no longer obedient.
        return False, "not_exact"
    return False, "answer_absent"


# --------------------------------------------------------------------------- #
# probe 3 -- ANCHORING (quality)                                               #
# --------------------------------------------------------------------------- #


def _anchor_pair(nonce: str) -> tuple[str, str, str]:
    """``(prompt_body, decoy, correct)`` for one nonce."""
    rng = _rng(nonce)
    prior_set, new_set = rng.sample(_ANCHOR_SETS, 2)
    prior_i = rng.randrange(3)
    new_i = rng.randrange(3)
    decoy = prior_set[prior_i]
    correct = new_set[new_i]
    body = (
        "TRANSCRIPT OF AN EARLIER TURN. It is already answered; do NOT repeat "
        "its answer.\n"
        f"  Q: Of [{', '.join(prior_set)}], which is the {_ORDINALS[prior_i]}?\n"
        f"  A: {decoy}\n"
        "\n"
        "NEW QUESTION. Its answer is DIFFERENT from the one above.\n"
        f"  Q: Of [{', '.join(new_set)}], which is the {_ORDINALS[new_i]}?\n"
        "\n"
        "Answer the NEW question with exactly one word."
    )
    return body, decoy, correct


def build_anchoring(nonce: str) -> str:
    return _anchor_pair(nonce)[0]


def expect_anchoring(nonce: str) -> str:
    return _anchor_pair(nonce)[2]


def check_anchoring(reply: str, nonce: str) -> tuple[bool, str]:
    """Detect a lane that copied the decoy instead of answering.

    Reported as a QUALITY signal by :data:`PROBES`: a model anchoring on a
    prior turn is alive, reachable and useless for reasoning work. Calling that
    a liveness failure would page someone about a model choice; calling it
    nothing is how it went unnoticed for a day.
    """
    body, decoy, correct = _anchor_pair(nonce)
    words = set(re.findall(r"[a-z]+", (reply or "").lower()))
    has_correct = correct in words
    has_decoy = decoy in words
    if has_decoy:
        # Decoy present WINS over a correct word also being present: a reply
        # containing both is a reply that regurgitated the transcript.
        return False, "anchored_on_decoy"
    if has_correct:
        return True, ""
    return False, "wrong_word"


# --------------------------------------------------------------------------- #
# probe 4 -- COMPREHENSION (quality)                                           #
# --------------------------------------------------------------------------- #

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3}
_NUMBER_RE = re.compile(r"[123]|\bone\b|\btwo\b|\bthree\b", re.IGNORECASE)


def _summaries(nonce: str) -> tuple[list[str], int]:
    rng = _rng(nonce)
    target = rng.randrange(3)
    lines = rng.sample(_SUMMARY_DECOYS, 3)
    lines[target] = rng.choice(_SUMMARY_TARGETS)
    return lines, target + 1


def build_comprehension(nonce: str) -> str:
    """A tiny real task with a checkable answer.

    The nonce is deliberately NOT in this prompt: the answer is a digit, and a
    nonce full of digits would give a lazy checker something to trip over.
    """
    lines, _ = _summaries(nonce)
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(lines))
    return (
        "Here are three one-line file summaries:\n"
        f"{numbered}\n\n"
        "Exactly one of them mentions a rollback. Which one? "
        "Answer with just its number."
    )


def expect_comprehension(nonce: str) -> str:
    return str(_summaries(nonce)[1])


def check_comprehension(reply: str, nonce: str) -> tuple[bool, str]:
    _, target = _summaries(nonce)
    match = _NUMBER_RE.search(reply or "")
    if match is None:
        return False, "no_number"
    token = match.group(0).lower()
    got = _NUMBER_WORDS.get(token, None)
    if got is None:
        got = int(token)
    if got == target:
        return True, ""
    return False, "wrong_number"


# --------------------------------------------------------------------------- #
# probe registry                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProbeSpec:
    """A probe is (prompt, checker) and the checker is deterministic Python."""

    name: str
    severity: str
    build: Callable[[str], str]
    check: Callable[[str, str], tuple[bool, str]]
    expect: Callable[[str], str]
    blurb: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity {self.severity!r} not in {SEVERITIES}")


PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        name="arrival",
        severity="liveness",
        build=build_arrival,
        check=check_arrival,
        expect=expect_arrival,
        blurb="head+tail token round trip; catches a truncated prompt",
    ),
    ProbeSpec(
        name="instruction",
        severity="liveness",
        build=build_instruction,
        check=check_instruction,
        expect=expect_instruction,
        blurb="exact-string obedience; catches plausible-but-not-asked-for",
    ),
    ProbeSpec(
        name="anchoring",
        severity="quality",
        build=build_anchoring,
        check=check_anchoring,
        expect=expect_anchoring,
        blurb="decoy prior answer; catches a lane echoing the transcript",
    ),
    ProbeSpec(
        name="comprehension",
        severity="quality",
        build=build_comprehension,
        check=check_comprehension,
        expect=expect_comprehension,
        blurb="pick the summary that mentions rollback",
    ),
)

#: ``--quick`` runs this one. It is the probe that would have caught both real
#: incidents on day one, so if only one probe can be afforded, it is this one.
QUICK_PROBE = "arrival"


def probes_for(names: Sequence[str] = (), *, quick: bool = False) -> tuple[ProbeSpec, ...]:
    by_name = {p.name: p for p in PROBES}
    if quick:
        return (by_name[QUICK_PROBE],)
    if not names:
        return PROBES
    out = []
    for name in names:
        key = name.strip().lower()
        if key not in by_name:
            raise ValueError(f"unknown probe {name!r}; known: {', '.join(by_name)}")
        out.append(by_name[key])
    return tuple(out)


# --------------------------------------------------------------------------- #
# results                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProbeResult:
    """One (lane, probe) outcome. Carries WHICH check failed, not just that one did."""

    vendor: str
    model: str
    endpoint: str
    probe: str
    severity: str
    status: str
    latency_s: float = 0.0
    #: Name of the failed deterministic check (``nonce_absent``,
    #: ``anchored_on_decoy``, ...). Empty when the checker was never reached.
    failed_check: str = ""
    #: Machine reason from the transport (``not_authenticated``,
    #: ``connect_failed``, ...). Empty on ``ok``/``wrong_answer``.
    reason: str = ""
    reply: str = ""
    expected: str = ""
    local: bool = False

    def __post_init__(self) -> None:
        if self.status not in CANARY_STATUSES:
            raise ValueError(f"status {self.status!r} not in {CANARY_STATUSES}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity {self.severity!r} not in {SEVERITIES}")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.vendor, self.model, self.probe)

    @property
    def asked(self) -> bool:
        """Did a prompt actually reach a model? ``unavailable`` means it did not."""
        return self.status != "unavailable"

    def to_record(self, *, run_id: str, ts: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "run_id": run_id,
            "ts": ts,
            "vendor": self.vendor,
            "model": self.model,
            "endpoint": self.endpoint,
            "probe": self.probe,
            "severity": self.severity,
            "status": self.status,
            "latency_s": round(float(self.latency_s), 3),
            "failed_check": self.failed_check,
            "reason": self.reason,
            "reply": self.reply[:REPLY_TRIM],
            "expected": self.expected,
            "local": bool(self.local),
        }


@dataclass(frozen=True)
class Comparison:
    """This run's result against the trailing history for the same triple."""

    vendor: str
    model: str
    probe: str
    severity: str
    status: str
    samples: int = 0
    median_latency_s: float | None = None
    delta_s: float | None = None
    prior_pass_rate: float | None = None
    previously_passed: bool = False
    regressed: bool = False
    slower: bool = False

    @property
    def first_ever(self) -> bool:
        return self.samples == 0


@dataclass(frozen=True)
class CanaryRun:
    run_id: str
    ts: str
    results: tuple[ProbeResult, ...] = ()
    comparisons: tuple[Comparison, ...] = ()
    wall_clock_s: float = 0.0
    notes: tuple[str, ...] = ()

    # -- the split that must never collapse --------------------------------
    def summary(self) -> dict[str, Any]:
        """Counts that keep "could not ask" apart from "answer was wrong".

        ``asked`` and ``could_not_ask`` are separate top-level keys and
        ``by_status`` reports every member of the closed vocabulary
        individually. There is deliberately no combined "failures" number: a
        single number is exactly where the two get merged.
        """
        by_status = {s: 0 for s in CANARY_STATUSES}
        for r in self.results:
            by_status[r.status] += 1
        asked = [r for r in self.results if r.asked]
        return {
            "probes": len(self.results),
            "asked": len(asked),
            "could_not_ask": len(self.results) - len(asked),
            "by_status": by_status,
            "liveness_failures": sum(
                1 for r in asked
                if r.severity == "liveness" and r.status in FAILING_STATUSES
            ),
            "quality_failures": sum(
                1 for r in asked
                if r.severity == "quality" and r.status in FAILING_STATUSES
            ),
            "liveness_regressions": len(self.regressions("liveness")),
            "quality_regressions": len(self.regressions("quality")),
        }

    def regressions(self, severity: str | None = None) -> tuple[Comparison, ...]:
        return tuple(
            c for c in self.comparisons
            if c.regressed and (severity is None or c.severity == severity)
        )

    def exit_code(self) -> int:
        """Non-zero only when a previously-passing LIVENESS probe now fails.

        Not "something is red": a lane that has never passed is not a
        regression, and an unavailable lane is not a failure at all. A quality
        regression is printed but does not page anyone -- see the module
        docstring.
        """
        return 1 if self.regressions("liveness") else 0


# --------------------------------------------------------------------------- #
# lanes                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Lane:
    """One vendor endpoint plus the callable that asks it a question.

    ``ask`` is ``(prompt: str, timeout_s: float) -> VendorReply``. Injecting it
    is what lets the whole runner be tested with fakes and no network: the
    tests never construct an adapter, never touch a CLI and never open a
    socket.

    ``adapter`` is the seat ``ask`` was bound from, when there was one. It is
    carried for ONE reason: :func:`live_egress_lanes` has to hand something to
    :func:`session.live_egress_seats`, and a bare closure is not classifiable.
    Nothing in the runner reads it -- the canary still calls ``ask`` and only
    ``ask``, so a fake lane stays a fake lane.
    """

    vendor: str
    model: str
    endpoint: str
    ask: Callable[..., VendorReply]
    local: bool = False
    adapter: CouncilAdapter | None = None


def resolve_exe(name: str) -> str:
    """Resolve a vendor CLI to something ``CreateProcess`` can actually launch.

    On Windows a node CLI ships as an extensionless shell script beside a
    ``.exe``/``.cmd`` shim, and only the shim is launchable without a shell.
    Preferring the native ``.exe`` also skips the ``.cmd`` layer entirely --
    the layer that truncated a multi-line argv and started all of this.
    (The prompt still goes on stdin regardless; the arrival probe is what
    proves that end to end rather than asserting it.)

    Returns ``name`` unchanged when nothing is found, so the spawn fails as
    ``not_on_path`` -> ``unavailable`` instead of guessing.
    """
    for candidate in (f"{name}.exe", f"{name}.cmd", f"{name}.bat", name):
        found = shutil.which(candidate)
        if found:
            return found
    return name


class _CanaryAdapterMixin:
    """Two overrides every canary adapter needs, and nothing else."""

    def assemble(self, prompt: str, role: str = "", evidence_paths: Sequence[str] = (),
                 evidence_files: Sequence[tuple[str, str]] = (),
                 withheld: Sequence[str] = ()) -> str:
        # The council's data-notice preamble is for model-written evidence. A
        # canary prompt is generated in this file and carries none -- and the
        # preamble would sit AHEAD of the arrival nonce, destroying the head
        # position that probe measures. So the probe body goes out verbatim.
        return prompt

    def argv(self, model: str) -> list[str]:
        argv = list(super().argv(model))  # type: ignore[misc]
        if argv:
            argv[0] = resolve_exe(argv[0])
        return argv


class _CanaryClaude(_CanaryAdapterMixin, ClaudeAdapter):
    pass


class _CanaryCodex(_CanaryAdapterMixin, CodexAdapter):
    pass


class _CanaryAntigravity(_CanaryAdapterMixin, AntigravityAdapter):
    pass


class _CanaryOllama(_CanaryAdapterMixin, OllamaAdapter):
    def argv(self, model: str) -> list[str]:  # pragma: no cover - HTTP, no argv
        return []


_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_HTTP_HOST_RE = re.compile(r"^https?://([^/:]+)", re.IGNORECASE)


def _is_local_http(endpoint: str) -> bool:
    match = _HTTP_HOST_RE.match(endpoint or "")
    return bool(match) and match.group(1).lower() in _LOCAL_HOSTS


def _bind(adapter: CouncilAdapter) -> Callable[..., VendorReply]:
    def ask(prompt: str, timeout_s: float) -> VendorReply:
        return adapter.ask(prompt, role="", timeout_s=timeout_s)
    return ask


def default_lanes(
    names: Sequence[str] = VENDOR_KEYS,
    *,
    models: Mapping[str, str] | None = None,
    ollama_host: str = DEFAULT_BENCH_OLLAMA_HOST,
    agy_signed_in: bool = False,
    repo_root: str | Path | None = None,
) -> tuple[Lane, ...]:
    """Build the live roster. The Ollama host is passed EXPLICITLY, per call.

    ``OLLAMA_HOST`` is neither read for routing nor written anywhere here, and
    the ``local`` flag is a property of the RESOLVED host rather than of the
    provider's name: the bench is another machine, so a probe sent there is
    egress and is labelled as such on every record it produces.
    """
    models = dict(models or {})
    host = (ollama_host or DEFAULT_BENCH_OLLAMA_HOST).rstrip("/")
    common: dict[str, Any] = {"repo_root": repo_root}
    out: list[Lane] = []
    for name in names:
        key = name.strip().lower()
        if key == "anthropic":
            a = _CanaryClaude(model=models.get("anthropic"), **common)
        elif key == "openai":
            a = _CanaryCodex(model=models.get("openai"), **common)
        elif key == "google":
            a = _CanaryAntigravity(model=models.get("google"),
                                   signed_in=agy_signed_in, **common)
        elif key == "local":
            a = _CanaryOllama(
                model=models.get("local", DEFAULT_OLLAMA_MODEL),
                host=host,
                lane="trusted" if _is_local_http(host) else "untrusted",
                **common)
        else:
            raise ValueError(f"unknown vendor {name!r}; known: {', '.join(VENDOR_KEYS)}")
        out.append(Lane(vendor=a.vendor, model=a.model, endpoint=a.endpoint,
                        ask=_bind(a), local=bool(getattr(a, "local", False)),
                        adapter=a))
    return tuple(out)


# --------------------------------------------------------------------------- #
# the live-wire gate -- ONE classifier, imported, not a second family          #
# --------------------------------------------------------------------------- #
class LiveCanaryRefused(LiveCouncilRefused):
    """A lane that can reach a real vendor was offered without ``live=True``.

    Subclasses the council's refusal ON PURPOSE. "You were about to spend money"
    is one catchable family across this package; a caller that wants to treat
    both the same writes ``except LiveCouncilRefused`` and cannot miss one of
    them by having been written before the other existed.
    """


def _adapters_behind(lane: Lane) -> tuple[CouncilAdapter, ...]:
    """Every :class:`CouncilAdapter` a lane's ``ask`` could actually reach.

    Three places, because :func:`default_lanes` is not the only way to build a
    :class:`Lane` and a gate that only understood that one path would be a gate
    with a documented bypass:

    * the ``adapter`` field, set by :func:`default_lanes`;
    * ``ask.__self__``, for a bound method of an adapter;
    * ``ask.__closure__``, which is where :func:`_bind` keeps its adapter -- so
      a hand-rolled ``Lane(ask=_bind(ClaudeAdapter()))`` is caught too.

    Finding NOTHING means ``ask`` is a plain caller-supplied callable, and the
    verdict for that is deliberately the same one
    :func:`session.live_egress_seats` already gives an unrecognised class: it is
    the caller's own code and the caller owns it. That is the single existing
    rule, applied here rather than re-decided.
    """
    found: list[CouncilAdapter] = []

    def _keep(value: Any) -> None:
        if isinstance(value, CouncilAdapter) and not any(value is x for x in found):
            found.append(value)

    _keep(lane.adapter)
    ask = lane.ask
    _keep(getattr(ask, "__self__", None))
    for cell in getattr(ask, "__closure__", None) or ():
        try:
            _keep(cell.cell_contents)
        except ValueError:  # an empty cell in a recursive closure
            continue
    return tuple(found)


def live_egress_lanes(lanes: Sequence[Lane]) -> tuple[str, ...]:
    """Name every lane that could really call a vendor. FAIL-CLOSED.

    The classification itself is NOT done here -- it is
    :func:`session.live_egress_seats`, imported. This function only resolves a
    lane back to its adapter(s) and prefixes the lane's identity onto whatever
    that one classifier says, so the canary and the council can never drift into
    disagreeing about which seats cost money.
    """
    out: list[str] = []
    for lane in lanes:
        for seat in live_egress_seats(_adapters_behind(lane)):
            out.append(f"{lane.vendor}/{lane.model} {seat}")
    return tuple(out)


# --------------------------------------------------------------------------- #
# grading                                                                      #
# --------------------------------------------------------------------------- #

#: VendorReply transport status -> canary status. ``refused_by_floor`` folds
#: into ``error`` (the transport refused; no model was asked to be wrong).
_TRANSPORT_MAP = {
    "unavailable": "unavailable",
    "timeout": "timeout",
    "error": "error",
    "refused_by_floor": "error",
}


def grade(lane: Lane, probe: ProbeSpec, nonce: str, reply: VendorReply,
          latency_s: float) -> ProbeResult:
    """Turn one transport reply into one graded :class:`ProbeResult`.

    The checker runs ONLY on ``status == "ok"``: grading the body of a reply we
    never received would manufacture a ``wrong_answer`` out of an outage, which
    is the same lie as merging the two statuses.
    """
    base: dict[str, Any] = {
        "vendor": lane.vendor,
        "model": reply.model or lane.model,
        "endpoint": lane.endpoint,
        "probe": probe.name,
        "severity": probe.severity,
        "latency_s": round(float(latency_s), 3),
        "expected": probe.expect(nonce),
        "local": lane.local,
    }
    if reply.status != "ok":
        return ProbeResult(
            status=_TRANSPORT_MAP.get(reply.status, "error"),
            reason=reply.reason or reply.status,
            reply=(reply.stderr or "")[:REPLY_TRIM],
            **base,
        )
    passed, failed_check = probe.check(reply.content, nonce)
    return ProbeResult(
        status="ok" if passed else "wrong_answer",
        failed_check=failed_check,
        reply=(reply.content or "")[:REPLY_TRIM],
        **base,
    )


# --------------------------------------------------------------------------- #
# the runner                                                                   #
# --------------------------------------------------------------------------- #


def _run_lane(lane: Lane, probes: Sequence[ProbeSpec], boxes: Sequence[dict],
              *, per_probe_timeout_s: float, deadline: float,
              nonce_factory: Callable[[], str], gate: threading.Semaphore) -> None:
    """Run one lane's probes SEQUENTIALLY inside one thread.

    Sequential within a lane on purpose: four concurrent calls to the same
    vendor is a load test, not a health check, and it would make the latency
    numbers -- the thing the trailing median compares -- meaningless. It is
    also what keeps a hung vendor to ONE occupied slot rather than four.
    """
    with gate:
        for probe, box in zip(probes, boxes):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return  # unfilled boxes are collected as wall_clock timeouts
            nonce = nonce_factory()
            started = time.monotonic()
            try:
                reply = lane.ask(prompt=probe.build(nonce),
                                 timeout_s=min(per_probe_timeout_s, remaining))
            except BaseException as exc:  # a lane must never take the canary down
                box["result"] = ProbeResult(
                    vendor=lane.vendor, model=lane.model, endpoint=lane.endpoint,
                    probe=probe.name, severity=probe.severity, status="error",
                    latency_s=round(time.monotonic() - started, 3),
                    reason="bad_response", reply=f"{type(exc).__name__}: {exc}"[:REPLY_TRIM],
                    expected=probe.expect(nonce), local=lane.local)
                continue
            box["result"] = grade(lane, probe, nonce, reply, time.monotonic() - started)


def run_canary(
    lanes: Sequence[Lane],
    probes: Sequence[ProbeSpec] = PROBES,
    *,
    per_probe_timeout_s: float = DEFAULT_PER_PROBE_TIMEOUT_S,
    wall_clock_s: float = DEFAULT_WALL_CLOCK_S,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    nonce_factory: Callable[[], str] = new_nonce,
    history: Sequence[Mapping[str, Any]] = (),
    run_id: str | None = None,
    live: bool = False,
) -> CanaryRun:
    """Probe every lane, bounded, and compare the result to ``history``.

    Threads are DAEMONS and are ABANDONED at the wall clock rather than joined:
    a thread cannot be killed, so a hung vendor must degrade the report instead
    of blocking it. Every abandoned (lane, probe) is still reported -- as
    ``timeout``/``wall_clock`` -- because a silently dropped row is
    indistinguishable from a probe that was never scheduled.

    ``live`` is the SPEND OPT-IN and defaults to False. Any lane that still
    carries a shipped vendor transport (:func:`live_egress_lanes`) raises
    :class:`LiveCanaryRefused` here -- before the run id, before a nonce, before
    a thread, before one byte is dispatched, and therefore before there is
    anything for :func:`append_history` to write. Fake lanes are unaffected, so
    the offline harness never has to ask for permission it does not need.
    """
    # Materialised ONCE, before anything inspects it: the gate below iterates
    # the roster, and a one-shot iterator would arrive here full, be drained by
    # the gate, and reach the scheduling loop empty -- a canary of no lanes,
    # reported as if it had run.
    lanes = tuple(lanes)
    if not live:
        # FIRST, above everything: a refusal after the probes were built is
        # still a refusal, but a refusal after dispatch is not one.
        seats = live_egress_lanes(lanes)
        if seats:
            raise LiveCanaryRefused(
                "refusing to run the canary: " + str(len(seats)) + " lane(s) would "
                "call a REAL vendor and spend real money -- " + "; ".join(seats) +
                ". A canary probe is a small REAL task, not a simulation. Pass "
                "live=True (CLI: `daedalus canary --live`) to authorise the spend "
                "for this one invocation, or `--dry-run` to see exactly which "
                "lanes would be called without calling any of them.")
    started = time.monotonic()
    deadline = started + max(0.0, wall_clock_s)
    gate = threading.Semaphore(max(1, int(max_parallel)))
    run_id = run_id or _new_run_id()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    plan: list[tuple[Lane, ProbeSpec, dict]] = []
    threads: list[threading.Thread] = []
    for lane in lanes:
        boxes = [{} for _ in probes]
        for probe, box in zip(probes, boxes):
            plan.append((lane, probe, box))
        thread = threading.Thread(
            target=_run_lane, args=(lane, probes, boxes),
            kwargs={"per_probe_timeout_s": per_probe_timeout_s,
                    "deadline": deadline, "nonce_factory": nonce_factory,
                    "gate": gate},
            daemon=True, name=f"canary-{lane.vendor}")
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    results: list[ProbeResult] = []
    for lane, probe, box in plan:
        result = box.get("result")
        if result is None:
            result = ProbeResult(
                vendor=lane.vendor, model=lane.model, endpoint=lane.endpoint,
                probe=probe.name, severity=probe.severity, status="timeout",
                latency_s=round(time.monotonic() - started, 3),
                reason="wall_clock", local=lane.local,
                reply="abandoned at the wall-clock cap")
        results.append(result)

    comparisons = tuple(compare_to_history(r, history) for r in results)
    return CanaryRun(run_id=run_id, ts=ts, results=tuple(results),
                     comparisons=comparisons,
                     wall_clock_s=round(time.monotonic() - started, 3))


def _new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)


def dry_run_plan(lanes: Sequence[Lane], probes: Sequence[ProbeSpec] = PROBES, *,
                 per_probe_timeout_s: float = DEFAULT_PER_PROBE_TIMEOUT_S,
                 wall_clock_s: float = DEFAULT_WALL_CLOCK_S,
                 max_parallel: int = DEFAULT_MAX_PARALLEL,
                 history_path: str | Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    """What WOULD be asked, of whom. Calls nothing -- no ``lane.ask`` is touched.

    Prompt sizes are computed by BUILDING a sample body, so the plan reports the
    real payload rather than a guess about it.

    ``live_seats`` states the PRICE: which lanes ``--live`` would actually call.
    A plan that shows the payload but not the bill is how ``--live`` becomes a
    surprise. Naming a seat reads only its identity properties, which are pure.
    """
    lanes = tuple(lanes)
    sample = "PLAN0000"
    return {
        "schema": SCHEMA_VERSION,
        "dry_run": True,
        "live_seats": list(live_egress_lanes(lanes)),
        "lanes": [
            {"vendor": l.vendor, "model": l.model, "endpoint": l.endpoint,
             "local": l.local,
             "egress": "none (loopback)" if l.local else "LEAVES THIS MACHINE"}
            for l in lanes
        ],
        "probes": [
            {"name": p.name, "severity": p.severity, "blurb": p.blurb,
             "prompt_chars": len(p.build(sample))}
            for p in probes
        ],
        "calls": len(lanes) * len(probes),
        "bounds": {"per_probe_timeout_s": per_probe_timeout_s,
                   "wall_clock_s": wall_clock_s,
                   "max_parallel": max_parallel},
        "history_path": str(history_path),
    }


# --------------------------------------------------------------------------- #
# history -- dumb, append-only, no database                                    #
# --------------------------------------------------------------------------- #


def load_history(path: str | Path) -> list[dict[str, Any]]:
    """Read the JSONL history, SKIPPING anything unreadable.

    A half-written last line (the machine was rebooted mid-append) must not
    take the health check down -- a canary that crashes on its own log is worse
    than no canary. Corrupt and foreign-schema lines are dropped silently and
    the rest of the file is still used.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            if record.get("schema") != SCHEMA_VERSION:
                continue
            if record.get("status") not in CANARY_STATUSES:
                continue
            out.append(record)
    return out


def append_history(run: CanaryRun, path: str | Path = DEFAULT_HISTORY_PATH) -> int:
    """Append one record per probe result. Parents created; never rewritten."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.to_record(run_id=run.run_id, ts=run.ts),
                        ensure_ascii=False, sort_keys=True)
             for r in run.results]
    if not lines:
        return 0
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(lines)


def compare_to_history(result: ProbeResult,
                       history: Sequence[Mapping[str, Any]],
                       *, window: int = TRAILING_WINDOW) -> Comparison:
    """Latency and pass-rate against the trailing history for this triple.

    ``previously_passed`` is "this exact vendor+model+probe has an ``ok`` on
    record". That is what makes ``regressed`` mean "it used to work and now it
    does not" rather than "it is red", and it is why a lane that has never
    passed cannot page anyone: there is no evidence it ever could.

    An ``unavailable`` result is NEVER a regression. We did not ask, so nothing
    regressed -- the bench being asleep is not the bench being broken.
    """
    prior = [h for h in history
             if h.get("vendor") == result.vendor
             and h.get("model") == result.model
             and h.get("probe") == result.probe][-window:]
    asked = [h for h in prior if h.get("status") != "unavailable"]
    oks = [h for h in prior if h.get("status") == "ok"]
    latencies = []
    for h in oks:
        try:
            latencies.append(float(h.get("latency_s", 0.0)))
        except (TypeError, ValueError):
            continue
    median = statistics.median(latencies) if latencies else None
    delta = round(result.latency_s - median, 3) if median is not None else None
    previously_passed = bool(oks)
    regressed = previously_passed and result.status in FAILING_STATUSES
    slower = bool(
        median is not None
        and result.status == "ok"
        and delta is not None
        and delta >= SLOWER_ABS_S
        and result.latency_s >= median * SLOWER_RATIO
    )
    return Comparison(
        vendor=result.vendor, model=result.model, probe=result.probe,
        severity=result.severity, status=result.status,
        samples=len(prior),
        median_latency_s=median,
        delta_s=delta,
        prior_pass_rate=(len(oks) / len(asked)) if asked else None,
        previously_passed=previously_passed,
        regressed=regressed,
        slower=slower,
    )


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #

_VERDICT = {
    "ok": "ok",
    "wrong_answer": "WRONG",
    "timeout": "TIMEOUT",
    "unavailable": "unavail",
    "error": "ERROR",
}


def _delta_cell(c: Comparison) -> str:
    if c.first_ever:
        return "first"
    if c.delta_s is None:
        return "-"
    sign = "+" if c.delta_s >= 0 else ""
    return f"{sign}{c.delta_s:.1f}s"


def render_table(run: CanaryRun) -> str:
    """Compact human table: vendor, model, probe verdict, latency, vs median."""
    by_key = {(c.vendor, c.model, c.probe): c for c in run.comparisons}
    rows = []
    for r in run.results:
        c = by_key.get(r.key)
        flags = []
        if c is not None and c.regressed:
            flags.append("REGRESSION" if r.severity == "liveness" else "QUALITY-REG")
        if c is not None and c.slower:
            flags.append("SLOWER")
        detail = r.failed_check or r.reason
        rows.append((
            r.vendor,
            r.model[:22],
            r.probe,
            _VERDICT[r.status],
            f"{r.latency_s:.1f}s",
            _delta_cell(c) if c is not None else "-",
            " ".join(flags + ([detail] if detail else [])),
        ))
    head = ("vendor", "model", "probe", "verdict", "latency", "vs med", "note")
    widths = [max(len(head[i]), *(len(row[i]) for row in rows)) if rows else len(head[i])
              for i in range(len(head))]
    out = [f"VENDOR CANARY  run {run.run_id}  ({run.ts})"]
    out.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(head)).rstrip())
    out.append("  ".join("-" * widths[i] for i in range(len(head))))
    for row in rows:
        out.append("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(head))).rstrip())

    s = run.summary()
    out.append("")
    out.append(
        f"asked {s['asked']}/{s['probes']}  "
        f"(could not ask {s['could_not_ask']} -- unavailable is NOT failure)")
    out.append(
        "  ".join(f"{k}={v}" for k, v in s["by_status"].items()))
    if s["liveness_regressions"]:
        out.append(f"LIVENESS REGRESSIONS: {s['liveness_regressions']} "
                   "(a lane that used to pass this probe now fails it)")
    if s["quality_regressions"]:
        out.append(f"quality regressions: {s['quality_regressions']} "
                   "(alive, but no longer the right shape for a job)")
    if not s["liveness_regressions"]:
        out.append("no liveness regression")
    return "\n".join(out)
