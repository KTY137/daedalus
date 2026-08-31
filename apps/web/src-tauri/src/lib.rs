use std::{
    error::Error,
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Component, Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use sha2::{Digest, Sha256};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const BACKEND_ADDR: &str = "127.0.0.1:8765";
const BACKEND_URL: &str = "http://127.0.0.1:8765";
const DESKTOP_READY_PATH: &str = "/api/desktop-ready";
const DESKTOP_SHUTDOWN_PATH: &str = "/api/desktop/shutdown";
const DESKTOP_NONCE_HEADER: &str = "X-Daedalus-Desktop-Nonce";
const DESKTOP_STARTUP_NONCE_ENV: &str = "DAEDALUS_DESKTOP_STARTUP_NONCE";
const BACKEND_BUNDLE_ID: &str = env!("DAEDALUS_BACKEND_BUNDLE_ID");
const BUNDLE_ID_NAME: &str = "BUNDLE_ID";
const BUNDLE_FILES_NAME: &str = "BUNDLE_FILES";
const BACKEND_GENERATIONS_DIR: &str = "backend-generations";
const ACTIVE_BACKEND_MARKER: &str = "backend-current";
const LEGACY_BACKEND_DIR: &str = "backend";
const BACKEND_LOG_NAME: &str = "desktop-backend.log";
const STARTUP_LOG_NAME: &str = "desktop-startup.log";
const BUNDLE_READ_CHUNK_BYTES: usize = 1024 * 1024;
const BUNDLE_FILES_MAX_BYTES: u64 = 16 * 1024 * 1024;
const BUNDLE_FILES_MAX_COUNT: usize = 100_000;
const BUNDLE_PATH_MAX_BYTES: usize = 4096;
const MUTABLE_STATE_PATHS: [&str; 7] = [
    "_internal/config",
    "_internal/inbox",
    "_internal/memory",
    "_internal/outbox",
    "_internal/projects",
    "_internal/runs",
    "_internal/.env",
];
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);
const READINESS_RESPONSE_MAX_BYTES: u64 = 8 * 1024;

struct ManagedBackend {
    child: Child,
    startup_nonce: String,
}

struct BackendProcess(Mutex<Option<ManagedBackend>>);

#[derive(Debug)]
struct InstalledBackend {
    app_data_root: PathBuf,
    backend_root: PathBuf,
    executable: PathBuf,
    identity: String,
    fresh: bool,
}

#[derive(Debug)]
struct VerifiedResourceBundle {
    identity: String,
    files: Vec<String>,
}

fn backend_executable_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "daedalus-web-api.exe"
    } else {
        "daedalus-web-api"
    }
}

fn metadata_is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return true;
        }
    }
    false
}

fn metadata_is_plain_file(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_file() && !metadata_is_link_or_reparse(metadata)
}

fn metadata_is_plain_directory(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_dir() && !metadata_is_link_or_reparse(metadata)
}

fn valid_bundle_identity(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn bundle_path_component_equal(left: &str, right: &str) -> bool {
    if cfg!(target_os = "windows") {
        left.eq_ignore_ascii_case(right)
    } else {
        left == right
    }
}

fn bundle_path_is_or_is_under(relative: &str, parent: &str) -> bool {
    let mut relative_parts = relative.split('/');
    parent.split('/').all(|parent_part| {
        relative_parts
            .next()
            .is_some_and(|relative_part| bundle_path_component_equal(relative_part, parent_part))
    })
}

fn is_mutable_state_path(relative: &str) -> bool {
    MUTABLE_STATE_PATHS
        .iter()
        .any(|state| bundle_path_is_or_is_under(relative, state))
}

fn is_bundle_metadata_path(relative: &str) -> bool {
    !relative.contains('/')
        && [BUNDLE_ID_NAME, BUNDLE_FILES_NAME]
            .iter()
            .any(|name| bundle_path_component_equal(relative, name))
}

fn relative_bundle_path(root: &Path, path: &Path) -> io::Result<String> {
    let relative = path.strip_prefix(root).map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("backend path escaped its bundle root: {error}"),
        )
    })?;
    let mut parts = Vec::new();
    for component in relative.components() {
        let text = component.as_os_str().to_str().ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                format!("backend bundle path is not UTF-8: {}", path.display()),
            )
        })?;
        parts.push(text);
    }
    Ok(parts.join("/"))
}

fn collect_bundle_files(
    root: &Path,
    directory: &Path,
    exclude_mutable_state: bool,
    reject_mutable_state: bool,
    files: &mut Vec<(String, PathBuf)>,
) -> io::Result<()> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let relative = relative_bundle_path(root, &path)?;
        if is_bundle_metadata_path(&relative) {
            continue;
        }
        if is_mutable_state_path(&relative) {
            if reject_mutable_state {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("packaged backend contains mutable state: {relative}"),
                ));
            }
            if exclude_mutable_state {
                continue;
            }
        }
        let metadata = fs::symlink_metadata(&path)?;
        if metadata_is_link_or_reparse(&metadata) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("backend bundle contains a link: {}", path.display()),
            ));
        }
        if metadata.file_type().is_dir() {
            collect_bundle_files(
                root,
                &path,
                exclude_mutable_state,
                reject_mutable_state,
                files,
            )?;
        } else if metadata.file_type().is_file() {
            files.push((relative, path));
        } else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "backend bundle contains a special entry: {}",
                    path.display()
                ),
            ));
        }
    }
    Ok(())
}

fn bundle_tree_identity(
    root: &Path,
    exclude_mutable_state: bool,
    reject_mutable_state: bool,
) -> io::Result<String> {
    let metadata = fs::symlink_metadata(root)?;
    if !metadata_is_plain_directory(&metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend bundle root is not a plain directory: {}",
                root.display()
            ),
        ));
    }
    let mut files = Vec::new();
    collect_bundle_files(
        root,
        root,
        exclude_mutable_state,
        reject_mutable_state,
        &mut files,
    )?;
    files.sort_by(|left, right| left.0.cmp(&right.0));

    hash_bundle_files(&files)
}

