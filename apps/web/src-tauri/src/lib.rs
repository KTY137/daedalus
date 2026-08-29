use std::{
    error::Error,
    fs, io,
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
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);

struct BackendProcess(Mutex<Option<Child>>);

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

fn spawn_backend(backend_root: &Path, executable: &Path) -> io::Result<Child> {
    let log_path = backend_root.join("desktop-backend.log");
    let stdout = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)?;
    let stderr = stdout.try_clone()?;

    let mut command = Command::new(executable);
    command
        .args(["--host", "127.0.0.1", "--port", "8765"])
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

fn wait_until_ready(child: &mut Child) -> io::Result<()> {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let address: SocketAddr = BACKEND_ADDR.parse().expect("constant socket address");

    while Instant::now() < deadline {
        if let Some(status) = child.try_wait()? {
            return Err(io::Error::other(format!(
                "Daedalus backend exited before startup completed: {status}"
            )));
        }
        if TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok() {
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
    let mut child = spawn_backend(&backend_root, &executable)?;
    if let Err(error) = wait_until_ready(&mut child) {
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

    app.manage(BackendProcess(Mutex::new(Some(child))));

    let url = BACKEND_URL.parse().expect("constant backend URL");
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("Daedalus")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .build()?;

    Ok(())
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .setup(start_desktop)
        .build(tauri::generate_context!())
        .expect("failed to build Daedalus desktop application");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_backend(app_handle);
        }
    });
}
