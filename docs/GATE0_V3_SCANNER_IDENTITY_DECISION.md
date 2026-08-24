# Gate 0 — v3 scanner identity: owner decision packet

Status: PARTIALLY RESOLVED — options B+D applied and landed
(`ee45877` in the lane, `aafd2a1` on the trunk, 46 passed across the
7-file family); **only option A (inventory schema /1 → /2) and the
`report_v3.py:344` exception-conflation note still await the owner.**
Prepared: 2026-08-17
Worktree: `grind/v3-scanner-owner-prep`
Base commit: `7c88f72b120f6a36c2ce5d21ea1733ddf3524322` [MEASURED, `git rev-parse HEAD`]
Iron Plan guard: `Iron Plan OK: revision 4, Gate 0 — Canonical Kernel,
sha256 9329de665ba96a79e28989b7538ca93a176cd50337a66a977506db45c7a2aa00`
[MEASURED, `python tools/iron_plan_guard.py (removed 2026-08-22) verify`]

At preparation time nothing in this document was applied; the status line
above records what has landed since. Every code block below is the original
`daedalus/` source file, no test, and no schema was edited to produce it; the
one end-to-end verification below was performed by an in-process monkeypatch in
a scratch directory outside the repository.

---

## 1. The three failures, raw

Command form: `PYTHONUTF8=1 python -m pytest <file> -x -q`.
All three reproduce at `7c88f72`. [MEASURED]

### 1.1 `tests/gates/test_gate_report_v3.py::test_builder_binds_live_canonical_repository_write_inventory`

```
    def test_builder_binds_live_canonical_repository_write_inventory() -> None:
>       report = build_gate0_report_v3(ROOT, source_revision=REVISION)

tests\gates\test_gate_report_v3.py:213:
daedalus\gates\report_v3.py:416: in build_gate0_report_v3
    inventory_before = _repository_write_evidence(
daedalus\gates\report_v3.py:340: in _repository_write_evidence
    inventory = scan_repository_write_surfaces_v2(
daedalus\gates\repository_write_inventory_v2.py:232: in scan_repository_write_surfaces_v2
    base_before = scan_repository_write_surfaces(
daedalus\gates\repository_write_inventory.py:804: in scan_repository_write_surfaces
    return RepositoryWriteInventory(
<string>:8: in __init__

        if len(set(self.callsites)) != len(self.callsites):
>           raise ValueError("callsites must be unique")
E           ValueError: callsites must be unique

daedalus\gates\repository_write_inventory.py:221: ValueError
1 failed in 22.47s
```

### 1.2 `tests/gates/test_gate_report_v3_cli.py::test_cli_emits_machine_v3_report_and_blocked_exit`

```
    def test_cli_emits_machine_v3_report_and_blocked_exit(capsys) -> None:
        result = main([str(ROOT), "--source-revision", REVISION])
>       assert result == 1
E       assert 2 == 1

tests\gates\test_gate_report_v3_cli.py:15: AssertionError
---------------------------- Captured stdout call -----------------------------
{"closed":false,"error":"callsites must be unique","schema":"daedalus-gate-report-v3-error/1"}
1 failed in 16.80s
```

### 1.3 `tests/gates/test_gate_report_v3_review.py::test_v3_module_has_no_release_promotion_or_execution_authority`

```
        assert {"write_text", "write_bytes", "mkdir", "unlink", "replace"}.isdisjoint(called)
>       assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
E       AssertionError: assert False
E        +  where False = <built-in method isdisjoint of set object at 0x...>({'GateReportV3', 'GateReportV3Error', 'Path', '__post_init__', '__setattr__', '_body_v2', ...})
E        +    where <...> = {'compile', 'eval', 'exec', 'popen', 'system'}.isdisjoint

tests\gates\test_gate_report_v3_review.py:87: AssertionError
1 failed in 0.80s
```

Family-level blast radius: of the seven v3/inventory gate test files,
**3 failed, 43 passed in 52.20s**. Only the three named tests fail. [MEASURED]

---

## 2. Where the identity question actually sits

