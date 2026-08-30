use std::{
    error::Error,
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const BACKEND_ADDR: &str = "127.0.0.1:8765";
const BACKEND_URL: &str = "http://127.0.0.1:8765";
const DESKTOP_READY_PATH: &str = "/api/desktop-ready";
const DESKTOP_SHUTDOWN_PATH: &str = "/api/desktop/shutdown";
const DESKTOP_NONCE_HEADER: &str = "X-Daedalus-Desktop-Nonce";
const DESKTOP_STARTUP_NONCE_ENV: &str = "DAEDALUS_DESKTOP_STARTUP_NONCE";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);
const READINESS_RESPONSE_MAX_BYTES: u64 = 8 * 1024;

struct ManagedBackend {
    child: Child,
    startup_nonce: String,
}

struct BackendProcess(Mutex<Option<ManagedBackend>>);

fn backend_executable_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "daedalus-web-api.exe"
    } else {
        "daedalus-web-api"
    }
}

fn copy_tree(source: &Path, destination: &Path) -> io::Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let destination_path = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&source_path, &destination_path)?;
        } else {
            fs::copy(&source_path, &destination_path)?;
        }
    }
    Ok(())
}

fn install_backend(app: &tauri::App) -> Result<(PathBuf, PathBuf), Box<dyn Error>> {
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

    // Stable app-data path on purpose. The package contains no runtime state,
    // so an upgrade overwrites code/assets but does not delete runs/, inbox/,
    // outbox/, projects/ or .env created by Daedalus itself.
    let backend_root = app.path().app_local_data_dir()?.join("backend");
    copy_tree(&resource_backend, &backend_root)?;

    let executable = backend_root.join(backend_executable_name());
    if !executable.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!(
                "desktop backend executable is missing: {}",
                executable.display()
            ),
        )
        .into());
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(&executable)?.permissions();
        permissions.set_mode(permissions.mode() | 0o755);
        fs::set_permissions(&executable, permissions)?;
    }

    Ok((backend_root, executable))
}

fn port_is_busy() -> bool {
    let address: SocketAddr = BACKEND_ADDR.parse().expect("constant socket address");
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

fn spawn_backend(backend_root: &Path, executable: &Path, startup_nonce: &str) -> io::Result<Child> {
    let log_path = backend_root.join("desktop-backend.log");
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

fn readiness_poll(child: &mut Child, address: SocketAddr, startup_nonce: &str) -> io::Result<bool> {
    if let Some(status) = child.try_wait()? {
        return Err(io::Error::other(format!(
            "Daedalus backend exited before startup completed: {status}"
        )));
    }
    if !probe_authenticated_readiness(address, startup_nonce) {
        return Ok(false);
    }
    // A raced listener must not win merely because our child exited between
    // the first lifecycle check and the authenticated HTTP response.
    if let Some(status) = child.try_wait()? {
        return Err(io::Error::other(format!(
            "Daedalus backend exited during startup readiness: {status}"
        )));
    }
    Ok(true)
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

fn start_desktop(app: &mut tauri::App) -> Result<(), Box<dyn Error>> {
    // Never silently attach to an unrelated service and later kill it as if it
    // were our child. A second Daedalus instance gets an explicit refusal.
    if port_is_busy() {
        return Err(io::Error::new(
            io::ErrorKind::AddrInUse,
            format!("{BACKEND_ADDR} is already in use; close the other Daedalus instance first"),
        )
        .into());
    }

    let (backend_root, executable) = install_backend(app)?;
    let startup_nonce = generate_startup_nonce()?;
    let mut child = spawn_backend(&backend_root, &executable, &startup_nonce)?;
    if let Err(error) = wait_until_ready(&mut child, &startup_nonce) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(io::Error::new(
            error.kind(),
            format!(
                "{error}. Backend log: {}",
                backend_root.join("desktop-backend.log").display()
            ),
        )
        .into());
    }

    app.manage(BackendProcess(Mutex::new(Some(ManagedBackend {
        child,
        startup_nonce,
    }))));

    let url = BACKEND_URL.parse().expect("constant backend URL");
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("Daedalus")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .build()?;

    Ok(())
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
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(start_desktop)
        .build(tauri::generate_context!())
        .expect("failed to build Daedalus desktop application");

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
    fn generic_listener_cannot_satisfy_readiness() {
        let address = one_response("HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}".to_owned());
        assert!(!probe_authenticated_readiness(address, &"a".repeat(64)));
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
