"""Computer due work uses the existing watcher and its cancellation signal."""
from contextlib import nullcontext
import threading

from daedalus.interfaces.bridge.watcher import watch_loop


def run_watcher(tmp_path, stop, tick, *, process=None):
    beats = []
    watch_loop(
        outbox=tmp_path / "outbox", inbox=tmp_path / "inbox",
        watcher_lock_path=tmp_path / "lock", default_repo_root=str(tmp_path),
        interval_s=0, project=None, owner_token="fixture", process_identity="fixture",
        stop_event=stop, heartbeat=lambda **kwargs: beats.append(kwargs),
        watcher_lock=lambda path: nullcontext(), process_request=process or (lambda *args: None),
        handle_poison=lambda *args: None, pending_exceptions=(), now_epoch=lambda: 0,
        now_iso=lambda: "2026-09-05T00:00:00+00:00", sleep=lambda seconds: None,
        scheduled_tick=tick,
    )
    return beats


def test_due_tick_reuses_watcher_and_reports_busy(tmp_path):
    stop = threading.Event()
    calls = []
    def tick():
        calls.append(True)
        stop.set()
        return [{"state": "completed"}]
    beats = run_watcher(tmp_path, stop, tick)
    assert calls == [True]
    assert any(beat["current"] and beat["current"]["file"] == "computer schedule" for beat in beats)
    assert beats[-1]["current"] is None


def test_existing_request_cancellation_prevents_scheduled_tick(tmp_path):
    stop = threading.Event()
    (tmp_path / "outbox").mkdir()
    request = tmp_path / "outbox" / "fixture.json"
    request.write_text("{}")
    calls = []
    def process(path, root):
        stop.set()
        return tmp_path / "report.json"
    run_watcher(tmp_path, stop, lambda: calls.append(True), process=process)
    assert not calls


def test_due_failure_does_not_kill_existing_watcher(tmp_path, capsys):
    stop = threading.Event()
    def tick():
        stop.set()
        raise RuntimeError("fixture refusal")
    beats = run_watcher(tmp_path, stop, tick)
    assert "COMPUTER SCHEDULE BLOCKED" in capsys.readouterr().out
    assert beats[-1]["current"] is None
