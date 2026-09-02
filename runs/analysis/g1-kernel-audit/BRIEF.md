# G1 kernel audit — shared worker brief

Base: local `main` @ `54f09753` in `C:/Users/Administrator/daedalus`.
Subject: all 50 files of `daedalus/kernel/` (the trust kernel), 25,010 LOC.

## Hard rules

- **READ-ONLY on tracked files.** Never edit, never `git add`, never `git commit`,
  never `git checkout`/`stash`/`restore`. Do not run the test suite.
- You may write **only** new files under
  `C:/Users/Administrator/daedalus/runs/analysis/g1-kernel-audit/`.
- Hands off entirely: `vault/` (a daemon rewrites it), `.quarantine/` (evidence),
  `daedalus/lanes/` (under review). Do not read-audit or report on them.
- Static analysis only. No test runs, no imports that execute side effects.
  If you need a script, use `C:/Users/Administrator/daedalus/.venv/Scripts/python.exe`
  and put the script under the audit dir. Bare `python` on this box is a
  different venv and lies about results.
- Use absolute paths in every Bash call; cwd is reset between calls.

## Files owned by other running write-packets

Read them, but **flag rather than deep-audit** — they are being modified right now,
so any finding may already be stale:

- `daedalus/kernel/offload_lease.py` and the string-evidence sites in
  `daedalus/kernel/attempt_execution.py` (owned by the "chip-refusal" packet)
- `daedalus/kernel/effects.py` (just received a fix)

For these, note the observation in one line and mark it `OWNED-FLAG` rather than
building a full case.

## Deliverable

One dossier per assigned file: `<basename>.md` in the audit dir. E.g.
`daedalus/kernel/policy/ledger.py` -> `policy_ledger.py.md` (flatten the
subdirectory with an underscore so names stay unique).

Each dossier covers the five axes below. **Every claim needs a `file:line`.**
Separate **CONFIRMED** (you read the code and the defect is visible in it) from
**PLAUSIBLE** (the shape is wrong but reachability/impact is not proven). Never
promote a plausible finding to confirmed to make the dossier look stronger. If a
file is clean on an axis, say so explicitly — "no findings" is a result.

### Axis 1 — docstring truth

Grep the module and every class/function docstring for the words
`authenticated`, `verified`, `always`, `guaranteed`, `never`, `enforced`,
`cannot`, `impossible`, `all `, `every`, `only`. For each hit, check the claim
against the code that is supposed to implement it.

Known context that defines the quarry: a kill-switch audit just showed a
**plan-level** "always enforced" claim was false while the **module** docstring
was honest. So module-level and class-level overclaims are the target — a
docstring that promises a property the code does not implement, or implements
only on one of several paths. Universal words ("all", "every", "only", "never")
must be checked by enumerating the actual set, not by reading the sentence.

### Axis 2 — effect surface vs the Effect Registry

Enumerate every site in your files that does any of:
- `subprocess.` / `os.system` / `os.spawn` / `Popen` (process spawn/control)
- network: `socket`, `urllib`, `requests`, `httpx`, `http.client`, `bind`, `listen`
- filesystem write: `open(..., "w"/"a"/"x"/"wb")`, `Path.write_text/write_bytes/mkdir/touch`,
  `os.replace/rename/remove/unlink`, `shutil.copy*/move/rmtree`, `sqlite3.connect`
  to a real path, `tempfile` writers
- environment reads: `os.environ`, `os.getenv`

Compare against the Effect Registry in `daedalus/spine/effect_boundary.py`
(the `Effect` enum at :43 and the 108 `EntrypointSpec(` rows). **Measured fact:
only 4 of those 108 rows have a `target="daedalus.kernel...."`** — at
:350, :372, :394 (attempt_ledger begin/complete, attempt_workspace prepare) and
:2304 (approvals:main). So an effectful kernel site with no covering row is the
expected finding, not the exception; what matters is which sites are *reachable
without* passing through one of those four, and whether the module claims
otherwise. Report the unregistered sites as a table, and say for each whether a
covering row plausibly exists elsewhere in the registry under a non-kernel target.