**One root cause produces failures 1.1, 1.2 and 1.3: the scanner establishes
identity by *name and start position*, and neither is injective.**

### 2.1 Two identity contracts, both keyed on a non-injective position

| Layer | File:line | Identity contract |
| --- | --- | --- |
| v1 record | `daedalus/gates/repository_write_inventory.py:220-221` | the whole tuple `(path, line, column, kind, callee, operation)` must be unique |
| v2 surface | `daedalus/gates/repository_write_inventory_v2.py:109-111` | `(path, line, column)` alone must be unique across **all** surfaces |

Both derive position from `daedalus/gates/repository_write_inventory.py:708-709`:

```python
                line=node.lineno,
                column=node.col_offset,
```

For a chained method call — `x.replace(a, b).replace(c, d)` — Python's AST gives
every link in the chain the **same** `lineno` and `col_offset`, namely the start
of the receiver expression. The links are distinct `ast.Call` nodes but share a
position. Additionally, `_syntactic_name` cannot name a receiver that is itself
a call, so `daedalus/gates/repository_write_inventory.py:684` synthesises the
literal string `<expression>.replace` for every outer link:

```python
                raw = f"<expression>.{node.func.attr}"
```

Same path, same line, same column, same kind, same callee, same operation —
the records are indistinguishable, and the uniqueness invariant fires.

Measured at `7c88f72` over the live `daedalus/` package: [MEASURED]

```
files scanned            : 275
callsite records         : 505
distinct records         : 496   -> v1 needs 505, short by 9
distinct start positions : 492   -> v2 needs 505, short by 13
```

The nine duplicate records sit at seven positions, all `<expression>.replace`:

```
  x2  daedalus/budget.py:1013:24        for word in str(tok).replace("'", " ").replace('"', " ").split():
  x2  daedalus/context_plan.py:78:15    expanded = _CAMEL.sub(" ", str(text)).replace("_", " ").replace("-", " ")
  x3  daedalus/conversation.py:163:12   return (str(path).replace("\\", "/").replace("?", "%3f").replace("#", "%23"))
  x2  daedalus/mapping/render.py:698:7  (triple-quoted CSS constant, chained .replace)
  x3  daedalus/spine/ledger.py:147:12   return (str(path).replace("\\", "/") ...
  x2  daedalus/spine/ledger.py:606:23   escaped = (fragment.replace("\\", "\\\\").replace("%", "\\%") ...
  x2  daedalus/wiki/vault.py:241:11     return PurePosixPath(rel).stem.replace("-", " ").replace("_", " ")
```

Three further positions hold *different* records at one position — a named
receiver plus its synthetic chain links — which v1 tolerates but v2's
position-uniqueness rule at `repository_write_inventory_v2.py:109-111` does not:

```
  daedalus/kairos/orchestrate.py:19:17   ambiguous_binding text.replace          + path_mutation <expression>.replace
  daedalus/providers/ollama.py:1115:28   ambiguous_binding disk_original.replace + path_mutation <expression>.replace
  daedalus/skills.py:411:17              ambiguous_binding text.replace          + path_mutation <expression>.replace
```

**Consequence for option design:** deduplicating v1 is provably not enough.
496 deduplicated records still occupy only 492 positions, so v2 raises
`surface positions must be unique across components`. Any option must satisfy
both contracts. [MEASURED]

### 2.2 Why `.replace` is in the scanner's mouth at all — the substantive identity question

`daedalus/gates/repository_write_inventory.py:55-67` puts `replace` into
`_PATH_METHODS` because `pathlib.Path.replace(target)` is an atomic rename — a
genuine filesystem write. `daedalus/gates/repository_write_inventory.py:618`
then classifies purely on the trailing name:

```python
    if terminal in _PATH_METHODS:
        return ("path_mutation", resolved or raw, terminal)
```

The scanner has no receiver type. So `str.replace`, `bytes.replace`,
`datetime.replace` and `dataclasses.replace` are all reported as filesystem
write surfaces. `_BLOCKING_KINDS` at line 108 is every kind except
`sqlite_read_only`, so **each one is a Gate 0 blocker.**

