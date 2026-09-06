"""Copy the G1-IKARUS-34 experiment results into the evidence directory (paths scrubbed)
and fill the packet's result placeholders from the results JSON. Idempotent."""
import json, sys
from pathlib import Path
S = Path(sys.argv[1]); W = Path(sys.argv[2]); home = str(Path.home())
E = W / "docs/evidence/G1-IKARUS-34_PLAN_PROGRESS_SHAPE"
def variants(p):
    p = p.replace("/", "\\"); return [p, p.replace("\\", "\\\\"), p.replace("\\", "/")]
def scrub(t):
    for v in variants(str(S)): t = t.replace(v, "<SCRATCH>")
    for v in variants(home): t = t.replace(v, "<USERPROFILE>")
    return t
res = json.loads((S / "exp01_results.json").read_text(encoding="utf-8"))
(E / "exp01_results.json").write_text(scrub(json.dumps(res, indent=1, ensure_ascii=False)), encoding="utf-8")
(E / "exp01.log.txt").write_text(scrub((S / "exp01.log.txt").read_bytes().decode("utf-8", errors="replace")), encoding="utf-8")
for f in E.iterdir():
    assert "nukei" not in f.read_text(encoding="utf-8"), f.name
rows = res["results"]
def summ(v):
    r = [x for x in rows if x["variant"] == v]
    return r, sum(x["finished"] for x in r)
r1, f1 = summ("v1"); r2, f2 = summ("v2")
decision = ("V2 adopted (strict lead)" if f2 > f1 else "V1 retained; V2 recorded as negative evidence" if f2 < f1 else "tie: V1 retained; V2 recorded as negative evidence")
table = "| run | variant | state | finished | calls | tool steps | replans | elapsed s |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(
    f"| {x['run']} | {x['variant']} | {x['state']} | {'yes' if x['finished'] else 'no'} | {x['planner_calls']} | {x['tool_steps']} | {x['replans']} | {x['elapsed_s']} |" for x in rows)
measured = (f"Runs executed on 2026-09-06 in one process (`source_sha256` {res['source_sha256'][:12]}…, policy {res['policy_sha256'][:12]}…), "
            f"order {', '.join(res['order'])}. Per-run proposal lists are in `exp01_results.json`.\n\n{table}\n\n"
            f"V1 finished {f1}/{len(r1)}; V2 finished {f2}/{len(r2)}. Decision per the pre-registered rule: {decision}.")
p = W / "docs/work-packets/G1-IKARUS-34_PLAN_PROGRESS_SHAPE_EXPERIMENT.md"; t = p.read_text(encoding="utf-8")
t = t.replace("RESULT_V1", f"{f1}/{len(r1)}").replace("RESULT_V2", f"{f2}/{len(r2)}").replace("RESULT_DECISION", decision).replace("MEASURED_PLACEHOLDER", measured)
p.write_text(t, encoding="utf-8")
print("retained;", "v1", f1, "/", len(r1), "v2", f2, "/", len(r2), "->", decision)
