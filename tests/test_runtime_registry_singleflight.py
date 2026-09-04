from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from daedalus import runtime_registry


class RuntimeRegistrySingleFlightTest(unittest.TestCase):
    """Cold/expired UI polls must not fan out duplicate runtime probes."""

    def setUp(self) -> None:
        runtime_registry.reset_status_cache()

    def tearDown(self) -> None:
        runtime_registry.reset_status_cache()

    def test_concurrent_miss_for_same_runtime_runs_one_probe(self) -> None:
        worker_count = 8
        start = threading.Barrier(worker_count)
        probe_entered = threading.Event()
        release_probe = threading.Event()
        calls_lock = threading.Lock()
        results_lock = threading.Lock()
        calls = 0
        results: list[dict] = []
        errors: list[BaseException] = []

        def slow_probe(runtime_id: str) -> dict:
            nonlocal calls
            with calls_lock:
                calls += 1
            probe_entered.set()
            if not release_probe.wait(timeout=3):
                raise AssertionError("test probe was never released")
            return {
                "id": runtime_id,
                "available": True,
                "auth_status": "cli_detected",
            }

        def worker() -> None:
            try:
                start.wait(timeout=3)
                row = runtime_registry.cached_runtime_status(
                    "claude_code_cli", ttl_s=30.0
                )
                with results_lock:
                    results.append(row)
            except BaseException as exc:  # keep thread failures visible to unittest
                with results_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(worker_count)]
        with mock.patch.object(runtime_registry, "runtime_status", slow_probe):
            for thread in threads:
                thread.start()
            self.assertTrue(probe_entered.wait(timeout=3), "no worker reached the probe")
            # The leader is deliberately blocked. Every other worker has time to
            # reach the same cold cache edge; single-flight means none can start
            # a second expensive CLI probe while it waits.
            time.sleep(0.05)
            with calls_lock:
                self.assertEqual(calls, 1)
            release_probe.set()
            for thread in threads:
                thread.join(timeout=3)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        with calls_lock:
            self.assertEqual(calls, 1)
        self.assertEqual(len(results), worker_count)
        measured = {row["measured_at"] for row in results}
        self.assertEqual(len(measured), 1, results)
        self.assertTrue(all(row["available"] for row in results))

    def test_different_runtimes_are_not_serialized_behind_one_probe(self) -> None:
        entered = {
            "claude_code_cli": threading.Event(),
            "codex_cli": threading.Event(),
        }
        calls_lock = threading.Lock()
        calls: list[str] = []
        errors: list[BaseException] = []

        def coordinated_probe(runtime_id: str) -> dict:
            with calls_lock:
                calls.append(runtime_id)
            entered[runtime_id].set()
            other = "codex_cli" if runtime_id == "claude_code_cli" else "claude_code_cli"
            if not entered[other].wait(timeout=2):
                raise AssertionError(
                    "different runtime probes were serialized by a global lock"
                )
            return {
                "id": runtime_id,
                "available": True,
                "auth_status": "cli_detected",
            }

        def worker(runtime_id: str) -> None:
            try:
                runtime_registry.cached_runtime_status(runtime_id, ttl_s=30.0)
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("claude_code_cli",)),
            threading.Thread(target=worker, args=("codex_cli",)),
        ]
        with mock.patch.object(runtime_registry, "runtime_status", coordinated_probe):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(calls, ["claude_code_cli", "codex_cli"])


if __name__ == "__main__":
    unittest.main()
