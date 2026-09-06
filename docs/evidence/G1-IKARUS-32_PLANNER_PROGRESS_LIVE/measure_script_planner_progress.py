"""G1-IKARUS-32: live computer-loop measurement with the plan-progress prompt.

PLANNER=ollama  -> qwen2.5-coder:7b over loopback Ollama (bounded default policy)
PLANNER=codex   -> codex_cli as planner via allow_remote_context (owner-declared flat rate)
MISSION=<id>    -> mission id; the report lands next to this script as <MISSION>.json
"""
import io, json, os, sys, time
from pathlib import Path

S = Path(os.environ["DAEDALUS_KILLSWITCH"]).parent.parent
subject = S / "subject"
port = io.open(S / "www" / "port.txt").read().strip()
planner = os.environ.get("PLANNER", "ollama")
mission_id = os.environ["MISSION"]

from daedalus.spine.killswitch import KillSwitch
print("killswitch:", KillSwitch(repo_root=subject).arm(force=True, note=f"G1-IKARUS-32 {mission_id}"))
from daedalus.runtimes.computer import computer_status, setup_computer
from daedalus.interfaces.computer_configuration import configure_computer
from daedalus.orchestration.ikarus.computer_loop import run_computer_task

st = computer_status(subject)
if not st.get("configuration"):
    print("setup:", setup_computer(subject, owner_confirmed=True))
    st = computer_status(subject)
current, digest = st["configuration"], st["policy_sha256"]
print("policy before:", digest, "| tools:", current.get("tools"), "| enabled:", st["enabled"])
payload = dict(current)
payload.update({
    "tools": ["browser.navigate", "browser.read"],
    "origins": [f"http://127.0.0.1:{port}"],
    "max_steps": int(os.environ.get("MAX_STEPS", "8")), "timeout_s": 900,
})
if planner == "ollama":
    payload.update({"planner_provider": "ollama_http", "planner_model": "qwen2.5-coder:7b", "allow_remote_context": False})
elif planner == "codex":
    payload.update({"planner_provider": "codex_cli", "planner_model": os.environ.get("CODEX_MODEL") or None,
                    "allow_remote_context": True})
else:
    raise SystemExit(f"unknown PLANNER {planner}")
res = configure_computer(subject, payload, owner_confirmed=True, expected_policy_sha256=digest)
print("configured:", res)
st2 = computer_status(subject)
print("policy after:", st2["policy_sha256"], "| enabled:", st2["enabled"],
      "| tools:", [t["name"] for t in st2["tools"]], "| unavailable:", st2["unavailable"],
      "| planner:", st2["configuration"].get("planner_provider"), st2["configuration"].get("planner_model"),
      "| remote:", st2["configuration"].get("allow_remote_context"))

objective = (f"Open http://127.0.0.1:{port}/notes.html in the browser, read the page, and report "
             "the page title, the three items listed under Today, and the sentinel code.")
t0 = time.time()
report = run_computer_task(subject, objective, mission_id=mission_id)
elapsed = time.time() - t0
out = {"port": port, "objective": objective, "planner": planner, "elapsed_s": elapsed,
       "policy_sha256": st2["policy_sha256"], "report": report}
io.open(S / f"{mission_id}.json", "w", encoding="utf-8").write(json.dumps(out, indent=1, default=str))
print("state:", report.get("state"), "| ok:", report.get("ok"), "| tool_steps:", report.get("tool_steps"),
      "| planner_calls:", report.get("planner_calls"), "| replans:", report.get("replans"),
      "| repair_calls:", report.get("repair_calls"), "| elapsed_s:", round(elapsed, 1))
print("summary:", report.get("summary"))
print("planner_summary:", str(report.get("planner_summary"))[:600])
for step in report.get("steps", []):
    oc = step.get("outcome", {})
    r = oc.get("result", {}) if isinstance(oc.get("result"), dict) else {}
    print(" step", step.get("step"), step.get("tool"), "| ok:", oc.get("ok"), "| status:", r.get("status"),
          "| url:", r.get("url"), "| text:", repr(str(r.get("text", ""))[:160]))
# retain every planner proposal verbatim (the artifacts are content-addressed under the control root)
props = []
for p in report.get("proposals", []):
    path = S / "control" / "ikarus-computer-artifacts" / f"{p.get('sha256', '')}.json"
    body = None
    try:
        body = json.loads(io.open(path, encoding="utf-8").read()) if path.is_file() else None
    except Exception as exc:
        body = {"unreadable": f"{type(exc).__name__}: {exc}"}
    props.append({"artifact": p, "response": (body or {}).get("response"), "planner_call": (body or {}).get("planner_call")})
io.open(S / f"{mission_id}_planner_proposals.json", "w", encoding="utf-8").write(json.dumps(props, indent=1, default=str))
print("proposals retained:", len(props))
