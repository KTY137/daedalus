// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

//! LanguageSpec registry — mirrors `daedalus/structcore/languages.py` (subset).
//! One entry per language: extensions, the tree-sitter grammar, the node types
//! that count as a clone-able unit, and comment markers for normalization.

use tree_sitter::Language;

pub struct LangSpec {
    pub name: &'static str,
    pub exts: &'static [&'static str],
    pub language: fn() -> Language,
    pub function_types: &'static [&'static str],
    pub line_comment: &'static [&'static str],
    pub block_comment: Option<(&'static str, &'static str)>,
}

fn lang_python() -> Language {
    tree_sitter_python::LANGUAGE.into()
}
fn lang_rust() -> Language {
    tree_sitter_rust::LANGUAGE.into()
}
fn lang_javascript() -> Language {
    tree_sitter_javascript::LANGUAGE.into()
}
fn lang_java() -> Language {
    tree_sitter_java::LANGUAGE.into()
}
fn lang_c() -> Language {
    tree_sitter_c::LANGUAGE.into()
}
fn lang_go() -> Language {
    tree_sitter_go::LANGUAGE.into()
}

pub static SPECS: &[LangSpec] = &[
    LangSpec {
        name: "python",
        exts: &["py", "pyi"],
        language: lang_python,
        function_types: &["function_definition"],
        line_comment: &["#"],
        block_comment: None,
    },
    LangSpec {
        name: "rust",
        exts: &["rs"],
        language: lang_rust,
        function_types: &["function_item"],
        line_comment: &["//"],
        block_comment: Some(("/*", "*/")),
    },
    LangSpec {
        name: "javascript",
        exts: &["js", "jsx", "mjs", "cjs"],
        language: lang_javascript,
        function_types: &["function_declaration", "method_definition", "arrow_function"],
        line_comment: &["//"],
        block_comment: Some(("/*", "*/")),
    },
    LangSpec {
        name: "java",
        exts: &["java"],
        language: lang_java,
        function_types: &["method_declaration", "constructor_declaration"],
        line_comment: &["//"],
        block_comment: Some(("/*", "*/")),
    },
    LangSpec {
        name: "c",
        exts: &["c", "h"],
        language: lang_c,
        function_types: &["function_definition"],
        line_comment: &["//"],
        block_comment: Some(("/*", "*/")),
    },
    LangSpec {
        name: "go",
        exts: &["go"],
        language: lang_go,
        function_types: &["function_declaration", "method_declaration"],
        line_comment: &["//"],
        block_comment: Some(("/*", "*/")),
    },
];

pub fn spec_for_ext(ext: &str) -> Option<&'static LangSpec> {
    SPECS.iter().find(|s| s.exts.contains(&ext))
}
