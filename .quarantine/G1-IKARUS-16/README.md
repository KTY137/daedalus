# `voice_execution.py.blocked` — why this is here

Quarantined 2026-09-01 14:10. **Not abandoned, not defective — stopped on a
design objection before it landed.** Read this before restoring it; it does not
import against the current tree.

## What it is

The execution half of `G1-IKARUS-16`: Daedalus running the repository's tests on
behalf of a conversational turn, under an Effect Lease. 32 KB, and the shape is
sound — bounded output capture, a credential sweep over the child environment, a
containment decision, a spend net, a process-group spawn with a hard deadline,
and a receipt that keeps `exit_code=None` for a killed run rather than reporting
a failure it did not observe. `begin_effect` is taken **before** the argv exists,
so a refused run costs zero spawns.

Written to the brief. The brief was the problem.

## Why it was stopped

A design critique attacked the plan on paper and found the premise false. In
short:

1. **The design said "the model never gets a shell"; the code said otherwise.**
   `voice_scope.resolve_voice_scope` appended a bare `Bash` to the tool allowlist
   whenever a lease was present. The branch was dormant *only* because nothing
   constructed a lease — and this module is what constructs the first one. It
   would have handed the runtime an unrestricted shell for the whole turn, in
   addition to the command Daedalus ran itself.
2. **`python -m pytest` is not a fixed command in this repository.**
   `pyproject.toml` has no `[tool.pytest.ini_options]`, so a root-level
   collection walks into `runs/`, whose `conftest.py` mutates `sys.path` and
   whose modules evaluate generated candidate trees at import time. `-k` filters
   *after* collection, so a selector bounds what is reported, not what runs.
3. **`VoiceExecutionLease` is a second, unsigned lease type** beside
   `daedalus/kernel/contracts.py::EffectLease` — 3 fields against 18, no
   signature, no `expires_at`, no `kill_switch_generation`, no ledger, no replay
   refusal. Calling it "an Effect Lease" in a packet launders it as the real one.
4. **Whoever picks the selector picks which arbitrary code runs.** Nothing
   constructs a lease today; the obvious next step is to let the model propose a
   selector, at which point the design has quietly become model-chosen execution.

Defects 1 and 2 were fixed in `voice_scope.py` regardless, because they were
live defects in already-written code. The rest are the standing objection.

## It no longer imports

`voice_scope.TEST_COMMAND_PREFIX` was removed. It was `("python", "-m", "pytest")`
— a **bare** `python`, which on this machine resolves to an unrelated virtualenv
with no pytest.

The original text of this section said that invocation exits **0**, and drew the
conclusion that the Voice would report a green suite for a run that never
happened. **That is wrong, and it was measured wrong.** Re-measured 2026-09-02,
without a pipe:

```console
$ which python
/c/.../plugins/cache/trailofbits/modern-python/1.6.0/hooks/shims/python
$ python -c "import sys; print(sys.prefix)"
C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv
$ python -m pytest --version; echo $?
...\hermes\hermes-agent\venv\Scripts\python.exe: No module named pytest
1
```

The `0` came from reading the exit status of a **pipeline** — `cmd | tail; echo
$?` reports `tail`'s status, not `cmd`'s. Two sessions made that same mistake on
2026-09-01 and one of them corrected the other.

The correction does not rescue the bare `python`; it changes which lie it tells.
Exit 1 with no test ever collected is indistinguishable from a suite that ran
and failed, so the Voice would report a **red** suite for a run that never
happened. That is the more dangerous direction of the two, because a green
claim invites a spot-check and a red one invites debugging the wrong thing.
The absolute-interpreter requirement below is what actually fixes it.

The replacement is `TEST_COMMAND_ARGS = ("-m", "pytest", "tests")` plus
`VoiceExecutionLease.command_for(interpreter)`, which requires an **absolute**
interpreter path and refuses a bare or relative name. Line 85 and line 462 of the
blocked file both need updating for that.

## What would have to be true to restore it

The critique's own conditions, and note that satisfying them converges on the
existing Hand/supervisor path rather than on this module:

1. no `Bash` grant, qualified or otherwise — **already true** in the current
   `voice_scope.py`;
2. an absolute interpreter and an explicit test target — **already true**, and
   this file must be updated to the new API to inherit it;
3. execution in a disposable worktree, not the primary checkout;
4. admission as an Attempt of a Mission through `EffectLeaseLedger`, carrying
   `kill_switch_generation`, with `VoiceExecutionLease` **deleted** rather than
   kept beside `EffectLease`;
5. the selector chosen by deterministic policy, never from the message;
6. the packet stating plainly that this executes arbitrary repository code.

Items 3–5 are the Hand path. That convergence is the argument against restoring
this module as it stands.

## The alternative that was recommended instead

Chat never becomes effectful. The Voice **reads recorded** test evidence — the
mission path already produces `EvidencePacket`s under a real lease, with
containment and a ledger, and nothing reads them back for a conversation — and
"run the tests" becomes an enqueue the owner approves, executing on the Hand
path. The next turn then explains the result with full tool-bearing reading of
the failures.

That needs no new lease type, no new subprocess sink, and no second control
plane. It is unimplemented; this file is the road not taken, kept because the
bounded-capture, environment-sweep and receipt work in it is reusable wherever
execution eventually lands.

## The packet document this used to point at does not exist

The original last line sent the reader to
`docs/work-packets/G1-IKARUS-15_TOOL_BEARING_VOICE.md` "for the defects that
were fixed and the one that remains open". Checked 2026-09-02: no such file,
under that name or any other — `docs/work-packets/` holds a G1-IKARUS-15, but
it is `G1-IKARUS-15_MISSION_SUPERVISOR_COMPOSITION.md`, a different subject,
and nothing in that directory mentions `TOOL_BEARING` or `voice_scope`.

Recorded rather than quietly repaired, because a dangling pointer in retained
negative evidence is itself evidence: it says the tool-bearing-Voice packet was
never written down, so the two live defects listed under "Why it was stopped"
(the bare `Bash` grant and the unbounded root collection) were fixed in
`voice_scope.py` with no packet record of their own. The standing objection —
items 3 to 6 above — has never been written up anywhere else either. This file
is the whole record.

Whoever restores this module writes that packet first.
