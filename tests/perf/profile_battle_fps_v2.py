"""
Battle FPS Profiler v2 — measures frame rate during active combat.

Injects profiler BEFORE page load by intercepting route, ensuring
WebSocket messages are captured. Hooks TritiumStore.updateUnit for
reliable WS message counting.

Run:
    .venv/bin/python3 tests/perf/profile_battle_fps_v2.py
"""

import json
import time
import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
PROFILE_DURATION_S = 90  # longer to capture multiple waves


PROFILER_SCRIPT = """
window.__perfData = {
    secondBuckets: {},
    consoleLogCount: 0,
    startTime: performance.now(),
    updateUnitCalls: 0,
    notifyCalls: 0,
};

// Frame time profiler
let _lastFrameTime = performance.now();
let _frameCount = 0;
function _measureFrame() {
    const now = performance.now();
    const dt = now - _lastFrameTime;
    const fps = dt > 0 ? 1000 / dt : 0;
    _lastFrameTime = now;
    _frameCount++;

    const elapsed = (now - window.__perfData.startTime) / 1000;
    const sec = Math.floor(elapsed);
    const b = _getBucket(sec);
    b.fps.push(fps);
    b.frameTimes.push(dt);

    requestAnimationFrame(_measureFrame);
}
requestAnimationFrame(_measureFrame);

function _getBucket(sec) {
    if (!window.__perfData.secondBuckets[sec]) {
        window.__perfData.secondBuckets[sec] = {
            wsCount: 0, domMutCount: 0, geojsonCount: 0,
            fps: [], frameTimes: [], consoleLogCount: 0,
            unitCount: 0, hostileCount: 0, friendlyCount: 0,
            setDataCount: 0, updateUnitCount: 0, notifyCount: 0,
            gamePhase: '', waveNum: 0,
        };
    }
    return window.__perfData.secondBuckets[sec];
}

// DOM Mutation observer on body (to catch everything)
const _mutObserver = new MutationObserver((mutations) => {
    const now = performance.now();
    const elapsed = (now - window.__perfData.startTime) / 1000;
    const sec = Math.floor(elapsed);
    _getBucket(sec).domMutCount += mutations.length;
});
// Will be connected after page loads
window.__perfHookDOMMutations = function() {
    const target = document.getElementById('tactical-area')
        || document.getElementById('maplibre-map')
        || document.body;
    _mutObserver.observe(target, {
        childList: true, subtree: true,
        attributes: true, characterData: true,
    });
};

// Console.log counter
const _origLog = console.log;
console.log = function() {
    const now = performance.now();
    const elapsed = (now - window.__perfData.startTime) / 1000;
    const sec = Math.floor(elapsed);
    _getBucket(sec).consoleLogCount++;
    window.__perfData.consoleLogCount++;
    return _origLog.apply(console, arguments);
};

// Unit count + game state sampler (every 200ms)
setInterval(() => {
    const now = performance.now();
    const elapsed = (now - window.__perfData.startTime) / 1000;
    const sec = Math.floor(elapsed);
    const b = _getBucket(sec);
    try {
        const store = window.TritiumStore;
        if (store && store.units) {
            let total = 0, hostile = 0, friendly = 0;
            store.units.forEach(u => {
                total++;
                if (u.alliance === 'hostile') hostile++;
                else if (u.alliance === 'friendly') friendly++;
            });
            b.unitCount = total;
            b.hostileCount = hostile;
            b.friendlyCount = friendly;
        }
        if (store) {
            b.gamePhase = store.game?.phase || '';
            b.waveNum = store.game?.wave || 0;
        }
    } catch(e) {}
}, 200);

// Hook TritiumStore when it becomes available
window.__perfHookStore = function() {
    if (!window.TritiumStore) return false;
    const store = window.TritiumStore;

    // Hook updateUnit
    const origUpdateUnit = store.updateUnit.bind(store);
    store.updateUnit = function(id, data) {
        const now = performance.now();
        const elapsed = (now - window.__perfData.startTime) / 1000;
        const sec = Math.floor(elapsed);
        _getBucket(sec).updateUnitCount++;
        _getBucket(sec).wsCount++;
        window.__perfData.updateUnitCalls++;
        return origUpdateUnit(id, data);
    };

    // Hook _notify to count how often store notifies listeners
    const origNotify = store._notify.bind(store);
    store._notify = function(path, value, oldValue) {
        const now = performance.now();
        const elapsed = (now - window.__perfData.startTime) / 1000;
        const sec = Math.floor(elapsed);
        _getBucket(sec).notifyCount++;
        window.__perfData.notifyCalls++;
        return origNotify(path, value, oldValue);
    };

    return true;
};

// Hook MapLibre setData when map is ready
window.__perfHookSetData = function() {
    const mapState = window._mapState;
    if (!mapState || !mapState.map) return false;
    const map = mapState.map;
    const origGetSource = map.getSource.bind(map);
    map.getSource = function(sourceId) {
        const source = origGetSource(sourceId);
        if (source && source.setData && !source._hooked) {
            const origSetData = source.setData.bind(source);
            source.setData = function(data) {
                const now = performance.now();
                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);
                _getBucket(sec).setDataCount++;
                _getBucket(sec).geojsonCount++;
                return origSetData(data);
            };
            source._hooked = true;
        }
        return source;
    };
    return true;
};

console.log('[PROFILER] FPS profiler core installed');
"""


