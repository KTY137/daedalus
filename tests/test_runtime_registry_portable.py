from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import runtime_registry
from daedalus.providers.ollama import ollama_http_base_url


class PortableRuntimeRegistryTest(unittest.TestCase):
    def test_codex_extension_payload_is_specific_to_os_and_architecture(self) -> None:
        cases = (
            ("win32", "AMD64", ("windows-x86_64", "codex.exe")),
            ("win32", "arm64", ("windows-aarch64", "codex.exe")),
            ("linux", "x86_64", ("linux-x86_64", "codex")),
            ("linux", "aarch64", ("linux-aarch64", "codex")),
            ("darwin", "x86_64", ("macos-x86_64", "codex")),
            ("darwin", "arm64", ("macos-aarch64", "codex")),
        )
        for platform_name, machine, expected in cases:
            with self.subTest(platform=platform_name, machine=machine):
                self.assertEqual(
                    runtime_registry._codex_extension_payload(
                        platform_name=platform_name, machine=machine
                    ),
                    expected,
                )
        self.assertIsNone(
            runtime_registry._codex_extension_payload(
                platform_name="win32", machine="i686"
            )
        )
        self.assertIsNone(
            runtime_registry._codex_extension_payload(
                platform_name="freebsd", machine="x86_64"
            )
        )

    def test_codex_extension_discovery_never_crosses_native_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            extension = home / ".vscode" / "extensions" / "openai.chatgpt-1.2.3-win32-x64"
            linux = extension / "bin" / "linux-x86_64" / "codex"
            windows = extension / "bin" / "windows-x86_64" / "codex.exe"
            linux.parent.mkdir(parents=True)
            windows.parent.mkdir(parents=True)
            linux.write_bytes(b"linux")
            windows.write_bytes(b"windows")
            linux.chmod(0o700)
            windows.chmod(0o700)
            env = {"HOME": str(home), "PATH": ""}

            with mock.patch.object(
                runtime_registry,
                "_codex_extension_payload",
                return_value=("windows-x86_64", "codex.exe"),
            ):
                self.assertEqual(
                    runtime_registry.resolve_runtime_command(
                        "codex_cli", environ=env
                    ),
                    str(windows.resolve()),
                )
            with mock.patch.object(
                runtime_registry,
                "_codex_extension_payload",
                return_value=("linux-x86_64", "codex"),
            ):
                self.assertEqual(
                    runtime_registry.resolve_runtime_command(
                        "codex_cli", environ=env
                    ),
                    str(linux.resolve()),
                )

    def test_explicit_cli_override_wins_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / ("codex.exe" if os.name == "nt" else "codex")
            binary.write_bytes(b"test")
            if os.name != "nt":
                binary.chmod(0o700)
            env = {"PATH": "", "DAEDALUS_CODEX_CLI": str(binary)}
            self.assertEqual(
                runtime_registry.resolve_runtime_command("codex_cli", environ=env),
                str(binary.resolve()),
            )

    def test_explicit_cli_override_keeps_precedence_over_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            override = root / ("override.exe" if os.name == "nt" else "override")
            on_path = root / ("codex.exe" if os.name == "nt" else "codex")
            for binary in (override, on_path):
                binary.write_bytes(b"test")
                if os.name != "nt":
                    binary.chmod(0o700)
            env = {
                "PATH": str(root),
                "DAEDALUS_CODEX_CLI": str(override),
            }
            with mock.patch.object(
                runtime_registry.shutil, "which", return_value=str(on_path)
            ):
                self.assertEqual(
                    runtime_registry.resolve_runtime_command(
                        "codex_cli", environ=env
                    ),
                    str(override.resolve()),
                )

    def test_codex_child_binds_existing_home_without_copying_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            codex_home = Path(td) / ".codex"
            codex_home.mkdir()
            env = runtime_registry.runtime_subprocess_env(
                "codex_cli", environ={"HOME": td, "PATH": ""}
            )
            self.assertEqual(env["CODEX_HOME"], str(codex_home))
            self.assertEqual(list(codex_home.iterdir()), [])

    def test_remote_ollama_is_refused_before_network_probe(self) -> None:
        remote = "100.119.126.9:11434"
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_HOST": remote, "DAEDALUS_OLLAMA_REMOTE_OK": ""},
            clear=False,
        ), mock.patch.object(runtime_registry.urllib.request, "urlopen") as urlopen:
            status = runtime_registry.runtime_status("ollama_http")
        self.assertFalse(status["available"])
        self.assertEqual(status["auth_status"], "egress_refused")
        urlopen.assert_not_called()

    def test_schemeless_ollama_host_gets_http_request_spelling(self) -> None:
        self.assertEqual(
            ollama_http_base_url("127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )


if __name__ == "__main__":
    unittest.main()
