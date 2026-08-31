use std::{env, fs, path::Path};

const BUNDLE_ID_PATH: &str = "backend/BUNDLE_ID";
const BUNDLE_FILES_PATH: &str = "backend/BUNDLE_FILES";

fn valid_bundle_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn backend_bundle_id() -> String {
    println!("cargo:rerun-if-changed={BUNDLE_ID_PATH}");
    println!("cargo:rerun-if-changed={BUNDLE_FILES_PATH}");
    let marker = Path::new(BUNDLE_ID_PATH);
    match fs::read_to_string(marker) {
        Ok(raw)
            if valid_bundle_id(
                raw.trim_end_matches(|character| character == '\r' || character == '\n'),
            ) => {
                let metadata = fs::metadata(BUNDLE_FILES_PATH).unwrap_or_else(|error| {
                    panic!(
                        "{BUNDLE_FILES_PATH} is required with {BUNDLE_ID_PATH}; run tools/build_tauri_sidecar.py first: {error}"
                    )
                });
                assert!(
                    metadata.is_file(),
                    "{BUNDLE_FILES_PATH} must be a regular file"
                );
                raw.trim_end_matches(|character| character == '\r' || character == '\n')
                    .to_owned()
            }
        Ok(_) => panic!("{BUNDLE_ID_PATH} must contain one lowercase SHA-256 identity"),
        Err(error) if env::var("PROFILE").as_deref() != Ok("release") => {
            println!(
                "cargo:warning={BUNDLE_ID_PATH} is unavailable ({error}); debug build uses development identity"
            );
            "development".to_owned()
        }
        Err(error) => panic!(
            "{BUNDLE_ID_PATH} is required for a release build; run tools/build_tauri_sidecar.py first: {error}"
        ),
    }
}

fn main() {
    println!(
        "cargo:rustc-env=DAEDALUS_BACKEND_BUNDLE_ID={}",
        backend_bundle_id()
    );
    tauri_build::build()
}