def main():
    # Reset game to setup state
    print("[RESET] Resetting game to setup...")
    try:
        resp = requests.post(f"{BASE}/api/game/reset")
        print(f"  Response: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"  Failed: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-gpu-vsync",
                "--disable-frame-rate-limit",
            ],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Inject profiler script BEFORE navigating (via addInitScript)
        page.add_init_script(script=PROFILER_SCRIPT)

        # Navigate
        print("[NAV] Opening Command Center...")
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Connect hooks now that the page is loaded
        print("[HOOK] Connecting DOM mutation observer...")
        page.evaluate("() => window.__perfHookDOMMutations()")

        print("[HOOK] Connecting TritiumStore hooks...")
        for attempt in range(10):
            hooked = page.evaluate("() => window.__perfHookStore()")
            if hooked:
                print(f"  TritiumStore hooked on attempt {attempt + 1}")
                break
            page.wait_for_timeout(500)
        else:
            print("  WARNING: TritiumStore hook failed")

        print("[HOOK] Connecting MapLibre setData hooks...")
        for attempt in range(10):
            hooked = page.evaluate("() => window.__perfHookSetData()")
            if hooked:
                print(f"  MapLibre setData hooked on attempt {attempt + 1}")
                break
            page.wait_for_timeout(500)
        else:
            print("  WARNING: MapLibre setData hook failed")

        # Reset profiler baseline
        page.evaluate("""() => {
            window.__perfData.secondBuckets = {};
            window.__perfData.startTime = performance.now();
            window.__perfData.consoleLogCount = 0;
            window.__perfData.updateUnitCalls = 0;
            window.__perfData.notifyCalls = 0;
        }""")

        # Measure idle for 5 seconds
        print("\n[IDLE] Measuring idle FPS for 5 seconds...")
        page.wait_for_timeout(5000)
        idle_summary = _get_summary(page)
        _print_table_header()
        for d in idle_summary:
            _print_row(d)

        # Reset profiler
        page.evaluate("""() => {
            window.__perfData.secondBuckets = {};
            window.__perfData.startTime = performance.now();
            window.__perfData.consoleLogCount = 0;
            window.__perfData.updateUnitCalls = 0;
            window.__perfData.notifyCalls = 0;
        }""")

        # Start the battle
        print(f"\n[BATTLE] Starting battle...")
        resp = requests.post(f"{BASE}/api/game/begin")
        print(f"  Response: {resp.status_code} {resp.text[:200]}")

        # Profile for PROFILE_DURATION_S seconds with progress updates
        print(f"\n[PROFILE] Recording battle FPS for {PROFILE_DURATION_S} seconds...")
        for i in range(PROFILE_DURATION_S):
            time.sleep(1)
            if (i + 1) % 5 == 0:
                quick = page.evaluate("""() => {
                    const buckets = window.__perfData.secondBuckets;
                    const keys = Object.keys(buckets).map(Number).sort((a,b) => b-a);
                    if (keys.length === 0) return null;
                    const latest = buckets[keys[0]];
                    const avgFps = latest.fps.length > 0
                        ? (latest.fps.reduce((a,b) => a+b, 0) / latest.fps.length).toFixed(1)
                        : '?';
                    return {
                        second: keys[0],
                        fps: avgFps,
                        units: latest.unitCount || 0,
                        hostile: latest.hostileCount || 0,
                        friendly: latest.friendlyCount || 0,
                        wsPerSec: latest.updateUnitCount || latest.wsCount || 0,
                        domMut: latest.domMutCount || 0,
                        setData: latest.setDataCount || 0,
                        notify: latest.notifyCount || 0,
                        phase: latest.gamePhase || '?',
                        wave: latest.waveNum || 0,
                        logs: latest.consoleLogCount || 0,
                    };
                }""")
                if quick:
                    print(f"  [{i+1:3d}s] FPS={quick['fps']:>6}  phase={quick['phase']:>12}  "
                          f"wave={quick['wave']}  units={quick['units']:>3} "
                          f"(H:{quick['hostile']} F:{quick['friendly']})  "
                          f"ws/s={quick['wsPerSec']:>4}  domMut/s={quick['domMut']:>5}  "
                          f"setData/s={quick['setData']:>3}  notify/s={quick['notify']:>4}  "
                          f"logs/s={quick['logs']:>3}")

        # Collect final data
        print("\n[COLLECT] Gathering profiling data...")
        battle_data = _get_summary(page)
        total_update_calls = page.evaluate("() => window.__perfData.updateUnitCalls")
        total_notify_calls = page.evaluate("() => window.__perfData.notifyCalls")
        total_console_logs = page.evaluate("() => window.__perfData.consoleLogCount")

        # Print full results
        print("\n" + "=" * 140)
        print("BATTLE FPS PROFILE RESULTS (FULL)")
        print("=" * 140)
        _print_table_header()
        for d in battle_data:
            _print_row(d)

        print(f"\nTotal updateUnit calls: {total_update_calls}")
        print(f"Total _notify calls:    {total_notify_calls}")
        print(f"Total console.log:      {total_console_logs}")

        # Summary
        if battle_data:
            _print_summary(battle_data)
            _print_correlations(battle_data)

        # Save raw data
        output_path = "/home/scubasonar/Code/tritium-sc/tests/perf/battle_fps_profile_v2.json"
        with open(output_path, "w") as f:
            json.dump({
                "battle_data": battle_data,
                "idle_data": idle_summary,
                "total_update_unit_calls": total_update_calls,
                "total_notify_calls": total_notify_calls,
                "total_console_logs": total_console_logs,
            }, f, indent=2)
        print(f"\n[SAVED] Raw data saved to {output_path}")

        print("\n[DONE] Closing browser in 3 seconds...")
        page.wait_for_timeout(3000)
        browser.close()


