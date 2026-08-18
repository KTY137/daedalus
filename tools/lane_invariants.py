"""Assertions over a recorded lane run. Deterministic, free, exact.

Layer 2 of the observation stack: **flight recorder -> invariants -> model.**

Every check here corresponds to a failure that actually happened on 2026-07-30
and was INVISIBLE at the time. An audit fan-out sent 169 modules to an external
lane, got 715 usable answers, and produced 2 findings. Every cause was
arithmetic, and none of it was being computed:

    votes byte-identical              -> len(set(hashes)) == 1
    the unit's source sent twice      -> substring test
    148 answers were one template     -> structural comparison
    `status` constant across 715      -> len(set(...)) == 1
    system prompt vs question         -> keyword conflict
    a refusal counted as an answer    -> status partition

The reason this is a script and not a fleet of agents is measured, twice. On 29
July, 8 model refuters produced 0 usable findings while two AST functions of ~40
lines caught 3 of 3 destructions with 0 false positives across 336 files. On 30
July, 715 model answers produced 2 findings while 2 focused agents produced more
than ten. A cheap model reading a log and *believing* the votes look similar is
strictly worse than a hash comparison that knows.

What this deliberately does NOT check: whether an answer is any good. "Does this
engage with the code or is it fluent nothing?" is not expressible as an
assertion, it is the one question worth paying a model for, and it is layer 3.

    python tools/lane_invariants.py runs/audit_swarm
    python tools/lane_invariants.py runs/audit_swarm --json report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: Phrases in a system prompt that suppress the multi-step comparison a review
#: task needs. MEASURED: `token_policy.STATIC_PROMPT_PREFIX` carries
#: "Do not include chain-of-thought; include only conclusions and evidence" and
#: "Minimize tokens", and it is prepended to every advisory call by
#: `providers/_report.py::build_prompt`. Correct for the bridge protocol it was
#: written for; fatal for an audit, because finding a docstring that contradicts
#: its code IS a comparison and the scratchpad is where a comparison happens.
_SUPPRESSORS = (
    "do not include chain-of-thought",
    "minimize tokens",
    "short summaries",
    "no conversational",
)

#: Phrases in a QUESTION that demand the reasoning the suppressors forbid. When
#: both sets fire on one request, the request contradicts itself and the
#: higher-authority message wins -- which is the system one.
_DEMANDS = (
    "enumerate", "for each", "step 1", "compare", "every claim",
    "one line per", "in the order you found",
)


@dataclass
class Violation:
    check: str
    severity: str            # "blocking" | "serious" | "note"
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "severity": self.severity,
                "detail": self.detail, "evidence": self.evidence[:8]}


def _load(in_dir: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(in_dir.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _answer_shape(rep: dict[str, Any]) -> str:
    """A structural fingerprint: which fields are populated, not what is in them.

    This is how a template completion is caught. 148 answers had identical shape
    -- status set, summary set, every list empty -- which is precisely the worked
    example in the system prompt with one slot filled. Comparing CONTENT would
    have missed it, because the one filled slot differed.
    """
    def filled(k: str) -> str:
        v = rep.get(k)
        if isinstance(v, (list, dict)):
            return "1" if v else "0"
        return "1" if (isinstance(v, str) and v.strip()) else "0"
    return "".join(filled(k) for k in
                   ("status", "summary", "files_changed", "tests_run",
                    "risks", "todos", "handoff"))


def check(results: list[dict[str, Any]]) -> tuple[list[Violation], dict[str, Any]]:
    v: list[Violation] = []
    stats: dict[str, Any] = {}

    answers: list[tuple[str, int, dict[str, Any]]] = []   # (task_id, vote, answer)
    for r in results:
        for a in r.get("answers") or []:
            answers.append((r.get("task_id", "?"), a.get("vote", 0), a))
    stats["units"] = len(results)
    stats["answers"] = len(answers)
    if not answers:
        v.append(Violation("no_data", "blocking",
                           "no answers recorded; nothing can be checked"))
        return v, stats

    recorded = [a for _, _, a in answers if a.get("sent")]
    stats["answers_with_flight_recorder"] = len(recorded)
    if not recorded:
        v.append(Violation(
            "no_flight_recorder", "blocking",
            "no answer records what was SENT, so every check below that needs "
            "the request is unavailable. This is the gap that made the "
            "2026-07-30 failures invisible: results without requests can only "
            "be debugged by re-deriving the request.",
            [f"{len(answers)} answers, 0 with a 'sent' block"]))

    # ---- 1. are multi-vote units actually independent? ---------------------
    identical_units: list[str] = []
    multi = 0
    for r in results:
        ans = r.get("answers") or []
        if len(ans) < 2:
            continue
        multi += 1
        digests = {hashlib.sha256(
            json.dumps(a.get("report"), sort_keys=True, default=str)
            .encode("utf-8")).hexdigest() for a in ans}
        if len(digests) == 1:
            identical_units.append(r.get("task_id", "?"))
    stats["multi_vote_units"] = multi
    stats["units_whose_votes_are_identical"] = len(identical_units)
    # THRESHOLD, not equality. It was `== multi` and the first real corpus came
    # in at 242 of 246 -- 98.4% identical, which fell through to a "note" and
    # would have been read past. A check whose bar is "every single one" is a
    # check that a single trivially-varying unit disables, and this one is
    # reporting the difference between corroboration and a decoder artifact.
    if multi and len(identical_units) / multi > 0.5:
        temps = {a.get("sent", {}).get("temperature") for a in recorded}
        v.append(Violation(
            "votes_are_not_independent", "blocking",
            f"{len(identical_units)} of {multi} multi-vote unit(s) returned "
            f"byte-identical reports across every vote. Recorded temperature(s): "
            f"{sorted(t for t in temps if t is not None) or 'unrecorded'}. "
            "N samples of one prompt at temperature 0 are ONE sample counted N "
            "times, so the vote count is a cost multiplier and any 'unanimous' "
            "agreement is an artifact of the decoder, not corroboration.",
            identical_units[:6]))
    elif identical_units:
        v.append(Violation(
            "some_votes_identical", "note",
            f"{len(identical_units)} of {multi} multi-vote units returned "
            "identical reports across votes -- expected for trivial units, "
            "suspicious if it is most of them.", identical_units[:6]))

    # ---- 2. is the answer set actually varied, or one template? -----------
    shapes = Counter(_answer_shape(a.get("report") or {}) for _, _, a in answers)
    top_shape, top_n = shapes.most_common(1)[0]
    stats["distinct_answer_shapes"] = len(shapes)
    stats["most_common_shape_share"] = round(top_n / len(answers), 3)
    if top_n / len(answers) > 0.8 and len(answers) > 20:
        v.append(Violation(
            "answers_are_one_template", "blocking",
            f"{top_n} of {len(answers)} answers share the field-population "
            f"pattern '{top_shape}' (1=populated, in order status, summary, "
            "files_changed, tests_run, risks, todos, handoff). A lane whose "
            "answers all have the same SHAPE is completing a template, not "
            "answering a question -- check whether the shape matches the worked "
            "example in the system prompt.",
            [f"shape {s} x{n}" for s, n in shapes.most_common(4)]))

    # ---- 3. does any field carry zero bits? -------------------------------
    for field_name in ("status",):
        vals = Counter(str((a.get("report") or {}).get(field_name))
                       for _, _, a in answers)
        if len(vals) == 1 and len(answers) > 20:
            v.append(Violation(
                f"{field_name}_carries_no_information", "serious",
                f"'{field_name}' is '{next(iter(vals))}' in all "
                f"{len(answers)} answers. A field the model never varies is "
                "either a hardcoded default it did not choose or a value it was "
                "shown -- either way every consumer reading it as a verdict is "
                "reading a constant.", [f"{k} x{n}" for k, n in vals.items()]))

    # ---- 4. was a refusal counted as an answer? ---------------------------
    blocked = [(t, a) for t, _, a in answers
               if ((a.get("report") or {}).get("status")) == "blocked"]
    stats["answers_blocked"] = len(blocked)
    if blocked:
        v.append(Violation(
            "refusals_land_as_answers", "serious",
            f"{len(blocked)} answer(s) are refusals (status='blocked') and are "
            "stored in the same 'answers' array as real results. A unit with "
            "only refusals therefore counts as OK, is never retried by resume, "
            "and reads as clean in any aggregate. A blocked unit is OWED to "
            "another lane, not audited.",
            [t for t, _ in blocked[:6]]))
        unattributed = [t for t, a in blocked
                        if not ((a.get("report") or {}).get("handoff") or {}).get("offending")]
        if unattributed:
            v.append(Violation(
                "refusals_are_unattributable", "serious",
                f"{len(unattributed)} refusal(s) name nothing in "
                "handoff.offending, so an operator cannot tell WHICH line "
                "triggered the fence. A refusal nobody can locate is a refusal "
                "nobody can act on or dispute.",
                unattributed[:6]))

    # ---- 5. was the unit's own source sent twice? -------------------------
    dupes = [t for t, _, a in answers
             if (a.get("sent") or {}).get("paths")]
    if dupes:
        v.append(Violation(
            "source_may_be_sent_twice", "serious",
            f"{len(set(dupes))} unit(s) declared 'paths', which makes the "
            "provider re-read those files from disk and append them as "
            "'Context (read-only excerpts)' truncated at MAX_CONTEXT_CHARS "
            "(24,000) with no truncation marker -- in ADDITION to whatever the "
            "objective already contains. For a chunked unit the two copies are "
            "DIFFERENT regions of one file under contradictory labels. Pass "
            "paths=() and put the context in the objective yourself.",
            sorted(set(dupes))[:6]))

    # ---- 6. does the request contradict itself? ---------------------------
    # Only checkable when the system message was recorded. This is the check
    # that would have explained the whole run in one line.
    sys_hashes = {(a.get("sent") or {}).get("system_override_sha256")
                  for _, _, a in answers}
    sys_hashes.discard(None)
    if sys_hashes == {""}:
        v.append(Violation(
            "system_prompt_not_recorded", "serious",
            "no answer recorded a system prompt, so the highest-authority "
            "message in every request is unknown. If the default stack was "
            "used, it contains 'Do not include chain-of-thought' and a worked "
            "example whose risks list is empty -- both of which outrank any "
            "wording in the question."))

    # ---- 7. finding rate, stated even when zero -------------------------
    usable = [a for _, _, a in answers
              if ((a.get("report") or {}).get("status")) != "blocked"]
    with_risk = [a for a in usable if (a.get("report") or {}).get("risks")]
    stats["usable_answers"] = len(usable)
    stats["answers_with_a_finding"] = len(with_risk)
    if usable:
        rate = len(with_risk) / len(usable)
        stats["finding_rate"] = round(rate, 4)
        if rate < 0.02 and len(usable) > 50:
            v.append(Violation(
                "finding_rate_near_zero", "blocking",
                f"{len(with_risk)} of {len(usable)} usable answers contain any "
                f"finding ({rate:.2%}). On a codebase where hand review and two "
                "focused agents found real defects the same day, this is a "
                "statement about the harness, not the code. A zero reported as "
                "silence reads as a clean bill of health."))
    return v, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.lane_invariants")
    p.add_argument("in_dir")
    p.add_argument("--json", metavar="PATH", default=None)
    args = p.parse_args(argv)

    if args.json:
        # The printed invariant check stays fail-open read-only inspection;
        # the JSON result write starts at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "tools.lane_invariants",
            REGISTRY_BY_ID["tools.lane_invariants"].effects,
            (process_guard_boundary_decision(),),
        )
    in_dir = Path(args.in_dir)
    if not in_dir.is_dir():
        print(f"no such directory: {in_dir}")
        return 2
    results = _load(in_dir)
    violations, stats = check(results)

    print(f"=== {in_dir} ===")
    for k, val in stats.items():
        print(f"  {k:42} {val}")
    order = {"blocking": 0, "serious": 1, "note": 2}
    violations.sort(key=lambda x: order.get(x.severity, 3))
    print(f"\n=== {len(violations)} VIOLATION(S) ===")
    for x in violations:
        print(f"\n[{x.severity.upper()}] {x.check}")
        print(f"  {x.detail}")
        for e in x.evidence[:6]:
            print(f"    - {e}")
    if not violations:
        print("  none. The recorded run is self-consistent -- which is not the "
              "same as its findings being right.")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"stats": stats, "violations": [x.to_dict() for x in violations]},
            indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    # Exit 1 on any blocking violation: this is meant to run in a pipeline
    # BEFORE anyone reads the findings.
    return 1 if any(x.severity == "blocking" for x in violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
