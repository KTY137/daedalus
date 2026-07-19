//! Clone detection — normalize, SHA1-fingerprint, cluster exact clones.
//! Mirrors `daedalus/structcore/clones.py` (exact / Type-1 tier).
//!
//! NORMALIZATION IS STRUCTURAL (tree-sitter), not lexical. The Python oracle
//! uses a DIFFERENT strategy per language, and cluster membership only matches
//! if we mirror each one, so this module has two normalizers:
//!
//!   * python  -> `_normalize_python`: the stdlib `tokenize` lexer, emitting
//!     `" ".join(tok.string)`. Comments/NL/NEWLINE/INDENT/DEDENT are dropped and
//!     bare triple-quoted strings (block docstrings) are dropped entirely; every
//!     other token is space-separated. Because tokens are re-joined with a
//!     single space, the oracle is INSENSITIVE to intra-line spacing (`x+1` and
//!     `x + 1` fingerprint the same). We reproduce that by walking the
//!     tree-sitter parse tree and joining LEAF nodes with a space. The two
//!     tokenizers need not agree byte-for-byte on the normalized string -- they
//!     must induce the same equivalence classes, which is what membership
//!     parity measures.
//!
//!   * everything else -> `_normalize_generic`: strip comments, then collapse
//!     all whitespace. This preserves intra-line spacing distinctions, so a
//!     token-join here would be COARSER than the oracle and would merge
//!     clusters the oracle keeps apart. We therefore keep the oracle's
//!     whitespace semantics and only make the comment detection structural:
//!     comment NODE spans are blanked out, then whitespace is collapsed. This
//!     is strictly more correct than the oracle's `line.find("//")` (a `//` or
//!     `#` inside a string literal no longer truncates the line) and identical
//!     everywhere else.
//!
//! Both walks are ITERATIVE. A recursive walk blows the stack on deeply nested
//! real-world ASTs (long chained/generated expressions) — the same bug that was
//! just fixed in the Python `parse.py`/`imports.py` walks.

use crate::languages::LangSpec;
use crate::parse::Unit;
use sha1::{Digest, Sha1};
use std::cell::RefCell;
use std::collections::HashMap;
use tree_sitter::{Node, Parser, Tree};

// One parser per language per thread, reused across every unit. Building a
// Parser + Language for each of ~10k units is the dominant cost otherwise.
thread_local! {
    static PARSERS: RefCell<HashMap<&'static str, Option<Parser>>> =
        RefCell::new(HashMap::new());
}

fn parse_with<T>(source: &str, spec: &LangSpec, f: impl FnOnce(&Tree) -> T) -> Option<T> {
    PARSERS.with(|cell| {
        let mut map = cell.borrow_mut();
        let slot = map.entry(spec.name).or_insert_with(|| {
            let mut parser = Parser::new();
            match parser.set_language(&(spec.language)()) {
                Ok(()) => Some(parser),
                Err(_) => None,
            }
        });
        let parser = slot.as_mut()?;
        let tree = parser.parse(source, None)?;
        Some(f(&tree))
    })
}

/// Grammars disagree on the node name: `comment` (c/go/java/js/python),
/// `line_comment`/`block_comment`/`doc_comment` (rust). Match the family.
fn is_comment_kind(kind: &str) -> bool {
    kind.contains("comment")
}

fn collapse_ws(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn push_children_in_order<'a>(node: Node<'a>, stack: &mut Vec<Node<'a>>) {
    let mut cursor = node.walk();
    // Push reversed so children pop back in source order (pre-order walk).
    let children: Vec<Node> = node.children(&mut cursor).collect();
    for child in children.into_iter().rev() {
        stack.push(child);
    }
}