fn hash_bundle_files(files: &[(String, PathBuf)]) -> io::Result<String> {
    let mut digest = Sha256::new();
    digest.update(b"daedalus-backend-bundle-v1\0");
    for (relative, path) in files {
        let encoded_path = relative.as_bytes();
        let size = fs::symlink_metadata(&path)?.len();
        digest.update((encoded_path.len() as u64).to_be_bytes());
        digest.update(encoded_path);
        digest.update(size.to_be_bytes());
        let mut input = fs::File::open(&path)?;
        let mut observed = 0_u64;
        // The Windows GUI main thread has a small default stack. Keep the
        // release-sized I/O buffer on the heap; a 1 MiB stack array crashes
        // before setup can record a diagnostic (0xC00000FD).
        let mut chunk = vec![0_u8; BUNDLE_READ_CHUNK_BYTES];
        loop {
            let count = input.read(&mut chunk)?;
            if count == 0 {
                break;
            }
            observed += count as u64;
            digest.update(&chunk[..count]);
        }
        if observed != size {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("backend bundle changed while hashing: {}", path.display()),
            ));
        }
    }
    let digest = digest.finalize();
    Ok(format!("{digest:x}"))
}

fn read_bundle_identity(root: &Path) -> io::Result<String> {
    let marker = root.join(BUNDLE_ID_NAME);
    let metadata = fs::symlink_metadata(&marker)?;
    if !metadata_is_plain_file(&metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend identity marker is not a plain file: {}",
                marker.display()
            ),
        ));
    }
    let raw = fs::read_to_string(&marker)?;
    let identity = raw.trim_end_matches(|character| character == '\r' || character == '\n');
    if !valid_bundle_identity(identity) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend identity marker is not a lowercase SHA-256: {}",
                marker.display()
            ),
        ));
    }
    Ok(identity.to_owned())
}

fn valid_manifest_relative_path(relative: &str) -> bool {
    !relative.is_empty()
        && !relative.contains('\\')
        && !relative.contains('\r')
        && !relative.contains('\n')
        && !is_bundle_metadata_path(relative)
        && !is_mutable_state_path(relative)
        && Path::new(relative)
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn read_bundle_files(root: &Path) -> io::Result<Vec<String>> {
    let manifest = root.join(BUNDLE_FILES_NAME);
    let metadata = fs::symlink_metadata(&manifest)?;
    if !metadata_is_plain_file(&metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend file manifest is not a plain file: {}",
                manifest.display()
            ),
        ));
    }
    if metadata.len() > BUNDLE_FILES_MAX_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend file manifest exceeds {} bytes: {}",
                BUNDLE_FILES_MAX_BYTES,
                manifest.display()
            ),
        ));
    }
    let raw = fs::read_to_string(&manifest)?;
    if raw.len() as u64 > BUNDLE_FILES_MAX_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "backend file manifest grew beyond its size limit while reading",
        ));
    }
    if !raw.ends_with('\n') || raw.contains('\r') {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend file manifest must use one UTF-8 path per LF-terminated line: {}",
                manifest.display()
            ),
        ));
    }
    let body = raw
        .strip_suffix('\n')
        .expect("manifest LF ending was checked");
    if body.is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "backend file manifest is empty",
        ));
    }

    let mut files = Vec::new();
    let mut previous: Option<&str> = None;
    for relative in body.split('\n') {
        if relative.len() > BUNDLE_PATH_MAX_BYTES || !valid_manifest_relative_path(relative) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("backend file manifest contains an unsafe path: {relative:?}"),
            ));
        }
        if previous.is_some_and(|prior| prior >= relative) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "backend file manifest must be strictly sorted with no duplicates",
            ));
        }
        files.push(relative.to_owned());
        if files.len() > BUNDLE_FILES_MAX_COUNT {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "backend file manifest contains too many paths",
            ));
        }
        previous = Some(relative);
    }
    Ok(files)
}

fn checked_bundle_file(root: &Path, relative: &str) -> io::Result<PathBuf> {
    let root_metadata = fs::symlink_metadata(root)?;
    if !metadata_is_plain_directory(&root_metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend bundle root is not a plain directory: {}",
                root.display()
            ),
        ));
    }

    let components: Vec<&str> = relative.split('/').collect();
    let mut current = root.to_owned();
    for (index, component) in components.iter().enumerate() {
        current.push(component);
        let metadata = fs::symlink_metadata(&current)?;
        if metadata_is_link_or_reparse(&metadata) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("backend bundle path contains a link: {}", current.display()),
            ));
        }
        let is_file = index + 1 == components.len();
        if (is_file && !metadata_is_plain_file(&metadata))
            || (!is_file && !metadata_is_plain_directory(&metadata))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "backend bundle path has the wrong type: {}",
                    current.display()
                ),
            ));
        }
    }
    Ok(current)
}

fn verify_resource_identity(
    resource_backend: &Path,
    expected: &str,
) -> io::Result<VerifiedResourceBundle> {
    let root_metadata = fs::symlink_metadata(resource_backend)?;
    if !metadata_is_plain_directory(&root_metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "packaged backend resource is not a plain directory: {}",
                resource_backend.display()
            ),
        ));
    }
    let actual = read_bundle_identity(resource_backend)?;
    let files = read_bundle_files(resource_backend)?;
    let mut verified_files = Vec::with_capacity(files.len());
    for relative in &files {
        verified_files.push((
            relative.clone(),
            checked_bundle_file(resource_backend, relative)?,
        ));
    }
    let computed = hash_bundle_files(&verified_files)?;
    if computed != actual {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "packaged backend bytes do not match BUNDLE_ID: marker {actual}, computed {computed}"
            ),
        ));
    }
    if expected != "development" && actual != expected {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "packaged backend identity mismatch: native host expects {expected}, resource contains {actual}"
            ),
        ));
    }
    Ok(VerifiedResourceBundle {
        identity: actual,
        files,
    })
}

fn copy_plain_file_new(source: &Path, destination: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(source)?;
    if !metadata_is_plain_file(&metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend bundle entry is not a plain file: {}",
                source.display()
            ),
        ));
    }
    let mut input = fs::File::open(source)?;
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)?;
    io::copy(&mut input, &mut output)?;
    output.sync_all()?;
    fs::set_permissions(destination, metadata.permissions())?;
    Ok(())
}

