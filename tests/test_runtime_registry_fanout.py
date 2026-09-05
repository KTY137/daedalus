from __future__ import annotations

import threading
from unittest import mock

from daedalus import runtime_registry


def _spec(runtime_id: str) -> runtime_registry.RuntimeSpec:
    return runtime_registry.RuntimeSpec(
        id=runtime_id,
        label=runtime_id,
        mode="api",
        env_key=f"{runtime_id.upper()}_KEY",
    )


def test_all_status_fans_out_independent_probes_and_preserves_registry_order():
    specs = tuple(_spec(runtime_id) for runtime_id in ("alpha", "beta", "gamma"))
    rendezvous = threading.Barrier(len(specs), timeout=5.0)
    calls: list[str] = []
    calls_lock = threading.Lock()

    def probe(runtime_id: str) -> dict[str, object]:
        with calls_lock:
            calls.append(runtime_id)
        rendezvous.wait()
        return {"id": runtime_id, "available": True}

    with (
        mock.patch.object(runtime_registry, "RUNTIMES", specs),
        mock.patch.object(runtime_registry, "runtime_status", side_effect=probe),
    ):
        rows = runtime_registry.all_status()["runtimes"]

    assert [row["id"] for row in rows] == [spec.id for spec in specs]
    assert set(calls) == {spec.id for spec in specs}


def test_all_status_fans_out_cold_cache_misses_but_reuses_warm_rows():
    specs = tuple(_spec(runtime_id) for runtime_id in ("alpha", "beta", "gamma"))
    rendezvous = threading.Barrier(len(specs), timeout=5.0)
    calls: list[str] = []
    calls_lock = threading.Lock()

    def probe(runtime_id: str) -> dict[str, object]:
        with calls_lock:
            calls.append(runtime_id)
        rendezvous.wait()
        return {"id": runtime_id, "available": True}

    runtime_registry.reset_status_cache()
    try:
        with (
            mock.patch.object(runtime_registry, "RUNTIMES", specs),
            mock.patch.object(runtime_registry, "runtime_status", side_effect=probe),
        ):
            cold = runtime_registry.all_status(use_cache=True, ttl_s=60.0)["runtimes"]
            warm = runtime_registry.all_status(use_cache=True, ttl_s=60.0)["runtimes"]
    finally:
        runtime_registry.reset_status_cache()

    expected = [spec.id for spec in specs]
    assert [row["id"] for row in cold] == expected
    assert [row["id"] for row in warm] == expected
    assert sorted(calls) == sorted(expected)
    assert all(row["measured_age_s"] >= 0.0 for row in warm)


def test_all_status_isolates_probe_failure_without_reordering_other_rows():
    specs = tuple(_spec(runtime_id) for runtime_id in ("alpha", "beta", "gamma"))

    def probe(runtime_id: str) -> dict[str, object]:
        if runtime_id == "beta":
            raise RuntimeError("beta probe failed")
        return {"id": runtime_id, "available": True}

    with (
        mock.patch.object(runtime_registry, "RUNTIMES", specs),
        mock.patch.object(runtime_registry, "runtime_status", side_effect=probe),
    ):
        rows = runtime_registry.all_status()["runtimes"]

    assert [row["id"] for row in rows] == [spec.id for spec in specs]
    assert rows[0]["available"] is True
    assert rows[1]["available"] is False
    assert rows[1]["auth_status"] == "error"
    assert rows[1]["last_error"] == "beta probe failed"
    assert rows[2]["available"] is True