/// Does this node contain non-whitespace source text that NONE of its children
/// cover? Grammars hide tokens: in tree-sitter-python a `string_content` node's
/// only visible children are the `escape_sequence`s, so the literal text
/// between them belongs to no child. A leaf-only walk silently DROPS that text
/// — and dropping text fabricates clone clusters (every `"\tfoo\n"` collapses
/// to the same `\t \n`), which is the worst failure mode this engine has: it
/// recommends merging code that is not duplicated. When we detect it, we emit
/// the node verbatim instead of descending, so no source text can ever be lost.
fn hides_text(node: Node, source: &str) -> bool {
    let mut cursor = node.walk();
    let mut pos = node.start_byte();
    for child in node.children(&mut cursor) {
        if child.start_byte() > pos {
            match source.get(pos..child.start_byte()) {
                Some(gap) if gap.trim().is_empty() => {}
                _ => return true,
            }
        }
        pos = pos.max(child.end_byte());
    }
    if pos < node.end_byte() {
        return !matches!(source.get(pos..node.end_byte()), Some(gap) if gap.trim().is_empty());
    }
    false
}

/// Mirrors `clones._normalize_python`: space-joined token stream, comments and
/// bare triple-quoted strings dropped.
fn normalize_python(source: &str, spec: &LangSpec) -> Option<String> {
    parse_with(source, spec, |tree| {
        let bytes = source.as_bytes();
        let mut out: Vec<&str> = Vec::new();
        let mut stack = vec![tree.root_node()];
        while let Some(node) = stack.pop() {
            let kind = node.kind();
            if is_comment_kind(kind) || kind == "line_continuation" {
                continue; // `tokenize` emits neither
            }
            if kind == "string" {
                // `tok.string[:3] in ('"""', "'''")` — the PREFIX matters:
                // `f"""..."""` starts with `f""` and is KEPT by the oracle.
                let text = node.utf8_text(bytes).unwrap_or("");
                if text.starts_with("\"\"\"") || text.starts_with("'''") {
                    continue;
                }
                // Emit the literal VERBATIM rather than descending. On the
                // interpreter this repo runs (3.10) `tokenize` emits exactly one
                // STRING token per literal, f-strings included, so atomic is the
                // faithful mirror. CAVEAT: 3.12+ splits f-strings into
                // FSTRING_START/MIDDLE/END plus real tokens for the interpolated
                // expression, which makes the oracle blind to spacing inside
                // `{...}` (`f"{a+1}"` == `f"{a + 1}"`). We stay sensitive there.
                // Revisit if the oracle's interpreter moves to 3.12+.
                if !text.trim().is_empty() {
                    out.push(text);
                }
                continue;
            }
            if node.child_count() == 0 || hides_text(node, source) {
                let text = node.utf8_text(bytes).unwrap_or("");
                if !text.trim().is_empty() {
                    out.push(text);
                }
                continue;
            }
            push_children_in_order(node, &mut stack);
        }
        out.join(" ")
    })
}

/// Mirrors `clones._normalize_generic`, but detects comments structurally:
/// blank out every comment node's byte span, then collapse whitespace.
fn normalize_generic(source: &str, spec: &LangSpec) -> Option<String> {
    parse_with(source, spec, |tree| {
        let mut buf = source.as_bytes().to_vec();
        let mut stack = vec![tree.root_node()];
        while let Some(node) = stack.pop() {
            if is_comment_kind(node.kind()) {
                // Node boundaries are char boundaries, so blanking whole bytes
                // (newlines included, as the oracle's DOTALL regex does) leaves
                // the buffer valid UTF-8.
                let (start, end) = (node.start_byte(), node.end_byte().min(buf.len()));
                if start < end {
                    buf[start..end].fill(b' ');
                }
                continue;
            }
            if node.child_count() == 0 {
                continue;
            }
            push_children_in_order(node, &mut stack);
        }
        collapse_ws(&String::from_utf8_lossy(&buf))
    })
}

/// Last-resort lexical strip, used only when the grammar fails to load or the
/// parser returns no tree. Matches the pre-tree-sitter behaviour.
fn normalize_lexical(source: &str, spec: &LangSpec) -> String {
    let mut text = source.to_string();
    if let Some((open, close)) = spec.block_comment {
        while let Some(a) = text.find(open) {
            if let Some(rel) = text[a + open.len()..].find(close) {
                let end = a + open.len() + rel + close.len();
                text.replace_range(a..end, " ");
            } else {
                break;
            }
        }
    }
    let mut lines = Vec::new();
    for raw in text.lines() {
        let mut line = raw.trim().to_string();
        for marker in spec.line_comment {
            if let Some(idx) = line.find(marker) {
                line.truncate(idx);
            }
        }
        let trimmed = line.trim();
        if !trimmed.is_empty() {
            lines.push(trimmed.to_string());
        }
    }
    collapse_ws(&lines.join(" "))
}

