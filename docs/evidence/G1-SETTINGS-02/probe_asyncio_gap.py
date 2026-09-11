"""Reproduce the spend-fence gap the delta review reported. NOT this packet's
to fix -- recorded so the next packet inherits the measurement.

The claim under test: ``install_process_guard`` patches exactly three
attributes, and ``asyncio.create_subprocess_exec`` on Windows does not go
through any of them, so the two paid vendor CLIs spawn with no reservation.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main() -> None:
    # The live import order: web_api imports asyncio machinery before it
    # installs the guard, so windows_utils is already bound.
    import asyncio.windows_utils as wu  # noqa: F401  (Windows only)

    from daedalus.budget import install_process_guard

    print("asyncio.windows_utils in sys.modules before install:",
          "asyncio.windows_utils" in sys.modules)

    before_run = subprocess.run
    before_popen = subprocess.Popen
    install_process_guard()
    print("subprocess.run patched   :", subprocess.run is not before_run)
    print("subprocess.Popen patched :", subprocess.Popen is not before_popen)
    print("wu.Popen base is the patched Popen:",
          wu.Popen.__bases__[0] is subprocess.Popen)
    print("wu.Popen bases           :", [b.__name__ for b in wu.Popen.__bases__])

    async def spawn() -> int:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "pass",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await proc.wait()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    rc = asyncio.run(spawn())
    print("rc:", rc, "  <- spawned through create_subprocess_exec")

    # Did anything reserve?
    from daedalus.budget import Ledger
    print("ledger calls recorded    :", Ledger().state_readonly().calls)

    # Is the adapter site declared billable anywhere?
    adapters = ROOT / "daedalus" / "adapters"
    hits = []
    for path in adapters.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "budget" in text or "reserve(" in text:
            hits.append(path.name)
    print("budget/reserve mentions under daedalus/adapters/:", hits or "NONE")


if __name__ == "__main__":
    main()
