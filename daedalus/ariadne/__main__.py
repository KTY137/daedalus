"""The Ariadne campaign command line, and the exit-code contract both doors share.

``run_campaign`` has four typed outcomes plus cancellation: a nominated
receipt, a settled negative receipt (a domain verdict about the candidate),
``AriadneRequestError`` (refused before any effect), ``AriadneConflictError``
(the repository moved under the request), other ``AriadneCampaignError``
verdicts, and ``LoopHalted``.  A caller that has to read prose to tell those
apart cannot branch on them, so this module gives each one an exit code and one
machine-readable document on stdout.

The contract (G1-ARIADNE-09), for ``python -m daedalus.ariadne`` and for
``daedalus ariadne`` alike -- both doors emit identical bytes:

===== ====================================================== ==================
code  meaning                                                stdout
===== ====================================================== ==================
0     a settled receipt with outcome ``nominated``           the receipt
1     a settled receipt that nominates nothing               the receipt
      (``rejected``, ``failed``, ``cancelled``, or any
      outcome this contract does not yet know)
2     ``AriadneRequestError`` -- the request was refused      an error document
      before any effect; fix the request
3     ``AriadneConflictError`` -- stale or changed revision,  an error document
      identity reuse with changed inputs; re-read HEAD
4     ``LoopHalted`` -- the kill switch is engaged; nothing   an error document
      runs until it is armed again
5     any other ``AriadneCampaignError`` -- the campaign      an error document
      refused without settling a receipt, for a reason
      that is neither of the two named classes above
64    the command line is wrong (argparse)                    an error document
70    a foreign exception -- a defect in Daedalus             an error document
===== ====================================================== ==================

Nothing reaches stderr except argparse's usage message (64) and the traceback
of an internal defect (70); an internal defect still gets its document on
stdout, so a script never has to parse a traceback to learn what happened.
``--help`` keeps argparse's behaviour: the usage text on stdout, exit 0.

An error document is exactly one compact line, whether or not ``--json`` was
passed::

    {"error":{"kind":"conflict","message":"source_revision conflict: ..."}}

``--json`` renders the *receipt* as one compact line too; without it the
receipt stays indented for a human reader.  Errors are never indented because
a script must be able to read one without buffering to find its end.

Codes 0 to 5 are Daedalus outcomes.  64 and 70 are taken from ``sysexits.h``
(BSD ``/usr/include/sysexits.h``: ``EX_USAGE`` 64, "command was used
incorrectly"; ``EX_SOFTWARE`` 70, "internal software error"), not invented
here, and they sit deliberately far from the outcome block so that a mistyped
flag can never be read as a refusal.  The measured baseline before this packet
used argparse's exit 2 for a usage error AND for every refusal, which is
exactly the collision this separation removes.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from .campaign import (
    AriadneCampaignError,
    AriadneConflictError,
    AriadneRequestError,
    run_campaign,
)

#: A settled receipt that nominates a candidate for owner review.
EXIT_NOMINATED = 0
#: A settled receipt that nominates nothing.  The receipt is still on stdout.
EXIT_NEGATIVE_RECEIPT = 1
#: ``AriadneRequestError``: refused before any effect.
EXIT_REQUEST_REFUSED = 2
#: ``AriadneConflictError``: the repository moved under the request.
EXIT_REVISION_CONFLICT = 3
#: ``LoopHalted``: the kill switch is engaged.
EXIT_HALTED = 4
#: Any other ``AriadneCampaignError``: refused, no receipt, neither of the above.
EXIT_CAMPAIGN_REFUSED = 5
#: ``sysexits.h`` EX_USAGE.  NOT argparse's own 2, which a refusal already uses.
EXIT_USAGE = 64
#: ``sysexits.h`` EX_SOFTWARE: a foreign exception is a defect, not a verdict.
EXIT_INTERNAL = 70

#: Outcomes of a settled ``CampaignReceipt`` (``kernel/contracts/canonical.py``).
#: Only ``nominated`` exits 0; anything else -- including an outcome added after
#: this contract was written -- is not a success.
NOMINATING_OUTCOME = "nominated"


class _ArgumentParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that remembers the message it refused with.

    argparse writes its own usage text to stderr and exits 2.  Both are kept
    (the text is for the human who mistyped), but the code is remapped to
    :data:`EXIT_USAGE` and the message is repeated in the machine-readable
    document, so the caller does not have to read stderr to learn what was
    wrong with the command line.
    """

    usage_error: str | None = None

    def error(self, message: str):  # noqa: D102 - argparse's own contract
        self.usage_error = message
        super().error(message)


