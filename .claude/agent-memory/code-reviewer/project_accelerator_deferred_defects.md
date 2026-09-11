---
name: project-accelerator-deferred-defects
description: Two known defects in daedalus/foundation/accelerators.py the owner deliberately left out of PR #370 and is packeting separately — do not "fix" them in a passing lane
metadata:
  type: project
---

Two defects an independent review found in `daedalus/foundation/accelerators.py` and its
HTTP route were **deliberately excluded** from PR #370 (`fix/deps-detection-20260910`,
merged repairs 2026-09-11). The owner is turning them into their own Work Packets:

* the unregistered process spawn reachable on the **ungated `do_GET` route** —
  `/api/accelerators/status?deep=1` spawns a subprocess from a read endpoint that carries
  no `effect_boundary` row (`daedalus/interfaces/http/read.py`);
* **`DAEDALUS_RTX_SSH`** reaching `ssh` argv completely unvalidated, so a value beginning
  `-oProxyCommand=` is arbitrary execution. The owner called this "more serious than
  anything in that diff".

**Why:** scope discipline — a repair lane that also patches these produces a diff nobody
can review against one claim, and the owner wants the security fix packeted with its own
acceptance matrix rather than smuggled in.

**How to apply:** if a future task touches this module, flag either defect as *known and
already owned* rather than fixing it, and check whether its packet has landed before
assuming it is still open. Note the ComputeSection header still says
"nur Import geprüft, nichts ausgeführt" over rows that, in a frozen bundle, checked the
bundle rather than the machine — left alone on purpose, no test harness covers that
component. See [[feedback-review-output-contract]] and [[project-daedalus-lane-hazards]].
