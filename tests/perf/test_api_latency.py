# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""API latency benchmarks for the 20 most important endpoints.

All endpoints should respond in <200ms.  Uses TestClient for synchronous
in-process testing (no network overhead) so we are measuring pure
handler + serialization time.

Run:
    .venv/bin/python3 -m pytest tests/perf/test_api_latency.py -v
"""

import time

import pytest

# Lazy import TestClient to handle missing deps gracefully
try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not installed", allow_module_level=True)


# Maximum allowed response time in milliseconds
MAX_LATENCY_MS = 200.0


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app."""
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
    os.environ.setdefault("SIMULATION_ENABLED", "false")
    os.environ.setdefault("AMY_ENABLED", "false")
    os.environ.setdefault("MQTT_ENABLED", "false")

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _measure(client, method: str, path: str, iterations: int = 3) -> float:
    """Measure average response time in ms over N iterations."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json={})
        else:
            resp = client.get(path)
        elapsed_ms = (time.perf_counter() - start) * 1000
        times.append(elapsed_ms)
    return sum(times) / len(times)


# The 20 most important API endpoints
_ENDPOINTS = [
    ("GET", "/api/health"),
    ("GET", "/api/version"),
    ("GET", "/api/cameras"),
    ("GET", "/api/targets"),
    ("GET", "/api/targets/hostiles"),
    ("GET", "/api/targets/friendlies"),
    ("GET", "/api/zones"),
    ("GET", "/api/fleet"),
    ("GET", "/api/fleet/nodes"),
    ("GET", "/api/devices"),
    ("GET", "/api/demo/status"),
    ("GET", "/api/sitrep"),
    ("GET", "/api/briefing"),
    ("GET", "/api/metrics"),
    ("GET", "/api/analytics/movement"),
    ("GET", "/api/heatmap"),
    ("GET", "/api/geofence/zones"),
    ("GET", "/api/plugins"),
    ("GET", "/api/layers"),
    ("GET", "/api/ollama/health"),
]


@pytest.mark.parametrize("method,path", _ENDPOINTS, ids=[p for _, p in _ENDPOINTS])
def test_endpoint_latency(client, method: str, path: str):
    """Each endpoint must respond in under 200ms."""
    avg_ms = _measure(client, method, path)
    # We allow any HTTP status (some return 503 without Amy running),
    # but the response itself must be fast.
    assert avg_ms < MAX_LATENCY_MS, (
        f"{method} {path} averaged {avg_ms:.1f}ms (max {MAX_LATENCY_MS}ms)"
    )


def test_latency_summary(client):
    """Generate a summary report of all endpoint latencies."""
    results = []
    for method, path in _ENDPOINTS:
        avg_ms = _measure(client, method, path, iterations=5)
        results.append((method, path, avg_ms))

    # Print summary table
    print("\n" + "=" * 60)
    print(f"{'Method':<6} {'Path':<35} {'Avg (ms)':>8} {'Status':>8}")
    print("-" * 60)
    all_pass = True
    for method, path, avg_ms in results:
        status = "PASS" if avg_ms < MAX_LATENCY_MS else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"{method:<6} {path:<35} {avg_ms:>8.1f} {status:>8}")
    print("=" * 60)

    max_ms = max(r[2] for r in results)
    avg_all = sum(r[2] for r in results) / len(results)
    print(f"  Average: {avg_all:.1f}ms  Max: {max_ms:.1f}ms")
    print(f"  All under {MAX_LATENCY_MS}ms: {'YES' if all_pass else 'NO'}")

    assert all_pass, f"Some endpoints exceeded {MAX_LATENCY_MS}ms threshold"