def build_parser(prog: str) -> _ArgumentParser:
    """The one argument surface both doors expose."""
    parser = _ArgumentParser(prog=prog, description="Run one bounded Ariadne repair campaign.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument(
        "--json", action="store_true",
        help="render the receipt as one compact line (errors always are)",
    )
    return parser


def classify_failure(failure: BaseException) -> tuple[int, str]:
    """Map a raised failure to its exit code and the ``kind`` of its document.

    The order is load-bearing: ``AriadneRequestError`` and
    ``AriadneConflictError`` are subclasses of ``AriadneCampaignError``, so
    classifying the base first would make both named classes unobservable and
    collapse the contract back to the measured baseline.
    """
    from daedalus.spine.killswitch import LoopHalted

    if isinstance(failure, LoopHalted):
        return EXIT_HALTED, "halted"
    if isinstance(failure, AriadneRequestError):
        return EXIT_REQUEST_REFUSED, "request"
    if isinstance(failure, AriadneConflictError):
        return EXIT_REVISION_CONFLICT, "conflict"
    if isinstance(failure, AriadneCampaignError):
        return EXIT_CAMPAIGN_REFUSED, "campaign"
    return EXIT_INTERNAL, "internal"


def exit_code_for_receipt(receipt: dict) -> int:
    """0 only for a nomination.  Fail closed on an outcome this code predates."""
    outcome = receipt.get("outcome") if isinstance(receipt, dict) else None
    return EXIT_NOMINATED if outcome == NOMINATING_OUTCOME else EXIT_NEGATIVE_RECEIPT


def error_document(kind: str, message: str) -> str:
    """One compact line.  ``json.dumps`` escapes any newline inside the message,
    so the line really is a line even when the message is multi-line."""
    return json.dumps(
        {"error": {"kind": kind, "message": message}},
        ensure_ascii=False, separators=(",", ":"),
    )


def run_cli(argv: list[str] | None, *, prog: str, stdout=None, stderr=None) -> int:
    """Parse, run one campaign, and answer with the shared exit-code contract.

    Both doors call exactly this, so ``daedalus ariadne`` and
    ``python -m daedalus.ariadne`` cannot drift apart.  The caller owns the
    effect boundary: this function performs no guard installation of its own.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parser = build_parser(prog)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0  # --help / --version: argparse already printed the text
        print(
            error_document("usage", parser.usage_error or "invalid command line"),
            file=out,
        )
        return EXIT_USAGE

    try:
        receipt = run_campaign(
            repo_root=Path(args.repo_root),
            source_revision=args.source_revision,
            campaign_id=args.campaign_id,
            target_path=args.target,
            before=args.before,
            after=args.after,
            timeout_s=args.timeout_s,
        )
    except Exception as failure:  # noqa: BLE001 - every outcome is classified below
        code, kind = classify_failure(failure)
        if code == EXIT_INTERNAL:
            # The one deliberate stderr exception: an unclassified failure is a
            # defect and the operator needs the frame, but the document on
            # stdout still says what happened without parsing the traceback.
            traceback.print_exception(failure, file=err)
        print(error_document(kind, str(failure) or type(failure).__name__), file=out)
        return code

    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")), file=out)
    else:
        print(json.dumps(receipt, indent=2, ensure_ascii=False), file=out)
    return exit_code_for_receipt(receipt)


def main(argv: list[str] | None = None) -> int:
    # The module door is effectful even though run_campaign has its own exact
    # lease: argument handling must not be able to precede the process-wide
    # spend/process guard.  The inner python.ariadne_campaign boundary still
    # owns write policy, containment, the durable lease, and each trial.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.ariadne_campaign",
        REGISTRY_BY_ID["cli.ariadne_campaign"].effects,
        (process_guard_boundary_decision(),),
    )

    return run_cli(argv, prog="python -m daedalus.ariadne")


if __name__ == "__main__":
    raise SystemExit(main())
