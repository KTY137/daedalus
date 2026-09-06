#!/usr/bin/env bash
# daedalus bootstrap (Linux/macOS) -- drop the repo on a machine and run this.
#   ./bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")"

GPU_RESEARCH=0
case "${1:-}" in
  "") ;;
  --gpu-research) GPU_RESEARCH=1 ;;
  *) echo "Usage: ./bootstrap.sh [--gpu-research]" >&2; exit 2 ;;
esac

version_at_least() {
  local actual="$1" minimum="$2" index actual_part minimum_part
  local IFS=.
  local -a actual_parts minimum_parts
  read -r -a actual_parts <<<"$actual"
  read -r -a minimum_parts <<<"$minimum"
  for index in 0 1 2; do
    actual_part="${actual_parts[$index]:-0}"
    minimum_part="${minimum_parts[$index]:-0}"
    [[ "$actual_part" =~ ^[0-9]+$ && "$minimum_part" =~ ^[0-9]+$ ]] || return 2
    if (( 10#$actual_part > 10#$minimum_part )); then return 0; fi
    if (( 10#$actual_part < 10#$minimum_part )); then return 1; fi
  done
  return 0
}

gpu_research_preflight() {
  local kernel machine process_bits kernel_release gpu_names driver_versions
  local driver_version capabilities minimum_driver="560.35.05"
  kernel="$(uname -s)"
  machine="$(uname -m)"
  process_bits="$(getconf LONG_BIT 2>/dev/null || true)"
  kernel_release="$(uname -r)"

  if [ "$kernel" != "Linux" ] || [ "$machine" != "x86_64" ] || [ "$process_bits" != "64" ]; then
    echo "--gpu-research supports only native x86-64 Linux (OS=$kernel, machine=$machine, process_bits=${process_bits:-unknown}). No packages were installed." >&2
    exit 2
  fi
  if [[ "${kernel_release,,}" == *microsoft* ]]; then
    echo "--gpu-research requires native Linux; WSL is outside this experiment's frozen platform matrix. No packages were installed." >&2
    exit 2
  fi
  command -v nvidia-smi >/dev/null 2>&1 || {
    echo "--gpu-research requires nvidia-smi on PATH and a working NVIDIA driver. No packages were installed." >&2
    exit 2
  }

  if ! gpu_names="$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits 2>/dev/null)" ||
     [ -z "${gpu_names//[$'\t\r\n ']/}" ]; then
    echo "nvidia-smi did not enumerate an NVIDIA GPU. No packages were installed." >&2
    exit 2
  fi
  if ! driver_versions="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits 2>/dev/null)" ||
     [ -z "${driver_versions//[$'\t\r\n ']/}" ]; then
    echo "nvidia-smi could not report the NVIDIA driver version. No packages were installed." >&2
    exit 2
  fi

  echo "NVIDIA GPU(s):"
  printf '%s\n' "$gpu_names"
  echo "NVIDIA driver(s), required >= $minimum_driver for pinned CUDA 12.6.3:"
  printf '%s\n' "$driver_versions"
  while IFS= read -r driver_version; do
    driver_version="${driver_version//[[:space:]]/}"
    if ! version_at_least "$driver_version" "$minimum_driver"; then
      echo "NVIDIA driver $driver_version is below the conservative CUDA 12.6.3 Linux floor $minimum_driver (or was not parseable). No packages were installed." >&2
      exit 2
    fi
  done <<<"$driver_versions"

  if capabilities="$(nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader,nounits 2>/dev/null)" &&
     [ -n "${capabilities//[$'\t\r\n ']/}" ]; then
    echo "NVIDIA compute capability inventory:"
    printf '%s\n' "$capabilities"
  else
    echo "nvidia-smi could not report compute capability; continuing to the installed Torch/deep device probes." >&2
  fi
  echo "Pre-install compute capability is advisory; the exact Torch CUDA operation and final Daedalus deep probe decide readiness."
}

echo "== daedalus bootstrap =="

if [ "$GPU_RESEARCH" -eq 1 ]; then
  gpu_research_preflight
  command -v uv >/dev/null 2>&1 || {
    echo "--gpu-research requires uv so uv.lock and the exclusive CUDA index are enforced" >&2
    exit 2
  }
fi

# 1. Python 3.10+
command -v python3 >/dev/null 2>&1 || { echo "Python 3.10+ required (python3 not found)"; exit 1; }
python3 --version

# 2. venv
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. install the harness editable (+ optional YAML checks). The CUDA research
# stack is multi-gigabyte and remains an explicit owner opt-in. That path uses
# the checked-in uv lock; pip cannot publish an alternate-index mapping.
if [ "$GPU_RESEARCH" -eq 1 ]; then
  uv sync --locked --all-extras --python .venv/bin/python
  .venv/bin/python -c "import torch; assert torch.__version__ == '2.14.0+cu126' and torch.version.cuda == '12.6', (torch.__version__, torch.version.cuda); assert torch.cuda.is_available() and torch.cuda.device_count() > 0, 'Torch did not enumerate a CUDA device'; x = torch.arange(256, dtype=torch.float32, device='cuda:0'); y = (x * 2 + 1).cpu(); torch.cuda.synchronize(); assert torch.equal(y, torch.arange(256, dtype=torch.float32) * 2 + 1), 'bounded CUDA oracle mismatch'; print('Torch CUDA 12.6 bounded device oracle passed on', torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"
  uv pip check --python .venv/bin/python
  echo
  echo "== CUDA research evidence =="
  daedalus accelerators --deep --json
else
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -e ".[yaml]"
fi

# 4. Ollama (the local bench)
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
else
  echo "Ollama already installed."
fi

# 5. pull models (coder + embedder). Override coder with $OLLAMA_MODEL.
MODEL="${OLLAMA_MODEL:-qwen2.5-coder:7b}"
ollama pull "$MODEL" || echo "Pull later with: ollama pull $MODEL"
ollama pull nomic-embed-text || true

# 6. readiness check
echo
echo "== readiness =="
daedalus doctor
echo
echo "Done. To enable writes in a repo:  cd <repo> && daedalus init  (then edit .agentenv/agentenv.json)"
