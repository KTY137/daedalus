# G1-SELF-01 — exact campaign invocation and how to replay it

Measured 2026-09-05. Home paths are written `<HOME>`; the session scratch root
is `<SCRATCH>` (`<HOME>/AppData/Local/Temp/daedalus-lane8`, outside the
repository by construction).

## Isolation

| Thing | Where |
| --- | --- |
| subject | `<SCRATCH>/subject` — `git clone --no-local --shared` of the checkout, then `git checkout cfe8d34b8ef1438156e6fa3e6982f5a30d91696f` (detached). `.git` is a real directory, so `verify_repository_head_revision` admits it; a linked worktree is refused (G1-SELF-00 negative evidence 1). No `runs/spine/spine.sqlite3` is committed, so the clone starts with a fresh spine and the control-root override does not hit the split G1-SELF-00 negative evidence 2 recorded. |
| control root | `<SCRATCH>/control` — fresh, empty before the run. Holds the kill-switch permit, the lease ledger, the Ariadne source-tree CAS and the effect evidence. |
| interpreter | `<WORKTREE>/.venv/Scripts/python.exe` (uv venv, CPython 3.13.14), whose editable install maps `daedalus` to the lane worktree at the same revision. The main checkout's venv was deliberately not used. |
| gate verification copy | `<SCRATCH>/verify-after` — a second clone at the same revision, used only to run the frozen gate over CAS-materialized bytes. Never the campaign subject. |

The shared checkout, its control root and its spine database were not touched.

## Steps, in order

```
git clone --no-local --shared <checkout> <SCRATCH>/subject
git -C <SCRATCH>/subject checkout cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

DAEDALUS_KILLSWITCH=<SCRATCH>/control/killswitch \
  <WORKTREE>/.venv/Scripts/python.exe -m daedalus.spine.killswitch arm
# -> ARMED <SCRATCH>/control/killswitch: armed
```

Then the registered CLI door, run with cwd `<SCRATCH>/subject` and
`DAEDALUS_KILLSWITCH=<SCRATCH>/control/killswitch`:

```
<WORKTREE>/.venv/Scripts/python.exe -m daedalus.ariadne \
  --repo-root        <SCRATCH>/subject \
  --source-revision  cfe8d34b8ef1438156e6fa3e6982f5a30d91696f \
  --campaign-id      self-renovation-04 \
  --target           daedalus/build.py \
  --before           <contents of repair-before.txt, 764 bytes, 13 lines> \
  --after            <contents of repair-after.txt, 777 bytes> \
  --timeout-s        60
```

`--before` and `--after` are multi-line. They were passed as single argv
elements by building the argument vector in Python and handing it to
`subprocess.run` as a list, so no shell quoting touches the bytes. The door
invoked is unchanged: `daedalus/ariadne/__main__.py`, which calls
`begin_effect("cli.ariadne_campaign", …)` before it parses a single argument.

Exit code 0. The receipt is `campaign-self-renovation-04.receipt.json`.

## The frozen gate

`gate_docstring_symbol_refs.py` in this directory. It is **not** the campaign's
evaluator — the campaign's evaluator is the frozen exact-match SHA-256 check
built into `daedalus/ariadne/campaign.py` (`EVALUATOR_SOURCE`/`EVALUATOR_SHA256`),
and `python -m daedalus.ariadne` accepts no gate command. This gate is the
independent discriminator that establishes the defect is real and the
nominated repair removes it. It reuses the repository's own resolver,
`daedalus.spine.docrefs.resolve_reference`, and reads only: it parses with
`ast`, imports nothing it inspects, spawns nothing, writes nothing.

```
python gate_docstring_symbol_refs.py <repo_root> daedalus/build.py
# exit 0 = every first-party docstring symbol reference resolves
# exit 1 = at least one is broken
```

Run over the CAS bytes of all four trees (`gate-three-arms.json`):

| tree | source-tree sha256 (16) | exit | n_broken | n_resolving |
| --- | --- | --- | --- | --- |
| base | `5744722af8fc8829` | 1 | 2 | 11 |
| baseline arm (seed 0) | `e1f5371705d416f6` | 1 | 2 | 11 |
| negative control (seed 1) | `47edcd93efa334db` | 1 | 2 | 11 |
| repair arm (seed 2) | `81d0390463e8a0d1` | **0** | **0** | **13** |

The baseline arm's tree is byte-identical to the base tree (verified).

## Retained artifacts in this directory

| File | What it is |
| --- | --- |
| `campaign-self-renovation-04.receipt.json` | the `CampaignReceipt` the door printed, home paths sanitized |
| `candidate.diff` | base -> nominated repair, both materialized from the CAS |
| `negative-control.diff` | base -> negative control, from the CAS |
| `repair-fragments.json` | **authoritative** byte record of the two argv values, with their SHA-256 (`before` `0a7fa0a96c721b75111d544a6b07dfa0651e5618435fc2cd5b86763df44bcd8b`, 764 bytes; `after` `eaeb1cab3071ebcfc841c391a5d60fdf3aeb82e816d28e4a2b67d353d90127c7`, 777 bytes) |
| `repair-before.txt`, `repair-after.txt` | readable copies of the same fragments. `core.autocrlf` is true on this host (`.gitattributes` documents the recurring byte-pin/EOL failure), so a fresh checkout may rewrite their line endings; the JSON above is the record that survives that |
| `gate_docstring_symbol_refs.py` | the frozen gate |
| `gate-three-arms.json` | the gate's verdict on every arm's CAS bytes |
| `control-root/` | the 16 effect-evidence records the campaign wrote under the scratch control root, sanitized |
| `control-root/INDEX.json` | the SHA-256 of each record's **unsanitized** bytes |
| `source-cas-inventory.json` | the 30 object digests in the scratch source-tree CAS |
| `rejected-candidates.md` | every candidate considered and why it was not chosen |

Sanitization note: the retained control-root copies had home paths rewritten, so
a copy's bytes no longer hash to the `record_sha256` written inside it.
`control-root/INDEX.json` carries the digest of the original bytes for each.