fn bundle_file_destination(root: &Path, relative: &str) -> io::Result<PathBuf> {
    let mut components = relative.split('/').peekable();
    let mut destination = root.to_owned();
    while let Some(component) = components.next() {
        if components.peek().is_none() {
            destination.push(component);
            return Ok(destination);
        }
        destination.push(component);
        match fs::symlink_metadata(&destination) {
            Ok(metadata) if metadata_is_plain_directory(&metadata) => {}
            Ok(_) => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "backend staging path is not a plain directory: {}",
                        destination.display()
                    ),
                ));
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                fs::create_dir(&destination)?;
            }
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "backend bundle path is empty",
    ))
}

fn copy_verified_resource_bundle_new(
    source: &Path,
    destination: &Path,
    bundle: &VerifiedResourceBundle,
) -> io::Result<()> {
    fs::create_dir(destination)?;
    for relative in [BUNDLE_ID_NAME, BUNDLE_FILES_NAME]
        .into_iter()
        .chain(bundle.files.iter().map(String::as_str))
    {
        let source_path = checked_bundle_file(source, relative)?;
        let destination_path = bundle_file_destination(destination, relative)?;
        copy_plain_file_new(&source_path, &destination_path)?;
    }
    Ok(())
}

fn copy_state_missing(source: &Path, destination: &Path) -> io::Result<()> {
    let source_metadata = fs::symlink_metadata(source)?;
    let source_type = source_metadata.file_type();
    if metadata_is_link_or_reparse(&source_metadata)
        || (!source_type.is_dir() && !source_type.is_file())
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "desktop state contains a link or special entry: {}",
                source.display()
            ),
        ));
    }

    match fs::symlink_metadata(destination) {
        Ok(destination_metadata) => {
            let destination_type = destination_metadata.file_type();
            if metadata_is_link_or_reparse(&destination_metadata)
                || (source_type.is_dir() != destination_type.is_dir())
                || (source_type.is_file() != destination_type.is_file())
            {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "desktop state type conflict: {} -> {}",
                        source.display(),
                        destination.display()
                    ),
                ));
            }
            if source_type.is_dir() {
                for entry in fs::read_dir(source)? {
                    let entry = entry?;
                    copy_state_missing(&entry.path(), &destination.join(entry.file_name()))?;
                }
            }
            Ok(())
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            if source_type.is_dir() {
                fs::create_dir(destination)?;
                for entry in fs::read_dir(source)? {
                    let entry = entry?;
                    copy_state_missing(&entry.path(), &destination.join(entry.file_name()))?;
                }
                Ok(())
            } else {
                copy_plain_file_new(source, destination)
            }
        }
        Err(error) => Err(error),
    }
}

fn active_backend_identity(app_data_root: &Path) -> io::Result<Option<String>> {
    let marker = app_data_root.join(ACTIVE_BACKEND_MARKER);
    match fs::symlink_metadata(&marker) {
        Ok(metadata) => {
            if !metadata_is_plain_file(&metadata) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "active backend marker is not a plain file: {}",
                        marker.display()
                    ),
                ));
            }
            let raw = fs::read_to_string(&marker)?;
            let identity = raw.trim_end_matches(|character| character == '\r' || character == '\n');
            if !valid_bundle_identity(identity) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("active backend marker is invalid: {}", marker.display()),
                ));
            }
            Ok(Some(identity.to_owned()))
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error),
    }
}

fn active_backend_root(app_data_root: &Path) -> io::Result<Option<PathBuf>> {
    match active_backend_identity(app_data_root)? {
        Some(identity) => {
            let root = app_data_root.join(BACKEND_GENERATIONS_DIR).join(&identity);
            validate_generation(&root, &identity)?;
            Ok(Some(root))
        }
        None => {
            let legacy = app_data_root.join(LEGACY_BACKEND_DIR);
            match fs::symlink_metadata(&legacy) {
                Ok(metadata) if metadata_is_plain_directory(&metadata) => Ok(Some(legacy)),
                Ok(_) => Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "legacy backend path is not a plain directory: {}",
                        legacy.display()
                    ),
                )),
                Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
                Err(error) => Err(error),
            }
        }
    }
}

fn checked_state_source(root: &Path, relative: &str) -> io::Result<Option<PathBuf>> {
    let root_metadata = fs::symlink_metadata(root)?;
    if !metadata_is_plain_directory(&root_metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "state source root is not a plain directory: {}",
                root.display()
            ),
        ));
    }
    let mut current = root.to_owned();
    let mut components = Path::new(relative).components().peekable();
    while let Some(component) = components.next() {
        let std::path::Component::Normal(name) = component else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("state allowlist path is not relative: {relative}"),
            ));
        };
        current.push(name);
        let metadata = match fs::symlink_metadata(&current) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        if metadata_is_link_or_reparse(&metadata) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("desktop state path contains a link: {}", current.display()),
            ));
        }
        if components.peek().is_some() && !metadata_is_plain_directory(&metadata) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "desktop state ancestor is not a directory: {}",
                    current.display()
                ),
            ));
        }
        if components.peek().is_none()
            && !metadata_is_plain_directory(&metadata)
            && !metadata_is_plain_file(&metadata)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("desktop state is not a plain entry: {}", current.display()),
            ));
        }
    }
    Ok(Some(current))
}

fn migrate_state(source_root: &Path, destination_root: &Path) -> io::Result<()> {
    for relative in MUTABLE_STATE_PATHS {
        if let Some(source) = checked_state_source(source_root, relative)? {
            copy_state_missing(&source, &destination_root.join(relative))?;
        }
    }
    Ok(())
}

fn validate_state_tree(path: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata_is_link_or_reparse(&metadata)
        || (!metadata.file_type().is_dir() && !metadata.file_type().is_file())
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "desktop state contains a link or special entry: {}",
                path.display()
            ),
        ));
    }
    if metadata.file_type().is_dir() {
        for entry in fs::read_dir(path)? {
            validate_state_tree(&entry?.path())?;
        }
    }
    Ok(())
}

fn validate_generation_state(root: &Path) -> io::Result<()> {
    for relative in MUTABLE_STATE_PATHS {
        if let Some(path) = checked_state_source(root, relative)? {
            validate_state_tree(&path)?;
        }
    }
    Ok(())
}

