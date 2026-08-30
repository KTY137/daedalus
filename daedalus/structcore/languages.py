# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""LanguageSpec registry — declarative per-language facts, keyed by extension.

Adding a language is *data*, not code: one ``LanguageSpec`` entry. Fields are
consumed by three backends:

  * the stdlib/lexical path (always available) uses ``line_comment`` /
    ``block_comment`` / ``guard_keywords`` for comment-aware metrics and the
    universal windowed clone pass;
  * the tree-sitter path (optional) uses ``ts_grammar`` + ``function_types`` +
    ``import_types`` for precise unit-level extraction;
  * the safety fence uses ``safety_content`` regexes to raise the risk tier
    (Rust ``unsafe``, C register writes, …) on top of the path-based fence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    extensions: tuple[str, ...]
    line_comment: tuple[str, ...] = ()
    block_comment: tuple[tuple[str, str], ...] = ()
    # Quote characters that open a string/char literal. Load-bearing for comment
    # stripping: a "//" or "/*" INSIDE a string is not a comment, and treating it
    # as one silently deletes real code (see clones._strip_comments_generic).
    # Default covers the C family; override where ' is not a string opener --
    # Rust lifetimes ('a) and Swift, where consuming to the next ' would eat code.
    string_delims: tuple[str, ...] = ('"', "'")
    # tree-sitter-language-pack grammar name (optional precision backend)
    ts_grammar: str = ""
    # node types that count as an editable/clone-able unit
    function_types: tuple[str, ...] = ()
    # node types carrying an import/include/use edge
    import_types: tuple[str, ...] = ()
    # over-defensiveness signal (try/except density analog), counted lexically
    guard_keywords: tuple[str, ...] = ()
    # language-specific high-risk body markers -> raise risk tier (advisory)
    safety_content: tuple[re.Pattern, ...] = field(default_factory=tuple)


def _rx(*pats: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p) for p in pats)