Composition of the 505 records: [MEASURED]

```
  266  ambiguous_binding       blocking=True
  120  path_mutation           blocking=True
   49  process_effect_unknown  blocking=True
   35  filesystem_mutation     blocking=True
   19  ambiguous_sqlite_mode   blocking=True
    9  write_mode_open         blocking=True
    6  ambiguous_os_open_flags blocking=True
    1  os_open_write           blocking=True

path_mutation by method          ambiguous_binding by method (top 5)
   98  .replace                     102  .replace
   14  .write_text                   70  .mkdir
    5  .mkdir                        33  .write_text
    2  .unlink                       21  .open
    1  .touch                        13  .unlink

of the 98 path_mutation .replace:  75 `<expression>.replace`, 23 `dataclasses.replace`
```

Now the decisive measurement. `pathlib.Path.replace(target)` takes exactly one
positional argument and no keywords. `str.replace(old, new[, count])` takes two
or three. `dataclasses.replace(obj, **changes)` takes one positional plus
keywords. Every `.replace(` attribute call in `daedalus/`, by arity: [MEASURED]

```
  176  args=2 kwargs=0 starred=False     <- str.replace(old, new)
   17  args=1 kwargs=1 starred=False     <- dataclasses.replace(obj, **changes)
    2  args=0 kwargs=1 starred=False     <- dataclasses.replace(**changes)
    1  args=3 kwargs=0 starred=False     <- str.replace(old, new, count)
    1  args=0 kwargs=4 starred=False     <- dataclasses.replace(**changes)

calls matching the Path.replace(target) signature: 0
```

**There is not one `Path.replace()` call in the production package.** The real
atomic renames all go through `os.replace`, which the scanner already catches
correctly as `filesystem_mutation` via `_FILESYSTEM_FUNCTIONS`:

```
daedalus/atomic.py:74               os.replace(tmp, target)
daedalus/budget.py:738              os.replace(tmp, self.path)
daedalus/file_bridge.py:270         os.replace(path, dest)
daedalus/file_bridge.py:501         os.replace(path, dest)
daedalus/kernel/source_trees.py:653 os.replace(staging, target)
```

So roughly 200 of 505 blocking records — every `.replace` row — are false
positives generated by name collision, and the chained-call duplicates that
crash the builder are a *symptom* of the same name collision. [MEASURED]

### 2.3 The same error, one layer up, is failure 1.3

`tests/gates/test_gate_report_v3_review.py:78-87` builds `called` by mixing two
different namespaces into one set:

```python
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
```

A bare `ast.Name` call is a builtin or module-local function. An `ast.Attribute`
call is a method on some object. Collapsing both into one set and testing it
against `{"exec", "eval", "compile", "system", "popen"}` means the only
`compile` in the module —

`daedalus/gates/report_v3.py:30`:
```python
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
```

— is read as the builtin `compile()`. It is the identical mistake the scanner
makes with `.replace`: **a trailing name is not an identity.** [MEASURED, the
grep for `exec|eval|compile|system|popen` in `report_v3.py` returns exactly this
one line.]

Note the neighbouring assertion at line 86 already got this right for the write
methods by luck, not by construction: `report_v3.py` happens to contain no
`.replace(` call at all, so it passes.

### 2.4 A secondary defect, worth recording but not the decision

`daedalus/gates/report_v3.py:344` fails closed only on the declared error type:

```python
    except RepositoryWriteInventoryV2Error:
```

but the v2 wrapper at `repository_write_inventory_v2.py:244` converts only
`RepositoryWriteInventoryError` and `RepositoryWriteStdlibDeltaError`. The
`ValueError` raised by the frozen dataclass `__post_init__` is neither, so it
escapes the fail-closed path entirely and surfaces as CLI exit 2 with the
`daedalus-gate-report-v3-error/1` schema (see 1.2). The report never lies — it
still says `closed: false` — but "the scanner is internally broken" and "the
repository has blockers" are different states that currently differ only by
which exception class happens to escape. Recorded; not part of this decision.

### 2.5 Why this only shows up now

