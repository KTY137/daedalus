# Owner action: move the control root out of the Store-virtualized LOCALAPPDATA

Since 5d78d4b5 the kill switch, the lease issuer key and the promotion claim
ledger live under `%USERPROFILE%\.daedalus\control\<digest>`, and the loop
REFUSES TO ARM while the old root still holds state (a fresh ledger would be
a replay window). The old root for this checkout is
`%LOCALAPPDATA%\daedalus\control\2ea46e496ce4`, which the Microsoft-Store
python resolves to
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\LocalCache\Local\daedalus\control\2ea46e496ce4`
(Odysseus F1, MEASURED 2026-08-22). The harness classifier refused to let the
agent move it. Run ONCE, with the repo's python (so the virtualized path is
visible):

```powershell
python - <<'PY'
import os, shutil, pathlib
legacy = pathlib.Path(os.environ["LOCALAPPDATA"]) / "daedalus" / "control"
new = pathlib.Path(os.environ["USERPROFILE"]) / ".daedalus" / "control"
for d in legacy.iterdir():
    if d.is_dir() and not (new / d.name).exists():
        shutil.copytree(d, new / d.name); shutil.rmtree(d); print("moved", d.name)
PY
```

Then `python -m daedalus.spine.killswitch status` should report the new path
and `read_state` must see a STOP written by another process (the verifier
checks that itself).