fn validate_generation(root: &Path, identity: &str) -> io::Result<PathBuf> {
    let metadata = fs::symlink_metadata(root)?;
    if !metadata_is_plain_directory(&metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend generation is not a plain directory: {}",
                root.display()
            ),
        ));
    }
    let installed_identity = read_bundle_identity(root)?;
    if installed_identity != identity {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend generation identity mismatch at {}: expected {identity}, found {installed_identity}",
                root.display()
            ),
        ));
    }
    let manifest_files = read_bundle_files(root)?;
    let mut immutable_files = Vec::new();
    collect_bundle_files(root, root, true, false, &mut immutable_files)?;
    immutable_files.sort_by(|left, right| left.0.cmp(&right.0));
    let immutable_paths: Vec<&str> = immutable_files
        .iter()
        .map(|(relative, _)| relative.as_str())
        .collect();
    if manifest_files
        .iter()
        .map(String::as_str)
        .ne(immutable_paths.iter().copied())
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend generation does not contain the exact manifest file set at {}",
                root.display()
            ),
        ));
    }
    let computed_identity = hash_bundle_files(&immutable_files)?;
    if computed_identity != identity {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "backend generation bytes do not match BUNDLE_ID at {}: marker {identity}, computed {computed_identity}",
                root.display()
            ),
        ));
    }
    validate_generation_state(root)?;

    let executable = root.join(backend_executable_name());
    let executable_metadata = fs::symlink_metadata(&executable)?;
    if !metadata_is_plain_file(&executable_metadata) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "desktop backend executable is missing: {}",
                executable.display()
            ),
        ));
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if fs::metadata(&executable)?.permissions().mode() & 0o111 == 0 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                format!(
                    "desktop backend executable is not executable: {}",
                    executable.display()
                ),
            ));
        }
    }

    Ok(executable)
}

fn ensure_plain_directory(path: &Path) -> io::Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata_is_plain_directory(&metadata) => Ok(()),
        Ok(_) => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "desktop backend path is not a plain directory: {}",
                path.display()
            ),
        )),
        Err(error) if error.kind() == io::ErrorKind::NotFound => fs::create_dir_all(path),
        Err(error) => Err(error),
    }
}

fn install_backend_from(
    resource_backend: &Path,
    app_data_root: &Path,
    expected_identity: &str,
) -> io::Result<InstalledBackend> {
    // The compiled host/resource binding is checked before app-data is touched.
    let resource = verify_resource_identity(resource_backend, expected_identity)?;
    let identity = resource.identity.clone();
    let generations = app_data_root.join(BACKEND_GENERATIONS_DIR);
    let backend_root = generations.join(&identity);
    let active_identity = active_backend_identity(app_data_root)?;

    match fs::symlink_metadata(&backend_root) {
        Ok(_) => {
            let executable = validate_generation(&backend_root, &identity)?;
            if active_identity.as_deref() != Some(identity.as_str()) {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    format!(
                        "backend generation {identity} is an inactive state snapshot; explicit state reconciliation is required before rollback or retry"
                    ),
                ));
            }
            return Ok(InstalledBackend {
                app_data_root: app_data_root.to_owned(),
                backend_root,
                executable,
                identity,
                fresh: false,
            });
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }

    ensure_plain_directory(app_data_root)?;
    ensure_plain_directory(&generations)?;
    let staging = generations.join(format!(".staging-{identity}-{}", generate_startup_nonce()?));
    let result = (|| -> io::Result<()> {
        copy_verified_resource_bundle_new(resource_backend, &staging, &resource)?;
        if let Some(previous) = active_backend_root(app_data_root)? {
            migrate_state(&previous, &staging)?;
        }
        validate_generation(&staging, &identity)?;
        fs::rename(&staging, &backend_root)
    })();
    if staging.exists() {
        let _ = fs::remove_dir_all(&staging);
    }
    result?;

    let executable = validate_generation(&backend_root, &identity)?;
    Ok(InstalledBackend {
        app_data_root: app_data_root.to_owned(),
        backend_root,
        executable,
        identity,
        fresh: true,
    })
}

fn install_backend(app: &tauri::App) -> Result<InstalledBackend, Box<dyn Error>> {
    let resource_backend = app.path().resource_dir()?.join("backend");
    if !resource_backend.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!(
                "packaged backend resource is missing: {}",
                resource_backend.display()
            ),
        )
        .into());
    }
    let app_data_root = app.path().app_local_data_dir()?;
    Ok(install_backend_from(
        &resource_backend,
        &app_data_root,
        BACKEND_BUNDLE_ID,
    )?)
}

fn activate_backend(app_data_root: &Path, identity: &str) -> io::Result<()> {
    if !valid_bundle_identity(identity) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "cannot activate an invalid backend identity",
        ));
    }
    ensure_plain_directory(app_data_root)?;
    let target_root = app_data_root.join(BACKEND_GENERATIONS_DIR).join(identity);
    validate_generation(&target_root, identity)?;
    let marker = app_data_root.join(ACTIVE_BACKEND_MARKER);
    if let Some(current) = active_backend_identity(app_data_root)? {
        let current_root = app_data_root.join(BACKEND_GENERATIONS_DIR).join(&current);
        validate_generation(&current_root, &current)?;
    }
    let temporary = app_data_root.join(format!(
        ".{ACTIVE_BACKEND_MARKER}-{}",
        generate_startup_nonce()?
    ));
    let result = (|| -> io::Result<()> {
        let mut output = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        writeln!(output, "{identity}")?;
        output.sync_all()?;
        fs::rename(&temporary, &marker)
    })();
    if temporary.exists() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn append_startup_error(app: &tauri::App, error: &dyn std::fmt::Display) {
    let Ok(app_data_root) = app.path().app_local_data_dir() else {
        return;
    };
    if ensure_plain_directory(&app_data_root).is_err() {
        return;
    }
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    if let Ok(mut log) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(app_data_root.join(STARTUP_LOG_NAME))
    {
        let _ = writeln!(log, "{timestamp}: {error}");
    }
}

fn port_is_busy() -> bool {
    let address: SocketAddr = BACKEND_ADDR.parse().expect("constant socket address");
    port_is_busy_at(address)
}