`tests/gates/test_repository_write_inventory_cli.py:31-37` builds a synthetic
two-file package in `tmp_path` and scans that. Every v1/v2 scanner test is
fixture-based and passes. `tests/gates/test_gate_report_v3.py:213` is the first
consumer that points the scanner at the **live checkout** — the tree that
contains the scanner. The v3 report is where the scanner acquires an identity as
a thing that must survive reading itself, and the three duplicate-producing lines
were written long after the scanner's contract was frozen: [MEASURED, `git log -L`]

```
daedalus/spine/ledger.py:147   ebdfbfd 2026-07-28
daedalus/conversation.py:163   6e6b83c 2026-07-29
daedalus/wiki/vault.py:241     58f4fc4 2026-07-30
```

Any future contributor who writes `str(p).replace("\\", "/").replace(...)`
in `daedalus/` re-breaks the entire v3 report family. Whatever the owner picks,
that fragility is the thing being decided.

---

## 3. Options

Four options. A and B are alternatives; C is included because it is the obvious
cheap move and it is **refuted by measurement**; D is separate and addresses
failure 1.3 only.

### Option A — make the record identify the *call*, not the expression start

Add an end-position discriminator so chained links are distinguishable.

`daedalus/gates/repository_write_inventory.py`:
```diff
 @dataclass(frozen=True, order=True)
 class RepositoryWriteCallsite:
     path: str
     line: int
     column: int
+    end_line: int
+    end_column: int
     kind: str
     callee: str
     operation: str
 
     def __post_init__(self) -> None:
         if not isinstance(self.path, str) or not _safe_relative_posix(self.path):
             raise ValueError("callsite path must be repository-relative POSIX")
-        if type(self.line) is not int or type(self.column) is not int:
+        if any(
+            type(value) is not int
+            for value in (self.line, self.column, self.end_line, self.end_column)
+        ):
             raise ValueError("callsite position must use strict integers")
         if self.line < 1 or self.column < 0:
             raise ValueError("callsite position is invalid")
+        if self.end_line < self.line or self.end_column < 0:
+            raise ValueError("callsite end position is invalid")
```
```diff
     def to_dict(self) -> dict[str, Any]:
         return {
             "path": self.path,
             "line": self.line,
             "column": self.column,
+            "end_line": self.end_line,
+            "end_column": self.end_column,
             "kind": self.kind,
```
```diff
         sites.append(
             RepositoryWriteCallsite(
                 path=relative,
                 line=node.lineno,
                 column=node.col_offset,
+                end_line=node.func.end_lineno,
+                end_column=node.func.end_col_offset,
                 kind=kind,
```
```diff
     def _payload(self) -> dict[str, Any]:
         return {
-            "schema": "daedalus-gate0-repository-write-inventory/1",
+            "schema": "daedalus-gate0-repository-write-inventory/2",
```

`daedalus/gates/repository_write_inventory_v2.py` — mirror the two fields onto
`RepositoryWriteSurface` (lines 38-47), extend the construction at lines 267-296,
and widen both position keys:
```diff
-        positions = {(item.path, item.line, item.column) for item in self.surfaces}
+        positions = {
+            (item.path, item.line, item.column, item.end_line, item.end_column)
+            for item in self.surfaces
+        }
         if len(positions) != len(self.surfaces):
             raise ValueError("surface positions must be unique across components")
```
```diff
     base_positions = {
-        (site.path, site.line, site.column) for site in base_before.callsites
+        (site.path, site.line, site.column, site.end_line, site.end_column)
+        for site in base_before.callsites
     }
     delta_positions = {
-        (finding.path, finding.line, finding.column) for finding in delta.findings
+        (finding.path, finding.line, finding.column, finding.end_line, finding.end_column)
+        for finding in delta.findings
     }
```

Also required: `daedalus/gates/repository_write_stdlib_delta.py` finding records
must carry the same two fields; `configs/schemas/repository-write-inventory-v1.schema.json`
has `"additionalProperties": false` at lines 6 and 68, so a new schema file and a
`/2` const are mandatory; `tests/gates/test_repository_write_inventory_cli.py:67`
pins the `/1` const and must move.

