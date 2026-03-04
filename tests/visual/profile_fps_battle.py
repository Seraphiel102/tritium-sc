"""FPS Profiler -- measures frame rate during a live 90-second battle.

Spawns defenders, starts a battle via API, continuously spawns hostiles to
maintain 80-100+ units, and records FPS, unit count, WebSocket message
rate, and DOM mutations every second.

Run:
    .venv/bin/python3 tests/visual/profile_fps_battle.py
"""

from __future__ import annotations

import json
import sys
import time

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"
PROFILE_DURATION = 90  # seconds


def api_spawn(name, alliance, asset_type):
    """Spawn a single unit via the simulation API."""
    try:
        r = requests.post(
            f"{BASE_URL}/api/amy/simulation/spawn",
            json={"name": name, "alliance": alliance, "asset_type": asset_type},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


def spawn_batch(count, alliance, asset_type, prefix):
    """Spawn a batch of units. Return number successfully spawned."""
    ok = 0
    for i in range(count):
        if api_spawn(f"{prefix}-{i}", alliance, asset_type):
            ok += 1
    return ok


def main():
    # ------------------------------------------------------------------
    # 1.  Pre-flight: make sure the server is alive and reset game
    # ------------------------------------------------------------------
    try:
        r = requests.get(f"{BASE_URL}/api/game/state", timeout=5)
        r.raise_for_status()
        state = r.json()["state"]
        print(f"Server OK  -- game state: {state}")
    except Exception as e:
        print(f"FATAL: server not reachable at {BASE_URL}: {e}")
        sys.exit(1)

    # Always reset to setup first
    print("Resetting game ...")
    requests.post(f"{BASE_URL}/api/game/reset", timeout=5)
    time.sleep(1)

    # ------------------------------------------------------------------
    # 2.  Spawn defenders BEFORE starting the battle
    # ------------------------------------------------------------------
    print("\nSpawning defenders (turrets + rovers) ...")
    n_turrets = spawn_batch(4, "friendly", "turret", "turret")
    n_rovers = spawn_batch(2, "friendly", "rover", "rover")
    n_drones = spawn_batch(2, "friendly", "drone", "drone")
    print(f"  Spawned: {n_turrets} turrets, {n_rovers} rovers, {n_drones} drones")

    # Verify defenders exist (use simulation targets API, not unified)
    time.sleep(1)
    try:
        sr = requests.get(f"{BASE_URL}/api/amy/simulation/targets", timeout=5).json()
        targets = sr.get("targets", sr) if isinstance(sr, dict) else sr
        if isinstance(targets, list):
            friendlies = [t for t in targets if t.get("alliance") == "friendly"]
            friendly_count = len(friendlies)
        else:
            friendly_count = 0
        print(f"  Friendlies confirmed: {friendly_count}")
    except Exception as ex:
        print(f"  Warning: could not verify friendlies: {ex}")
        friendly_count = 0

    if friendly_count == 0:
        print("FATAL: No defenders spawned! Cannot run battle profiling.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3.  Launch browser and inject profiler
    # ------------------------------------------------------------------
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Collect console messages for debugging
        console_errors = []
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        print("\nOpening Command Center ...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(4000)

        if console_errors:
            print(f"  PAGE ERRORS ({len(console_errors)}):")
            for e in console_errors[:5]:
                print(f"    {e[:120]}")

        # Check if TritiumStore is available
        store_ok = page.evaluate(
            "typeof window.TritiumStore !== 'undefined' && window.TritiumStore !== null")
        ws_status = page.evaluate(
            "window.TritiumStore ? window.TritiumStore.connection.status : 'no store'")
        unit_count = page.evaluate(
            "window.TritiumStore ? window.TritiumStore.units.size : -1")
        print(f"  TritiumStore: {'OK' if store_ok else 'MISSING'}")
        print(f"  WebSocket: {ws_status}")
        print(f"  Units in store: {unit_count}")

        if not store_ok:
            print("\n  WARNING: TritiumStore not available!")
            print("  This means the JS modules failed to load.")
            if console_errors:
                print("  Possible cause: JS syntax error (see above)")
            print("  Profiling will continue but unit counts from store will be -1.")
            print("  Will use API polling for unit counts instead.\n")

        # Set up CDP for WebSocket frame counting (most reliable method)
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        ws_frame_count = [0]

        def on_ws_frame(params):
            ws_frame_count[0] += 1

        cdp.on("Network.webSocketFrameReceived", on_ws_frame)

        # Inject FPS profiler + DOM observer
        print("Injecting profiler ...")
        page.evaluate("""() => {
            window._perfData = [];
            window._perfRunning = true;
            let frameCount = 0;
            let secondStart = performance.now();

            function tick(now) {
                if (!window._perfRunning) return;
                frameCount++;
                const elapsed = now - secondStart;
                if (elapsed >= 1000) {
                    const store = window.TritiumStore;
                    const unitCount = store ? store.units.size : -1;
                    window._perfData.push({
                        time: Math.round((now - window._perfStart) / 1000),
                        fps:  Math.round(frameCount * 1000 / elapsed),
                        units: unitCount,
                        domMuts: window._domMutCount || 0,
                    });
                    window._domMutCount = 0;
                    frameCount = 0;
                    secondStart = now;
                }
                requestAnimationFrame(tick);
            }
            window._perfStart = performance.now();
            requestAnimationFrame(tick);

            window._domMutCount = 0;
            const observer = new MutationObserver((mutations) => {
                window._domMutCount += mutations.length;
            });
            observer.observe(document.body, {
                childList: true, subtree: true,
                attributes: true, characterData: true,
            });
        }""")

        # ------------------------------------------------------------------
        # 4.  Start the battle
        # ------------------------------------------------------------------
        print("\nStarting battle via API ...")
        r = requests.post(f"{BASE_URL}/api/game/begin", timeout=10)
        print(f"  Response: {r.status_code} {r.text[:200]}")

        # Wait for countdown (5s) + first wave to start
        page.wait_for_timeout(8000)

        gs = requests.get(f"{BASE_URL}/api/game/state", timeout=5).json()
        print(f"  Game state: {gs['state']}, wave: {gs['wave']}")

        if gs["state"] == "defeat":
            print("  ERROR: Game went to defeat despite spawning defenders.")
            print("  This might mean defenders aren't being treated as combatants.")
            print("  Continuing anyway to profile with manual spawning...")

        # ------------------------------------------------------------------
        # 5.  Pre-spawn a large batch of hostiles for stress
        # ------------------------------------------------------------------
        print("\nSpawning initial hostile batch ...")
        initial_hostile = spawn_batch(50, "hostile", "person", "h-init")
        print(f"  Spawned {initial_hostile} initial hostiles")
        page.wait_for_timeout(2000)

        # ------------------------------------------------------------------
        # 6.  Profile for PROFILE_DURATION seconds
        # ------------------------------------------------------------------
        print(f"\nProfiling for {PROFILE_DURATION}s -- watch the browser ...\n")
        game_states = []
        poll_interval = 5
        start = time.time()
        last_ws_count = 0
        last_ws_time = time.time()
        ws_rates = []

        while time.time() - start < PROFILE_DURATION:
            elapsed = int(time.time() - start)

            # Track WS frames/sec from CDP
            now_ws = ws_frame_count[0]
            dt = time.time() - last_ws_time
            if dt >= 1.0:
                ws_rate = (now_ws - last_ws_count) / dt
                ws_rates.append(ws_rate)
                last_ws_count = now_ws
                last_ws_time = time.time()

            if elapsed % poll_interval == 0:
                try:
                    gs = requests.get(
                        f"{BASE_URL}/api/game/state", timeout=3).json()
                    gs["elapsed"] = elapsed
                    game_states.append(gs)

                    # Get unit count from store (or API fallback)
                    try:
                        store_units = page.evaluate(
                            "window.TritiumStore ? window.TritiumStore.units.size : -1")
                    except Exception:
                        store_units = -1

                    # API unit count fallback (use simulation targets API)
                    try:
                        tgt = requests.get(
                            f"{BASE_URL}/api/amy/simulation/targets", timeout=3).json()
                        targets = tgt.get("targets", tgt) if isinstance(tgt, dict) else tgt
                        api_units = len(targets) if isinstance(targets, list) else 0
                    except Exception:
                        api_units = 0

                    wave = gs.get("wave", "?")
                    state = gs.get("state", "?")
                    score = gs.get("score", 0)

                    gs["_api_units"] = api_units
                    print(f"  t={elapsed:3d}s  wave={wave}  state={state:15s}  "
                          f"score={score:5d}  store={store_units:3d}  "
                          f"api={api_units:3d}  ws_frames={ws_frame_count[0]}")

                    # Keep spawning hostiles to maintain high unit count
                    if api_units < 80 and elapsed < PROFILE_DURATION - 15:
                        need = 80 - api_units
                        batch = min(need, 30)
                        s = spawn_batch(batch, "hostile", "person",
                                        f"h-t{elapsed}")
                        if s > 0:
                            print(f"         spawned {s} hostiles "
                                  f"(was {api_units})")

                except Exception as ex:
                    print(f"  t={elapsed:3d}s  poll error: {ex}")

            time.sleep(1)

        # ------------------------------------------------------------------
        # 7.  Stop profiler and extract data
        # ------------------------------------------------------------------
        print("\nStopping profiler ...")
        page.evaluate("window._perfRunning = false")
        page.wait_for_timeout(500)

        perf_data = page.evaluate("window._perfData")

        page.screenshot(path="tests/.test-results/fps_profile_battle.png")
        print("Screenshot saved: tests/.test-results/fps_profile_battle.png")

        browser.close()

    # ------------------------------------------------------------------
    # 8.  Analysis
    # ------------------------------------------------------------------
    if not perf_data:
        print("ERROR: No performance data collected!")
        sys.exit(1)

    total_cdp_ws = ws_frame_count[0]
    avg_ws_cdp = total_cdp_ws / PROFILE_DURATION if PROFILE_DURATION > 0 else 0

    # If store unit counts are all -1, use API-polled counts from game_states
    store_worked = any(d["units"] >= 0 for d in perf_data)
    if not store_worked:
        print("\nNOTE: TritiumStore unit counts not available.")
        print("      Using API-polled unit counts instead.\n")
        # Build a time->unit_count map from game_states
        # Use the api_units values we captured during the profiling loop
        api_unit_map = {}
        for gs in game_states:
            e = gs.get("elapsed", 0)
            # We stored api_units counts in the polling loop printout;
            # re-derive from captured game_states if needed
            api_unit_map[e] = gs.get("_api_units", 0)
        # Interpolate unit counts into perf_data based on closest poll time
        if api_unit_map:
            poll_times = sorted(api_unit_map.keys())
            for d in perf_data:
                t = d["time"]
                closest = min(poll_times, key=lambda pt: abs(pt - t))
                d["units"] = api_unit_map[closest]

    # Build API unit counts from game_states for correlation
    api_counts_by_time = {}
    for gs in game_states:
        elapsed = gs.get("elapsed", 0)
        api_counts_by_time[elapsed] = gs.get("_api_units", 0)

    # Print raw table
    print("\n" + "=" * 80)
    print("  FPS PROFILE -- BATTLE (post-optimization)")
    print("=" * 80)
    print(f"  {'Time':>5s}  {'FPS':>4s}  {'Units':>6s}  {'DOM mut/s':>10s}")
    print("-" * 80)
    for d in perf_data:
        units_display = d["units"] if d["units"] >= 0 else "?"
        print(f"  {d['time']:>5d}  {d['fps']:>4d}  {str(units_display):>6s}"
              f"  {d.get('domMuts', 0):>10d}")

    # Stats
    fps_values = [d["fps"] for d in perf_data]
    avg_fps = sum(fps_values) / len(fps_values) if fps_values else 0
    min_fps = min(fps_values) if fps_values else 0
    max_fps = max(fps_values) if fps_values else 0

    # Use only samples with valid unit counts
    valid = [d for d in perf_data if d["units"] > 0]

    heavy = [d for d in valid if d["units"] > 60]
    avg_fps_heavy = (sum(d["fps"] for d in heavy) / len(heavy)) if heavy else 0
    min_fps_heavy = min(d["fps"] for d in heavy) if heavy else 0

    very_heavy = [d for d in valid if d["units"] > 80]
    avg_fps_80 = (sum(d["fps"] for d in very_heavy) / len(very_heavy)
                  ) if very_heavy else 0
    min_fps_80 = min(d["fps"] for d in very_heavy) if very_heavy else 0
    above_30_at_80 = all(d["fps"] >= 30 for d in very_heavy) if very_heavy else None

    thresholds = [10, 20, 40, 60, 80, 100]
    threshold_stats = {}
    for t in thresholds:
        samples = [d for d in valid if d["units"] >= t]
        if samples:
            threshold_stats[t] = {
                "avg": sum(d["fps"] for d in samples) / len(samples),
                "min": min(d["fps"] for d in samples),
                "max": max(d["fps"] for d in samples),
                "n": len(samples),
            }

    dom_values = [d.get("domMuts", 0) for d in perf_data]
    avg_dom = sum(dom_values) / len(dom_values) if dom_values else 0
    max_dom = max(dom_values) if dom_values else 0

    max_units = max((d["units"] for d in perf_data if d["units"] >= 0), default=0)

    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Duration:             {len(perf_data)} seconds recorded")
    print(f"  Peak unit count:      {max_units}")
    print(f"  Store data available: {'Yes' if store_worked else 'No (used API polling)'}")
    print(f"  Overall avg FPS:      {avg_fps:.1f}")
    print(f"  Overall min FPS:      {min_fps}")
    print(f"  Overall max FPS:      {max_fps}")
    print()
    print(f"  {'Threshold':>12s}  {'Avg FPS':>8s}  {'Min FPS':>8s}  "
          f"{'Max FPS':>8s}  {'Samples':>8s}")
    print("-" * 60)
    for t in thresholds:
        if t in threshold_stats:
            s = threshold_stats[t]
            print(f"  {'>= ' + str(t) + ' units':>12s}  {s['avg']:>8.1f}  "
                  f"{s['min']:>8d}  {s['max']:>8d}  {s['n']:>8d}")
        else:
            print(f"  {'>= ' + str(t) + ' units':>12s}  {'N/A':>8s}  "
                  f"{'N/A':>8s}  {'N/A':>8s}  {'0':>8s}")
    print()
    if above_30_at_80 is not None:
        verdict_80 = "YES" if above_30_at_80 else "NO"
        print(f"  FPS >= 30 at 80+ units: {verdict_80}")
    else:
        print(f"  FPS >= 30 at 80+ units: N/A (never reached 80 units)")
    print()
    print(f"  CDP WebSocket frames total:  {total_cdp_ws}")
    print(f"  CDP WS frames/sec avg:       {avg_ws_cdp:.1f}")
    if ws_rates:
        print(f"  CDP WS frames/sec peak:      {max(ws_rates):.1f}")
    print(f"  Avg DOM mutations/sec:       {avg_dom:.1f}  (peak {max_dom})")

    # Before vs After comparison
    print("\n" + "=" * 80)
    print("  BEFORE vs AFTER COMPARISON")
    print("=" * 80)
    print(f"  {'Metric':<30s}  {'BEFORE':>12s}  {'AFTER':>12s}  {'Change':>12s}")
    print("-" * 80)

    before_fps_heavy = 12.5

    if avg_fps_heavy > 0:
        fps_pct = ((avg_fps_heavy - before_fps_heavy) / before_fps_heavy) * 100
        print(f"  {'FPS at 60+ units':<30s}"
              f"  {'10-15':>12s}"
              f"  {avg_fps_heavy:>12.1f}"
              f"  {fps_pct:>+11.0f}%")
    elif max_units > 0:
        # Use whatever units we had
        all_valid = [d for d in valid if d["units"] > 0]
        if all_valid:
            avg_all = sum(d["fps"] for d in all_valid) / len(all_valid)
            print(f"  {'FPS (all units > 0)':<30s}"
                  f"  {'10-15':>12s}"
                  f"  {avg_all:>12.1f}"
                  f"  {((avg_all - before_fps_heavy) / before_fps_heavy) * 100:>+11.0f}%")
    else:
        print(f"  {'FPS at 60+ units':<30s}"
              f"  {'10-15':>12s}"
              f"  {'N/A':>12s}"
              f"  {'N/A':>12s}")

    before_dom = 20000
    if max_dom > 0:
        dom_change_pct = ((avg_dom - before_dom) / before_dom) * 100
        print(f"  {'DOM mutations/sec (avg)':<30s}"
              f"  {'20,000+':>12s}"
              f"  {avg_dom:>12.0f}"
              f"  {dom_change_pct:>+11.0f}%")
        print(f"  {'DOM mutations/sec (peak)':<30s}"
              f"  {'20,000+':>12s}"
              f"  {max_dom:>12d}"
              f"  {((max_dom - before_dom) / before_dom) * 100:>+11.0f}%")
    else:
        print(f"  {'DOM mutations/sec':<30s}"
              f"  {'20,000+':>12s}"
              f"  {'0':>12s}"
              f"  {'-100%':>12s}")

    print(f"  {'WS frames/sec (CDP)':<30s}"
          f"  {'N/A':>12s}"
          f"  {avg_ws_cdp:>12.1f}"
          f"  {'(baseline)':>12s}")
    print(f"  {'Peak unit count':<30s}"
          f"  {'70-100':>12s}"
          f"  {max_units:>12d}"
          f"  {'':>12s}")

    # Final verdict
    print("\n" + "=" * 80)
    if max_units < 20:
        print("  VERDICT: INCONCLUSIVE -- Not enough units rendered")
    elif avg_fps_heavy >= 45:
        print("  VERDICT: EXCELLENT -- FPS well above 30 at high unit counts")
    elif avg_fps_heavy >= 30:
        print("  VERDICT: PASS -- FPS >= 30 at 60+ units")
    elif avg_fps_heavy >= 20:
        print("  VERDICT: IMPROVED -- FPS better than 10-15 but below 30 target")
    elif avg_fps_heavy > 0:
        print("  VERDICT: MARGINAL -- Some improvement but still needs work")
    else:
        if max_units >= 20:
            all_valid = [d for d in valid if d["units"] > 0]
            if all_valid:
                avg_all = sum(d["fps"] for d in all_valid) / len(all_valid)
                min_all = min(d["fps"] for d in all_valid)
                print(f"  VERDICT: Peak {max_units} units, "
                      f"avg FPS {avg_all:.0f}, min FPS {min_all}")
        else:
            print("  VERDICT: INCONCLUSIVE")
    print("=" * 80)

    # Save raw data
    import os
    os.makedirs("tests/.test-results", exist_ok=True)
    with open("tests/.test-results/fps_profile_data.json", "w") as f:
        json.dump({
            "perf_data": perf_data,
            "game_states": game_states,
            "api_unit_counts": api_counts_by_time,
            "summary": {
                "duration_seconds": len(perf_data),
                "peak_units": max_units,
                "store_data_available": store_worked,
                "avg_fps": round(avg_fps, 1),
                "min_fps": min_fps,
                "max_fps": max_fps,
                "avg_fps_60plus": round(avg_fps_heavy, 1),
                "min_fps_60plus": min_fps_heavy,
                "avg_fps_80plus": round(avg_fps_80, 1),
                "min_fps_80plus": min_fps_80,
                "fps_above_30_at_80_units": above_30_at_80,
                "threshold_stats": {str(k): v for k, v in threshold_stats.items()},
                "cdp_ws_total": total_cdp_ws,
                "cdp_ws_per_sec_avg": round(avg_ws_cdp, 1),
                "avg_dom_per_sec": round(avg_dom, 1),
                "peak_dom_per_sec": max_dom,
            }
        }, f, indent=2)
    print(f"\nRaw data saved: tests/.test-results/fps_profile_data.json")


if __name__ == "__main__":
    main()
