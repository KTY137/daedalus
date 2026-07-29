# Proposed: a project policy that lets Daedalus write to Daedalus

> ## CORRECTION, 2026-07-29 — this document's central claim was FALSE
>
> Kaya authorised this policy. Measured before installing it, the version below
> **did not confine writes at all**. The claim further down —
>
> > "The ONLY paths a candidate patch may touch. Everything else is denied by
> > `default_deny`, so this list is the whole permission."
>
> — is wrong. `allow` and `default_deny` are read by `classify_data`, the
> **egress** axis. `path_write_blocked`, which the local write lane actually
> calls, never looked at either. Measured: **8 of 12** paths this document
> claimed to deny were writable, including `daedalus/config.py`, which loads
> this policy — a candidate could have rewritten the policy loader.
>
> ```text
> WRITABLE  daedalus/core.py      WRITABLE  daedalus/cli.py
> WRITABLE  daedalus/offload.py   WRITABLE  daedalus/health.py
> WRITABLE  daedalus/router.py    WRITABLE  daedalus/config.py  <-- loads this file
> WRITABLE  daedalus/providers/ollama.py    WRITABLE  pyproject.toml
> ```
>
> **What was installed instead** is `.agentenv/agentenv.json`, using a new
> opt-in, prefix-anchored `write_allow` field that the write guard does read.
> See `docs/adrs/019-one-decision-point.md` for the structural finding behind
> it and `tests/test_self_policy_confinement.py` for the receipt.
>
> This document is kept rather than deleted because the mistake is the more
> useful artefact: it is the ninth time in one week that a *document described
> a capability the code did not have*, and the first time the author of both
> was the same.

**Status: SUPERSEDED by `.agentenv/agentenv.json` (installed 2026-07-29).**
Everything below is the original proposal, preserved unedited apart from this
header. Read it for the reasoning about *which paths*; do not trust it about
*how the mechanism works*.

## Why this is the last blocker

The self-improvement circle runs end to end and is fail-closed at every step.
A shadow run in a clean clone picks real work, routes it, and stops. The exact
line it stops on, measured:

```
routed to : ollama  mode=write  action=escalate_to_claude
note      : refusing live write: no project policy loaded (guards off) -- pass --project
```

`daedalus/offload.py`:

```python
if decision.mode == "write" and pol is None:
    return _escalate("refusing live write: no project policy loaded (guards off) -- pass --project")
```

That refusal is correct and load-bearing. Without a loaded policy the write
guards run under `DEFAULT_POLICY`, whose deny-list is empty — so **the safety
core itself would be writable** by a candidate. Refusing is the right answer.

The consequence is that **Daedalus has no policy for its own repository**:
`resolve_project("agent_env")` returns `None`, and there is no `.agentenv/`
directory. It can improve other projects and not itself.

## What the decision actually is

Not "should the loop be allowed to write" — it already cannot promote anything,
and a candidate patch is inert bytes a human applies. The decision is narrower:

> Which paths in Daedalus's own tree may a candidate's patch *touch*, so that
> the write guards have something concrete to enforce instead of an empty list?

## The proposal, and it is deliberately small

```jsonc
{
  "name": "agent_env",
  "repo_root": "C:/Users/nukei/Desktop/agent_env",
  "policy": {
    "default_deny": true,

    // The ONLY paths a candidate patch may touch. Everything else is denied by
    // default_deny, so this list is the whole permission.
    "allow": ["docs/", "tests/", "README"],

    // Belt to the allow-list's braces. If somebody widens `allow` later — and
    // somebody will — these must still be refused, and a widening that also
    // deletes a line here is a visible, deliberate act rather than an
    // accident.
    "high_risk_paths": [
      "daedalus/sensitivity.py",     // the egress fence and the secret floor
      "daedalus/enforce.py",
      "daedalus/budget.py",          // the spend ceiling
      "daedalus/spine/",             // attempt, containment, killswitch, ledger
      "daedalus/kairos/worktree.py", // the guarded deletes
      "tools/operability_drill.py",  // the thing that says autonomy is defensible
      "tools/system_check.py",
      "tools/gate_discrimination.py",
      "docs/adrs/",
      ".github/", ".git/"
    ]
  }
}
```

**Why `docs/` and `tests/` and nothing else.** Those are where the loop's own
top candidates already live — documentation drift and missing coverage — and
they are the two places where a wrong patch costs a review rather than an
incident. Source stays out until the gate can discriminate, which it currently
cannot: measured rejection rate 0 of 3 against the day's known-bad changes.

**Why the safety core is named explicitly even though `default_deny` already
covers it.** A future widening of `allow` is the realistic failure. Naming the
fence separately means that widening has to delete a line that says
"the egress fence" next to it.

**What this does NOT enable.** No promotion — `promotion_allowed` is a single
unconditional return gated on a discrimination receipt that does not exist. No
`--apply`. No scheduling. No spend beyond the ceiling now installed at the CLI
entry point. And the write itself still happens only inside a disposable
worktree whose gate runs under kernel-enforced containment.

## How to install it, and how to undo it

```
mkdir .agentenv
# write the JSON block above to .agentenv/agentenv.json, with repo_root fixed
python -m daedalus.cli doctor          # confirm the policy resolves
```

To undo: delete the file. There is no other state.

## What I would check first, if it were mine to take

Run one shadow attempt against a `docs/` candidate with the policy in place and
read the patch by hand. The interesting question is not whether the machinery
works — it does — but whether a 7B local model produces anything worth a human's
attention. Tonight's measurement says the router sends real write work to the
paid lane, so the honest first test is a small, local, documentation-shaped task
where a weak model has a chance.
