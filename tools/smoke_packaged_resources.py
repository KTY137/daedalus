"""Smoke an installed Daedalus wheel without importing the source checkout.

This helper is intentionally network-free.  Install a wheel into an isolated
target directory first, then pass that directory here with ``--site``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _wheel_web_file_closure(
    archive: zipfile.ZipFile,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return reachable and orphaned files below the packaged Vite root.

    Vite's index names the entry chunks and those chunks name lazy chunks.  A
    reused setuptools ``build/lib`` directory can otherwise smuggle old hashed
    bundles into a new wheel: they are valid files, but no current page can
    reach them.  Walking references from ``index.html`` makes that stale-cache
    failure a release refusal instead of harmless-looking package bloat.
    """

    prefix = "daedalus/resources/web_dist/"
    members = {
        name.removeprefix(prefix): name
        for name in archive.namelist()
        if name.startswith(prefix) and not name.endswith("/")
    }
    if "index.html" not in members:
        raise RuntimeError("wheel has no packaged web_dist/index.html")
    basenames = [Path(relative).name for relative in members]
    if len(basenames) != len(set(basenames)):
        raise RuntimeError("packaged web UI contains ambiguous duplicate basenames")

    reachable = {"index.html"}
    pending = ["index.html"]
    while pending:
        current = pending.pop()
        payload = archive.read(members[current])
        for relative in sorted(set(members) - reachable):
            # Hashed Vite chunks use root-relative or sibling-relative names;
            # matching the unique basename also covers CSS url(...) assets.
            if Path(relative).name.encode("utf-8") in payload:
                reachable.add(relative)
                pending.append(relative)
    orphaned = tuple(sorted(set(members) - reachable))
    return tuple(sorted(reachable)), orphaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()

    site = args.site.resolve()
    sys.path.insert(0, str(site))

    import daedalus
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.config import init_repo
    from daedalus.interfaces.http.web_api import DaedalusHandler, WEB_DIST
    from daedalus.orchestration.gui_catalogue import load_catalogue
    from daedalus.resources import schema_text
    from daedalus.router import load_agents
    from daedalus.spine.effect_boundary import (
        REGISTRY_BY_ID,
        GuardDecision,
        begin_effect,
    )

    begin_effect(
        "tools.packaged_resources_smoke",
        REGISTRY_BY_ID["tools.packaged_resources_smoke"].effects,
        (
            GuardDecision(
                "web.authenticated_bind",
                True,
                "release smoke uses one hard-coded ephemeral loopback listener",
            ),
            process_guard_boundary_decision(),
        ),
    )

    package_file = Path(daedalus.__file__).resolve()
    if not _under(package_file, site):
        raise RuntimeError(f"source-checkout import leaked into wheel smoke: {package_file}")

    init_result = init_repo(str(args.project))
    agents = load_agents()
    catalogue = load_catalogue()
    schema = json.loads(schema_text("attempt-start-v1.schema.json"))

    with zipfile.ZipFile(args.wheel) as archive:
        names = archive.namelist()
        reachable_web_files, orphaned_web_files = _wheel_web_file_closure(archive)
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
    if orphaned_web_files:
        raise RuntimeError(
            "unreachable stale web assets entered wheel: "
            + ", ".join(orphaned_web_files)
        )
    if not agents or not catalogue.entries or not resources:
        raise RuntimeError("one or more packaged resource families are empty")
    if not str(schema.get("$schema", "")).startswith("https://json-schema.org/"):
        raise RuntimeError("packaged attempt schema is not the expected JSON Schema")

    if not _under(WEB_DIST, package_file.parent):
        raise RuntimeError(f"web UI did not resolve from the installed wheel: {WEB_DIST}")
    index_bytes = (WEB_DIST / "index.html").read_bytes()
    index = index_bytes.decode("utf-8")
    asset_paths = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', index)))
    if "Daedalus Agent OS" not in index or not asset_paths:
        raise RuntimeError("packaged web UI is a placeholder or has no hashed assets")
    if not all(re.search(r"-[A-Za-z0-9_-]{8,}\.(?:css|js)$", path) for path in asset_paths):
        raise RuntimeError(f"web UI references non-hashed assets: {asset_paths}")
    if not all((WEB_DIST / path.lstrip("/")).is_file() for path in asset_paths):
        raise RuntimeError(f"web UI references missing packaged assets: {asset_paths}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), DaedalusHandler)
    server.daedalus_auth_token = ""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(origin + "/", timeout=5) as response:
            served_index = response.read()
        served_assets = []
        for path in asset_paths:
            with urlopen(origin + path, timeout=5) as response:
                served_assets.append(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    if served_index != index_bytes or not all(served_assets):
        raise RuntimeError("installed HTTP handler did not serve the packaged web UI")
    if not any(b"Genesis" in payload for payload in served_assets):
        raise RuntimeError("packaged JavaScript does not contain the Genesis UI")

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
                "web_assets": len(asset_paths),
                "web_dist_files": len(reachable_web_files),
                "web_dist": str(WEB_DIST),
                "wheel": args.wheel.name,
                "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