def _get_summary(page):
    return page.evaluate("""() => {
        const buckets = window.__perfData.secondBuckets;
        const result = [];
        for (const [sec, data] of Object.entries(buckets)) {
            if (data.fps.length === 0) continue;
            const fpsArr = data.fps.slice().sort((a,b) => a-b);
            const avgFps = fpsArr.reduce((a,b) => a+b, 0) / fpsArr.length;
            const minFps = fpsArr[0] || 0;
            const p1 = fpsArr[Math.floor(fpsArr.length * 0.01)] || 0;
            const p5 = fpsArr[Math.floor(fpsArr.length * 0.05)] || 0;
            const avgFrameTime = data.frameTimes && data.frameTimes.length > 0
                ? data.frameTimes.reduce((a,b) => a+b, 0) / data.frameTimes.length : 0;
            const maxFrameTime = data.frameTimes && data.frameTimes.length > 0
                ? Math.max(...data.frameTimes) : 0;
            result.push({
                second: parseInt(sec),
                avgFps: Math.round(avgFps * 10) / 10,
                minFps: Math.round(minFps * 10) / 10,
                p1Fps: Math.round(p1 * 10) / 10,
                p5Fps: Math.round(p5 * 10) / 10,
                frameCount: fpsArr.length,
                avgFrameTimeMs: Math.round(avgFrameTime * 100) / 100,
                maxFrameTimeMs: Math.round(maxFrameTime * 100) / 100,
                wsCount: data.wsCount || 0,
                updateUnitCount: data.updateUnitCount || 0,
                notifyCount: data.notifyCount || 0,
                domMutCount: data.domMutCount || 0,
                setDataCount: data.setDataCount || 0,
                consoleLogCount: data.consoleLogCount || 0,
                unitCount: data.unitCount || 0,
                hostileCount: data.hostileCount || 0,
                friendlyCount: data.friendlyCount || 0,
                gamePhase: data.gamePhase || '',
                waveNum: data.waveNum || 0,
            });
        }
        return result.sort((a,b) => a.second - b.second);
    }""")


def _print_table_header():
    print(f"{'Sec':>4} | {'Phase':>10} | {'Wave':>4} | {'AvgFPS':>7} | {'1%FPS':>6} | "
          f"{'Frms':>4} | {'AvgMS':>7} | {'MaxMS':>7} | "
          f"{'WS/s':>5} | {'Notify':>6} | {'DOMmut':>7} | "
          f"{'setDat':>6} | {'Logs':>4} | {'Units':>5} | {'Host':>4} | {'Fri':>4}")
    print("-" * 140)


def _print_row(d):
    print(f"{d['second']:4d} | {d['gamePhase']:>10} | {d['waveNum']:4d} | "
          f"{d['avgFps']:7.1f} | {d['p1Fps']:6.1f} | "
          f"{d['frameCount']:4d} | {d['avgFrameTimeMs']:7.2f} | {d['maxFrameTimeMs']:7.2f} | "
          f"{d['wsCount']:5d} | {d['notifyCount']:6d} | {d['domMutCount']:7d} | "
          f"{d['setDataCount']:6d} | {d['consoleLogCount']:4d} | "
          f"{d['unitCount']:5d} | {d['hostileCount']:4d} | {d['friendlyCount']:4d}")


