# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""daedalus.council -- "Der Rat": a cross-vendor council that produces EVIDENCE,
never a verdict.

THE GATE DECIDES, NOT A MODEL. This package may read, prompt, record and
verify. It has no writing, editing, applying or promotion capability anywhere,
by construction rather than by promise -- the same structural property
``spine/attempt.py`` earned with "THERE IS NO APPLY PATH". A council's product
is a queue of CHECKS for the existing deterministic gate (tests, fences, diffs)
to run; the gate's result is the only verdict. Dissent is recorded verbatim and
is never averaged away, which is why nothing in this package carries an
approve / reject / score / majority / consensus / confidence field. Advisory-by-
docstring is not a control; ABSENCE OF THE FIELD is the control.

FALSIFICATION PROTOCOL (stated in advance, before any wiring)
-------------------------------------------------------------
The premise -- independent vendors have independent blind spots -- is plausible
and UNTESTED. It is measured before ``session.py`` is wired into any real review
workflow, and the module is deleted if it fails:

  * ARM A: four vendors (anthropic / openai / google / local), one round each.
  * CONTROL: ONE vendor asked twice under two different role prompts. If four
    vendors do not beat one-vendor-twice, the council has bought four egress
    paths, an ssh surface and 4x latency for a prompt-diversity effect.
  * GROUND TRUTH: ``spine.attempt.GateResult.passed`` and
    ``AttemptResult.state`` -- already recorded, free to harvest. The question:
    does "the council raised an objection" predict ``gates_failed`` / a later
    revert better than the control, at what precision and recall?
  * INDEPENDENCE: pairwise agreement rate BETWEEN vendors versus WITHIN one
    vendor across two calls.
  * FALSIFIER: if inter-vendor agreement is within noise of intra-vendor
    agreement on N patches, THIS MODULE IS DELETED.
  * SMALL-N CAVEAT, stated in advance: the independent corpus is ~17-20 tasks.
    That is not enough for a significance claim. The honest move is to say so
    now rather than to report a percentage afterwards.

WHAT LIVES HERE
---------------
``bus.py``  -- the transcript: an append-only, hash-chained, offline-verifiable
              ``dcouncil/1`` store at ``runs/council/<council_id>.jsonl``. It is
              a SEPARATE store from the memory ledger and shares no code path
              with it: council turns are model chatter, and promoting model
              chatter to certified memory (three agreeing turns is three
              confirmations) is the fabrication failure this project treats as
              the worst one. COUNCIL RECORDS ARE NEVER AN INPUT TO MEMORY
              RECALL.
"""
from __future__ import annotations

from .bus import (  # noqa: F401
    ENTRY_VERSION,
    TURN_STATUS,
    actor_id,
    append_roster,
    append_round,
    append_turn,
    council_store_path,
    evidence_ref,
    load_transcript,
    transcript_head,
    verify_chain,
)

__all__ = [
    "ENTRY_VERSION",
    "TURN_STATUS",
    "actor_id",
    "append_roster",
    "append_round",
    "append_turn",
    "council_store_path",
    "evidence_ref",
    "load_transcript",
    "transcript_head",
    "verify_chain",
]