### Axis 3 — resource acquisitions without try/finally

13 sqlite sites were just fixed. The canonical statement of the pattern is the
comment in `daedalus/kernel/effects.py::_initialize` (:576-588): `with
sqlite3.Connection` **commits, it does not close**; a leaked connection keeps
`-wal`/`-shm` companions alive for an indeterminate lifetime, so anything that
stats those companions sees a file that can vanish between its existence check
and its resolve. The fixed shape is `conn = self._connect()` / `try:` / `finally:
conn.close()`.

Look for the *same* shape in **other resource types too**, not just sqlite:
open file handles, `tempfile.TemporaryDirectory`/`NamedTemporaryFile`,
`subprocess.Popen` without `wait`/`kill` in a finally, `threading.Lock` /
`filelock` / advisory lock files acquired outside try/finally, `socket`,
`os.open` file descriptors, `contextlib.ExitStack` misuse, `git` worktree or
lock allocation, and any acquire/release pair the module defines itself.
For each: is the release reachable on the exception path?

### Axis 4 — validator gaps of the W4 class

Confirmed in the W4 sweep (`runs/analysis/g1-security-sweep/W4-findings.md`):

- `daedalus/kernel/contracts/canonical.py:27` defines
  `_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")`, used by
  `_identifier()` (:54). It admits `.` and `/` anywhere after the first
  character with **no check that a `..` forms a path segment** — so
  `"x/../../../../tmp/evil"` fullmatches.
- `_repo_path()` at :124 in the same file is the correct validator: it rejects
  absolute paths, any `..` part, and drive-qualified paths.
- 14 files duplicate the weak regex locally.
- One confirmed exploit chain runs through `attempt_workspace.py`
  (`IsolatedAttemptCoordinator.prepare` at :236/:247/:249-252) into
  `source_trees.py::materialize_tree` (:621-679).

**Your job: find the siblings.** For each of your files, enumerate every value
that is validated by `_identifier` (or a local copy of the weak regex) and then
reaches **path construction** — `Path(...)  / value`, `os.path.join`, an f-string
building a path, a filename, a directory name, a `sqlite` file path, a git ref
or branch name, a URL path segment. Give the full chain with line numbers.
Distinguish: does the value reach a path *before* any `_repo_path`, `resolve()`,
or containment check? A value that is only ever used as a dict key or logged is
not a finding — say so and move on.

### Axis 5 — dead / duplicate candidates

Zero callers is a **FINDING, not a verdict**. For anything that looks unused:
- grep the whole repo (including `tests/`, `apps/`, `docs/`, `tools/`, `gates/`)
  for the symbol before calling it uncalled, and report the exact grep and count;
- read the docstring for a **promised reader** — "consumed by X", "the spine
  reads this", "callers must" — an unwired producer whose docstring names its
  consumer is a *seam* defect (missing consumer), not dead code;
- duplicates: the same regex, the same validator, the same canonicalization,
  the same digest helper implemented twice. Name both sites and say which is
  stricter.

## Dossier template

```markdown
# <relative path>  (<LOC> lines)

Base 54f09753. Static read-only.

## What the file is for
2-4 sentences, from the code not the docstring.

## Axis 1 — docstring truth
### CONFIRMED
- **<claim>** — `path:line` says "...". Code at `path:line` does X instead. <why it is false>
### PLAUSIBLE
- ...
### Checked and honest
- <claims you verified as true — list them, this is the enumeration that makes
  the "no findings" credible>

## Axis 2 — effect surface
| site (file:line) | effect | registry row | covered? |
### Notes

## Axis 3 — unreleased resources
## Axis 4 — validator gaps (W4 class)
## Axis 5 — dead / duplicate
## OWNED-FLAG (if the file is owned by a running packet)
## What I did not cover
```

End your reply to the parent with your **three most material findings**, each
with `file:line` and a CONFIRMED/PLAUSIBLE label, plus the list of dossier files
you wrote. Keep it under 40 lines; the parent reads your text, not your files.
