from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "writer_inventory.py"
TESTS = (
    "tests/test_spine_writer_inventory.py",
    "tests/test_spine_writer_inventory_review.py",
    "tests/test_spine_writer_inventory_cli.py",
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one mutation site, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("Event-Store writer inventory mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "legacy-direct-is-not-blocking",
            """_BLOCKING_KINDS = frozenset(
    {"legacy_direct", "ambiguous_direct", "ambiguous_binding"}
)
""",
            """_BLOCKING_KINDS = frozenset(
    {"ambiguous_direct", "ambiguous_binding"}
)
""",
        ),
        (
            "default-direct-constructor-is-read-only",
            '    return "read_only" if read_only is True else "legacy_direct"\n',
            '    return "read_only"\n',
        ),
        (
            "shadowed-binding-is-admitted-factory",
            """        elif ambiguous and (
            raw_terminal in _TRACKED_TERMINALS or tracked_alias
        ):
            kind = "ambiguous_binding"
            callee = raw
""",
            """        elif ambiguous and (
            raw_terminal in _TRACKED_TERMINALS or tracked_alias
        ):
            kind = "gate0_factory"
            callee = raw
""",
        ),
        (
            "skip-source-revision-validation",
            """    if not _SOURCE_REVISION.fullmatch(str(source_revision)):
        raise WriterInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
""",
            """    if False:
        raise WriterInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
""",
        ),
        (
            "omit-production-file-bytes-from-binding",
            '                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),\n',
            '                    "sha256": "0" * 64,\n',
        ),
        (
            "do-not-normalize-syntax-errors",
            "    except (OSError, UnicodeDecodeError, SyntaxError) as exc:\n",
            "    except (OSError, UnicodeDecodeError) as exc:\n",
        ),
    )

    killed: list[str] = []
    try:
        for label, old, new in mutations:
            TARGET.write_text(
                _replace_once(source, old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore inventory source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
