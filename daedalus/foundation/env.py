"""Server-side environment loading for Daedalus.

The web UI and VS Code wrapper must never receive secret values. This module
loads `.env` into the process environment and exposes only redacted readiness
metadata for status screens.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"

SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)

PUBLIC_KEYS = (
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "OLLAMA_EMBED_MODEL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw or raw.startswith("#") or "=" not in raw:
        return None
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return key, value


def load_env(path: str | Path | None = None, *, override: bool = False) -> dict[str, Any]:
    """Load `.env` values into `os.environ`.

    Returns redacted metadata only. Existing environment values win unless
    `override=True` is passed.
    """
    env_path = Path(path) if path else ENV_PATH
    loaded: list[str] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if not parsed:
                continue
            key, value = parsed
            if override or key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return env_status(env_path, loaded)


def env_status(path: str | Path | None = None, loaded_keys: list[str] | None = None) -> dict[str, Any]:
    env_path = Path(path) if path else ENV_PATH
    providers = {
        "ollama": {
            "configured": True,
            "host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            "embed_model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        },
        "deepseek": {
            "configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        },
        "anthropic_api": {"configured": bool(os.environ.get("ANTHROPIC_API_KEY"))},
        "openai_api": {"configured": bool(os.environ.get("OPENAI_API_KEY"))},
    }
    return {
        "env_file": str(env_path),
        "env_file_exists": env_path.exists(),
        "loaded_keys": sorted(set(loaded_keys or [])),
        "public": {key: os.environ.get(key, "") for key in PUBLIC_KEYS if os.environ.get(key, "")},
        "secrets": {key: {"configured": bool(os.environ.get(key))} for key in SECRET_KEYS},
        "providers": providers,
    }
