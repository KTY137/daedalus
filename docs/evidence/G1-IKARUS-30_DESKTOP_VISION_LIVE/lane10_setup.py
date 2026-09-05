"""G1-IKARUS-30 step 1: build the scratch authority root, control root and policy.

Run with the worktree venv:
    DAEDALUS_KILLSWITCH=<control>/killswitch .venv/Scripts/python.exe lane10_setup.py

Writes nothing into the repository. The fixture text file carries the sentinel
words the live OCR measurement has to find; no image is ever written.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

SCRATCH = Path(os.environ.get("DAEDALUS_LANE10_SCRATCH")
               or Path(os.environ["LOCALAPPDATA"]) / "Temp" / "daedalus-lane10")
AUTHORITY = SCRATCH / "authority"
FIXTURE = SCRATCH / "fixture" / "lane10-sentinel.txt"
# Round 1 used the owner-obvious spelling. Windows 11 redirects it at process
# creation to the packaged app, so round 2 names the image the adapter can
# actually verify. Pass the executable as argv[1] to switch rounds.
NOTEPAD = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Windows\System32\notepad.exe")

HOME = str(Path.home())
SENTINELS = ["DAEDALUS", "ZINNOBER", "LANE10", "SENTINEL", "739104"]


def sanitized(value: dict) -> str:
    """Every retained spelling of the home directory becomes <USERPROFILE>.

    All three forms matter: the plain path, the forward-slash form, and the
    JSON-escaped doubled-backslash form this very dump produces.
    """
    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    for spelling in (HOME.replace("\\", "\\\\"), HOME.replace("\\", "/"), HOME):
        text = text.replace(spelling, "<USERPROFILE>")
    return text
FIXTURE_TEXT = (
    "DAEDALUS ZINNOBER\n"
    "LANE10 SENTINEL 739104\n"
)


def main() -> int:
    from daedalus.spine.killswitch import control_root, KillSwitch
    from daedalus.runtimes.computer import setup_computer, computer_status
    from daedalus.interfaces.computer_configuration import configure_computer

    AUTHORITY.mkdir(parents=True, exist_ok=True)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(FIXTURE_TEXT, encoding="utf-8")

    control = control_root(AUTHORITY)
    control.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "authority_root": str(AUTHORITY),
        "control_root": str(control),
        "killswitch_env": os.environ.get("DAEDALUS_KILLSWITCH"),
        "fixture_path": str(FIXTURE),
        "fixture_sentinels": SENTINELS,
        "notepad": str(NOTEPAD),
    }

    switch = KillSwitch(repo_root=AUTHORITY)
    report["switch_path"] = str(switch.path)
    report["switch_state_before_setup"] = switch.read_state().reason

    created = setup_computer(AUTHORITY, owner_confirmed=True)
    report["setup_created"] = created["created"]

    status = computer_status(AUTHORITY)
    base = status["configuration"]
    report["policy_sha256_before"] = status["policy_sha256"]
    report["workspace"] = base["workspace"]

    payload = dict(base)
    payload["tools"] = ["app.launch", "desktop.observe", "vision.inspect",
                        "vision.ocr", "desktop.type", "desktop.key"]
    payload["applications"] = {"notepad": [str(NOTEPAD), str(FIXTURE)]}
    payload["timeout_s"] = 900
    payload["max_steps"] = 32

    result = configure_computer(AUTHORITY, payload, owner_confirmed=True,
                                expected_policy_sha256=status["policy_sha256"])
    report["configure_changed"] = result["changed"]
    report["policy_sha256_after"] = result["policy_sha256"]
    report["policy"] = result["policy"]

    after = computer_status(AUTHORITY)
    report["capabilities_enabled"] = after["enabled"]
    report["capability_tool_names"] = [t["name"] for t in after["tools"]]
    report["capability_unavailable"] = after["unavailable"]
    report["desktop_validation_note"] = after["desktop_validation"]

    print(sanitized(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
