---
name: project-byte-pin-text-gap
description: The .gitattributes `-text` byte-pin convention has an index-side hole the repo's own guards cannot see — measured 2026-09-11 during PR #376
metadata:
  type: project
---

The repository pins byte-exact files with `<path> -text` (owner decision D7). `-text`
disables git's check-IN normalisation as well as checkout translation, so on this host
(`core.autocrlf=true`, `core.safecrlf` unset) a pinned file that is CRLF on disk stages
its CRLF **into the index**, silently. Proven in a scratch repo 2026-09-11: pinned file
idxCR=2, unpinned sibling idxCR=0, no warning.

It has already fired. `git ls-files --eol | grep attr/-text` on `main` shows committed
CRLF/mixed blobs under a `-text` pin, including the Gate-1 bundle-closure member
`daedalus/eval/mint.py`, plus `daedalus/sensitivity.py`, `daedalus/structcore/tokens.py`,
`daedalus/kairos/drafts.py`, `daedalus/kernel/effect_replay.py` and a tail under
`docs/evidence/` and `runs/`.

Neither guard catches it: `tests/test_ignition_bundle_gitattributes.py` and
`tests/test_byte_pin_eol_durability.py` both only ask whether a *declaration exists*,
never whether the pinned bytes are LF. `test_the_gitattributes_pin_is_an_explicit_list_
not_a_wildcard` additionally hard-codes the literal `"<rel> -text"` spelling, so a file
cannot be switched to the safer `text eol=lf` without editing that test.

**Why:** the whole point of the pin is that a revision produces one digest everywhere; a
CRLF blob under a pin freezes the wrong bytes and every guard still reports green.

**How to apply:** when reviewing any `.gitattributes` addition here, check `i/lf` on the
index side, not just that the attribute resolves. When a lane asks "what else could the
repo do", the answer is an `i/lf` assertion over every `-text` path — that is the missing
guard, and PR #376 declined it deliberately to keep the diff one file. See
[[feedback-review-output-contract]] and [[project-daedalus-lane-hazards]].