def _print_summary(data):
    all_fps = [d['avgFps'] for d in data]
    all_min = [d['minFps'] for d in data]
    all_ws = [d['wsCount'] for d in data]
    all_notify = [d['notifyCount'] for d in data]
    all_dom = [d['domMutCount'] for d in data]
    all_setdata = [d['setDataCount'] for d in data]
    all_logs = [d['consoleLogCount'] for d in data]
    all_units = [d['unitCount'] for d in data if d['unitCount'] > 0]
    all_hostile = [d['hostileCount'] for d in data if d['hostileCount'] > 0]

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Average FPS:          {sum(all_fps)/len(all_fps):.1f}")
    print(f"  Median FPS:           {sorted(all_fps)[len(all_fps)//2]:.1f}")
    print(f"  Minimum avg FPS:      {min(all_fps):.1f}")
    print(f"  Worst 1% FPS:         {min(d['p1Fps'] for d in data):.1f}")
    print(f"  Max frame time:       {max(d['maxFrameTimeMs'] for d in data):.1f}ms")
    print(f"  WS/store updates/sec: {sum(all_ws)/len(all_ws):.1f} avg, {max(all_ws)} max")
    print(f"  Store _notify/sec:    {sum(all_notify)/len(all_notify):.1f} avg, {max(all_notify)} max")
    print(f"  DOM mutations/sec:    {sum(all_dom)/len(all_dom):.0f} avg, {max(all_dom)} max")
    print(f"  setData calls/sec:    {sum(all_setdata)/len(all_setdata):.1f} avg, {max(all_setdata)} max")
    print(f"  console.log/sec:      {sum(all_logs)/len(all_logs):.1f} avg, {max(all_logs)} max")
    if all_units:
        print(f"  Units (avg):          {sum(all_units)/len(all_units):.0f}")
        print(f"  Units (max):          {max(all_units)}")
    if all_hostile:
        print(f"  Hostiles (avg):       {sum(all_hostile)/len(all_hostile):.0f}")
        print(f"  Hostiles (max):       {max(all_hostile)}")

    # Per-phase breakdown
    print("\n--- FPS by Game Phase ---")
    phases = {}
    for d in data:
        phase = d['gamePhase'] or 'unknown'
        if phase not in phases:
            phases[phase] = []
        phases[phase].append(d)
    for phase, items in sorted(phases.items()):
        fps_vals = [i['avgFps'] for i in items]
        ws_vals = [i['wsCount'] for i in items]
        dom_vals = [i['domMutCount'] for i in items]
        units_vals = [i['unitCount'] for i in items if i['unitCount'] > 0]
        print(f"  {phase:>12}: FPS={sum(fps_vals)/len(fps_vals):6.1f} avg, "
              f"{min(fps_vals):6.1f} min | "
              f"WS={sum(ws_vals)/len(ws_vals):5.1f}/s | "
              f"DOM={sum(dom_vals)/len(dom_vals):6.0f}/s | "
              f"Units={sum(units_vals)/len(units_vals):.0f}" if units_vals else "")


def _print_correlations(data):
    # Only look at seconds with active gameplay
    active = [d for d in data if d['gamePhase'] == 'active' and d['unitCount'] > 0]
    if len(active) < 4:
        print("\nNot enough active battle data for correlation analysis.")
        return

    all_fps = [d['avgFps'] for d in active]
    median_fps = sorted(all_fps)[len(all_fps) // 2]

    low_fps = [d for d in active if d['avgFps'] < median_fps]
    high_fps = [d for d in active if d['avgFps'] >= median_fps]

    if not low_fps or not high_fps:
        return

    print("\n" + "=" * 80)
    print("CORRELATION: LOW FPS vs HIGH FPS SECONDS (active battle only)")
    print("=" * 80)
    metrics = ['wsCount', 'notifyCount', 'domMutCount', 'setDataCount',
               'consoleLogCount', 'unitCount', 'hostileCount']
    for m in metrics:
        low_avg = sum(d[m] for d in low_fps) / len(low_fps)
        high_avg = sum(d[m] for d in high_fps) / len(high_fps)
        ratio = low_avg / high_avg if high_avg > 0 else float('inf')
        indicator = " <<<" if ratio > 1.5 else ""
        print(f"  {m:20s}: low_fps={low_avg:8.1f}  high_fps={high_avg:8.1f}  "
              f"ratio={ratio:.2f}x{indicator}")


if __name__ == "__main__":
    main()