fn port_is_busy_at(address: SocketAddr) -> bool {
    TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok()
}

fn generate_startup_nonce() -> io::Result<String> {
    let mut bytes = [0_u8; 32];
    getrandom::getrandom(&mut bytes)
        .map_err(|error| io::Error::other(format!("operating-system RNG failed: {error}")))?;
    let mut nonce = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut nonce, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(nonce)
}

fn spawn_backend(
    backend_root: &Path,
    executable: &Path,
    startup_nonce: &str,
    log_path: &Path,
) -> io::Result<Child> {
    let stdout = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)?;
    let stderr = stdout.try_clone()?;

    let mut command = Command::new(executable);
    command
        .args(["--host", "127.0.0.1", "--port", "8765"])
        .env(DESKTOP_STARTUP_NONCE_ENV, startup_nonce)
        .current_dir(backend_root)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }

    command.spawn()
}

fn probe_authenticated_readiness(address: SocketAddr, startup_nonce: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    if stream
        .set_read_timeout(Some(Duration::from_millis(250)))
        .is_err()
        || stream
            .set_write_timeout(Some(Duration::from_millis(250)))
            .is_err()
    {
        return false;
    }
    let request = format!(
        "GET {DESKTOP_READY_PATH} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::new();
    if stream
        .take(READINESS_RESPONSE_MAX_BYTES)
        .read_to_end(&mut response)
        .is_err()
    {
        return false;
    }
    let Ok(response) = std::str::from_utf8(&response) else {
        return false;
    };
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    let status_ok = headers
        .lines()
        .next()
        .is_some_and(|line| line.starts_with("HTTP/1.0 200 ") || line.starts_with("HTTP/1.1 200 "));
    let expected = format!(
        "{{\"schema\": \"daedalus-desktop-startup/1\", \"ready\": true, \"nonce\": \"{startup_nonce}\"}}"
    );
    status_ok && body == expected
}

fn readiness_poll_with<ChildStatus, Probe, Status>(
    mut child_status: ChildStatus,
    probe: Probe,
) -> io::Result<bool>
where
    ChildStatus: FnMut() -> io::Result<Option<Status>>,
    Probe: FnOnce() -> bool,
    Status: std::fmt::Display,
{
    if let Some(status) = child_status()? {
        return Err(io::Error::other(format!(
            "Daedalus backend exited before startup completed: {status}"
        )));
    }
    if !probe() {
        return Ok(false);
    }
    // A raced listener must not win merely because our child exited between
    // the first lifecycle check and the authenticated HTTP response.
    if let Some(status) = child_status()? {
        return Err(io::Error::other(format!(
            "Daedalus backend exited during startup readiness: {status}"
        )));
    }
    Ok(true)
}

fn readiness_poll(child: &mut Child, address: SocketAddr, startup_nonce: &str) -> io::Result<bool> {
    readiness_poll_with(
        || Ok(child.try_wait()?),
        || probe_authenticated_readiness(address, startup_nonce),
    )
}

fn wait_until_ready(child: &mut Child, startup_nonce: &str) -> io::Result<()> {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let address: SocketAddr = BACKEND_ADDR.parse().expect("constant socket address");

    while Instant::now() < deadline {
        if readiness_poll(child, address, startup_nonce)? {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(200));
    }

    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        format!("Daedalus backend did not bind {BACKEND_ADDR} within 25 seconds"),
    ))
}

fn terminate_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn cleanup_unactivated_generation(installed: &InstalledBackend) -> io::Result<()> {
    if !installed.fresh
        || active_backend_identity(&installed.app_data_root)?.as_deref()
            == Some(installed.identity.as_str())
    {
        return Ok(());
    }
    fs::remove_dir_all(&installed.backend_root)
}

fn failed_startup_after_install(
    installed: &InstalledBackend,
    detail: impl std::fmt::Display,
) -> Box<dyn Error> {
    match cleanup_unactivated_generation(installed) {
        Ok(()) => io::Error::other(detail.to_string()).into(),
        Err(cleanup_error) => io::Error::other(format!(
            "{detail}; additionally could not remove the unactivated backend generation {}: {cleanup_error}",
            installed.backend_root.display()
        ))
        .into(),
    }
}

fn start_desktop_inner(app: &mut tauri::App) -> Result<(), Box<dyn Error>> {
    // Never silently attach to an unrelated service and later kill it as if it
    // were our child. A second Daedalus instance gets an explicit refusal.
    if port_is_busy() {
        return Err(io::Error::new(
            io::ErrorKind::AddrInUse,
            format!("{BACKEND_ADDR} is already in use; close the other Daedalus instance first"),
        )
        .into());
    }

    let startup_nonce = generate_startup_nonce()?;
    let installed = install_backend(app)?;
    let backend_log = installed.app_data_root.join(BACKEND_LOG_NAME);
    let mut child = match spawn_backend(
        &installed.backend_root,
        &installed.executable,
        &startup_nonce,
        &backend_log,
    ) {
        Ok(child) => child,
        Err(error) => return Err(failed_startup_after_install(&installed, error)),
    };
    if let Err(error) = wait_until_ready(&mut child, &startup_nonce) {
        terminate_child(&mut child);
        return Err(failed_startup_after_install(
            &installed,
            format!("{error}. Backend log: {}", backend_log.display()),
        ));
    }

    if let Err(error) = activate_backend(&installed.app_data_root, &installed.identity) {
        terminate_child(&mut child);
        return Err(failed_startup_after_install(&installed, error));
    }

    let url = BACKEND_URL.parse().expect("constant backend URL");
    if let Err(error) = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("Daedalus")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .build()
    {
        terminate_child(&mut child);
        return Err(error.into());
    }

    app.manage(BackendProcess(Mutex::new(Some(ManagedBackend {
        child,
        startup_nonce,
    }))));

    Ok(())
}

fn start_desktop(app: &mut tauri::App) -> Result<(), Box<dyn Error>> {
    match start_desktop_inner(app) {
        Ok(()) => Ok(()),
        Err(error) => {
            append_startup_error(app, error.as_ref());
            eprintln!("Daedalus desktop setup failed: {error}");
            // Tauri executes setup from App::run and panics if this callback
            // returns Err. Release builds use panic=abort, so exit explicitly
            // after recording the stable diagnostic instead.
            std::process::exit(1);
        }
    }
}