# One entry per language. Node-type names follow the corresponding
# tree-sitter grammar; they are only read when tree-sitter is installed.
_SPECS: tuple[LanguageSpec, ...] = (
    LanguageSpec(
        name="python",
        extensions=(".py", ".pyi"),
        line_comment=("#",),
        ts_grammar="python",
        function_types=("function_definition",),
        import_types=("import_statement", "import_from_statement"),
        guard_keywords=("try", "except", "finally"),
    ),
    LanguageSpec(
        name="c",
        extensions=(".c", ".h"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="c",
        function_types=("function_definition",),
        import_types=("preproc_include",),
        guard_keywords=("goto", "return", "assert"),
        safety_content=_rx(r"\bvolatile\b", r"\*\s*\(\s*volatile", r"\b__asm\b",
                           r"\binb\b|\boutb\b", r"0x[0-9A-Fa-f]{6,}"),
    ),
    LanguageSpec(
        name="cpp",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="cpp",
        function_types=("function_definition",),
        import_types=("preproc_include",),
        guard_keywords=("try", "catch", "throw", "assert"),
        safety_content=_rx(r"\bvolatile\b", r"reinterpret_cast", r"\b__asm\b"),
    ),
    LanguageSpec(
        name="java",
        extensions=(".java",),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="java",
        function_types=("method_declaration", "constructor_declaration"),
        import_types=("import_declaration",),
        guard_keywords=("try", "catch", "finally", "throws", "throw"),
        safety_content=_rx(r"\bnative\b", r"Runtime\.getRuntime\(\)\.exec",
                           r"\bUnsafe\b", r"System\.load"),
    ),
    LanguageSpec(
        name="rust",
        string_delims=('"',),   # 'a is a lifetime, not a string
        extensions=(".rs",),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="rust",
        function_types=("function_item",),
        import_types=("use_declaration",),
        guard_keywords=("match", "Result", "unwrap", "?"),
        safety_content=_rx(r"\bunsafe\b", r"\basm!|\bglobal_asm!",
                           r"\btransmute\b", r"#\[no_mangle\]", r"\*mut\b|\*const\b"),
    ),
    LanguageSpec(
        name="go",
        string_delims=('"', "'", "`"),   # ` opens a raw string
        extensions=(".go",),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="go",
        function_types=("function_declaration", "method_declaration"),
        import_types=("import_spec",),
        guard_keywords=("if err", "recover", "panic", "defer"),
        safety_content=_rx(r"\bunsafe\.", r"//go:nosplit"),
    ),
    LanguageSpec(
        name="javascript",
        string_delims=('"', "'", "`"),
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="javascript",
        function_types=("function_declaration", "method_definition", "arrow_function"),
        import_types=("import_statement",),
        guard_keywords=("try", "catch", "finally", "throw"),
        safety_content=_rx(r"\beval\s*\(", r"child_process", r"dangerouslySetInnerHTML"),
    ),
    LanguageSpec(
        name="typescript",
        string_delims=('"', "'", "`"),
        extensions=(".ts", ".tsx", ".mts", ".cts"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="typescript",
        function_types=("function_declaration", "method_definition", "arrow_function"),
        import_types=("import_statement",),
        guard_keywords=("try", "catch", "finally", "throw"),
        safety_content=_rx(r"\beval\s*\(", r"child_process", r"dangerouslySetInnerHTML"),
    ),
    LanguageSpec(
        name="csharp",
        extensions=(".cs",),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="c_sharp",
        function_types=("method_declaration", "constructor_declaration"),
        import_types=("using_directive",),
        guard_keywords=("try", "catch", "finally", "throw"),
        safety_content=_rx(r"\bunsafe\b", r"DllImport", r"Marshal\."),
    ),
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
    # --- styling / markup (GUI look-and-feel; clone-heavy, caught well at
    #     window level even when the grammar is imperfect) ---
    LanguageSpec(
        name="css",
        extensions=(".css",),
        block_comment=(("/*", "*/"),),
        ts_grammar="css",
        function_types=("rule_set",),
    ),
    LanguageSpec(
        # Qt Style Sheets — CSS-like; the css grammar parses most of it, and the
        # window-clone pass catches duplicated style blocks regardless.
        name="qss",
        extensions=(".qss",),
        block_comment=(("/*", "*/"),),
        ts_grammar="css",
        function_types=("rule_set",),
    ),
    LanguageSpec(
        name="scss",
        extensions=(".scss", ".sass"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="scss",
        function_types=("rule_set", "mixin_statement"),
    ),
    # --- more languages (each is one line of coverage) ---
    LanguageSpec(
        name="kotlin",
        extensions=(".kt", ".kts"),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="kotlin",
        function_types=("function_declaration",),
        import_types=("import_header",),
        guard_keywords=("try", "catch", "finally", "throw"),
    ),
    LanguageSpec(
        name="swift",
        string_delims=('"',),
        extensions=(".swift",),
        line_comment=("//",),
        block_comment=(("/*", "*/"),),
        ts_grammar="swift",
        function_types=("function_declaration",),
        import_types=("import_declaration",),
        guard_keywords=("guard", "try", "catch", "do", "throw"),
    ),
    LanguageSpec(
        name="ruby",
        extensions=(".rb",),
        line_comment=("#",),
        ts_grammar="ruby",
        function_types=("method", "singleton_method"),
        guard_keywords=("begin", "rescue", "ensure", "raise"),
    ),
    LanguageSpec(
        name="php",
        extensions=(".php",),
        line_comment=("//", "#"),
        block_comment=(("/*", "*/"),),
        ts_grammar="php",
        function_types=("function_definition", "method_declaration"),
        import_types=("namespace_use_declaration",),
        guard_keywords=("try", "catch", "finally", "throw"),
    ),
    LanguageSpec(
        name="lua",
        extensions=(".lua",),
        line_comment=("--",),
        ts_grammar="lua",
        function_types=("function_declaration", "function_definition"),
        guard_keywords=("pcall", "error"),
    ),
    LanguageSpec(
        name="shell",
        extensions=(".sh", ".bash"),
        line_comment=("#",),
        ts_grammar="bash",
        function_types=("function_definition",),
        guard_keywords=("trap", "set -e"),
    ),
)


# Extension -> spec, built once.
SPECS: dict[str, LanguageSpec] = {}
for _spec in _SPECS:
    for _ext in _spec.extensions:
        SPECS[_ext] = _spec


def spec_for(path) -> LanguageSpec | None:
    """Return the LanguageSpec for a path by extension, or None if unsupported."""
    from pathlib import Path

    return SPECS.get(Path(path).suffix.lower())


# --------------------------------------------------------------------------- #
# DOCUMENTS — a second node kind, deliberately a SEPARATE registry              #
# --------------------------------------------------------------------------- #
# A DocumentSpec is NOT a LanguageSpec and ``.md`` is deliberately NOT added to
# ``SPECS``. ``spec_for`` is not a lookup table, it is a CLAIM, and thirteen call
# sites read it as one:
#
#   * ``index._collect``          -- non-None decides what enters ``modules``;
#   * ``provider_router._looks_like_missed_source`` -- non-None + on disk + not a
#     graph node ⇒ ESCALATE the change-risk tier. Every .md in the repo would
#     start reading as "a source file the graph should have known about";
#   * ``eval/harness._whole_repo_text`` / ``_repo_chunks`` -- non-None decides
#     what the Tier-2 A/B baseline concatenates, i.e. the published denominator;
#   * ``eval/mint`` -- non-None makes a file an eligible label source, and a
#     markdown anchor would discard every code label as "cross-language";
#   * ``eval/ceiling._symbol_defs``, ``slice._skeleton``, ``room._skeleton`` --
#     non-None means "unit-level ground truth exists here", which for prose is
#     false.
#
# Every one of those reads is CORRECT about a document: prose has no functions,
# no imports and no clone units. So the honest move is to leave ``spec_for``
# answering None for documents -- it keeps its meaning, and all thirteen call
# sites keep theirs -- and to give documents their own registry that only the
# document path consults.
@dataclass(frozen=True)
class DocumentSpec:
    """Declarative facts about a document format. Same shape of contract as
    ``LanguageSpec``: adding a format is data, not code."""

    name: str
    extensions: tuple[str, ...]
    # Human-readable statement of what the parser is able to derive, carried
    # into the index so a consumer never has to infer coverage from silence.
    hierarchy: str = ""
    unit: str = ""


_DOC_SPECS: tuple[DocumentSpec, ...] = (
    DocumentSpec(
        name="markdown",
        # PDF is deliberately absent: no reliable structure, lossy extraction,
        # and it raises a separate egress question. Out of scope, on purpose.
        extensions=(".md", ".markdown", ".mdx"),
        hierarchy="heading levels (H1 -> H2 -> H3)",
        unit="section (heading + body up to the next heading of equal or higher level)",
    ),
)

DOC_SPECS: dict[str, DocumentSpec] = {}
for _dspec in _DOC_SPECS:
    for _ext in _dspec.extensions:
        DOC_SPECS[_ext] = _dspec

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(DOC_SPECS)


def doc_spec_for(path) -> DocumentSpec | None:
    """Return the DocumentSpec for a path by extension, or None.

    Independent of ``spec_for``: a path answers non-None to exactly one of them
    (or to neither). Nothing answers both.
    """
    from pathlib import Path

    return DOC_SPECS.get(Path(path).suffix.lower())
