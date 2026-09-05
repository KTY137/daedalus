"""Stage 13: live Ikarus computer-loop measurement on the scratch subject with release-enabled browser tools."""
import io, json, os, sys, time
from pathlib import Path

S = Path(os.environ["DAEDALUS_KILLSWITCH"]).parent.parent
subject = S / "subject"
port = io.open(S / "www" / "port.txt").read().strip()
env_file = S.parent / "limit_policy.env"
if env_file.is_file() and os.environ.get("STAGE13_UNBOUNDED") == "1":
    raw = io.open(env_file, encoding="utf-8").read().strip()
    key, _, value = raw.partition("=") if "=" in raw else ("DAEDALUS_EXECUTION_LIMIT_POLICY", "=", raw)
    os.environ[key.strip()] = value.strip()
    print("execution limit policy env applied from", env_file.name)

from daedalus.spine.killswitch import KillSwitch
print("killswitch:", KillSwitch(repo_root=subject).arm(force=True, note="stage15 native-route rerun"))
from daedalus.runtimes.computer import computer_status
from daedalus.interfaces.computer_configuration import configure_computer
from daedalus.orchestration.ikarus.computer_loop import run_computer_task

st = computer_status(subject)
current, digest = st["configuration"], st["policy_sha256"]
print("policy before:", digest, "| tools:", current["tools"], "| enabled:", st["enabled"])
payload = dict(current)
payload.update({
    "tools": ["browser.navigate", "browser.read"],
    "origins": [f"http://127.0.0.1:{port}"],
    "planner_provider": "ollama_http", "planner_model": "qwen2.5-coder:7b",
    "max_steps": 8, "timeout_s": 900,
})
res = configure_computer(subject, payload, owner_confirmed=True, expected_policy_sha256=digest)
print("configured:", res)
st2 = computer_status(subject)
print("policy after:", st2["policy_sha256"], "| enabled:", st2["enabled"],
      "| tools:", [t["name"] for t in st2["tools"]], "| unavailable:", st2["unavailable"])

objective = (f"Open http://127.0.0.1:{port}/notes.html in the browser, read the page, and report "
             "the page title, the three items listed under Today, and the sentinel code.")
t0 = time.time()
report = run_computer_task(subject, objective, mission_id="computer-loop-measure-06")
elapsed = time.time() - t0
out = {"port": port, "objective": objective, "elapsed_s": elapsed, "policy_sha256": st2["policy_sha256"],
       "report": report}
io.open(S / "ikarus-06.json", "w", encoding="utf-8").write(json.dumps(out, indent=1, default=str))
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
