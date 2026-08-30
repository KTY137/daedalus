# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""spine/docref_gate.py -- the gate a docref attempt is actually judged by.

WHAT THIS IS FOR
----------------
:mod:`daedalus.spine.docrefs` produces the one class of candidate the installed
local write policy permits (prose under ``docs/`` and ``README.md``). It also
ships the check that makes that class safe to point a weak model at --
:func:`docrefs.verify_fix`, which refuses a "fix" that lowered the number of
references that RESOLVE. Until this module existed that check had no caller: the
picker's docstring described it, the instruction handed to the model promised it
("the verifier checks the number of RESOLVING references before it checks the
broken one"), and nothing ran it. The promise was true about the code and false
about the system.

Worse than absent. The candidates carried ``gate_paths=(doc,)``, which becomes
``python -m pytest docs/THAT.md``; pytest exits non-zero on a markdown path it
cannot collect. So every docref attempt failed its gate, always, for a reason
that had nothing to do with the fix -- fail-closed, but indistinguishable from a
real finding and therefore useless. The loop's only permitted class of work
could not pass, and could not fail informatively either.

WHAT IT CHECKS, IN THIS ORDER
-----------------------------
1. **The denominator, FIRST.** The corpus must still resolve at least as many
   references as it did when the work was picked. Taking the document out
   withdraws the claim AND lowers that count in one move, so asking about the
   finding first would reward the deletion. The ordering is not re-implemented
   here: it is inside :func:`docrefs.verify_fixes`, which asks the denominator
   before it constructs a single per-reference verdict.
2. **The target document still exists and still has content.** The corpus
   denominator cannot see this one on its own: a document whose references were
   ALL broken contributes nothing to ``resolving``, so deleting it lowers no
   count and every finding in it disappears clean. Emptying it does the same.
   Neither is a remedy for "this sentence names code that is not there".
3. **Each dispatched finding.** Corrected (``fixed``) or honestly withdrawn
   (``claim_withdrawn``) both pass; still broken fails.

WHAT IT DELIBERATELY DOES NOT CHECK
-----------------------------------
Fact preservation -- whether the edit quietly deleted an unrelated true
sentence. That needs the document's text from the instant BEFORE the write, and
this process runs after it, inside a sandbox, with no honest source for it
(``git show HEAD:`` is a lie whenever the tree was already dirty). It is checked
where the before-image actually exists: ``daedalus.verifier.verify``'s prose
branch, fed from the writer's own rollback backups. The two checks are not
redundant and neither subsumes the other -- this one asks "did the claimed thing
get fixed honestly", the other asks "did anything else quietly vanish".

FAIL CLOSED, AND SAY WHICH KIND
-------------------------------
Exit ``0`` pass, ``1`` a measured failure of the candidate, ``2`` the gate could
not reach a verdict (bad arguments, no targets, unreadable tree). Both non-zero
codes block. They are separated because "the fix was bad" and "we never found
out" are opposite diagnoses, and recording the second as the first teaches the
router to distrust a lane that did nothing wrong.

Verifying ZERO targets is exit ``2``, never ``0``. A gate that passes because it
was given nothing to check is the empty green in its purest form.

NOTHING HERE WRITES, SPAWNS, OR REACHES THE NETWORK. It reads ``.md`` files and
parses ``.py`` with :mod:`ast`, which is all :mod:`docrefs` ever does. That is
what lets it run as the contained, low-integrity gate child.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import docrefs

__all__ = ["build_parser", "main", "run_gate"]

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCONCLUSIVE = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m daedalus.spine.docref_gate",
        description="Judge a docref fix: denominator first, then the findings.")
    p.add_argument("--repo-root", default=".",
                   help="tree to scan; defaults to the working directory, which "
                        "is the candidate worktree when run as a spine gate")
    p.add_argument("--doc", required=True,
                   help="repo-relative path of the document that was to be fixed")
    p.add_argument("--expect-resolving", type=int, required=True,
                   help="corpus-wide count of resolving references measured when "
                        "this work was picked -- the denominator")
    p.add_argument("--expect-doc-resolving", type=int, default=None,
                   help="optional: resolving references IN this document at pick "
                        "time, which catches a gutted document that contributed "
                        "nothing to the corpus count")
    p.add_argument("--ref", action="append", default=[], metavar="RAW",
                   help="raw text of one broken reference this attempt was "
                        "dispatched to fix; repeatable, at least one required")
    return p


