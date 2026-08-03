from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "source_trees.py"
TESTS = (
    "tests/kernel/test_source_tree_store.py",
    "tests/kernel/test_source_tree_store_adversarial.py",
    "tests/kernel/test_source_tree_store_review.py",
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
        raise RuntimeError(f"{label}: expected one site, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("source-tree mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "allow-store-inside-source",
            "        if self.root == root or self.root.is_relative_to(root):\n",
            "        if False:\n",
        ),
        (
            "remove-manifest-mandatory-exclusions",
            "        if missing:\n            raise ValueError(\n                \"ignored_roots must retain mandatory exclusions: \" + \", \".join(missing)\n            )\n        object.__setattr__(self, \"ignored_roots\", ignored)\n",
            "        if False:\n            raise ValueError(\n                \"ignored_roots must retain mandatory exclusions: \" + \", \".join(missing)\n            )\n        object.__setattr__(self, \"ignored_roots\", ignored)\n",
        ),
        (
            "case-sensitive-metadata-filter",
            "                    if name.casefold() not in ignored_casefold\n",
            "                    if name not in set(ignored)\n",
        ),
        (
            "allow-symlink-source-file",
            "                if path.is_symlink():\n                    raise SourceTreeCaptureError(\n                        f\"source contains symlink file: {path}\"\n                    )\n",
            "                if False:\n                    raise SourceTreeCaptureError(\n                        f\"source contains symlink file: {path}\"\n                    )\n",
        ),
        (
            "accept-noncanonical-manifest-wire",
            "        if submitted != manifest.to_dict():\n            raise SourceTreeCorruptionError(\n                \"source tree manifest wire is noncanonical\"\n            )\n",
            "        if False:\n            raise SourceTreeCorruptionError(\n                \"source tree manifest wire is noncanonical\"\n            )\n",
        ),
        (
            "skip-cas-address-recomputation",
            "        if len(payload) != after.st_size or sha256(payload).hexdigest() != ref.sha256:\n",
            "        if len(payload) != after.st_size:\n",
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
        raise RuntimeError("mutation runner failed to restore source bytes")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
