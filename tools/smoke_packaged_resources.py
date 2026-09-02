"""Smoke an installed Daedalus wheel without importing the source checkout.

This helper is intentionally network-free.  Install a wheel into an isolated
target directory first, then pass that directory here with ``--site``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()

    site = args.site.resolve()
    sys.path.insert(0, str(site))

    import daedalus
    from daedalus.config import init_repo
    from daedalus.orchestration.gui_catalogue import load_catalogue
    from daedalus.resources import schema_text
    from daedalus.router import load_agents

    package_file = Path(daedalus.__file__).resolve()
    if not _under(package_file, site):
        raise RuntimeError(f"source-checkout import leaked into wheel smoke: {package_file}")

    init_result = init_repo(str(args.project))
    agents = load_agents()
    catalogue = load_catalogue()
    schema = json.loads(schema_text("attempt-start-v1.schema.json"))

    with zipfile.ZipFile(args.wheel) as archive:
        names = archive.namelist()
    resources = sorted(
        name
        for name in names
        if name.startswith("daedalus/resources/") and not name.endswith("/")
    )
    forbidden = [
        name
        for name in names
        if name.startswith(("projects/", "runs/"))
        or Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        or "credentials" in name.lower()
    ]
    if forbidden:
        raise RuntimeError(f"local/runtime state entered wheel: {forbidden}")
    if not agents or not catalogue.entries or not resources:
        raise RuntimeError("one or more packaged resource families are empty")
    if not str(schema.get("$schema", "")).startswith("https://json-schema.org/"):
        raise RuntimeError("packaged attempt schema is not the expected JSON Schema")

    print(
        json.dumps(
            {
                "agentenv_roles": len(
                    list((args.project / ".agentenv" / "agents").glob("*.json"))
                ),
                "catalogue_entries": len(catalogue.entries),
                "catalogue_sources": len(catalogue.sources),
                "init_result": init_result,
                "package_file": str(package_file),
                "resource_files": len(resources),
                "roles": len(agents),
                "wheel": args.wheel.name,
                "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