def run_gate(repo_root: str, doc: str, expect_resolving: int,
             refs: list[str], expect_doc_resolving: int | None = None
             ) -> tuple[int, list[str]]:
    """Return ``(exit_code, report_lines)``. Never raises."""
    out: list[str] = []
    doc_rel = str(doc).replace("\\", "/").lstrip("/")
    out.append(f"docref-gate: document={doc_rel!r} targets={len(refs)} "
               f"expect_resolving={expect_resolving}")

    if not refs:
        out.append("docref-gate: NO target references were supplied. Verifying "
                   "nothing is not a pass -- refusing rather than reporting a "
                   "green tick for an unjudged edit.")
        out.append("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE, out

    root = Path(repo_root)
    if not root.is_dir():
        out.append(f"docref-gate: repo root {repo_root!r} is not a directory; "
                   f"the corpus could not be measured at all.")
        out.append("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE, out

    after = docrefs.scan(root)
    out.append(f"docref-gate: after-scan files={after.files_scanned} "
               f"resolving={after.n_resolving} broken={after.n_broken} "
               f"skipped={len(after.skipped)}")
    for err in after.errors[:5]:
        out.append(f"docref-gate: scan error: {err}")

    if expect_resolving <= 0:
        out.append("docref-gate: NOTE the pick-time denominator was "
                   f"{expect_resolving}, so the anti-deletion check is vacuous "
                   f"this run. The per-document guards below are all that stands.")

    # A reference's identity is the text INSIDE the backticks; prose and humans
    # both write the backticks. Strip them, or every target key misses and every
    # finding reads as withdrawn.
    clean_refs = [r.strip().strip("`").strip() for r in refs]
    targets = [{"doc_path": doc_rel, "raw": raw} for raw in clean_refs]

    # 1. DENOMINATOR FIRST -- inside verify_fixes, structurally, not here.
    #
    # NOTHING may precede this, and in particular no "could the gate even run?"
    # guard may precede it. The first version of this file checked
    # ``files_scanned == 0`` up here and called it inconclusive; deleting the
    # last document in the corpus triggers exactly that, so the one move the
    # denominator exists to catch was being reported as "we could not tell"
    # instead of "you destroyed the evidence". Both blocked, which is why it was
    # nearly invisible -- and the routing record would still have been wrong.
    ok, verdicts = docrefs.verify_fixes(expect_resolving, after, targets)
    destroyed = [v for v in verdicts if v.verdict == "evidence_destroyed"]
    if destroyed:
        for v in destroyed:
            out.append(f"docref-gate: FAIL evidence_destroyed -- {v.detail}")
        out.append("VERDICT: fail")
        return EXIT_FAIL, out

    # 2. The document itself must have survived. Checked AFTER the denominator
    #    on purpose: the denominator is the check that a deletion cannot dodge,
    #    and it stays the first thing anyone reads in the output.
    target_path = root / doc_rel
    if not target_path.is_file():
        out.append(f"docref-gate: FAIL the target document {doc_rel!r} is GONE. "
                   f"Deleting the file is not a remedy for a reference that names "
                   f"code which does not exist; it is the removal of the evidence "
                   f"that the reference was ever made.")
        out.append("VERDICT: fail")
        return EXIT_FAIL, out
    try:
        body = target_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out.append(f"docref-gate: the target document could not be read ({exc}); "
                   f"no verdict was reached about it.")
        out.append("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE, out
    if not body.strip():
        out.append(f"docref-gate: FAIL the target document {doc_rel!r} is EMPTY. "
                   f"Emptying a file is deleting it with the name left behind.")
        out.append("VERDICT: fail")
        return EXIT_FAIL, out

    if after.files_scanned == 0:
        out.append("docref-gate: the scan read ZERO documents even though the "
                   "target file is present, so the corpus was never measured and "
                   "no finding could have been seen. This is the absence of a "
                   "verdict, not a clean one.")
        out.append("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE, out

    if expect_doc_resolving is not None:
        now_in_doc = after.resolving_in(doc_rel)
        out.append(f"docref-gate: in-document resolving {expect_doc_resolving} "
                   f"-> {now_in_doc}")
        if now_in_doc < expect_doc_resolving:
            out.append(f"docref-gate: FAIL {doc_rel!r} went from "
                       f"{expect_doc_resolving} to {now_in_doc} references that "
                       f"resolve. The corpus total hid it; this document did not.")
            out.append("VERDICT: fail")
            return EXIT_FAIL, out
    else:
        out.append("docref-gate: NOTE no per-document denominator was supplied "
                   "(--expect-doc-resolving), so a document that contributed "
                   "nothing to the corpus count is guarded only by the existence "
                   "and non-empty checks above.")

    # 3. Each dispatched finding.
    #
    # ``claim_withdrawn`` is verify_fix's verdict for a target key found in
    # NEITHER the broken list nor the resolving list. Inside verify_fix that is
    # sound, because its target came out of the before-report and absence really
    # does mean the sentence was taken out. Here the target came off a COMMAND
    # LINE, so absence has a second explanation the check cannot distinguish:
    # the key never matched anything in the first place. MEASURED while writing
    # this file -- a target passed with its backticks still on produced a
    # confident "claim_withdrawn / pass" for a document whose reference was
    # still sitting there broken. The queue also truncates a reference's raw
    # text to 160 characters, which is the same failure with no typo required.
    #
    # So a withdrawal is only credited when the text really is gone from the
    # document. If it is still in there, we do not know what happened, and not
    # knowing is exit 2 -- never a pass.
    unresolved: list[str] = []
    for raw, v in zip(clean_refs, verdicts):
        label = "ok" if v.ok else "FAIL"
        note = ""
        if v.ok and v.verdict == "claim_withdrawn" and raw and raw in body:
            unresolved.append(raw)
            label, note = "UNKNOWN", (
                "  <- but this text is STILL in the document, so the claim was "
                "not withdrawn and the target may simply never have matched a "
                "finding. Refusing to read that as a fix.")
        out.append(f"docref-gate: {label} {v.verdict} {raw!r} -- {v.detail}{note}")

    if unresolved:
        out.append(f"docref-gate: {len(unresolved)} target(s) could not be "
                   f"accounted for; the gate reached no verdict about them.")
        out.append("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE, out

    out.append(f"VERDICT: {'pass' if ok else 'fail'}")
    return (EXIT_PASS if ok else EXIT_FAIL), out


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits 2 for a usage error, which is already this module's
        # "could not run" code -- but say so in words, because a gate whose
        # entire output is an argparse usage message reads like a crash.
        print("docref-gate: the gate was invoked with arguments it could not "
              "understand, so it judged nothing.", file=sys.stderr)
        return EXIT_INCONCLUSIVE
    try:
        code, lines = run_gate(args.repo_root, args.doc, args.expect_resolving,
                               list(args.ref), args.expect_doc_resolving)
    except Exception as exc:                       # noqa: BLE001 - unknown == unsafe
        print(f"docref-gate: the gate itself failed ({type(exc).__name__}: {exc}), "
              f"so no verdict was reached about the candidate.")
        print("VERDICT: inconclusive")
        return EXIT_INCONCLUSIVE
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
