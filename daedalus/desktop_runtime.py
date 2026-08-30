"""Desktop-owned lifecycle for the Daedalus file bridge and Ollama."""
from __future__ import annotations

import atexit
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONFIG_REL = Path("config/connections.json")
KNOWN_HOSTS_REL = Path("config/known_hosts")
LOG_REL = Path("runs/desktop_runtime.log")

TUNNEL_FORWARD_VAR = "DAEDALUS_OLLAMA_TUNNEL_FORWARD"
TUNNEL_TARGET_VAR = "DAEDALUS_OLLAMA_TUNNEL_TARGET"
REMOTE_OK_VAR = "DAEDALUS_OLLAMA_REMOTE_OK"
TRUSTED_HOSTS_VAR = "DAEDALUS_TRUSTED_HOSTS"

DEFAULT_CONFIG: dict[str, Any] = {
    "bridge": {"auto_start": True},
    "ollama": {
        "mode": "local",
        "auto_start": True,
        "model": "qwen2.5-coder:7b",
        "local_host": "http://127.0.0.1:11434",
        "remote": {
            "host": "",
            "user": "",
            "port": 22,
            "identity_file": "",
            "host_key_fingerprint": "",
            "local_port": 11435,
            "remote_port": 11434,
            "start_method": "systemd",
            "trust_remote_host": False,
        },
    },
}

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FP_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,}={0,2}$")


class DesktopRuntimeError(RuntimeError):
    pass


def _defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _port(value: Any, name: str, low: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a TCP port")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a TCP port") from None
    if not low <= port <= 65535:
        raise ValueError(f"{name} must be between {low} and 65535")
    return port


