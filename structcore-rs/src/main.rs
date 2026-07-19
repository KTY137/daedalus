//! structcore-rs — the go-forward Rust code-intelligence engine.
//!
//! v0 mirrors the proven Python `daedalus/structcore` core: walk a repo,
//! tree-sitter parse each supported language, extract function/method units,
//! normalize + SHA1-fingerprint them, cluster exact clones, emit a JSON index
//! (same shape as the Python reference so the two can be diffed for parity).
//! Grows toward the full engine (T2/T3 clones, dep graph, slice).

mod clones;
mod index;
mod languages;
mod parse;

use std::env;
use std::path::PathBuf;

fn main() {
    let args: Vec<String> = env::args().collect();
    let mut repo = String::from(".");
    let mut json_out: Option<String> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--json" => {
                i += 1;
                if i < args.len() {
                    json_out = Some(args[i].clone());
                }
            }
            other => repo = other.to_string(),
        }
        i += 1;
    }

    let idx = index::build_index(PathBuf::from(&repo));
    if let Some(path) = &json_out {
        if let Ok(json) = serde_json::to_string_pretty(&idx) {
            let _ = std::fs::write(path, json);
            println!("wrote {}", path);
        }
    }
    index::print_summary(&idx);
}
