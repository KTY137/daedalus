"""Offline packaging contracts for the opt-in CUDA research environment."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PYTORCH_CU126_INDEX = "https://download.pytorch.org/whl/cu126"


def _section(text: str, header: str) -> str:
    match = re.search(
        rf"^\[{re.escape(header)}\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing [{header}]"
    return match.group("body")


def _bash_executable() -> str:
    candidates: list[str] = []
    if os.name == "nt":
        candidates.append(r"C:\Program Files\Git\bin\bash.exe")
    discovered = shutil.which("bash")
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        completed = subprocess.run(
            [candidate, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if completed.returncode == 0 and "GNU bash" in completed.stdout:
            return candidate
    pytest.skip("GNU Bash is not available for the offline preflight refusal fixture")


def _run_posix_preflight_fixture(tmp_path: Path, fixture: str) -> subprocess.CompletedProcess[str]:
    script = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")
    functions = script[
        script.index("version_at_least() {") : script.index('\necho "== daedalus bootstrap =="')
    ]
    function_file = tmp_path / "gpu-preflight-functions.sh"
    function_file.write_text(functions, encoding="utf-8")
    return subprocess.run(
        [_bash_executable(), "-c", f'source "$1"\n{fixture}', "fixture", str(function_file)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )


def test_gpu_extra_is_explicit_and_core_stays_dependency_free() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    project = _section(text, "project")
    optional = _section(text, "project.optional-dependencies")

    assert re.search(r"^dependencies\s*=\s*\[\s*\]\s*$", project, re.MULTILINE)
    gpu_match = re.search(r"^gpu\s*=\s*\[(?P<body>.*?)^\]", optional, re.MULTILINE | re.DOTALL)
    assert gpu_match is not None
    gpu = gpu_match.group("body")

    requirements = set(re.findall(r'^\s*"([^"]+)",?\s*$', gpu, re.MULTILINE))
    marker = "; sys_platform == 'win32' or sys_platform == 'linux'"
    assert requirements == {
        f"torch==2.14.0+cu126{marker}",
        f"newton==1.5.1{marker}",
        f"warp-lang==1.17.0{marker}",
        f"cupy-cuda12x[ctk]==14.2.0{marker}",
        f"cuda-toolkit[cublas,cudart,cufft,curand,cusolver,cusparse,nvrtc]==12.6.3{marker}",
    }
    assert "cugraph" not in gpu.lower()
    assert "cuvs" not in gpu.lower()


def test_uv_uses_an_explicit_cuda_126_source_for_torch_only() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    sources = _section(text, "tool.uv.sources")
    index_match = re.search(
        r'^\[\[tool\.uv\.index\]\]\s*$\n(?P<body>.*?)(?=^\[|\Z)',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert index_match is not None
    index = index_match.group("body")

    assert re.search(r'^torch\s*=\s*\{\s*index\s*=\s*"pytorch-cu126"\s*\}\s*$', sources, re.MULTILINE)
    assert 'name = "pytorch-cu126"' in index
    assert f'url = "{PYTORCH_CU126_INDEX}"' in index
    assert re.search(r"^explicit\s*=\s*true\s*$", index, re.MULTILINE)


def test_bootstrap_keeps_gpu_packages_behind_an_explicit_flag() -> None:
    windows = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    posix = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")
    windows_commands = "\n".join(
        line for line in windows.splitlines() if not line.lstrip().startswith("#")
    )
    posix_commands = "\n".join(
        line for line in posix.splitlines() if not line.lstrip().startswith("#")
    )

    assert "[switch]$GpuResearch" in windows
    assert 'if ($GpuResearch)' in windows
    assert "uv sync --locked --all-extras" in windows
    assert '".[yaml]"' in windows
    assert "Get-Command uv" in windows
    assert "--extra-index-url" not in windows_commands
    assert "torch.version.cuda == '12.6'" in windows
    assert "torch.cuda.is_available()" in windows
    assert "bounded CUDA oracle mismatch" in windows
    assert "uv pip check" in windows
    assert windows.index("bounded CUDA oracle mismatch") < windows.index(
        "daedalus accelerators --deep --json"
    ) < windows.index("# 4. Ollama")

    assert "--gpu-research" in posix
    assert '[ "$GPU_RESEARCH" -eq 1 ]' in posix
    assert "uv sync --locked --all-extras" in posix
    assert '".[yaml]"' in posix
    assert "command -v uv" in posix
    assert "--extra-index-url" not in posix_commands
    assert "torch.version.cuda == '12.6'" in posix
    assert "torch.cuda.is_available()" in posix
    assert "bounded CUDA oracle mismatch" in posix
    assert "uv pip check" in posix
    assert posix.index("bounded CUDA oracle mismatch") < posix.index(
        "daedalus accelerators --deep --json"
    ) < posix.index("# 4. Ollama")


def test_gpu_preflight_refuses_unsupported_architecture_before_install() -> None:
    windows = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    posix = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")

    windows_call = windows.index("    Assert-GpuResearchHost")
    windows_venv = windows.index("if (-not (Test-Path .venv))")
    windows_sync = windows.index("    uv sync --locked --all-extras")
    assert windows_call < windows_venv < windows_sync
    assert '$osArchitecture -ne "X64"' in windows
    assert '$processArchitecture -ne "X64"' in windows
    assert "only native x86-64 Windows" in windows

    posix_call = posix.index("  gpu_research_preflight")
    posix_venv = posix.index("[ -d .venv ]")
    posix_sync = posix.index("  uv sync --locked --all-extras")
    assert posix_call < posix_venv < posix_sync
    assert '[ "$machine" != "x86_64" ]' in posix
    assert '[ "$process_bits" != "64" ]' in posix
    assert "WSL is outside this experiment's frozen platform matrix" in posix


def test_gpu_preflight_requires_real_nvidia_inventory_before_install() -> None:
    windows = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    posix = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")

    for script in (windows, posix):
        preflight = script.index("nvidia-smi")
        sync = script.index("uv sync --locked --all-extras")
        assert preflight < sync
        assert "--query-gpu=name" in script
        assert "--query-gpu=driver_version" in script
        assert "--query-gpu=name,compute_cap" in script
        assert "No packages were installed" in script
        assert "Pre-install compute capability is advisory" in script

    assert 'Get-Command nvidia-smi -ErrorAction SilentlyContinue' in windows
    assert '[Version]"561.17.0.0"' in windows
    assert "nvidia-smi did not enumerate an NVIDIA GPU" in windows
    assert "command -v nvidia-smi" in posix
    assert 'minimum_driver="560.35.05"' in posix
    assert "nvidia-smi did not enumerate an NVIDIA GPU" in posix


def test_default_bootstrap_does_not_enter_gpu_preflight_or_locked_sync() -> None:
    windows = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    posix = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")

    windows_default = re.search(
        r"if \(\$GpuResearch\) \{\s+uv sync.*?\}\s+else \{(?P<body>.*?)\n\}",
        windows,
        flags=re.DOTALL,
    )
    posix_default = re.search(
        r'if \[ "\$GPU_RESEARCH" -eq 1 \]; then\s+uv sync.*?else\n(?P<body>.*?)\nfi',
        posix,
        flags=re.DOTALL,
    )
    assert windows_default is not None
    assert posix_default is not None
    for body in (windows_default.group("body"), posix_default.group("body")):
        assert '".[yaml]"' in body
        assert "nvidia-smi" not in body
        assert "uv sync" not in body


def test_posix_preflight_refuses_arm_offline(tmp_path: Path) -> None:
    completed = _run_posix_preflight_fixture(
        tmp_path,
        """
