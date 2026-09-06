//! Windows desktop ownership, acquired before Tauri or backend setup begins.
//!
//! The named object's lifetime is the guard; it is not a persistent lock file
//! or a claim about ownership of any service listening on the backend port.

use std::ffi::OsString;
use std::io;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::ptr;
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE, HWND, LPARAM,
};
use windows_sys::Win32::System::Threading::{
    CreateMutexW, OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindow, GetWindowTextW, GetWindowThreadProcessId, IsIconic, IsWindowVisible,
    SetForegroundWindow, ShowWindowAsync, GW_OWNER, SW_RESTORE, SW_SHOW,
};

const INSTANCE_NAME: &str = r"Local\dev.daedalus.desktop.instance";

/// Keep this value alive until the desktop event loop and child cleanup finish.
#[must_use = "dropping the guard permits another desktop process to start"]
pub struct InstanceGuard(HANDLE);

impl Drop for InstanceGuard {
    fn drop(&mut self) {
        // SAFETY: this guard exclusively owns a valid, non-inherited handle.
        unsafe { CloseHandle(self.0) };
    }
}

pub fn acquire() -> io::Result<Option<InstanceGuard>> {
    acquire_named(INSTANCE_NAME)
}

fn acquire_named(name: &str) -> io::Result<Option<InstanceGuard>> {
    let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    // Object creation is atomic across processes. No thread takes mutex
    // ownership: only the existence of our non-inherited handle matters.
    // SAFETY: the name is NUL-terminated and valid throughout the call.
    let (handle, error) = unsafe {
        let handle = CreateMutexW(ptr::null(), 0, name.as_ptr());
        (handle, GetLastError())
    };
    if handle.is_null() {
        return Err(io::Error::from_raw_os_error(error as i32));
    }
    if error == ERROR_ALREADY_EXISTS {
        // A second process must refuse even if the first has no window yet.
        // SAFETY: CreateMutexW returned our own valid handle to the object.
        unsafe { CloseHandle(handle) };
        return Ok(None);
    }
    Ok(Some(InstanceGuard(handle)))
}

/// Best-effort activation only of this executable's existing main window.
/// A first launch that is still preparing resources may have no window yet.
pub fn focus_existing() {
    let Ok(executable) = std::env::current_exe().and_then(std::fs::canonicalize) else {
        return;
    };
    // SAFETY: EnumWindows invokes its callback synchronously; the immutable
    // path remains live for the entire enumeration and is never retained.
    unsafe {
        EnumWindows(Some(focus_window), &executable as *const PathBuf as LPARAM);
    }
}

unsafe extern "system" fn focus_window(window: HWND, context: LPARAM) -> i32 {
    // Only the unowned top-level main window has this title. Dialogs and other
    // applications with the same title are excluded by owner and image path.
    if !GetWindow(window, GW_OWNER).is_null() {
        return 1;
    }
    let mut title = [0_u16; 64];
    let length = GetWindowTextW(window, title.as_mut_ptr(), title.len() as i32);
    if length != 8 || title[..8] != [68, 97, 101, 100, 97, 108, 117, 115] {
        return 1;
    }
    let mut process_id = 0;
    GetWindowThreadProcessId(window, &mut process_id);
    if process_id == 0 || process_id == std::process::id() {
        return 1;
    }
    let executable = &*(context as *const PathBuf);
    if !process_matches_executable(process_id, executable) {
        return 1;
    }

    // Posting the show operation avoids waiting for a busy startup thread.
    // Preserve an already maximized window; restore only a minimized one.
    if IsIconic(window) != 0 {
        ShowWindowAsync(window, SW_RESTORE);
    } else if IsWindowVisible(window) == 0 {
        ShowWindowAsync(window, SW_SHOW);
    }
    SetForegroundWindow(window);
    0
}