pub fn normalize(source: &str, spec: &LangSpec) -> String {
    let structural = if spec.name == "python" {
        normalize_python(source, spec)
    } else {
        normalize_generic(source, spec)
    };
    structural.unwrap_or_else(|| normalize_lexical(source, spec))
}

pub fn fingerprint(source: &str, spec: &LangSpec) -> String {
    let mut hasher = Sha1::new();
    hasher.update(normalize(source, spec).as_bytes());
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{:02x}", b)).collect();
    hex[..12].to_string()
}

pub struct Cluster {
    pub fingerprint: String,
    pub language: String,
    pub name: String,
    pub count: usize,
    pub loc: usize,
    pub sites: Vec<(String, usize)>,
}

pub fn unit_clusters(units: &[(Unit, &'static LangSpec)]) -> Vec<Cluster> {
    let mut by_print: HashMap<String, Vec<&(Unit, &'static LangSpec)>> = HashMap::new();
    for entry in units {
        if entry.0.loc < 4 {
            continue;
        }
        let fp = fingerprint(&entry.0.source, entry.1);
        by_print.entry(fp).or_default().push(entry);
    }
    let mut clusters = Vec::new();
    for (fp, group) in by_print {
        if group.len() < 2 {
            continue;
        }
        clusters.push(Cluster {
            fingerprint: fp,
            language: group[0].0.language.clone(),
            name: group[0].0.name.clone(),
            count: group.len(),
            loc: group[0].0.loc,
            sites: group.iter().map(|g| (g.0.module.clone(), g.0.line)).collect(),
        });
    }
    clusters.sort_by(|a, b| (b.count * b.loc).cmp(&(a.count * a.loc)));
    clusters
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::languages::spec_for_ext;

    fn py() -> &'static LangSpec {
        spec_for_ext("py").unwrap()
    }
    fn rs() -> &'static LangSpec {
        spec_for_ext("rs").unwrap()
    }

    // --- python path: must reproduce `tokenize`-join equivalence classes ---

    #[test]
    fn python_is_insensitive_to_intra_line_spacing() {
        // The oracle re-joins tokens with one space, so these collide. The old
        // lexical normalizer kept them apart — this is the parity bug.
        let a = "def f(x):\n    return x+1\n";
        let b = "def f( x ):\n    return  x  +  1\n";
        assert_eq!(normalize(a, py()), normalize(b, py()));
        assert_eq!(fingerprint(a, py()), fingerprint(b, py()));
    }

    #[test]
    fn python_drops_comments_and_block_docstrings() {
        let a = "def f(x):\n    \"\"\"Doc.\"\"\"\n    return x  # tail\n";
        let b = "def f(x):\n    return x\n";
        assert_eq!(normalize(a, py()), normalize(b, py()));
    }

    #[test]
    fn python_keeps_inline_and_prefixed_string_literals() {
        // Only BARE triple-quoted strings are dropped: `f"""..."""` starts with
        // `f""` and the oracle keeps it. Inline literals are always kept.
        let plain = "def f():\n    return \"a\"\n";
        let other = "def f():\n    return \"b\"\n";
        assert_ne!(normalize(plain, py()), normalize(other, py()));

        let fstr = "def f():\n    return f\"\"\"a\"\"\"\n";
        let dropped = "def f():\n    return\n";
        assert_ne!(normalize(fstr, py()), normalize(dropped, py()));
        assert!(normalize(fstr, py()).contains("a"));
    }

    #[test]
    fn python_bare_triple_quoted_is_dropped_anywhere() {
        // `tok.string[:3]` is checked on every STRING token, not just docstrings.
        let a = "def f():\n    x = \"\"\"body\"\"\"\n    return x\n";
        let b = "def f():\n    x = \"\"\"other\"\"\"\n    return x\n";
        assert_eq!(normalize(a, py()), normalize(b, py()));
    }

    #[test]
    fn python_string_bodies_with_escapes_are_not_collapsed() {
        // REGRESSION: tree-sitter-python exposes only the `escape_sequence`
        // children of `string_content`; the literal text between them belongs
        // to no child. A leaf-only walk dropped it, so these two normalized to
        // the same `\t ... \n` and got reported as a clone cluster the oracle
        // (which keeps inline literals) never produced. Measured on
        // project_tct: 4 win32com `GetParsePostCode` methods wrongly merged.
        let a = "def f(self):\n    return \"\\tif (PyWinLong_AsULONG(ob))\\n\".format(1)\n";
        let b = "def f(self):\n    return \"\\tif (PyWinObject_AsTCHAR(ob))\\n\".format(1)\n";
        assert_ne!(normalize(a, py()), normalize(b, py()));
        assert!(normalize(a, py()).contains("PyWinLong_AsULONG"));
    }

    #[test]
    fn python_normalization_preserves_every_non_whitespace_char() {
        // The general invariant behind `hides_text`: normalization may reorder
        // whitespace and drop comments/docstrings, but it must never lose
        // source text, because lost text manufactures false clones.
        let src = "def f(x):\n    s = \"a\\tb c\\nd\"\n    return s + f\"{x!r:>10}\" + '\\N{BULLET}'\n";
        let norm = normalize(src, py());
        // Compare with whitespace removed: normalization is free to insert or
        // drop whitespace between tokens, but must not lose a single glyph.
        let squash = |s: &str| s.chars().filter(|c| !c.is_whitespace()).collect::<String>();
        let (got, want) = (squash(&norm), squash(src));
        for frag in ["a\\tbc\\nd", "f\"{x!r:>10}\"", "'\\N{BULLET}'"] {
            assert!(got.contains(frag), "lost {frag:?} from {norm:?}");
        }
        // This snippet has no comments or docstrings, so nothing is legitimately
        // dropped: the token stream must be the source, glyph for glyph.
        assert_eq!(got, want, "normalization lost source text");
    }

    #[test]
    fn python_distinguishes_real_structural_differences() {
        let a = "def f(x):\n    return x + 1\n";
        let b = "def f(x):\n    return x - 1\n";
        assert_ne!(normalize(a, py()), normalize(b, py()));
    }

    // --- generic path: oracle whitespace semantics, structural comments ---

    #[test]
    fn generic_preserves_intra_line_spacing() {
        // The oracle's generic path only collapses whitespace RUNS, so these
        // stay distinct. A token-join here would wrongly merge them.
        let a = "fn f(x: i32) -> i32 { x+1 }";
        let b = "fn f(x: i32) -> i32 { x + 1 }";
        assert_ne!(normalize(a, rs()), normalize(b, rs()));
    }

    #[test]
    fn generic_strips_line_and_block_comments() {
        let a = "fn f() -> i32 {\n    // pick one\n    /* or two */\n    1\n}";
        let b = "fn f() -> i32 {\n    1\n}";
        assert_eq!(normalize(a, rs()), normalize(b, rs()));
    }

    #[test]
    fn generic_does_not_treat_comment_marker_inside_string_as_a_comment() {
        // The structural win over the lexical strip: `line.find("//")` truncated
        // this line mid-literal and merged two genuinely different functions.
        let a = "fn f() -> &'static str {\n    \"http://a\"\n}";
        let b = "fn f() -> &'static str {\n    \"http://b\"\n}";
        assert_ne!(normalize(a, rs()), normalize(b, rs()));
        assert!(normalize(a, rs()).contains("http://a"));
        assert_ne!(normalize_lexical(a, rs()), normalize(a, rs()));
    }

    #[test]
    fn generic_collapses_multiline_block_comment_like_the_oracle() {
        // The oracle's DOTALL regex replaces the whole comment (newlines too)
        // with a single space, joining the code around it.
        let a = "fn f() {\n    let a = 1; /* one\n       two */ let b = 2;\n}";
        let b = "fn f() {\n    let a = 1; let b = 2;\n}";
        assert_eq!(normalize(a, rs()), normalize(b, rs()));
    }

    #[test]
    fn fingerprint_is_twelve_hex_chars() {
        let fp = fingerprint("def f():\n    return 1\n", py());
        assert_eq!(fp.len(), 12);
        assert!(fp.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
