# Review: `daedalus/tools/vet.py`

**Reviewed:** 2026-08-26 against HEAD `e83d8d8a`. **Classification:** `ALIGNED`
-- read-only review plus one stale-test repair. No rule, severity, allowance
semantic or policy was changed. **Iron Gate:** 0.

**Scope.** 1668 lines, 208 unit tests plus 102 subtests, two prior review
commits (`5b26ddef`, `765b6c36`). Consumers: `daedalus/tools/inventory.py`
(both `vet_skill` and `vet_mcp_server`) and the `daedalus.tools` package facade.

## Verdict

The module is in good shape and its core discipline holds under probing. One
substantive gap, one stale test (repaired here), two prose drifts. Nothing
release-blocking; the gap is a decision for the tool-allowance owner, not a bug
to patch quietly.

## What was probed and held `[MEASURED]`

| Property | How it was checked | Result |
| --- | --- | --- |
| "unknown" is never "clean" | read the outcome fold at the end of `vet_skill` | any entry in `skipped` folds the verdict to `UNSCANNABLE`; the file-size bound, the truncated bundle listing, and the over-cap file list all append to it |
| a truncated scan cannot read as clean | `MAX_FILES_SCANNED` path | the count of unscanned files is appended verbatim before the list is clipped, so the cap reports itself -- the failure mode this repository keeps rediscovering elsewhere is closed here |
| an allowance cannot clear a block | `apply_allowances` | downgrades `BLOCK` to `REVIEW` only, carries the acknowledgement text onto the finding, and never reaches `CLEAR` |
| static only | module imports | file reads and regex; nothing imports, resolves or starts the subject |
| the rules still fire | injected a synthetic `npx -y <pkg>` spec | `mcp.unpinned` / `mcp.remote_fetch` fire |

## Finding 1 (substantive) -- an MCP filesystem grant is invisible to the gate

The module's first line is "the gate a tool must pass before an agent may be
given it." Its declared attack model for MCP is EXECUTION and EGRESS. A
filesystem server is neither: it is a **write-root grant**, and the gate has no
rule that looks at a path argument.

`[MEASURED]` four synthetic specs, all reaching `vet_mcp_server` unmodified:

```text
fs-vault        outcome=clear  findings=[]
fs-whole-disk   outcome=clear  findings=[]     # rooted at C:/
fs-user-home    outcome=clear  findings=[]     # rooted at C:/Users/nukei
fs-ssh-keys     outcome=clear  findings=[]     # rooted at C:/Users/nukei/.ssh
```

This is not hypothetical for this repository: `.mcp.json` ships
`obsidian-vault`, a `@modelcontextprotocol/server-filesystem` rooted inside the
checkout. It vets `clear` with zero findings, and so would the same server
rooted at the drive.

Why it matters beyond this module: master-plan invariant 8 puts write roots at
the effect boundary. An MCP server handed to an agent is a write root granted
outside that boundary, and the one gate in front of it does not model the
question.

**Recommendation, not a change.** A `mcp.filesystem_scope` rule at `REVIEW`
that fires when any argument resolves to an existing directory, escalating to
`BLOCK` for a root/home/credential-directory grant. It is deliberately left
unimplemented here: it changes what the gate refuses, which is a policy
decision for the tool-allowance owner and belongs with the fence owner
(`sensitivity` / `enforce`), exactly as this module already delegates host
trust to `sensitivity.lane_for_host` rather than re-deciding it. Adding it
inline would be this module's own rule 4 violated by its reviewer.

## Finding 2 (repaired) -- `LiveRepoConfig` pinned a fact about the world

`test_this_repos_context7_entry_is_flagged_unpinned` asserted that this
checkout's context7 entry was flagged `mcp.unpinned`. It failed
`[MEASURED: 1 failed, 206 passed]`, and both the gate and the config were
right: every entry in `.mcp.json` has since been rewritten to an absolute path
to an already-installed module (an unrelated Windows fix -- the npx shim opened
a console window per launch). Nothing fetches at start any more.

Re-aimed at the intent rather than deleted, because the intent was good: the
gate must be run against what the repository actually ships. Two probes now:
no live entry fetches an unpinned spec at start, and every live entry produces
a verdict that is neither `UNSCANNABLE` nor `BLOCK`. The first carries a
CONTROL -- it flags a synthetic `npx -y` spec before reporting the live sweep
clean -- because "no offenders" and "the rule stopped firing" produce the same
empty set.

`[MEASURED]` after: 208 passed, 102 subtests.

**Named, not asserted:** an absolute path to an installed module carries no
version identity, so `npm update` changes what runs without changing what
`mcp_spec_digest` binds. That is weaker than a pinned spec. It is recorded in
the test's docstring and left to the allowance owner.

## Finding 3 (prose drift, fixed) -- one stale citation, and one that only looks stale

`daedalus/observe/shape.py:38` cited ``tools/vet.py`` in current prose. The file
is `daedalus/tools/vet.py`; corrected here.

`tools/docs_reference_check.py:8` names the same old path and is NOT drift: it
appears inside that module's own explanation of why stale paths matter, as a
dated example of a reference a 2026-08-25 sweep found. Changing it would erase
the evidence the sentence is about. Recorded because the distinction --
current surface versus dated evidence -- is the one a grep-driven fix gets
wrong, and getting it wrong here would have rewritten a finding into a lie.

## What this review did NOT do

- It did not re-derive the rule table. 207 existing probes cover it, including
  the negative controls (`RemoteFetchNonEvents`, `UnpinnedNonEvents`) that stop
  the broad patterns from becoming rubber stamps.
- It did not exercise the skill path against a real community skill bundle.
  The bundled-file, bytecode-exemption and truncation paths were read, not run
  against a large hostile fixture.
- It did not review `daedalus/tools/inventory.py`, the consumer that turns
  these verdicts into an installed-tool decision. That is where a `REVIEW`
  verdict either stops something or does not, and it is the natural next
  review.

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: `python -m pytest tests/test_tools_vet.py -q` (208 passed, 102
subtests); the four synthetic filesystem specs above, re-runnable against
`vet_mcp_server` unmodified.