fn process_matches_executable(process_id: u32, executable: &Path) -> bool {
    // SAFETY: no write/terminate access is requested, and handle inheritance
    // is disabled. Query failure simply excludes this window.
    let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, process_id) };
    if process.is_null() {
        return false;
    }
    let mut path = vec![0_u16; 32_768];
    let mut length = path.len() as u32;
    // SAFETY: path provides the advertised UTF-16 buffer capacity.
    let queried = unsafe { QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut length) };
    // SAFETY: this function exclusively owns the successful OpenProcess handle.
    unsafe { CloseHandle(process) };
    if queried == 0 {
        return false;
    }
    let path = PathBuf::from(OsString::from_wide(&path[..length as usize]));
    // Canonical full paths avoid accepting an unrelated executable by basename
    // or window title, including another installation of Daedalus.
    path.canonicalize().is_ok_and(|path| path == executable)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::os::windows::process::CommandExt;
    use std::process::{Child, Command, Stdio};
    use std::sync::mpsc;
    use std::time::{Duration, Instant};
    use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

    const CHILD_TEST: &str = "instance::tests::instance_guard_child";
    const NAME_ENV: &str = "DAEDALUS_TEST_INSTANCE_NAME";
    const MODE_ENV: &str = "DAEDALUS_TEST_INSTANCE_MODE";

    fn unique_name() -> String {
        let mut nonce = [0_u8; 16];
        getrandom::getrandom(&mut nonce).expect("test name entropy");
        let nonce: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
        format!(
            r"Local\dev.daedalus.desktop.test.{}.{nonce}",
            std::process::id()
        )
    }

    // Own and reap every helper, including on assertion failure. No files,
    // production mutex names, application windows, or backend ports are used.
    struct Helper {
        child: Child,
        output: mpsc::Receiver<String>,
    }

    impl Helper {
        fn spawn(name: &str, mode: &str) -> Self {
            let mut child = Command::new(std::env::current_exe().unwrap())
                .args(["--exact", CHILD_TEST, "--nocapture", "--test-threads=1"])
                .env(NAME_ENV, name)
                .env(MODE_ENV, mode)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::inherit())
                .creation_flags(CREATE_NO_WINDOW)
                .spawn()
                .expect("spawn isolated instance helper");
            let stdout = child.stdout.take().unwrap();
            let (sender, output) = mpsc::channel();
            std::thread::spawn(move || {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    if sender.send(line).is_err() {
                        break;
                    }
                }
            });
            Self { child, output }
        }

        fn expect(&mut self, marker: &str) {
            let deadline = Instant::now() + Duration::from_secs(15);
            let mut received = Vec::new();
            loop {
                let line = self
                    .output
                    .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                    .unwrap_or_else(|error| panic!("missing {marker}: {error}; {received:?}"));
                if line.contains(marker) {
                    return;
                }
                received.push(line);
            }
        }

        fn wait_success(&mut self) {
            let deadline = Instant::now() + Duration::from_secs(15);
            loop {
                if let Some(status) = self.child.try_wait().unwrap() {
                    assert!(status.success(), "instance helper failed: {status}");
                    return;
                }
                assert!(Instant::now() < deadline, "instance helper did not exit");
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }

    impl Drop for Helper {
        fn drop(&mut self) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }

    // This is invoked by the same console test executable in a fresh process.
    // The ordinary test run has no environment values and performs no action.
    #[test]
    fn instance_guard_child() {
        let Ok(name) = std::env::var(NAME_ENV) else {
            return;
        };
        assert!(name.starts_with(r"Local\dev.daedalus.desktop.test."));
        let mode = std::env::var(MODE_ENV).unwrap();
        let guard = acquire_named(&name).unwrap();
        println!(
            "{}",
            if guard.is_some() {
                "INSTANCE_ACQUIRED"
            } else {
                "INSTANCE_BUSY"
            }
        );
        io::stdout().flush().unwrap();
        if mode == "hold" || mode == "exit-without-drop" {
            assert!(guard.is_some());
            let mut signal = [0];
            io::stdin().read_exact(&mut signal).unwrap();
            if mode == "exit-without-drop" {
                std::process::exit(0);
            }
        }
        drop(guard);
    }

    #[test]
    fn second_process_refuses_while_owner_lives_then_acquires_after_drop() {
        let name = unique_name();
        let owner = acquire_named(&name)
            .unwrap()
            .expect("first process owns instance");
        let mut second = Helper::spawn(&name, "probe");
        second.expect("INSTANCE_BUSY");
        second.wait_success();
        drop(owner);
        let mut third = Helper::spawn(&name, "probe");
        third.expect("INSTANCE_ACQUIRED");
        third.wait_success();
    }

    #[test]
    fn owner_process_exit_releases_instance_without_rust_drop() {
        let name = unique_name();
        let mut owner = Helper::spawn(&name, "exit-without-drop");
        owner.expect("INSTANCE_ACQUIRED");
        assert!(acquire_named(&name).unwrap().is_none());
        owner.child.stdin.as_mut().unwrap().write_all(b"x").unwrap();
        owner.wait_success();
        assert!(acquire_named(&name).unwrap().is_some());
    }

    #[test]
    fn terminated_owner_releases_instance() {
        let name = unique_name();
        let mut owner = Helper::spawn(&name, "hold");
        owner.expect("INSTANCE_ACQUIRED");
        assert!(acquire_named(&name).unwrap().is_none());
        owner.child.kill().unwrap();
        owner.child.wait().unwrap();
        assert!(acquire_named(&name).unwrap().is_some());
    }

    #[test]
    fn focus_image_check_requires_matching_full_executable_path() {
        let executable = std::env::current_exe().unwrap().canonicalize().unwrap();
        assert!(process_matches_executable(std::process::id(), &executable));
        assert!(!process_matches_executable(
            std::process::id(),
            &executable.with_file_name("unrelated-executable.exe")
        ));
    }
}
