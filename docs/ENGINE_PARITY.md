# Engine parity: `daedalus/structcore` (Python) vs `structcore-rs` (Rust)

**Status of this document:** measurement + source reading only. `cargo` is not on `PATH`
in the environment where this was written, so **no Rust code was built, run, or edited
while producing this file**. The wall-clock numbers in [§5](#5-wall-clock-measurements)
were taken earlier in the same session from an already-built binary. Everything else is
read directly off the two sources named below.

Sources of truth:

| Engine | File |
| --- | --- |
| Python | `daedalus/structcore/languages.py`, `daedalus/structcore/index.py`, `daedalus/structcore/ignore.py`, `daedalus/structcore/parse.py` |
| Rust | `structcore-rs/src/languages.rs`, `structcore-rs/src/index.rs`, `structcore-rs/src/parse.rs`, `structcore-rs/src/main.rs` |

---

## 1. Language coverage

Python registers 18 `LanguageSpec` entries covering 33 extensions. Rust registers 6
`LangSpec` entries covering 11 extensions. Rust's set is a strict subset of Python's.

### 1.1 Supported by both

| Language | Extensions | Python `function_types` | Rust `function_types` | Identical? |
| --- | --- | --- | --- | --- |
| python | `.py` `.pyi` | `function_definition` | `function_definition` | yes |
| rust | `.rs` | `function_item` | `function_item` | yes |
| javascript | `.js` `.jsx` `.mjs` `.cjs` | `function_declaration`, `method_definition`, `arrow_function` | same | yes |
| java | `.java` | `method_declaration`, `constructor_declaration` | same | yes |
| c | `.c` `.h` | `function_definition` | `function_definition` | yes |
| go | `.go` | `function_declaration`, `method_declaration` | same | yes |

`line_comment` / `block_comment` agree for all six.

### 1.2 Present in Python, **missing from Rust**

12 of 18 languages, 22 extensions. A file with one of these extensions is not counted,
not parsed, and contributes no units to Rust's clone pass — it is invisible, not merely
unparsed.

| Language | Extensions missing from Rust | Python `ts_grammar` | Python `function_types` |
| --- | --- | --- | --- |
| cpp | `.cpp` `.cc` `.cxx` `.hpp` `.hh` | `cpp` | `function_definition` |
| typescript | `.ts` `.tsx` `.mts` `.cts` | `typescript` | `function_declaration`, `method_definition`, `arrow_function` |
| csharp | `.cs` | `c_sharp` | `method_declaration`, `constructor_declaration` |
| **qml** | **`.qml`** | **`qmljs`** | **`function_declaration`, `ui_object_definition`** |
| css | `.css` | `css` | `rule_set` |
| qss | `.qss` | `css` | `rule_set` |
| scss | `.scss` `.sass` | `scss` | `rule_set`, `mixin_statement` |
| kotlin | `.kt` `.kts` | `kotlin` | `function_declaration` |
| swift | `.swift` | `swift` | `function_declaration` |
| ruby | `.rb` | `ruby` | `method`, `singleton_method` |
| php | `.php` | `php` | `function_definition`, `method_declaration` |
| lua | `.lua` | `lua` | `function_declaration`, `function_definition` |
| shell | `.sh` `.bash` | `bash` | `function_definition` |

### 1.3 The exact `.qml` entry a Rust port must add

Verbatim from `daedalus/structcore/languages.py`:

```python
LanguageSpec(
    name="qml",
    extensions=(".qml",),
    line_comment=("//",),
    block_comment=(("/*", "*/"),),
    ts_grammar="qmljs",
    function_types=("function_declaration", "ui_object_definition"),
    import_types=("import",),
    guard_keywords=("try", "catch"),
),
```

The Rust equivalent would be a `LangSpec` in `SPECS` in `structcore-rs/src/languages.rs`:

```rust
LangSpec {
    name: "qml",
    exts: &["qml"],            // NOTE: no leading dot — see §1.4
    language: lang_qml,        // needs a tree-sitter qmljs crate in Cargo.toml
    function_types: &["function_declaration", "ui_object_definition"],
    line_comment: &["//"],
    block_comment: Some(("/*", "*/")),
},
```

**Blocker, stated plainly:** `structcore-rs/Cargo.toml` has no QML grammar dependency,
and there is no first-party `tree-sitter-qmljs` crate on crates.io equivalent to the
`tree-sitter-language-pack` `qmljs` grammar Python uses. Adding `.qml` to Rust is a
dependency-sourcing problem, not a one-line registry edit. The same is true for
`qss`/`scss`/`kotlin`/`swift`/`php`/`lua`; `cpp`, `typescript`, `c_sharp`, `css`, `ruby`
and `bash` all have well-maintained crates and are the cheap wins.

### 1.4 Registry-shape differences a porter will hit

* **Dot convention differs.** Python keys `SPECS` by suffix *with* the dot (`".py"`,
  via `Path(path).suffix.lower()`). Rust's `spec_for_ext` matches *without* the dot
  (`"py"`, via `path.extension()`). Do not copy Python's tuples verbatim.
* **Rust `LangSpec` has no `import_types`, `guard_keywords`, or `safety_content` field.**
  Those three drive Python's dependency graph, over-defensiveness metric, and safety
  fence respectively. Porting a language to Rust today ports only its clone detection.
* Python's `qss` deliberately reuses the `css` grammar; a Rust port can do the same with
  one grammar function serving two `LangSpec` entries.

### 1.5 Repo walker: **at parity**

`structcore-rs/src/index.rs::IGNORE` and `daedalus/structcore/index.py::_IGNORE_DIRS`
contain the same 22 entries, and both additionally skip every dot-prefixed directory.
Both cap at 20000 files, and both apply the cap to *supported* files (after the
extension filter), not to every file on disk. Both count `total_chars` in characters
rather than bytes. This part was ported carefully and no divergence was found.

---

## 2. Measured evidence — `project_tct/TCT_app`

| Metric | Python | Rust | Delta |
| --- | --- | --- | --- |
| Files seen | **385** (344 `.py` + 41 `.qml`) | **344** | −41 |
| Exact (Type-1) clusters | **196** | **170** | −26 |

The file delta is **exactly** the `.qml` count, which tells us something useful: TCT_app
contains no `.cpp`, `.ts`, `.cs`, `.css`, `.qss`, `.scss`, `.kt`, `.swift`, `.rb`,
`.php`, `.lua`, or `.sh` files either. `.qml` is the *only* gap that bites on this
repo. Consequently the 344 files Rust indexed are the same 344 `.py` files Python
indexed — the populations are identical apart from QML.

**The 26-cluster delta is NOT yet attributed, and I am not going to guess.** Because the
Python-only files are all QML, the delta is *at most* fully explained by QML clusters —
but it could equally be, say, 30 QML clusters minus 4 clusters Rust finds on shared `.py`
files that Python does not (or vice versa). Distinguishing those requires re-running both
engines and diffing cluster fingerprints on the `.py` subset alone, which needs `cargo`.
**Until that diff is run, treat "Python and Rust agree on Python files" as unverified.**
It is the single most important open parity question in this document, because a
disagreement there would mean a normalization bug, not just a coverage gap.

`project_tct` overall contains 2,484 C files, so C behaviour (§4) matters at scale even
though it does not show up in the TCT_app subtree.

---

## 3. Output shape

Rust's `Index` struct (`structcore-rs/src/index.rs`) serializes exactly five top-level
keys:

```
root, n_files, languages, unit_clusters, total_chars
```

Python's `build_index` returns fifteen:

```
root, backend, n_files, ignored, languages, modules, dependencies,
import_edges, import_edges_reverse, fan_in, duplication, scope_key,
hotspots, module_heat, total_chars
```

(`scope_key` is the `(root, scope)` cache identity of the index. It exists so a
consumer holding only the index dict can fetch the symbol resolver built in the
same pass; a Rust port that implements no scope has nothing to mirror here.)

### 3.1 Missing from Rust entirely

`backend`, `ignored`, `modules`, `dependencies`, `import_edges`,
`import_edges_reverse`, `fan_in`, `scope_key`, `hotspots`, `module_heat` — ten keys. There is no
dependency graph, no fan-in, no hotspot ranking, and no scope/ignore reporting block on
the Rust side. Rust is an exact-clone engine and nothing more.

### 3.2 Nesting mismatch on the key they share

This is a real incompatibility, not a cosmetic one:

* Python: `idx["duplication"]["unit_clusters"]`, alongside sibling keys
  `renamed_clusters` (Type-2), `near_clusters` (Type-3), `window_clusters`, and
  `near_excluded_languages`.
* Rust: `idx["unit_clusters"]`, top level, with no `duplication` wrapper.

So even the one tier Rust implements is not drop-in readable by a Python consumer.
Rust implements **only Type-1**; Types 2 and 3 and the window pass do not exist there.

`languages` values agree in shape (`{files, loc}`) — Python builds
`{"files": 0, "loc": 0}` and Rust's `LangSum` has the same two fields. Python sorts
`languages` by descending LOC for display; Rust emits a `BTreeMap`, i.e. sorted by
language name. Both are deterministic, but the orders differ.

### 3.3 No Python code path invokes the Rust binary

Verified by searching every `.py` file in the repo for `structcore-rs`, `structcore_rs`,
`target/release`, and `cargo`: **zero matches**. `structcore-rs` is reachable only by
running its binary by hand (`structcore-rs <repo> --json <out>`, per
`structcore-rs/src/main.rs`). Nothing in the product, the API, or the test suite calls
it. It cannot currently cause a regression in shipped behaviour — and it is not covered
by `python -m pytest -q` either.

---

## 4. Scope / `.daedalusignore`: not implemented in Rust

`daedalus/structcore/ignore.py` is new this session. `structcore-rs` has **no equivalent
of any part of it**: no `.daedalusignore` parsing, no `center`, no environment variables,
no presets, and no withheld-file reporting. A Rust scan of a repo with a configured
center silently analyses the whole repo, including vendored trees.

That last word matters. Because Rust also emits no `ignored` block, there is no place in
its output where the discrepancy could even be noticed — which violates the project's
"never silently exclude" rule in the opposite direction: it never silently *excludes*,
but it silently *includes* material the repo has declared is not its code, and reports
metrics over it as if they were project metrics.

A Rust port must honour all of the following to be faithful:

1. **`.daedalusignore` at repo root**, gitignore-flavoured, parsed by `_parse_line`:
   * blank lines and `#` comments skipped;
   * `!foo` negates (re-includes);
   * trailing `/` means directory-only — and per `_hit`, a `dir_only` rule matches only
     *directory* segments, so `build/` must not swallow a **file** named `build`;
   * a pattern containing `/` (or a leading `/`) is repo-root **anchored**; otherwise it
     matches **any path segment at any depth**;
   * anchored rules also match by directory prefix (`docs/vendor` swallows
     `docs/vendor/x.py`), and `**` spans separators where `fnmatch`'s `*` does not.
2. **Last-match-wins ordering.** `IgnoreRules.matches` walks rules in order and keeps
   overwriting the verdict. Rule order is load-bearing; a port must not sort, dedupe, or
   short-circuit on first match.
3. **`center` (`ProjectScope`)** — the declarative half. `in_center(rel)` is true when
   `center` is empty (whole repo is core) or `rel` equals or is under any center root.
   Center paths are normalised by `_norm_center`: backslashes to `/`, stripped of
   leading/trailing `/`, `.` dropped, then **sorted and de-duplicated** so two configs
   naming the same roots in different order produce one cache entry.
4. **Three zones, and the middle one is the whole point.**
   * *core* — inside a center root: full metrics, clone passes, hotspots, free slice
     expansion.
   * *shell* — `is_shell(rel)` is `(not in_center) or ignore.matches(rel)`: **still
     indexed and still parsed**, so it remains resolvable as an import target and its own
     outgoing edges stay honest, but withheld from `modules`, `dependencies`, `hotspots`,
     `module_heat`, the language/LOC summary, and **every clone pass** — and treated as a
     boundary by the slicer (you may name it, you do not expand through it).
   * *outside* — not in the repo: an external name.
5. **Precedence and composition.** `project_scope` takes an explicit `center` argument
   over `DAEDALUS_CENTER`. Ignore rules compose in the fixed order
   `.daedalusignore` → `DAEDALUS_IGNORE` → `extra_ignore` (project config), later
   winning because matching is last-match-wins — which is the only mechanism by which a
   project config can re-include (`!path`) something the shared repo file excluded.
6. **Environment variables**, both `os.pathsep`-separated: `DAEDALUS_IGNORE` (patterns),
   `DAEDALUS_CENTER` (repo-relative roots).
7. **Presets.** `IGNORE_PRESETS["@tests"]` expands to
   `tests/`, `test/`, `test_*.py`, `*_test.py`, `*_test.go`, `conftest.py`, `__tests__/`,
   `*.test.ts`, `*.test.tsx`, `*.test.js`, `*.spec.ts`, `*.spec.js`.
   An unknown `@name` is **passed through unchanged, never dropped** — a silent no-op
   would be indistinguishable from a preset that did nothing.
8. **Fingerprints feed the cache key.** `IgnoreRules.fingerprint` is
   `sha256(raw file text)[:16]`; `ProjectScope.fingerprint` is
   `sha256("|".join(center) + "#" + ignore.fingerprint)[:16]`. Without folding these into
   the index cache key, editing the ignore file hands back a stale index and looks exactly
   like the feature not working.
9. **Report the withholding.** Python emits an `ignored` block —
   `count`, `n_files_scanned`, the `describe()` payload (`center`, `ignore_patterns`,
   `source`), a `sorted(...)[:25]` sample and a `truncated` flag. Exclusion is never
   silent, and the sample is sorted for byte-identical output across runs.

---

## 5. Wall-clock measurements

Taken this session:

| Run | Wall clock |
| --- | --- |
| Rust, full `project_tct` | **216.4 s** |
| Rust, `TCT_app` | **3.5 s** |
| Python, `TCT_app`, full pipeline | **26.0 s** |
| Python, `TCT_app`, exact clusters only | **4.6 s** |

**These are not a clean speed ratio and must not be quoted as one.** Confounds, all
material:

* **Cache asymmetry (the big one).** Python was running against a *warm content-hash disk
  cache*; Rust has no cache at all and did full work every time. The 3.5 s vs 4.6 s
  comparison is warm-Python against cold-Rust.
* **Different amounts of work.** Python's 26.0 s full pipeline includes the dependency
  graph, fan-in, hotspots, module heat, and Type-2/Type-3/window clone passes — none of
  which Rust implements. Only the 4.6 s figure is tier-comparable to Rust's 3.5 s.
* **Different file populations.** Python processed 385 files, Rust 344 (§2). Rust did
  ~11% less input work in the TCT_app runs.

The honest summary: on this evidence the two engines are in the *same order of magnitude*
on the exact-clone tier, and no stronger claim is supported. Establishing a real ratio
needs a cold-cache Python run against the identical file set — which needs `cargo`.

---

## 6. Known defect shared by both engines: C/C++ function naming

Flagged here because it changes what "achieving parity" means.

Python's `_ts_name` (`daedalus/structcore/parse.py`) scans only the **direct** children of
a node for the identifier. C and C++ nest the name under
`declarator → function_declarator`, so it is never found and the unit is named
`<anonymous>`.

**Rust has the same class of defect**, via a different route.
`structcore-rs/src/parse.rs::node_name` first tries `child_by_field_name("name")` — which
C's `function_definition` does not have, since its fields are `type`, `declarator`, `body`
— and then falls back to scanning direct children for
`identifier | field_identifier | type_identifier`. It does not descend into
`function_declarator` either. On a function returning a typedef'd type, that fallback
matches the `type_identifier` **return type** and names the unit after it.

Two consequences for whoever does the port:

1. **Fixing S1 in Python widens the divergence.** Once Python names C/C++ functions
   correctly, its C unit names, clone clusters, and call graph will all differ from
   Rust's until `node_name` is fixed to walk into `declarator`/`function_declarator`.
   Any future parity diff over a C-bearing repo will be dominated by this and should not
   be read as a normalization regression.
2. **Rust's fallback is internally inconsistent**: it returns `"<anon>"` on a UTF-8
   decode failure but `"<anonymous>"` when no candidate child is found. Python uses
   `"<anonymous>"` throughout. Since `clones.py` filters on the literal string
   `"<anonymous>"`, a port that emits `"<anon>"` would leak unnamed units past a filter
   that was meant to catch them. Standardise on `"<anonymous>"`.

---

## 7. Summary for a porter, in priority order

1. Fix `node_name` in `structcore-rs/src/parse.rs` to descend through `declarator` /
   `function_declarator`, and standardise the sentinel on `"<anonymous>"` (§6).
2. Add the cheap grammars that already have good crates: `cpp`, `typescript`, `c_sharp`,
   `css`, `ruby`, `bash` (§1.2).
3. Run a fingerprint-level cluster diff on a Python-only file set to settle whether the
   26-cluster delta is pure coverage or partly a normalization disagreement (§2). This
   should happen **before** any further feature porting.
4. Implement `ProjectScope` / `.daedalusignore` — all nine requirements in §4, including
   the `ignored` reporting block.
5. Source or vendor a QML grammar (§1.3) — the largest single coverage gap on the
   reference repo, but dependency-blocked.
6. Only then consider `import_edges` / `fan_in` / `hotspots`, and align the
   `duplication.unit_clusters` nesting (§3.2).