def _loopback_endpoint(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        host, port = parsed.hostname or "", parsed.port
        local = bool(ipaddress.ip_address(host).is_loopback)
    except (ValueError, UnicodeError):
        raise ValueError("local_host must look like http://127.0.0.1:11434") from None
    if (
        not local
        or parsed.scheme != "http"
        or port is None
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("local_host must look like http://127.0.0.1:11434")
    # Preserve brackets around IPv6 loopback. Reconstructing from
    # parsed.hostname would turn http://[::1]:11434 into an invalid URL.
    return raw


def _numeric_host(value: str) -> str | None:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if addr.is_unspecified or addr.is_multicast or addr.is_reserved or addr.is_link_local:
        return None
    return str(addr)


def normalize_config(raw: Any) -> dict[str, Any]:
    """Whitelist settings. Passwords, tokens, key bytes and commands are invalid."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("settings must be a JSON object")
    b = raw.get("bridge") if isinstance(raw.get("bridge"), dict) else {}
    o = raw.get("ollama") if isinstance(raw.get("ollama"), dict) else {}
    r = o.get("remote") if isinstance(o.get("remote"), dict) else {}

    cfg = _defaults()
    cfg["bridge"]["auto_start"] = bool(b.get("auto_start", True))
    mode = str(o.get("mode", "local")).strip()
    if mode not in {"local", "remote_ssh"}:
        raise ValueError("ollama.mode must be local or remote_ssh")
    cfg["ollama"]["mode"] = mode
    cfg["ollama"]["auto_start"] = bool(o.get("auto_start", True))

    model = str(o.get("model", cfg["ollama"]["model"])).strip()
    if not model or len(model) > 200 or any(ord(ch) < 32 for ch in model):
        raise ValueError("ollama.model must be 1..200 printable characters")
    cfg["ollama"]["model"] = model
    cfg["ollama"]["local_host"] = _loopback_endpoint(
        o.get("local_host", cfg["ollama"]["local_host"])
    )

    dst = cfg["ollama"]["remote"]
    host, user = str(r.get("host", "")).strip(), str(r.get("user", "")).strip()
    if host and (host.startswith("-") or not _HOST_RE.fullmatch(host)):
        raise ValueError("remote.host must be a DNS name or IPv4 address")
    if user and not _USER_RE.fullmatch(user):
        raise ValueError("remote.user contains unsupported characters")
    dst["host"], dst["user"] = host, user
    dst["port"] = _port(r.get("port", 22), "remote.port")
    dst["local_port"] = _port(r.get("local_port", 11435), "remote.local_port", 1024)
    dst["remote_port"] = _port(r.get("remote_port", 11434), "remote.remote_port")

    identity = str(r.get("identity_file", "")).strip()
    if any(ch in identity for ch in ("\x00", "\n", "\r")):
        raise ValueError("remote.identity_file is invalid")
    dst["identity_file"] = identity

    fingerprint = str(r.get("host_key_fingerprint", "")).strip()
    if fingerprint and not _FP_RE.fullmatch(fingerprint):
        raise ValueError("host key fingerprint must use OpenSSH SHA256:... format")
    dst["host_key_fingerprint"] = fingerprint

    method = str(r.get("start_method", "systemd")).strip()
    if method not in {"systemd", "windows", "none"}:
        raise ValueError("remote.start_method must be systemd, windows, or none")
    dst["start_method"] = method
    dst["trust_remote_host"] = bool(r.get("trust_remote_host", False))

    if mode == "remote_ssh":
        if not host or not user:
            raise ValueError("remote SSH mode requires remote.host and remote.user")
        if dst["trust_remote_host"] and _numeric_host(host) is None:
            raise ValueError("trusted remote hosts must be numeric IP addresses")
    return cfg


def install_tunnel_egress_policy() -> None:
    """Classify a local SSH forward by its physical peer, not 127.0.0.1."""
    from . import sensitivity

    current = sensitivity.lane_for_host
    if getattr(current, "_daedalus_tunnel_aware", False):
        return
    original = current

    def tunnel_aware(host: str | None) -> str:
        forward = os.environ.get(TUNNEL_FORWARD_VAR, "").strip().rstrip("/")
        target = os.environ.get(TUNNEL_TARGET_VAR, "").strip().rstrip("/")
        asked = (host or "").strip().rstrip("/")
        return original(target) if forward and target and asked == forward else original(host)

    tunnel_aware._daedalus_tunnel_aware = True  # type: ignore[attr-defined]
    sensitivity.lane_for_host = tunnel_aware


class DesktopRuntimeManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / CONFIG_REL
        self.known_hosts_path = self.root / KNOWN_HOSTS_REL
        self.log_path = self.root / LOG_REL
        self._lock = threading.RLock()
        self._bridge: threading.Thread | None = None
        self._tunnel: subprocess.Popen[bytes] | None = None
        self._ollama: subprocess.Popen[bytes] | None = None
        self._tunnel_log = None
        self._ollama_log = None
        self._closed = False
        self._base_trusted = os.environ.get(TRUSTED_HOSTS_VAR, "")
        self._config_error = ""
        self.config = self._load()
        self.apply_environment()
        atexit.register(self.close)

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _defaults()
        except (OSError, json.JSONDecodeError) as exc:
            self._config_error = f"cannot read {self.config_path}: {exc}"
            return _defaults()
        try:
            return normalize_config(raw)
        except ValueError as exc:
            self._config_error = f"invalid desktop settings: {exc}"
            return _defaults()

    def _save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.config_path.with_name(f".{self.config_path.name}.{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps(self.config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            os.replace(tmp, self.config_path)
        except OSError as exc:
            raise DesktopRuntimeError(f"cannot write {self.config_path}: {exc}") from exc

    def _log(self, message: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as out:
                out.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
        except OSError:
            pass

    @staticmethod
    def _creationflags() -> int:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0

    def _child_log(self, label: str):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        out = self.log_path.open("ab", buffering=0)
        out.write(f"\n--- {label} {time.strftime('%Y-%m-%dT%H:%M:%S')} ---\n".encode())
        return out

    def save_settings(self, raw: Any) -> dict[str, Any]:
        new = normalize_config(raw)
        old_route = (
            self.config["ollama"]["mode"],
            json.dumps(self.config["ollama"]["remote"], sort_keys=True),
        )
        new_route = (new["ollama"]["mode"], json.dumps(new["ollama"]["remote"], sort_keys=True))
        with self._lock:
            if old_route != new_route:
                self.stop_ollama_transport()
            previous = self.config
            self.config = new
            try:
                self._save()
            except DesktopRuntimeError:
                self.config = previous
                raise
            self._config_error = ""
            self.apply_environment()
        startup_error = ""
        if new["bridge"]["auto_start"]:
            self.ensure_bridge()
        if new["ollama"]["auto_start"]:
            try:
                self.ensure_ollama()
            except DesktopRuntimeError as exc:
                startup_error = str(exc)
                self._log(f"ollama settings autostart failed: {exc}")
        snap = self.snapshot()
        if startup_error:
            snap["startup_error"] = startup_error
        return snap

    def apply_environment(self) -> None:
        o = self.config["ollama"]
        os.environ["OLLAMA_MODEL"] = o["model"]
        trusted = [x.strip() for x in self._base_trusted.split(",") if x.strip()]
        if o["mode"] == "remote_ssh":
            r = o["remote"]
            forward = f"http://127.0.0.1:{r['local_port']}"
            target = f"http://{r['host']}:{r['remote_port']}"
            os.environ["OLLAMA_HOST"] = forward
            os.environ[TUNNEL_FORWARD_VAR] = forward
            os.environ[TUNNEL_TARGET_VAR] = target
            # Consent opens this exact transport; the egress wrapper still
            # classifies it by the physical peer unless that peer is trusted.
            os.environ[REMOTE_OK_VAR] = forward
            if r["trust_remote_host"]:
                numeric = _numeric_host(r["host"])
                if numeric:
                    trusted.append(numeric)
        else:
            os.environ["OLLAMA_HOST"] = o["local_host"]
            for key in (TUNNEL_FORWARD_VAR, TUNNEL_TARGET_VAR, REMOTE_OK_VAR):
                os.environ.pop(key, None)
        if trusted:
            os.environ[TRUSTED_HOSTS_VAR] = ",".join(dict.fromkeys(trusted))
        else:
            os.environ.pop(TRUSTED_HOSTS_VAR, None)

    def bootstrap(self) -> dict[str, Any]:
        if self.config["bridge"]["auto_start"]:
            self.ensure_bridge()
        if self.config["ollama"]["auto_start"]:
            try:
                self.ensure_ollama()
            except DesktopRuntimeError as exc:
                self._log(f"ollama autostart failed: {exc}")
        return self.snapshot()

    # Bridge ---------------------------------------------------------------

    def _watch_bridge(self) -> None:
        from . import file_bridge

        while not self._closed:
            try:
                file_bridge.watch(str(self.root), 2.0, project="daedalus")
            except Exception as exc:
                self._log(f"bridge failed: {type(exc).__name__}: {exc}")
                if not self._closed:
                    time.sleep(2)

    def ensure_bridge(self) -> dict[str, Any]:
        from . import file_bridge

        status = file_bridge.heartbeat_status()
        if status.get("state") in {"alive", "busy", "wedged"}:
            return {"managed": bool(self._bridge and self._bridge.is_alive()), **status}
        with self._lock:
            if not (self._bridge and self._bridge.is_alive()):
                self._bridge = threading.Thread(
                    target=self._watch_bridge, name="daedalus-file-bridge", daemon=True
                )
                self._bridge.start()
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            status = file_bridge.heartbeat_status()
            if status.get("state") in {"alive", "busy", "wedged"}:
                break
            time.sleep(0.05)
        return {"managed": bool(self._bridge and self._bridge.is_alive()), **status}

    # Ollama ---------------------------------------------------------------

    def _probe(self, timeout: float = 1.5) -> tuple[bool, str]:
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        try:
            with urllib.request.urlopen(host + "/api/tags", timeout=timeout) as response:
                json.loads(response.read().decode("utf-8"))
                return 200 <= response.status < 300, ""
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
            return False, str(exc)

    def ensure_ollama(self) -> dict[str, Any]:
        return (
            self.ensure_remote_ollama()
            if self.config["ollama"]["mode"] == "remote_ssh"
            else self.ensure_local_ollama()
        )

    def ensure_local_ollama(self) -> dict[str, Any]:
        ok, detail = self._probe()
        if ok:
            return {"mode": "local", "running": True, "reachable": True, "detail": ""}
        with self._lock:
            if not (self._ollama and self._ollama.poll() is None):
                exe = shutil.which("ollama")
                if not exe:
                    raise DesktopRuntimeError(
                        "Ollama is offline and the 'ollama' executable is not on PATH"
                    )
                self._ollama_log = self._child_log("local ollama")
                self._ollama = subprocess.Popen(
                    [exe, "serve"],
                    stdin=subprocess.DEVNULL,
                    stdout=self._ollama_log,
                    stderr=self._ollama_log,
                    creationflags=self._creationflags(),
                )
            proc = self._ollama
        end = time.monotonic() + 6
        while proc and proc.poll() is None and time.monotonic() < end:
            ok, detail = self._probe(0.5)
            if ok:
                break
            time.sleep(0.2)
        return {
            "mode": "local",
            "running": bool(proc and proc.poll() is None),
            "reachable": ok,
            "detail": detail,
        }

    # SSH ------------------------------------------------------------------

    def _remote(self) -> dict[str, Any]:
        return self.config["ollama"]["remote"]

    def _pin_host_key(self) -> None:
        r = self._remote()
        fp = r["host_key_fingerprint"]
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        if not fp:
            if self.known_hosts_path.exists() and self.known_hosts_path.stat().st_size:
                return
            raise DesktopRuntimeError(
                "First SSH connection requires the server's SHA256 host-key fingerprint"
            )
        keyscan, keygen = shutil.which("ssh-keyscan"), shutil.which("ssh-keygen")
        if not keyscan or not keygen:
            raise DesktopRuntimeError("ssh-keyscan and ssh-keygen are required")
        try:
            scan = subprocess.run(
                [keyscan, "-T", "5", "-p", str(r["port"]), r["host"]],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
                creationflags=self._creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesktopRuntimeError(f"SSH host-key scan failed: {exc}") from exc
        keys = [
            line.strip()
            for line in scan.stdout.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        matched: list[str] = []
        for key in keys:
            name = ""
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.known_hosts_path.parent, delete=False
                ) as tmp:
                    tmp.write(key + "\n")
                    name = tmp.name
                checked = subprocess.run(
                    [keygen, "-lf", name, "-E", "sha256"],
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                    creationflags=self._creationflags(),
                )
                if checked.returncode == 0 and fp in checked.stdout.split():
                    matched.append(key)
            finally:
                if name:
                    try:
                        Path(name).unlink()
                    except OSError:
                        pass
        if not matched:
            raise DesktopRuntimeError("SSH host-key fingerprint mismatch; connection refused")
        tmp = self.known_hosts_path.with_name(f".{self.known_hosts_path.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(matched) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.known_hosts_path)

    def _ssh(self) -> list[str]:
        r = self._remote()
        exe = shutil.which("ssh")
        if not exe:
            raise DesktopRuntimeError("OpenSSH client 'ssh' is not on PATH")
        args = [
            exe, "-T", "-p", str(r["port"]),
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
        ]
        if r["identity_file"]:
            key = Path(r["identity_file"]).expanduser()
            if not key.is_file():
                raise DesktopRuntimeError(f"SSH identity file does not exist: {key}")
            args += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
        return args

    def _target(self) -> str:
        r = self._remote()
        return f"{r['user']}@{r['host']}"

    def _start_remote_service(self) -> None:
        method = self._remote()["start_method"]
        if method == "none":
            return
        command = (
            "sudo -n systemctl start ollama && systemctl is-active --quiet ollama"
            if method == "systemd"
            else (
                'powershell.exe -NoProfile -NonInteractive -Command '
                '"$p=Get-Process ollama -ErrorAction SilentlyContinue; '
                "if (-not $p) { Start-Process -WindowStyle Hidden "
                "-FilePath 'ollama' -ArgumentList 'serve' }\""
            )
        )
        try:
            run = subprocess.run(
                self._ssh() + [self._target(), command],
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=self._creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesktopRuntimeError(f"remote Ollama start failed: {exc}") from exc
        if run.returncode:
            detail = (run.stderr or run.stdout or f"exit {run.returncode}").strip()
            if method == "systemd":
                detail += " (use passwordless permission for 'systemctl start ollama', or 'already running')"
            raise DesktopRuntimeError(f"remote Ollama start failed: {detail[:500]}")

    def ensure_remote_ollama(self) -> dict[str, Any]:
        if self.config["ollama"]["mode"] != "remote_ssh":
            raise DesktopRuntimeError("remote Ollama is not selected")
        self._pin_host_key()
        with self._lock:
            if not (self._tunnel and self._tunnel.poll() is None):
                self._start_remote_service()
                r = self._remote()
                self._tunnel_log = self._child_log("ollama ssh tunnel")
                args = self._ssh() + [
                    "-o", "ExitOnForwardFailure=yes",
                    "-L", f"127.0.0.1:{r['local_port']}:127.0.0.1:{r['remote_port']}",
                    self._target(),
                    "cat",
                ]
                self._tunnel = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=self._tunnel_log,
                    stderr=self._tunnel_log,
                    creationflags=self._creationflags(),
                )
            proc = self._tunnel
        ok, detail = False, ""
        end = time.monotonic() + 8
        while proc and proc.poll() is None and time.monotonic() < end:
            ok, detail = self._probe(0.5)
            if ok:
                break
            time.sleep(0.25)
        if not proc or proc.poll() is not None:
            raise DesktopRuntimeError(f"SSH tunnel exited; see {self.log_path}")
        return {
            "mode": "remote_ssh",
            "running": True,
            "reachable": ok,
            "detail": detail,
            "target": os.environ.get(TUNNEL_TARGET_VAR, ""),
        }

    def stop_ollama_transport(self) -> None:
        with self._lock:
            proc, self._tunnel = self._tunnel, None
            if proc and proc.poll() is None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                    proc.terminate()
                    proc.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            if self._tunnel_log:
                try:
                    self._tunnel_log.close()
                except OSError:
                    pass
                self._tunnel_log = None

    def close(self) -> None:
        self._closed = True
        self.stop_ollama_transport()
        with self._lock:
            proc, self._ollama = self._ollama, None
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            if self._ollama_log:
                try:
                    self._ollama_log.close()
                except OSError:
                    pass
                self._ollama_log = None

    def snapshot(self) -> dict[str, Any]:
        from . import file_bridge

        ok, err = self._probe()
        r = self.config["ollama"]["remote"]
        return {
            "config": self.config,
            "config_path": str(self.config_path),
            "config_error": self._config_error,
            "credential_policy": {
                "ssh_key_only": True,
                "stores_passwords": False,
                "stores_private_key_bytes": False,
                "host_key_verification": "strict",
            },
            "services": {
                "bridge": {
                    "managed": bool(self._bridge and self._bridge.is_alive()),
                    **file_bridge.heartbeat_status(),
                },
                "ollama": {
                    "mode": self.config["ollama"]["mode"],
                    "endpoint": os.environ.get("OLLAMA_HOST", ""),
                    "physical_target": os.environ.get(TUNNEL_TARGET_VAR, ""),
                    "reachable": ok,
                    "last_error": "" if ok else err,
                    "tunnel_running": bool(self._tunnel and self._tunnel.poll() is None),
                    "local_process_running": bool(self._ollama and self._ollama.poll() is None),
                    "host_key_pinned": bool(
                        r["host_key_fingerprint"]
                        or (self.known_hosts_path.exists() and self.known_hosts_path.stat().st_size)
                    ),
                },
            },
        }


def install_web_integration(web_api: Any, manager: DesktopRuntimeManager) -> None:
    """Add desktop routes without creating a second HTTP/control server."""
    base = web_api.DaedalusHandler

    class ManagedHandler(base):
        def _handle_get(self) -> None:
            if urlsplit(self.path).path == "/api/desktop/settings":
                self._send_json(web_api.core.envelope(None, desktop=manager.snapshot()))
                return
            super()._handle_get()

        def _handle_put(self) -> None:
            if urlsplit(self.path).path == "/api/desktop/settings":
                try:
                    snap = manager.save_settings(web_api._read_body(self))
                    web_api.runtime_registry.reset_status_cache()
                    self._send_json(web_api.core.envelope(None, desktop=snap))
                except (ValueError, DesktopRuntimeError) as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            super()._handle_put()

        def _handle_post(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path == "/api/desktop/services/bridge/start":
                    result = manager.ensure_bridge()
                elif path == "/api/desktop/services/ollama/start":
                    result = manager.ensure_ollama()
                    web_api.runtime_registry.reset_status_cache()
                elif path == "/api/desktop/services/ollama/stop":
                    manager.stop_ollama_transport()
                    result = manager.snapshot()["services"]["ollama"]
                else:
                    super()._handle_post()
                    return
                self._send_json(web_api.core.envelope(None, service=result))
            except DesktopRuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    web_api.DaedalusHandler = ManagedHandler