**Verified effect** [MEASURED, simulation over the live tree — the classifier was
re-run in a scratch script with each candidate discriminator, records were not
constructed through the dataclass]:

```
discriminator = node.func.end_lineno/end_col_offset
     records=505  distinct_records=505  distinct_keyed_positions=505
     v1 unique OK: True   v2 position-unique OK: True

discriminator = node.end_lineno/end_col_offset
     records=505  distinct_records=505  distinct_keyed_positions=505
     v1 unique OK: True   v2 position-unique OK: True
```

Consequences:
- Fixes 1.1 and 1.2. Does not touch 1.3.
- The record shape, the schema version and therefore **every inventory digest
  and every `report_sha256` derived from one** change. No stored receipt is
  invalidated by this in practice: the only pinned inventory hashes in the tree
  are placeholders (`"b" * 64` at `tests/gates/test_gate_report_v3_drift.py:106`,
  `"c" * 64` at `tests/gates/test_repository_write_evidence.py:30`), and a search
  of `runs/` returns no stored inventory artifact. [MEASURED]
- Keeps all 505 blockers, including ~200 `.replace` false positives. Gate 0's
  write-surface inventory stays unusable as a triage list.
- Widest diff: 3 production modules, 1 schema file, at least 1 test.
- Authority boundary: unchanged. Nothing gains an effect.

Rollback: `git revert` of the single commit. Because the schema const moves
`/1 -> /2`, a partial revert is not safe; revert all files or none.

### Option B — make the scanner's *surface* identity type-aware where the syntax already proves it — RECOMMENDED

Keep the record shape. Refuse to call a `.replace` a filesystem write unless the
call site has the `pathlib.Path.replace(target)` signature.

`daedalus/gates/repository_write_inventory.py`, one helper plus one guard at the
top of `_classify_call` (inserted before line 589):

```diff
+def _matches_pathlib_replace(call: ast.Call) -> bool:
+    """`Path.replace(target)` takes exactly one positional argument.
+
+    `str.replace(old, new[, count])` takes two or three; `dataclasses.replace`
+    and `datetime.replace` take keywords. The scanner has no types, but this
+    arity is decidable from the syntax alone, and it is the only shape that can
+    be an atomic rename.
+    """
+
+    return (
+        len(call.args) == 1
+        and not call.keywords
+        and not any(isinstance(arg, ast.Starred) for arg in call.args)
+    )
+
+
 def _classify_call(
     call: ast.Call,
     *,
     raw: str,
     resolved: str | None,
     ambiguous: bool,
     aliases: Mapping[str, frozenset[str]],
     indirect: frozenset[str],
 ) -> tuple[str, str, str] | None:
     terminal = raw.rsplit(".", 1)[-1]
     root = raw.partition(".")[0]
     resolved_terminal = (resolved or "").rsplit(".", 1)[-1]
+    if (
+        terminal == "replace"
+        and resolved not in _FILESYSTEM_FUNCTIONS
+        and not _matches_pathlib_replace(call)
+    ):
+        return None
     if raw in indirect or terminal in indirect:
```

The `resolved not in _FILESYSTEM_FUNCTIONS` clause preserves `os.replace(src, dst)`,
which is two-positional and is the form every real atomic rename in the package
actually uses.

**Verified effect** [MEASURED, end-to-end: `_classify_call` was replaced in
process by exactly this logic from a scratch script outside the repository, then
the real `build_gate0_report_v3` and the real `scripts/report_gate0_v3.main` were
run against the live checkout. The repository was not modified.]

```
=== builder test assertions (test_gate_report_v3.py:212-219) ===
  PASS  inventory_sha256 is not None      PASS  generation == 2
  PASS  scan_input_sha256 is not None     PASS  failures truthy
  PASS  files_scanned > 0                 PASS  closed is False
  files_scanned = 275   blocker rows = 360
  inventory sha = 1aadcc31d2aa4c484ecceb72f8429e8e5097ff696b2a856779353fd02c1674a6

=== CLI test assertions (test_gate_report_v3_cli.py:13-26) ===
  PASS  exit code == 1                    PASS  inventory_sha256 not None
  PASS  schema == daedalus-gate-report/3  PASS  scan_input_sha256 not None
  PASS  closed is False                   PASS  files_scanned > 0
  PASS  security_boundary_claimed False   PASS  generation == 2
  PASS  failures truthy
  rc = 1
```

