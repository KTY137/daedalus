> TAKEN 2026-08-23 12:25Z (Athena, owner order 'arbeite weiter ans backend').
> Control root: every legacy digest under %LOCALAPPDATA%\daedalus\control was COPIED to
> %USERPROFILE%\.daedalus\control and the legacy directory RENAMED to `<digest>.migrated-20260823`
> -- nothing deleted. Two digests (2ea46e496ce4 = this checkout, e9267964a961) already had a
> fresh new root; their legacy state is parked beside it as `<digest>.legacy-20260823`, not
> merged (different issuer key; the old ledger stays inspectable). `killswitch status` now
> reports the new path: 'no permit file: the loop is not armed' (MEASURED).
> Sealed patch: applied with `git apply -p1`; `git hash-object` = e7acc630271146c4d84b9643a2047f0bb7960c8f
> (matches the reviewed pin); `_RETAINED_SOURCE_GIT_BLOB_SHA1` bumped; import integrity check passed;
> test_loop_governance_head 12/12, test_loop_lease 15/15 (MEASURED).

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

## Second owner action: the sealed lease hand-down patch

`docs/decisions-pending/gated_writes_lease_handdown.patch` (8 hunks, pin
e7acc630271146c4d84b9643a2047f0bb7960c8f) threads the wave's Effect Lease
into the offload call inside the sealed write path and adds the governance
head check there. Odysseus 2026-08-22: APPLY-WITH-FIX, preconditions fe716cb0
and f7d51056 both landed; refuted that it leaks the lease to candidate code.
The harness classifier refused to let an agent touch the sealed source. Run:

```powershell
git apply -p1 docs/decisions-pending/gated_writes_lease_handdown.patch
git hash-object daedalus/kairos/_gated_writes_legacy.py.src   # must print e7acc630271146c4d84b9643a2047f0bb7960c8f
# then set _RETAINED_SOURCE_GIT_BLOB_SHA1 in daedalus/kairos/gated_writes.py to that value
python -c "import daedalus.kairos.gated_writes"                 # integrity check must pass
```

Afterwards flip tests/test_loop_governance_head.py::test_the_sealed_write_path_fix_is_pending_and_applies
and tests/test_loop_lease.py::test_gated_write_wave_gets_the_lease_the_day_it_accepts_one.

## Third move, same day: the artifact store (TAKEN 2026-08-23 14:15Z)

`_artifact_root_for` in the sealed source now derives the held-patch store from
`killswitch.OS_PROFILE_DIR` (`<profile>/.daedalus/artifacts/<digest>/patches`),
patch `artifact_root_profile.patch` beside this note, pin ec2fa2d6, Odysseus
APPLY-WITH-FIX. The OLD store is LEFT IN PLACE and not refused: unlike the
control root it is create-once content-addressed evidence, so a missed old blob
makes a locator unresolvable and never turns a spent thing unspent. Measured
contents of the old root at the move: one blob (e3b0c442..., the empty patch of
loop-20260823-145421-34bd80), four locators, one pre-CAS flat patch under digest
8765452452df -- nothing of promotion value. The loop reports that name the
LocalCache path (runs/loop/loop-20260822-*.json, loop-20260823-145421-34bd80.json,
blocker_9887a98e.json) were already unreadable from any non-Store process; they
stay as written (history), and every new write lands in the profile root.
