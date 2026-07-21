"""Regressions for the fence path-anchoring repair group.

Two confirmed defects are pinned here, each with the BLOCKED and the ALLOWED
half:

* [D1] The high-blast-radius PATH fence under-escalated a *top-level* fenced
  tree. ``sensitivity.change_risk`` / ``path_write_blocked`` substring-matched a
  bare repo-relative path, so a slash-anchored fragment like ``/controller``
  could not match ``controller/core.py`` -- the literally-fenced file scored
  ``low`` and reached the local 7B WRITE lane. It now root-anchors (mirroring
  ``structcore.graph._fence_norm``), so a top-level fenced file escalates. This
  also closes the dominance stand-down hole: an itself-fenced edit is now caught
  by path-local risk BEFORE the reachability pre-check runs, exactly as the
  stand-down comment always claimed it would be.

* [D3] The reachability verdict was dropped at the ``offload`` seam. The
  dominance stand-down notice / empty-index error / unresolved list lived only
  on ``decision.reachability`` and never reached the operator-visible result
  dict, so a run where the graph fence stood down looked like a clean low-risk
  offload. The seam now surfaces it.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daedalus.offload import offload
from daedalus.provider_router import (FENCE_DOMINANCE_MIN_SAMPLE,
                                      select_provider)
from daedalus.sensitivity import change_risk, path_write_blocked

CODER = {"name": "coder", "external_ok": True}
AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}
# No risk/review wording, so only the PATH decides the verdict.
OBJECTIVE = "adjust the defaults"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TopLevelFenceAnchoringTests(unittest.TestCase):
    """D1: a top-level fenced tree must escalate/block, a sibling must not."""

    def test_change_risk_anchors_top_level_fenced_tree(self):
        # BLOCKED: '/controller' now matches the repo-relative top-level path.
        self.assertEqual(change_risk(OBJECTIVE, ["controller/core.py"]), "high")
        self.assertEqual(change_risk(OBJECTIVE, ["safety/limits.py"]), "high")
        # ALLOWED: a genuinely non-fenced top-level file stays low, and a name
        # that merely CONTAINS a fragment without the slash boundary is not
        # over-matched into the fence.
        self.assertEqual(change_risk(OBJECTIVE, ["utils/clamp.py"]), "low")
        self.assertEqual(change_risk(OBJECTIVE, ["mycontroller/core.py"]), "low")

    def test_change_risk_still_matches_nested_fenced_tree(self):
        # The pre-existing (already-working) case must be unchanged.
        self.assertEqual(change_risk(OBJECTIVE, ["src/controller/core.py"]), "high")

    def test_path_write_blocked_anchors_top_level_fenced_tree(self):
        # BLOCKED half.
        self.assertTrue(path_write_blocked("controller/core.py"))
        self.assertTrue(path_write_blocked(r"controller\core.py"))
        # ALLOWED half: sibling that is not fenced, and the substring-without-
        # boundary false-positive stays writable.
        self.assertFalse(path_write_blocked("utils/clamp.py"))
        self.assertFalse(path_write_blocked("mycontroller/core.py"))

    def test_select_provider_escalates_top_level_fenced_edit_under_dominance(self):
        # The exact defect-1 scenario: a fenced-dominant index (so the
        # reachability stand-down would otherwise fire) editing the literally-
        # fenced top-level controller file. Path-local risk must catch it BEFORE
        # the pre-check, so it never reaches the local write lane.
        fenced = "controller/core.py"
        leaves = [f"utils/leaf{i:03d}.py" for i in range(FENCE_DOMINANCE_MIN_SAMPLE + 4)]
        idx = {
            "modules": {m: {} for m in [fenced] + leaves},
            "import_edges": {fenced: sorted(leaves)},
            "import_edges_reverse": {m: [fenced] for m in leaves},
        }
        d = select_provider(CODER, OBJECTIVE, [fenced], AVAIL, idx=idx)
        self.assertEqual(d.risk, "high")
        self.assertEqual(d.provider, "claude_cli")
        # ALLOWED half: a non-fenced leaf in the same dominant repo still takes
        # the cheap lane (the fence did not simply escalate everything).
        d2 = select_provider(CODER, OBJECTIVE, ["utils/leaf000.py"], AVAIL, idx=idx)
        self.assertEqual(d2.provider, "ollama")
        self.assertFalse(d2.reachability["escalate"])


class OffloadSurfacesReachabilityTests(unittest.TestCase):
    """D3: the dominance stand-down must be visible in the offload result."""

    def _dominant_repo(self, tmp: str) -> str:
        root = Path(tmp)
        cfg = root / ".agentenv"
        (cfg / "agents").mkdir(parents=True, exist_ok=True)
        (cfg / "agentenv.json").write_text(
            '{"policy": {"default_deny": true, "allow": ["utils/", "controller/"]}}',
            encoding="utf-8")
        (cfg / "agents" / "coder.json").write_text(
            '{"name": "coder", "call_name": "Cody", "model_tier": "sonnet",'
            ' "external_ok": true, "owns": ["utils"], "triggers": ["leaf", "adjust"],'
            ' "must_read": [], "output_schema": "agent_report_v1",'
            ' "category": "implementation"}', encoding="utf-8")
        # A fenced controller importing >= MIN_SAMPLE leaves -> fenced dominance
        # trips and the reachability check stands down to path-local risk.
        n = FENCE_DOMINANCE_MIN_SAMPLE + 4
        leaves = [f"utils/leaf{i:03d}" for i in range(n)]
        for name in leaves:
            _write(root, f"{name}.py", "def v():\n    return 1\n")
        imports = "".join(f"from {m.replace('/', '.')} import v as v{i}\n"
                          for i, m in enumerate(leaves))
        _write(root, "controller/hub.py", imports + "\n\ndef run():\n    return 0\n")
        return str(root)

    def test_dominance_standdown_is_surfaced_in_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._dominant_repo(tmp)
            res = offload("adjust the leaf helper", repo, ["utils/leaf000.py"],
                          live=False, availability=AVAIL)
            # BLOCKED-from-silence: the stand-down notice reaches the operator.
            self.assertIn("reachability", res)
            self.assertTrue(res["reachability"]["dominance"]["fallback"])
            self.assertIn("fence dominates", res["reachability"]["reason"])
            # The edit still took the cheap lane (path-local low risk) -- the
            # point of D3 is that the stand-down is no longer invisible, not that
            # the routing changed.
            self.assertEqual(res["provider"], "ollama")
