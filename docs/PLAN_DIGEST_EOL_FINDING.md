# Hashing the plan from disk reports an intact constitution as tampered

**MEASURED 2026-08-25 at `2de997ef` on branch `main`.** Reproduce with the
commands in "How to see it" below; every number here came from one of them.

**The amendment chain is intact and the plan is unmodified.** Read that first,
because the arithmetic below looks alarming and is not: `docs/…MASTER_PLAN.md`
is bit-identical to what revision 7 pinned. What this page records is a
*measuring* defect — the obvious way to check the pin returns the wrong answer
on Windows — not a governance one. Nothing here calls for an amendment **on its
own**; the one owner-shaped item at the end is a question about whether §16
step 3 should survive at all, and it is not urgent.

## What was measured

`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` record 7 pins
`result_plan_sha256 = 306115e6527adc8a4d8cb83003bfa1d5839525a35a62eed5274b1a2ac85c62ca`.
Hashing `docs/IKARUS_ARIADNE_MASTER_PLAN.md` as it lies in the working tree on
this Windows host gives
`01df5d2e47df688ade80244fbb803d097ef2133269bd731d8b0d178b01d2a89f`.

The plan did **not** silently change, and it is not missing a protection it
ought to have. Markdown without a `text` attribute under `core.autocrlf=true`
is *supposed* to sit as CRLF on disk and as LF in the blob; `git check-attr -a`
on the plan returns no attributes at all, which is the normal state, not an
omission. The record pins the blob, and the blob matches it exactly. The two
digests are one document in two line-ending forms:

| | bytes | sha256 (first 16) | CRLF pairs |
|---|---:|---|---:|
| working tree (`open(..., "rb")`) | 31474 | `01df5d2e47df688a` | 585 |
| Git blob (`git show HEAD:...`) | 30889 | `306115e6527adc8a` | 0 |

`disk.replace(b"\r\n", b"\n")` hashes to exactly the recorded digest. The
amendment chain itself is intact: 7 records, sequences 1..7, every
`previous_record_sha256` matching its predecessor's `record_sha256`, and the
newest commit that touched the plan (`79825b57`, 2026-08-22) produces the
recorded blob digest.

## Why it happens, and why nothing caught it

`core.autocrlf` is `true` on this host, so a checkout translates LF to CRLF.
`.gitattributes` carries a byte-pin list for the cases where that is harmful —
~150 entries under the "CRLF DAEMON" banner, owner decision D7 — and the plan
is deliberately not among them [MEASURED: `grep -n MASTER_PLAN .gitattributes`
finds nothing; `git check-attr -a` on the plan returns no attributes]. That is
the correct configuration. The defect is not a missing entry; it is that
nothing in the repository states *which bytes* a pinned document's digest is
taken over, so the naive answer and the recorded answer differ.

Nor could anything catch it. The pin list is guarded by `tests/test_byte_pin_eol_durability.py`, whose stated
job is that "the CRLF pin daemon has no next victim" by re-deriving the census
from the source instead of trusting a hand-maintained list. It cannot see this
subject: `_SEARCH_ROOTS = ("daedalus", "tests", "tools")` and the walk is
`base.rglob("*.py")`. A markdown document whose sha256 is pinned into a JSONL
chain is outside the census by construction, so the test passes by finding
nothing — the failure direction is *less coverage, reported as green*.

## Why it matters

The plan's sha256 is not a checksum, it is the constitutional anchor. Section
16 step 3 instructs an amending session to start with
`DAEDALUS_IRON_PLAN_AMENDMENT=<current full plan sha256>`, and invariant 10
("no silent constitution change") is verified by comparing that digest against
the chain. On this host the two ways of computing "the current full plan
sha256" disagree, and only one of them matches the record:

- hash the **blob** (`git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.md`) → matches;
- hash the **file** → mismatch that looks exactly like a tampered constitution.

There are two failure directions, and the loud one is not the dangerous one.

**Read side, loud, self-correcting.** Someone hashes the file and reports an
untouched constitution as manipulated. Alarming, but it argues with itself
within a minute. Note also that nothing currently *emits* this signal
automatically: the guard that read `DAEDALUS_IRON_PLAN_AMENDMENT` was deleted
on 2026-08-22 by the same retirement decision. What remains is a human
comparing digests by hand.

**Write side, silent, permanent.** A future amending session follows §16 step 3
on this host, hashes the plan *from disk*, and writes a CRLF digest into
`result_plan_sha256`. Nothing fails: the chain's `previous_record_sha256`
linkage still verifies, every record still links. The chain has simply pinned
bytes that no checkout on any platform reproduces — a fabricated anchor, in the
one artifact whose whole job is to be unfabricatable. **This is the direction
that deserves the headline**, and it is why the rule below is worth stating
before anyone amends anything.

**The rule that fixes it costs nothing:** the digest of a pinned document is
always taken against `git show HEAD:<path>`, never against the file on disk.

## How to see it

```powershell
python -c "import hashlib;print(hashlib.sha256(open('docs/IKARUS_ARIADNE_MASTER_PLAN.md','rb').read()).hexdigest())"
git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.md | python -c "import sys,hashlib;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"
python -c "import json;print([json.loads(l)['result_plan_sha256'] for l in open('docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl',encoding='utf-8') if l.strip()][-1])"
```