Base-scanner uniqueness under the gate: `records=430 distinct_records=430
distinct_positions=430` — both contracts satisfied with margin. [MEASURED]

Consequences:
- Fixes 1.1 and 1.2. Does not touch 1.3.
- Record shape, schema version and `to_dict` are untouched. Nothing that reads
  `daedalus-gate0-repository-write-inventory/1` needs to change. Diff is one
  file, ~16 lines.
- Inventory digests change (fewer callsites), but no shape changes and no
  pinned real digest exists in the tree. [MEASURED, same evidence as Option A]
- Blocker count drops from 505 to 430 at the base scanner; the v3 report's
  blocker rows drop to 360. The removed rows are exactly the `.replace` name
  collisions. The remaining list becomes a triage list a human can act on —
  which is what Gate 0's exit criterion needs it to be.
- Precision claim, stated honestly: the gate is a **syntactic heuristic**, not a
  type check. It can only lose a write surface if someone writes
  `some_path.replace(other_path)` — one positional argument, no keywords — in
  which case the gate passes it through and classification is unchanged. It
  cannot lose `os.replace`. It can in principle miss a *user-defined* method
  named `replace` taking one argument that performs a write; that case was
  already indistinguishable from `Path.replace` before this change, and it is
  still flagged, not dropped. The change is strictly precision-increasing and
  never drops a call that matches the rename signature. [ASSUMED for
  hypothetical future code; MEASURED that zero such calls exist at `7c88f72`]
- Authority boundary: unchanged. The gate can only *remove* a blocker row, never
  add an effect, never claim closure. `security_boundary_claimed` stays `False`
  and the CLI still has no argument that could set it
  (`tests/gates/test_gate_report_v3_cli.py:40-55` passes today and is unaffected).
- Does **not** fix the underlying chained-call position collision. It removes
  today's only instances of it. A future chained `.write_text(...)` or
  `.mkdir(...)` on an expression receiver would reintroduce the crash. This is
  the honest cost of B versus A, and it is why 3.5 below proposes B+A.

Rollback: `git revert` of the single commit; no schema or cross-module coupling.

### Option C — deduplicate the records — REFUTED, do not choose

The obvious cheap move:

```diff
     callsites = tuple(
         sorted(
-            site
-            for path in files
-            for site in _callsites_for_file(root, package_root, path)
+            set(
+                site
+                for path in files
+                for site in _callsites_for_file(root, package_root, path)
+            )
         )
     )
```

**Measured refutation:** deduplication yields 496 records occupying 492 distinct
start positions. `repository_write_inventory_v2.py:109-111` requires distinct
positions to equal the surface count, so `scan_repository_write_surfaces_v2`
raises `surface positions must be unique across components` and failures 1.1 and
1.2 persist with a different message. [MEASURED]

Making C work requires additionally relaxing the v2 invariant:

```diff
-        positions = {(item.path, item.line, item.column) for item in self.surfaces}
-        if len(positions) != len(self.surfaces):
-            raise ValueError("surface positions must be unique across components")
+        # (deleted)
```

That trades a crash for a weaker artifact-identity guarantee: two blocker rows
that a reviewer cannot tell apart, and a component-overlap check
(`repository_write_inventory_v2.py:262-265`) that no longer means what its error
message says. Under invariant 2 (artifact identity) and invariant 7 (provenance),
this is the wrong direction. Recorded so the option is visibly closed, not
overlooked.

Rollback: n/a — not recommended for application.

### Option D — fix the review test's namespace collapse (failure 1.3, independent)

`tests/gates/test_gate_report_v3_review.py`:

```diff
     imported: set[str] = set()
-    called: set[str] = set()
+    called_names: set[str] = set()
+    called_attrs: set[str] = set()
     for node in ast.walk(tree):
         if isinstance(node, ast.Import):
             imported.update(alias.name.split(".")[0] for alias in node.names)
         elif isinstance(node, ast.ImportFrom) and node.module:
             imported.add(node.module.split(".")[0])
         elif isinstance(node, ast.Call):
             if isinstance(node.func, ast.Name):
-                called.add(node.func.id)
+                called_names.add(node.func.id)
             elif isinstance(node.func, ast.Attribute):
-                called.add(node.func.attr)
+                called_attrs.add(node.func.attr)
     assert imported.isdisjoint(
         {"subprocess", "socket", "requests", "httpx", "urllib", "sqlite3"}
     )
-    assert {"write_text", "write_bytes", "mkdir", "unlink", "replace"}.isdisjoint(called)
-    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
+    # Write authority is exercised through methods on a path object.
+    assert {"write_text", "write_bytes", "mkdir", "unlink", "replace"}.isdisjoint(
+        called_attrs
+    )
+    # Execution authority is the bare builtin; `re.compile` is an attribute on a
+    # module and is not code execution.
+    assert {"exec", "eval", "compile"}.isdisjoint(called_names)
+    assert {"system", "popen", "spawn", "fork", "execv"}.isdisjoint(called_attrs)
```

Consequences:
- Fixes 1.3 alone. Independent of A, B and C; can land in the same commit or a
  separate one.
- Strictly *stronger* than the current assertion, not weaker: `os.system` and
  `os.popen` are attribute calls and were only ever caught by accident of the
  merged set; the replacement checks them in the namespace they actually live in
  and adds `spawn`/`fork`/`execv`. The builtin set is checked where builtins
  actually appear.
- Edits a test, not production code. It relaxes nothing about what `report_v3`
  is permitted to do; `assert "begin_effect" not in source` and the
  `OwnerApproval`/`PromotionReceipt`/`Gate0ReleaseReceipt` assertions at lines
  88-91 are untouched.
- The alternative — rewriting `daedalus/gates/report_v3.py:30` to avoid
  `re.compile` — would edit production code to satisfy a test's misreading, and
  would leave the same test wrong for every other module. Rejected.

Rollback: `git revert`; test-only, no downstream coupling.

---

## 4. Recommendation

**Land D + B now; schedule A as a follow-up.**

Reasoning:

1. **D is not a judgement call.** `re.compile` is not code execution. The test is
   simply wrong, and the corrected form is stronger than what it replaces. It
   should not be bundled into the identity decision at all.

2. **B is the change that makes the artifact honest.** The owner block is
   "v3 scanner identity", and the substantive identity question is not
   *how do I key a record* but *what is a write surface*. A Gate 0 write-surface
   inventory in which ~200 of 505 blocking rows are `str.replace("\\", "/")` and
   `dataclasses.replace(record, ...)` does not describe the system's write
   surface; it describes the scanner's inability to tell a name from a type.
   Invariant 4 places the burden on evidence to be *valid*, not merely produced.
   B raises precision using a discriminator that is decidable from syntax, costs
   one file and sixteen lines, changes no schema, and is verified end-to-end
   against the live tree rather than a fixture.

3. **A is correct but is not urgent once B lands, and is dangerous to rush.**
   A changes the record shape, forces `daedalus-gate0-repository-write-inventory/1`
   to `/2`, and touches three production modules, a JSON schema with
   `additionalProperties: false`, and the pinned const at
   `tests/gates/test_repository_write_inventory_cli.py:67`. That is an
   artifact-identity change (invariant 2) and deserves its own reviewed commit
   with the schema migration written deliberately — not a commit whose purpose is
   to unblock three tests.

4. **B alone leaves a real hazard, and it must be recorded, not papered over.**
   B removes today's chained-call collisions; it does not remove the *mechanism*.
   The next contributor who writes `p.with_suffix(".tmp").write_text(a).…` — or
   any chained call on an expression receiver whose method is in `_PATH_METHODS`
   — reintroduces `callsites must be unique` and takes down the whole v3 family
   again, from a file that has nothing to do with the gates package. A is the
   only option that closes that mechanism. Recommendation is therefore B *first*
   for correctness of the evidence, A *next* for durability of the contract —
   not B *instead of* A.

