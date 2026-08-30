// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

//! Parse a source file with tree-sitter and extract function/method units.
//! Mirrors `daedalus/structcore/parse.py::extract_units`.

use crate::languages::LangSpec;
use tree_sitter::{Node, Parser};

pub struct Unit {
    pub module: String,
    pub name: String,
    pub language: String,
    pub line: usize,
    pub loc: usize,
    pub source: String,
}

pub fn extract_units(module: &str, text: &str, spec: &LangSpec) -> Vec<Unit> {
    let mut parser = Parser::new();
    if parser.set_language(&(spec.language)()).is_err() {
        return Vec::new();
    }
    let tree = match parser.parse(text, None) {
        Some(t) => t,
        None => return Vec::new(),
    };
    let bytes = text.as_bytes();
    let mut units = Vec::new();
    let mut stack = vec![tree.root_node()];
    while let Some(node) = stack.pop() {
        if spec.function_types.contains(&node.kind()) {
            let start = node.start_position().row + 1;
            let end = node.end_position().row + 1;
            let source = node.utf8_text(bytes).unwrap_or("").to_string();
            units.push(Unit {
                module: module.to_string(),
                name: node_name(&node, bytes),
                language: spec.name.to_string(),
                line: start,
                loc: end.saturating_sub(start) + 1,
                source,
            });
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            stack.push(child);
        }
    }
    units
}

fn node_name(node: &Node, bytes: &[u8]) -> String {
    if let Some(name) = node.child_by_field_name("name") {
        return name.utf8_text(bytes).unwrap_or("<anon>").to_string();
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if matches!(child.kind(), "identifier" | "field_identifier" | "type_identifier") {
            return child.utf8_text(bytes).unwrap_or("<anon>").to_string();
        }
    }
    "<anonymous>".to_string()
}
