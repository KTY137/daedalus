//! Walk a repo and build the derived index. Mirrors
//! `daedalus/structcore/index.py::build_index` (exact-clone tier).
//! Uses a stdlib `std::fs` walk (no walkdir) to keep the dependency surface
//! minimal and sidestep the windows-sys/dlltool chain on the GNU toolchain.

use crate::clones::unit_clusters;
use crate::languages::{spec_for_ext, LangSpec};
use crate::parse::{extract_units, Unit};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub struct SiteJson {
    pub module: String,
    pub line: usize,
}

#[derive(Serialize)]
pub struct ClusterJson {
    pub fingerprint: String,
    pub language: String,
    pub name: String,
    pub count: usize,
    pub loc: usize,
    pub sites: Vec<SiteJson>,
}

#[derive(Serialize, Default, Clone)]
pub struct LangSum {
    pub files: usize,
    pub loc: usize,
}

#[derive(Serialize)]
pub struct Index {
    pub root: String,
    pub n_files: usize,
    pub languages: BTreeMap<String, LangSum>,
    pub unit_clusters: Vec<ClusterJson>,
    pub total_chars: usize,
}

/// Mirrors `index.py::_IGNORE_DIRS` exactly — a dir the oracle walks and we
/// skip (or vice versa) shows up as a pure membership diff that has nothing to
/// do with normalization. Dot-prefixed entries are redundant with the
/// `starts_with('.')` rule below but are kept so the two lists diff cleanly.
const IGNORE: &[&str] = &[
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
];

/// Mirrors `build_index(max_files=20000)`.
const MAX_FILES: usize = 20000;

fn collect_files(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let read = match std::fs::read_dir(&dir) {
            Ok(r) => r,
            Err(_) => continue,
        };
        for entry in read.flatten() {
            let file_type = match entry.file_type() {
                Ok(ft) => ft,
                Err(_) => continue,
            };
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if file_type.is_dir() {
                if IGNORE.contains(&name.as_ref()) || name.starts_with('.') {
                    continue;
                }
                stack.push(entry.path());
            } else if file_type.is_file() {
                files.push(entry.path());
            }
        }
    }
    files
}

pub fn build_index(root: PathBuf) -> Index {
    let root = root.canonicalize().unwrap_or(root);
    let mut all: Vec<(Unit, &'static LangSpec)> = Vec::new();
    let mut languages: BTreeMap<String, LangSum> = BTreeMap::new();
    let mut n_files = 0usize;
    let mut total_chars = 0usize;

    for path in collect_files(&root) {
        let ext = match path.extension().and_then(|e| e.to_str()) {
            Some(e) => e.to_lowercase(),
            None => continue,
        };
        let spec = match spec_for_ext(&ext) {
            Some(s) => s,
            None => continue,
        };
        // The oracle reads with `errors="replace"`, so a file with invalid
        // UTF-8 is still indexed. `read_to_string` would drop it entirely.
        let text = match std::fs::read(&path) {
            Ok(raw) => String::from_utf8_lossy(&raw).into_owned(),
            Err(_) => continue,
        };
        let rel = path
            .strip_prefix(&root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        n_files += 1;
        total_chars += text.chars().count(); // `len(text)` in Python is chars, not bytes
        let summary = languages.entry(spec.name.to_string()).or_default();
        summary.files += 1;
        summary.loc += text.lines().count();
        for unit in extract_units(&rel, &text, spec) {
            all.push((unit, spec));
        }
        // The oracle caps SUPPORTED files (the `spec_for` filter runs first),
        // not every file on disk — cap the same population.
        if n_files >= MAX_FILES {
            break;
        }
    }

    let clusters = unit_clusters(&all);
    let unit_clusters_json = clusters
        .into_iter()
        .map(|c| ClusterJson {
            fingerprint: c.fingerprint,
            language: c.language,
            name: c.name,
            count: c.count,
            loc: c.loc,
            sites: c
                .sites
                .into_iter()
                .map(|(module, line)| SiteJson { module, line })
                .collect(),
        })
        .collect();

    Index {
        root: root.to_string_lossy().to_string(),
        n_files,
        languages,
        unit_clusters: unit_clusters_json,
        total_chars,
    }
}

pub fn print_summary(idx: &Index) {
    println!(
        "\n=== STRUCTCORE-RS -- {} files across {} languages ===",
        idx.n_files,
        idx.languages.len()
    );
    let mut langs: Vec<(&String, &LangSum)> = idx.languages.iter().collect();
    langs.sort_by(|a, b| b.1.loc.cmp(&a.1.loc));
    for (name, sum) in langs {
        println!("  {:7} {:4} files  {}", sum.loc, sum.files, name);
    }
    println!("\nUNIT CLONE CLUSTERS ({}):", idx.unit_clusters.len());
    for c in idx.unit_clusters.iter().take(12) {
        let sites: Vec<String> = c
            .sites
            .iter()
            .take(5)
            .map(|s| format!("{}:{}", s.module, s.line))
            .collect();
        println!(
            "  x{}  (~{} loc)  {}:{}  [{}]",
            c.count,
            c.loc,
            c.language,
            c.name,
            sites.join(", ")
        );
    }
}