fn request_backend_shutdown(address: SocketAddr, startup_nonce: &str, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let connect_timeout = std::cmp::min(timeout, Duration::from_millis(500));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, connect_timeout) else {
        return false;
    };
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero()
        || stream
            .set_write_timeout(Some(std::cmp::min(remaining, Duration::from_secs(1))))
            .is_err()
    {
        return false;
    }
    let request = format!(
        "POST {DESKTOP_SHUTDOWN_PATH} HTTP/1.0\r\nHost: 127.0.0.1\r\n{DESKTOP_NONCE_HEADER}: {startup_nonce}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::new();
    loop {
        if response.len() >= READINESS_RESPONSE_MAX_BYTES as usize {
            return false;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() || stream.set_read_timeout(Some(remaining)).is_err() {
            return false;
        }
        let mut chunk = [0_u8; 512];
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(count) => {
                response.extend_from_slice(&chunk[..count]);
                if response.windows(2).any(|window| window == b"\r\n") {
                    break;
                }
            }
            Err(_) => return false,
        }
    }
    let Ok(response) = std::str::from_utf8(&response) else {
        return false;
    };
    matches!(response.lines().next(), Some(line) if line.starts_with("HTTP/1.0 200 ") || line.starts_with("HTTP/1.1 200 "))
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut backend) = guard.take() {
                if backend.child.try_wait().ok().flatten().is_none() {
                    let address = BACKEND_ADDR.parse().expect("constant backend address");
                    // The Python runtime owns all child/container policy. Give
                    // its nonce-authenticated, idempotent close route a bounded
                    // chance to finish before terminating the backend itself.
                    let _ =
                        request_backend_shutdown(address, &backend.startup_nonce, SHUTDOWN_TIMEOUT);
                }
                let _ = backend.child.kill();
                let _ = backend.child.wait();
            }
        }
    }
}