5. **What is explicitly not recommended:** C, in either form. Deduplication does
   not work (measured), and the variant that makes it work deletes an
   artifact-identity invariant to silence a crash.

A defensible alternative, if the owner prefers one commit over two: land D + A
together and leave the false positives. That fixes all three tests and closes the
structural hazard, but it ships a Gate 0 inventory whose blocker list is 40%
noise, and the noise will have to be removed before the inventory can serve as a
Gate 0 exit artifact. The recommendation above prefers a truthful artifact first.

### Suggested landing order

| Step | Change | Fixes | Files |
| --- | --- | --- | --- |
| 1 | Option D | 1.3 | `tests/gates/test_gate_report_v3_review.py` |
| 2 | Option B | 1.1, 1.2 | `daedalus/gates/repository_write_inventory.py` |
| 3 | Option A (follow-up, own review) | structural hazard in 2.1 | 3 modules + schema + 1 test |
| 4 | Section 2.4 (follow-up) | error taxonomy | `daedalus/gates/report_v3.py` or the v2 wrapper |

---

## 5. Provenance

| Claim | Stamp | How |
| --- | --- | --- |
| three raw failure signatures | [MEASURED] | `PYTHONUTF8=1 python -m pytest <file> -x -q`, `7c88f72` |
| 3 failed / 43 passed across the v3+inventory family | [MEASURED] | one pytest run over 7 files |
| 275 files, 505 records, 496 distinct records, 492 distinct positions | [MEASURED] | scratch script driving `_production_files` + `_callsites_for_file` |
| duplicate and mixed-record position lists | [MEASURED] | same script, `collections.Counter` |
| kind and method histograms | [MEASURED] | same script |
| `.replace` arity table; zero `Path.replace(target)` calls | [MEASURED] | scratch AST walk over all 275 files |
| `os.replace` call sites | [MEASURED] | ripgrep over `daedalus/` |
| Option A satisfies both uniqueness contracts | [MEASURED, simulation] | classifier re-run with each candidate discriminator; dataclasses not constructed |
| Option B passes every assertion of 1.1 and 1.2 | [MEASURED, end-to-end] | in-process monkeypatch of `_classify_call` from a scratch script; real builder and real CLI; repository unmodified |
| Option C is insufficient | [MEASURED] | 496 records vs 492 positions against `repository_write_inventory_v2.py:109-111` |
| no real inventory digest is pinned anywhere | [MEASURED] | grep of `tests/` for `repository_write_inventory_sha256="`; grep of `runs/` for the schema name — no hits |
| blame dates on the three duplicate lines | [MEASURED] | `git log -1 -L <n>,<n>:<file>` |
| Iron Plan guard state | [MEASURED] | `python tools/iron_plan_guard.py (removed 2026-08-22) verify` |
| Option B never loses a future genuine `Path.replace` | [ASSUMED] | argued from the CPython signature; not provable without types. Zero instances exist today [MEASURED] |
| Option A's schema migration cost | [ASSUMED] | read from `additionalProperties: false` at schema lines 6/68 and the pinned const at `test_repository_write_inventory_cli.py:67`; migration not written or executed |
| the v3 report is the first live-tree consumer | [MEASURED] | `test_repository_write_inventory_cli.py:31-37` builds a `tmp_path` fixture; `test_gate_report_v3.py:213` passes `ROOT` |

Scratch scripts were written to the session scratchpad, outside the repository,
and are not retained as artifacts.

---

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: three named tests reproduced raw at `7c88f72`; identity defect located
at `repository_write_inventory.py:220-221`, `:708-709`, `:684`, `:618` and
`repository_write_inventory_v2.py:109-111`; Option A verified by simulation
(505/505/505), Option B verified end-to-end against the live tree (all builder
and CLI assertions PASS, rc=1), Option C refuted by measurement (496 records /
492 positions); no production file, test, or schema modified.