## What this document does not do

It changes nothing, and it does **not** propose adding the plan to the
`.gitattributes` byte-pin list. That was this page's first reading and it was
wrong: `-text` would rewrite the working-tree bytes of a protected file to fix
a checker that should not have been reading those bytes in the first place. The
other ~150 entries are pinned because *code* hashes its own file at runtime;
the plan is hashed by a human following section 16, who can be told which bytes
to hash. [Corrected after `agent-env-8e` re-measured the chain, 2026-08-25.]

What remains is one owner-shaped item, and it is a question rather than a
proposal. §16 step 3 instructs an amending session to export
`DAEDALUS_IRON_PLAN_AMENDMENT=<current full plan sha256>` — an environment
variable read by a tool that was deleted on 2026-08-22. Opening §16 only to
specify which bytes that dead variable's digest covers would spend an owner
amendment record polishing a corpse. The real question is whether step 3
survives at all. If §16 is opened, the same commit should settle §15 step 2,
which still mandates running the same deleted tool (see
`docs/STATUS.md`, unsettled table).

1. **Define the digest, if the step survives.** Say *which* bytes are hashed
   (the Git blob), making the on-disk form irrelevant. This costs an
   amendment record but ends the ambiguity for every host, not just this one.

Either way, the detector gap is separate and is not owner-shaped: extend
`tests/test_byte_pin_eol_durability.py` so its census includes non-`.py`
artefacts whose digest is recorded elsewhere — today the plan and its amendment
chain — so that "no byte-pin subject is unlisted" stops depending on the
subject happening to be Python.

## The same daemon has a third face

While this page was being written, the parallel session `agent-env-8e` measured
the tooling side of the identical problem and it is worth recording together.
``pathlib.Path.write_text()`` emits the platform line ending, so the common
patch idiom

```python
s = p.read_text(); p.write_text(s.replace(a, b))
```

rewrites every line of the file. On an ordinary text file under
``core.autocrlf=true`` that is invisible -- the working tree is already CRLF and
Git normalises on commit. On a file listed ``-text`` in ``.gitattributes`` it is
not invisible at all: that file is checked out with LF *precisely because* its
bytes are pinned, so the idiom converts the whole file to CRLF and buries the
real change. MEASURED 2026-08-25: ``daedalus/ignition/gate1.py`` 19 real changed
lines rendered as 4293 in the diff, ``daedalus/spine/effect_boundary.py`` 42 as
7002. Three of three lanes hit it.

So the byte-pin list has two failure directions, not one. A subject **missing**
from it drifts to CRLF on checkout and stops matching its recorded digest (this
page's subject). A subject **in** it is checked out as LF and any tool that
rewrites the file with platform newlines corrupts the diff. The cheap habit that
catches the second is to compare

```powershell
git diff --stat
git diff --ignore-cr-at-eol --stat
```

after any scripted edit: if the two disagree, the difference is line endings.
For writing, ``write_bytes`` or ``open(..., newline="")`` preserves what was
there.

## Two more faces, found the same day

**Third: the pin list grows until it eats its own control sample.**
`tests/test_byte_pin_eol_durability.py` carried
`test_an_ordinary_module_is_not_eol_pinned`, whose whole job was to refute a
vacuous guard — "without this, a repo-wide `* -text` would make the guard
vacuously green" — by asserting that one named module, `daedalus/router.py`,
was *not* pinned. The evaluator closure then grew (`5ebd9395`, "the evaluator
closure grew by 3 modules, and the pin follows it") until it included that
module, and the test went red for a reason unrelated to its own claim. There is
no catch-all: 146 of 1163 tracked `.py` files are pinned, 12.6% [MEASURED
2026-08-25, `git check-attr --stdin text` over `git ls-files -- '*.py'`].

A control sample frozen as a path constant is a control that the thing it
controls for can eventually swallow. Repaired 2026-08-25: the catch-all is now
refuted directly (no `*`, `**`, `*.py`, `**/*.py` pattern carries `-text`) and
the unpinned control is chosen at run time. Mutation-checked against four
catch-all shapes, each caught, without touching the shared `.gitattributes`.
[Reported by the parallel session `agent-env-8e`; re-measured here.]

**Fourth: the same daemon in `stdin`, not just in file writes.**
Measuring the third face went wrong twice before it went right, in a way worth
recording because the failure printed a tidy answer:

```python
subprocess.run(["git", "check-attr", "--stdin", "text"],
               input="
".join(paths), text=True)   # WRONG on Windows
```

`text=True` applies newline translation on the **write** side too, so git
receives `daedalus/router.py` — a path that matches nothing. The command
returned one clean line per input path and reported **3** pinned files instead
of 146, with a plausible-looking histogram and no error. Pass `input=` as
`bytes`, or open with `newline=""`.

That is the same lesson as the rest of this page from a third direction: the
CRLF daemon does not announce itself, and every one of its faces so far has
failed toward *less* — fewer bytes matched, fewer files counted, less coverage —
while printing something that reads like a result.

## Related

- `docs/AMENDMENT_PROPOSAL_004_BYTE_EXACT_RESOURCE_EOL.md` — the earlier round
  of this same daemon, written while the retired iron guard still existed.
- `docs/GATE0_OWNER_DECISIONS_20260817.md` sections 5 and 6 — two of the four
  recorded appearances.
