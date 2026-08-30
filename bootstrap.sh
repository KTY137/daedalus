#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

# daedalus bootstrap (Linux/macOS) -- drop the repo on a machine and run this.
#   ./bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== daedalus bootstrap =="

# 1. Python 3.10+
command -v python3 >/dev/null 2>&1 || { echo "Python 3.10+ required (python3 not found)"; exit 1; }
python3 --version

# 2. venv
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. install the harness editable (+ optional YAML checks)
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[yaml]"

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