pub fn run() {
    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(start_desktop)
        .build(tauri::generate_context!())
    {
        Ok(app) => app,
        Err(error) => {
            eprintln!("Daedalus desktop startup failed: {error}");
            std::process::exit(1);
        }
    };

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_backend(app_handle);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    struct TestDirectory(PathBuf);

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn test_directory(label: &str) -> TestDirectory {
        let path = std::env::temp_dir().join(format!(
            "daedalus-desktop-{label}-{}-{}",
            std::process::id(),
            generate_startup_nonce().expect("test directory nonce")
        ));
        fs::create_dir(&path).expect("create isolated test directory");
        TestDirectory(path)
    }

    fn write_backend_fixture(root: &Path, payload: &[u8]) -> String {
        fs::create_dir_all(root.join("_internal")).expect("create backend fixture");
        fs::write(root.join("_internal/runtime.bin"), b"runtime")
            .expect("write backend fixture runtime");
        let executable = root.join(backend_executable_name());
        fs::write(&executable, payload).expect("write backend executable");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = fs::metadata(&executable)
                .expect("read fixture permissions")
                .permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(&executable, permissions).expect("make fixture executable");
        }
        let mut files = Vec::new();
        collect_bundle_files(root, root, false, true, &mut files)
            .expect("collect backend fixture manifest");
        files.sort_by(|left, right| left.0.cmp(&right.0));
        let manifest = files
            .iter()
            .map(|(relative, _)| format!("{relative}\n"))
            .collect::<String>();
        fs::write(root.join(BUNDLE_FILES_NAME), manifest).expect("write bundle file manifest");
        let identity = bundle_tree_identity(root, false, true).expect("hash backend fixture");
        fs::write(root.join(BUNDLE_ID_NAME), format!("{identity}\n"))
            .expect("write bundle identity");
        identity
    }

    fn one_response(response: String) -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake listener");
        let address = listener.local_addr().expect("fake listener address");
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept readiness request");
            let mut request = [0_u8; 512];
            let _ = stream.read(&mut request);
            stream
                .write_all(response.as_bytes())
                .expect("write fake response");
        });
        address
    }

    #[test]
    fn bundle_identity_matches_the_cross_language_golden_vector() {
        let fixture = test_directory("identity-golden");
        fs::write(fixture.0.join("payload.bin"), b"payload").expect("write golden payload");
        assert_eq!(
            bundle_tree_identity(&fixture.0, false, true).expect("hash golden tree"),
            "fa93401a3e96f55a3931a789d1ded6702c98c28a46f2d082de10a5b5143e2783"
        );
    }

    #[test]
    fn bundle_path_matching_uses_host_filesystem_case_semantics() {
        assert!(is_mutable_state_path("_internal/config/runtime.json"));
        assert!(is_bundle_metadata_path("BUNDLE_ID"));
        assert!(is_bundle_metadata_path("BUNDLE_FILES"));
        if cfg!(target_os = "windows") {
            assert!(is_mutable_state_path("_INTERNAL/CONFIG/runtime.json"));
            assert!(is_bundle_metadata_path("bundle_id"));
            assert!(is_bundle_metadata_path("bundle_files"));
        } else {
            assert!(!is_mutable_state_path("_INTERNAL/CONFIG/runtime.json"));
            assert!(!is_bundle_metadata_path("bundle_id"));
            assert!(!is_bundle_metadata_path("bundle_files"));
        }
    }

    #[test]
    fn unlisted_installer_overlay_files_are_not_copied_into_a_generation() {
        let fixture = test_directory("resource-overlay");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let identity = write_backend_fixture(&resource, b"current payload");
        let stale = resource.join("_internal/stale-runtime.dll");
        fs::write(&stale, b"left by an older installer").expect("write stale resource file");

        let verified = verify_resource_identity(&resource, &identity)
            .expect("unlisted resource overlay is inert");
        assert!(!verified
            .files
            .iter()
            .any(|relative| relative.contains("stale")));
        let installed = install_backend_from(&resource, &app_data, &identity)
            .expect("install exact manifest files");
        assert!(!installed
            .backend_root
            .join("_internal/stale-runtime.dll")
            .exists());
        assert_eq!(
            bundle_tree_identity(&installed.backend_root, true, false)
                .expect("hash installed exact generation"),
            identity
        );
        fs::write(
            installed
                .backend_root
                .join("_internal/injected-runtime.dll"),
            b"not in the manifest",
        )
        .expect("inject unlisted generation file");
        let error = validate_generation(&installed.backend_root, &identity)
            .expect_err("unlisted immutable generation files must be refused");
        assert!(error.to_string().contains("exact manifest file set"));
    }

    #[test]
    fn bundle_identity_mismatch_refuses_before_installation() {
        let fixture = test_directory("identity-mismatch");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let _resource_identity = write_backend_fixture(&resource, b"resource A");

        let error = install_backend_from(&resource, &app_data, &"b".repeat(64))
            .expect_err("mismatched native host/resource identity must fail");
        assert!(error.to_string().contains("identity mismatch"));
        assert!(!app_data.exists());
    }

    #[test]
    fn changed_resource_bytes_are_refused_even_when_the_marker_is_unchanged() {
        let fixture = test_directory("identity-mutated");
        let resource = fixture.0.join("resource");
        let identity = write_backend_fixture(&resource, b"original payload");
        fs::write(resource.join(backend_executable_name()), b"changed payload")
            .expect("mutate resource after identity publication");

        let error = verify_resource_identity(&resource, &identity)
            .expect_err("mutated resource bytes must fail identity verification");
        assert!(error.to_string().contains("bytes do not match BUNDLE_ID"));
    }

    #[test]
    fn an_existing_generation_is_validated_and_never_overwritten() {
        let fixture = test_directory("existing-generation");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let identity = write_backend_fixture(&resource, b"same payload");
        let installed_root = app_data.join(BACKEND_GENERATIONS_DIR).join(&identity);
        write_backend_fixture(&installed_root, b"same payload");
        let installed_state = installed_root.join("_internal/config");
        fs::create_dir_all(&installed_state).expect("create installed mutable state");
        fs::write(installed_state.join("installed-sentinel"), b"keep")
            .expect("write installed sentinel");
        fs::write(
            app_data.join(ACTIVE_BACKEND_MARKER),
            format!("{identity}\n"),
        )
        .expect("write active marker");

        let installed =
            install_backend_from(&resource, &app_data, &identity).expect("reuse valid generation");
        assert_eq!(installed.backend_root, installed_root);
        assert_eq!(
            fs::read(
                installed
                    .backend_root
                    .join("_internal/config/installed-sentinel")
            )
            .expect("read installed sentinel"),
            b"keep"
        );
    }

    #[test]
    fn an_existing_inactive_generation_requires_explicit_state_reconciliation() {
        let fixture = test_directory("inactive-generation");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let identity = write_backend_fixture(&resource, b"inactive payload");
        let installed_root = app_data.join(BACKEND_GENERATIONS_DIR).join(&identity);
        write_backend_fixture(&installed_root, b"inactive payload");

        let error = install_backend_from(&resource, &app_data, &identity)
            .expect_err("an inactive snapshot must not be started as current state");
        assert!(error.to_string().contains("explicit state reconciliation"));
    }

    #[test]
    fn failed_fresh_generation_is_removed_but_an_active_generation_is_retained() {
        let fixture = test_directory("failed-generation-cleanup");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let identity = write_backend_fixture(&resource, b"cleanup payload");

        let failed = install_backend_from(&resource, &app_data, &identity)
            .expect("install fresh generation");
        assert!(failed.fresh);
        cleanup_unactivated_generation(&failed).expect("remove unactivated generation");
        assert!(!failed.backend_root.exists());

        let ready = install_backend_from(&resource, &app_data, &identity)
            .expect("reinstall clean generation");
        activate_backend(&app_data, &identity).expect("activate ready generation");
        cleanup_unactivated_generation(&ready).expect("active generation is retained");
        assert!(ready.backend_root.is_dir());
    }

    #[test]
    fn new_generation_migrates_only_missing_allowlisted_state_before_activation() {
        let fixture = test_directory("state-migration");
        let resource = fixture.0.join("resource");
        let app_data = fixture.0.join("app-data");
        let previous_seed = fixture.0.join("previous-seed");
        let previous_identity = write_backend_fixture(&previous_seed, b"previous payload");
        let previous = app_data
            .join(BACKEND_GENERATIONS_DIR)
            .join(&previous_identity);
        fs::create_dir_all(previous.parent().expect("generation parent"))
            .expect("create generation parent");
        fs::rename(previous_seed, &previous).expect("publish previous generation");
        let previous_config = previous.join("_internal/config");
        fs::create_dir_all(&previous_config).expect("create previous state");
        fs::write(previous_config.join("missing.json"), b"migrated")
            .expect("write previous missing state");
        fs::write(previous.join("_internal/.env"), b"TOKEN=local\n").expect("write previous env");
        fs::write(
            app_data.join(ACTIVE_BACKEND_MARKER),
            format!("{previous_identity}\n"),
        )
        .expect("write previous active marker");

        let next_identity = write_backend_fixture(&resource, b"next payload");

        let installed = install_backend_from(&resource, &app_data, &next_identity)
            .expect("install next generation");
        let installed_config = installed.backend_root.join("_internal/config");
        assert_eq!(
            fs::read(installed_config.join("missing.json")).expect("read migrated state"),
            b"migrated"
        );
        assert_eq!(
            fs::read(installed.backend_root.join("_internal/.env")).expect("read migrated env"),
            b"TOKEN=local\n"
        );
        assert_eq!(
            fs::read_to_string(app_data.join(ACTIVE_BACKEND_MARKER))
                .expect("read unchanged active marker"),
            format!("{previous_identity}\n")
        );

        activate_backend(&app_data, &next_identity).expect("activate ready generation");
        assert_eq!(
            fs::read_to_string(app_data.join(ACTIVE_BACKEND_MARKER))
                .expect("read next active marker"),
            format!("{next_identity}\n")
        );
    }

    #[test]
    fn state_copy_preserves_existing_files_and_adds_only_missing_files() {
        let fixture = test_directory("state-missing-only");
        let source = fixture.0.join("source");
        let destination = fixture.0.join("destination");
        fs::create_dir_all(&source).expect("create source state");
        fs::create_dir_all(&destination).expect("create destination state");
        fs::write(source.join("shared.json"), b"old value").expect("write source shared");
        fs::write(source.join("missing.json"), b"migrated").expect("write source missing");
        fs::write(destination.join("shared.json"), b"new value").expect("write destination shared");

        copy_state_missing(&source, &destination).expect("copy missing state only");
        assert_eq!(
            fs::read(destination.join("shared.json")).expect("read preserved destination"),
            b"new value"
        );
        assert_eq!(
            fs::read(destination.join("missing.json")).expect("read migrated destination"),
            b"migrated"
        );
    }

    #[test]
    fn state_migration_refuses_type_conflicts() {
        let fixture = test_directory("state-conflict");
        let source = fixture.0.join("source");
        let destination = fixture.0.join("destination");
        fs::write(&source, b"file state").expect("write source state file");
        fs::create_dir(&destination).expect("create destination state directory");

        let error = copy_state_missing(&source, &destination)
            .expect_err("state type conflict must fail closed");
        assert!(error.to_string().contains("state type conflict"));
    }

    #[test]
    fn state_migration_refuses_a_linked_allowlist_ancestor() {
        let fixture = test_directory("state-linked-ancestor");
        let source = fixture.0.join("source");
        let outside = fixture.0.join("outside");
        fs::create_dir_all(outside.join("config")).expect("create outside state");
        fs::write(outside.join("config/settings.json"), b"outside").expect("write outside state");
        fs::create_dir(&source).expect("create state source");

        #[cfg(unix)]
        std::os::unix::fs::symlink(&outside, source.join("_internal"))
            .expect("create state ancestor symlink");
        #[cfg(target_os = "windows")]
        {
            let status = Command::new("cmd")
                .args(["/C", "mklink", "/J"])
                .arg(source.join("_internal"))
                .arg(&outside)
                .status()
                .expect("invoke junction creation");
            assert!(status.success(), "create state ancestor junction");
        }

        let error = checked_state_source(&source, "_internal/config")
            .expect_err("linked allowlist ancestor must fail closed");
        assert!(error.to_string().contains("contains a link"));
    }

    #[test]
    fn generic_listener_cannot_satisfy_readiness() {
        let address = one_response("HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}".to_owned());
        assert!(!probe_authenticated_readiness(address, &"a".repeat(64)));
    }

    #[test]
    fn listener_present_before_spawn_is_detected() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind pre-existing listener");
        let address = listener
            .local_addr()
            .expect("pre-existing listener address");
        assert!(port_is_busy_at(address));
    }

    #[test]
    fn listener_winning_bind_race_cannot_replay_another_nonce() {
        let raced_nonce = "e".repeat(64);
        let body = format!(
            "{{\"schema\": \"daedalus-desktop-startup/1\", \"ready\": true, \"nonce\": \"{raced_nonce}\"}}"
        );
        let response = format!(
            "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        );
        let address = one_response(response);
        assert!(!probe_authenticated_readiness(address, &"f".repeat(64)));
    }

    #[test]
    fn only_exact_child_nonce_satisfies_readiness() {
        let nonce = "b".repeat(64);
        let body = format!(
            "{{\"schema\": \"daedalus-desktop-startup/1\", \"ready\": true, \"nonce\": \"{nonce}\"}}"
        );
        let response = format!(
            "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        );
        let address = one_response(response);
        assert!(probe_authenticated_readiness(address, &nonce));
    }

    #[test]
    fn child_exit_before_probe_wins_without_contacting_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake ready listener");
        listener
            .set_nonblocking(true)
            .expect("make fake listener observable without blocking");
        let address = listener.local_addr().expect("fake ready listener address");
        let error = readiness_poll_with(
            || Ok(Some("fixture exit 17".to_owned())),
            || probe_authenticated_readiness(address, &"1".repeat(64)),
        )
        .expect_err("an exited child must refuse readiness before probing");
        assert!(error
            .to_string()
            .contains("exited before startup completed"));
        assert_eq!(
            listener
                .accept()
                .expect_err("readiness probe must not run")
                .kind(),
            io::ErrorKind::WouldBlock
        );
    }

    #[test]
    fn child_exit_during_probe_wins_over_exact_nonce_response() {
        let nonce = "2".repeat(64);
        let body = format!(
            "{{\"schema\": \"daedalus-desktop-startup/1\", \"ready\": true, \"nonce\": \"{nonce}\"}}"
        );
        let response = format!(
            "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        );
        let address = one_response(response);
        let mut statuses = [None, Some("fixture exit 23".to_owned())].into_iter();
        let error = readiness_poll_with(
            || Ok(statuses.next().expect("exactly two child status checks")),
            || probe_authenticated_readiness(address, &nonce),
        )
        .expect_err("child exit must win over exact readiness evidence");
        assert!(error
            .to_string()
            .contains("exited during startup readiness"));
        assert!(statuses.next().is_none());
    }

    #[test]
    fn shutdown_requests_the_nonce_authenticated_runtime_close_route() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake backend");
        let address = listener.local_addr().expect("fake backend address");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept shutdown request");
            let mut request = [0_u8; 512];
            let count = stream.read(&mut request).expect("read shutdown request");
            let request = std::str::from_utf8(&request[..count]).expect("request is UTF-8");
            assert!(request.starts_with(
                "POST /api/desktop/shutdown HTTP/1.0\r\nHost: 127.0.0.1\r\nX-Daedalus-Desktop-Nonce: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\r\n"
            ));
            stream
                .write_all(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                .expect("write shutdown response");
        });

        assert!(request_backend_shutdown(
            address,
            &"c".repeat(64),
            Duration::from_secs(1)
        ));
        server.join().expect("fake backend thread");
    }

    #[test]
    fn shutdown_response_wait_has_an_absolute_budget() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind hung backend");
        let address = listener.local_addr().expect("hung backend address");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept shutdown request");
            let mut request = [0_u8; 512];
            let _ = stream.read(&mut request);
            thread::sleep(Duration::from_millis(500));
        });

        let started = Instant::now();
        assert!(!request_backend_shutdown(
            address,
            &"d".repeat(64),
            Duration::from_millis(100)
        ));
        assert!(started.elapsed() < Duration::from_millis(400));
        server.join().expect("hung backend thread");
    }
}
