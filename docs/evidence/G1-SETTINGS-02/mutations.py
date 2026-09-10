"""Disable one guard at a time and record which tests notice.

Every mutation is applied to a COPY of the worktree so the real tree is never
edited, and the copy is discarded afterwards. Run from the worktree root.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = Path("daedalus/kernel/policy/ledger.py")
INVENTORY = Path("daedalus/interfaces/desktop/settings_inventory.py")
SENSITIVITY = Path("daedalus/sensitivity.py")

MUTATIONS = [
    (
        "M1 the document is never read",
        LEDGER,
        "    path = admitted_settings_path(runtime_root)\n"
        "    try:\n"
        "        text = path.read_text(encoding=\"utf-8\")\n",
        "    path = admitted_settings_path(runtime_root)\n"
        "    return None  # MUTATION\n"
        "    try:\n"
        "        text = path.read_text(encoding=\"utf-8\")\n",
    ),
    (
        "M2 the environment wins outright again",
        LEDGER,
        "    if environment <= document:\n"
        "        return environment, SOURCE_ENVIRONMENT, None\n"
        "    return document, SOURCE_ADMITTED_DOCUMENT, environment\n",
        "    return environment, SOURCE_ENVIRONMENT, None  # MUTATION\n",
    ),
    (
        "M3 caps compose by AND instead of OR",
        LEDGER,
        "            axis: getattr(doc_axes, axis) or getattr(env_axes, axis)\n",
        "            axis: getattr(doc_axes, axis) and getattr(env_axes, axis)\n",
    ),
    (
        "M4 a corrupt document falls back to the environment",
        LEDGER,
        "    except (json.JSONDecodeError, ValueError) as exc:\n"
        "        raise AdmittedSettingsUnreadable(\n"
        "            f\"admitted desktop settings '{path}' are corrupt ({exc}); \"\n"
        "            \"refusing to fall back to an unadmitted environment\"\n"
        "        ) from exc\n",
        "    except (json.JSONDecodeError, ValueError):\n"
        "        return None  # MUTATION\n",
    ),
    (
        "M5 an issued contract is re-resolved from the document",
        LEDGER,
        "        if self._ceiling_override is not None:\n"
        "            ceiling = _num(self._ceiling_override, ENV_CEILING, allow_zero=False)\n"
        "            ceiling_source: str = SOURCE_ISSUED_CONTRACT\n"
        "            refused_ceiling: float | None = None\n"
        "        else:\n",
        "        if False:  # MUTATION\n"
        "            ceiling = _num(self._ceiling_override, ENV_CEILING, allow_zero=False)\n"
        "            ceiling_source: str = SOURCE_ISSUED_CONTRACT\n"
        "            refused_ceiling: float | None = None\n"
        "        else:\n",
    ),
    (
        "M6 an absent variable asserts bounded over the document",
        LEDGER,
        "    legacy = source.get(ENV_PERIOD_CEILING_ENABLED)\n"
        "    if legacy is None or not legacy.strip():\n"
        "        return None\n",
        "    legacy = source.get(ENV_PERIOD_CEILING_ENABLED)\n"
        "    if legacy is None or not legacy.strip():\n"
        "        return ExecutionLimitPolicy()  # MUTATION\n",
    ),
    (
        "M7 the retired boolean is invisible to the projection again",
        INVENTORY,
        "        env_policy = environment_limit_policy(environ)\n",
        "        env_policy = (\n"
        "            ExecutionLimitPolicy.from_env_value(environ[ENV_LIMIT_POLICY])\n"
        "            if _present(environ, ENV_LIMIT_POLICY) else None\n"
        "        )  # MUTATION\n",
    ),
    (
        "M8 env-only rows report raw text again",
        INVENTORY,
        "    elif coerce is not None:\n"
        "        effective, source = coerce(raw), SOURCE_ENVIRONMENT\n",
        "    elif coerce is not None and False:  # MUTATION\n"
        "        effective, source = coerce(raw), SOURCE_ENVIRONMENT\n",
    ),
    (
        "M9 the trust parse is re-derived instead of reused",
        SENSITIVITY,
        "            if (addr.is_unspecified or addr.is_multicast or addr.is_reserved\r\n"
        "                    or addr.is_link_local):\r\n"
        "                continue\r\n",
        "            pass  # MUTATION\r\n",
    ),
]

SUITES = ["tests/test_admitted_execution_limits.py", "tests/test_settings_inventory.py"]


def run(copy: Path) -> str:
    proc = subprocess.run(
        [
            "uv", "run", "--directory", str(copy), "--frozen", "--extra", "test",
            "python", "-m", "pytest", *SUITES, "-q", "-p", "no:cacheprovider",
            "--no-header", "-x", "--tb=no",
        ],
        capture_output=True,
        text=True,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return tail[-1] if tail else f"NO OUTPUT (rc={proc.returncode})"


def main() -> None:
    print("| mutation | file | result |")
    print("| --- | --- | --- |")
    for name, rel, old, new in MUTATIONS:
        tmp = Path(tempfile.mkdtemp(prefix="mut-"))
        copy = tmp / "tree"
        shutil.copytree(
            ROOT,
            copy,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "__pycache__", "node_modules", "runs", "apps"
            ),
        )
        target = copy / rel
        with io.open(target, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        # core.autocrlf=true: some worktree files are CRLF, some are LF.
        if "\r\n" in text and "\r\n" not in old:
            old = old.replace("\n", "\r\n")
            new = new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"| {name} | {rel.name} | ANCHOR NOT UNIQUE ({text.count(old)}) |")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        with io.open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace(old, new, 1))
        print(f"| {name} | {rel.name} | {run(copy)} |")
        sys.stdout.flush()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