uname() {
  case "$1" in
    -s) printf 'Linux\\n' ;;
    -m) printf 'aarch64\\n' ;;
    -r) printf 'test-kernel\\n' ;;
  esac
}
getconf() { printf '64\\n'; }
gpu_research_preflight
""",
    )

    assert completed.returncode == 2
    assert "only native x86-64 Linux" in completed.stderr
    assert "No packages were installed" in completed.stderr


def test_posix_preflight_refuses_missing_nvidia_smi_offline(tmp_path: Path) -> None:
    completed = _run_posix_preflight_fixture(
        tmp_path,
        """
uname() {
  case "$1" in
    -s) printf 'Linux\\n' ;;
    -m) printf 'x86_64\\n' ;;
    -r) printf 'test-kernel\\n' ;;
  esac
}
getconf() { printf '64\\n'; }
PATH=/definitely/not/a/real/path
gpu_research_preflight
""",
    )

    assert completed.returncode == 2
    assert "requires nvidia-smi on PATH" in completed.stderr
    assert "No packages were installed" in completed.stderr


def test_posix_preflight_refuses_empty_gpu_inventory_offline(tmp_path: Path) -> None:
    completed = _run_posix_preflight_fixture(
        tmp_path,
        """
uname() {
  case "$1" in
    -s) printf 'Linux\\n' ;;
    -m) printf 'x86_64\\n' ;;
    -r) printf 'test-kernel\\n' ;;
  esac
}
getconf() { printf '64\\n'; }
nvidia-smi() { return 0; }
gpu_research_preflight
""",
    )

    assert completed.returncode == 2
    assert "did not enumerate an NVIDIA GPU" in completed.stderr
    assert "No packages were installed" in completed.stderr


def test_lock_binds_gpu_sources_versions_and_hashes() -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    root_match = re.search(
        r'^name = "daedalus"\s*$.*?^\[package\.metadata\]\s*$\n(?P<body>.*?)(?=^\[\[package\]\]|\Z)',
        lock,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert root_match is not None
    metadata = root_match.group("body")

    assert 'name = "torch"' in metadata
    assert 'specifier = "==2.14.0+cu126"' in metadata
    assert f'index = "{PYTORCH_CU126_INDEX}"' in metadata
    assert 'name = "newton"' in metadata and 'specifier = "==1.5.1"' in metadata
    assert 'name = "warp-lang"' in metadata and 'specifier = "==1.17.0"' in metadata
    assert 'name = "cuda-toolkit"' in metadata and 'specifier = "==12.6.3"' in metadata

    for name, version in (
        ("torch", "2.14.0+cu126"),
        ("newton", "1.5.1"),
        ("warp-lang", "1.17.0"),
        ("cupy-cuda12x", "14.2.0"),
        ("cuda-toolkit", "12.6.3"),
    ):
        package = re.search(
            rf'^name = "{re.escape(name)}"\s*$\nversion = "{re.escape(version)}"(?P<body>.*?)(?=^\[\[package\]\]|\Z)',
            lock,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert package is not None, f"missing locked {name}=={version}"
        assert 'hash = "sha256:' in package.group("body")


def test_readme_uses_locked_additive_environment_and_discloses_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv sync --locked --all-extras" in readme
    assert "uv sync --extra gpu" not in readme
    assert "torch==2.14.0+cu126" in readme
    assert re.search(r"fails?\s+closed", readme)
    assert "NVIDIA's\nproprietary software terms" in readme
    assert "not a\nredistribution grant" in readme
