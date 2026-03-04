"""
Battle FPS Profiler v3 — measures frame rate during active combat.

Uses street_combat scenario which has defenders + multiple waves.
Injects profiler before page load via addInitScript.

Run:
    .venv/bin/python3 tests/perf/profile_battle_fps_v3.py
"""

import json
import time
import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
PROFILE_DURATION_S = 120  # 2 minutes to capture multiple waves
SCENARIO = "street_combat"

PROFILER_SCRIPT = """
window.__perfData = {
    secondBuckets: {},
    consoleLogCount: 0,
    startTime: performance.now(),
    updateUnitCalls: 0,
    notifyCalls: 0,
};

function _getBucket(sec) {
    if (!window.__perfData.secondBuckets[sec]) {
        window.__perfData.secondBuckets[sec] = {
            wsCount: 0, domMutCount: 0, geojsonCount: 0,
            fps: [], frameTimes: [], consoleLogCount: 0,
            unitCount: 0, hostileCount: 0, friendlyCount: 0,
            setDataCount: 0, updateUnitCount: 0, notifyCount: 0,
            gamePhase: '', waveNum: 0, markerCount: 0,
            threeEffectCount: 0,
        };
    }
    return window.__perfData.secondBuckets[sec];
}

// Frame time profiler
let _lastFrameTime = performance.now();
function _measureFrame() {
    const now = performance.now();
    const dt = now - _lastFrameTime;
    const fps = dt > 0 ? 1000 / dt : 0;
    _lastFrameTime = now;
    const elapsed = (now - window.__perfData.startTime) / 1000;
    const sec = Math.floor(elapsed);
    const b = _getBucket(sec);
    b.fps.push(fps);
    b.frameTimes.push(dt);
    requestAnimationFrame(_measureFrame);
}
requestAnimationFrame(_measureFrame);

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
        // Count DOM markers
        const markers = document.querySelectorAll('.tritium-unit-marker');
        b.markerCount = markers.length;
        // Count 3D effects
        const mapState = window._mapState;
        if (mapState && mapState.effects) {
            b.threeEffectCount = mapState.effects.length;
        }
    } catch(e) {}
}, 200);

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

window.__perfHookDOMMutations = function() {
    const target = document.getElementById('tactical-area')
        || document.getElementById('maplibre-map')
        || document.body;
    new MutationObserver((mutations) => {
        const now = performance.now();
        const elapsed = (now - window.__perfData.startTime) / 1000;
        const sec = Math.floor(elapsed);
        _getBucket(sec).domMutCount += mutations.length;
    }).observe(target, {
        childList: true, subtree: true,
        attributes: true, characterData: true,
    });
};

window.__perfHookStore = function() {
    if (!window.TritiumStore) return false;
    const store = window.TritiumStore;
    const origUpdateUnit = store.updateUnit.bind(store);
    store.updateUnit = function(id, data) {
        const now = performance.now();
        const elapsed = (now - window.__perfData.startTime) / 1000;
        const sec = Math.floor(elapsed);
        const b = _getBucket(sec);
        b.updateUnitCount++;
        b.wsCount++;
        window.__perfData.updateUnitCalls++;
        return origUpdateUnit(id, data);
    };
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
    # Reset game
    print(f"[RESET] Resetting game...")
    requests.post(f"{BASE}/api/game/reset")
    time.sleep(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-gpu-vsync", "--disable-frame-rate-limit"],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Inject profiler before page load
        page.add_init_script(script=PROFILER_SCRIPT)

        # Navigate
        print("[NAV] Opening Command Center...")
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Connect hooks
        print("[HOOK] Connecting hooks...")
        page.evaluate("() => window.__perfHookDOMMutations()")
        for attempt in range(10):
            if page.evaluate("() => window.__perfHookStore()"):
                print(f"  Store hooked (attempt {attempt + 1})")
                break
            page.wait_for_timeout(500)

        for attempt in range(10):
            if page.evaluate("() => window.__perfHookSetData()"):
                print(f"  SetData hooked (attempt {attempt + 1})")
                break
            page.wait_for_timeout(500)

        # Reset profiler baseline
        page.evaluate("""() => {
            window.__perfData.secondBuckets = {};
            window.__perfData.startTime = performance.now();
            window.__perfData.consoleLogCount = 0;
            window.__perfData.updateUnitCalls = 0;
            window.__perfData.notifyCalls = 0;
        }""")

        # Start battle scenario
        print(f"\n[BATTLE] Starting {SCENARIO} scenario...")
        resp = requests.post(f"{BASE}/api/game/battle/{SCENARIO}")
        print(f"  Response: {resp.status_code} {resp.text[:200]}")

        # Profile for PROFILE_DURATION_S seconds
        print(f"\n[PROFILE] Recording for {PROFILE_DURATION_S}s...")
        for i in range(PROFILE_DURATION_S):
            time.sleep(1)
            if (i + 1) % 5 == 0:
                quick = page.evaluate("""() => {
                    const buckets = window.__perfData.secondBuckets;
                    const keys = Object.keys(buckets).map(Number).sort((a,b) => b-a);
                    if (keys.length === 0) return null;
                    const latest = buckets[keys[0]];
                    const avgFps = latest.fps.length > 0
                        ? (latest.fps.reduce((a,b) => a+b, 0) / latest.fps.length).toFixed(1) : '?';
                    return {
                        sec: keys[0], fps: avgFps,
                        units: latest.unitCount || 0,
                        hostile: latest.hostileCount || 0,
                        friendly: latest.friendlyCount || 0,
                        ws: latest.updateUnitCount || latest.wsCount || 0,
                        dom: latest.domMutCount || 0,
                        sd: latest.setDataCount || 0,
                        notify: latest.notifyCount || 0,
                        logs: latest.consoleLogCount || 0,
                        phase: latest.gamePhase || '?',
                        wave: latest.waveNum || 0,
                        markers: latest.markerCount || 0,
                        effects: latest.threeEffectCount || 0,
                    };
                }""")
                if quick:
                    print(f"  [{i+1:3d}s] FPS={quick['fps']:>7}  {quick['phase']:>10} w{quick['wave']}  "
                          f"units={quick['units']:>3}(H:{quick['hostile']} F:{quick['friendly']})  "
                          f"ws={quick['ws']:>4}  dom={quick['dom']:>5}  sd={quick['sd']:>3}  "
                          f"notify={quick['notify']:>4}  markers={quick['markers']:>3}  "
                          f"fx3d={quick['effects']:>2}  logs={quick['logs']:>3}")

        # Collect data
        print("\n[COLLECT] Gathering data...")
        battle_data = page.evaluate("""() => {
            const buckets = window.__perfData.secondBuckets;
            const result = [];
            for (const [sec, data] of Object.entries(buckets)) {
                if (data.fps.length === 0) continue;
                const fpsArr = data.fps.slice().sort((a,b) => a-b);
                const avgFps = fpsArr.reduce((a,b) => a+b, 0) / fpsArr.length;
                const avgFrameTime = data.frameTimes.length > 0
                    ? data.frameTimes.reduce((a,b) => a+b, 0) / data.frameTimes.length : 0;
                const maxFrameTime = data.frameTimes.length > 0
                    ? Math.max(...data.frameTimes) : 0;
                result.push({
                    second: parseInt(sec),
                    avgFps: Math.round(avgFps * 10) / 10,
                    minFps: Math.round((fpsArr[0] || 0) * 10) / 10,
                    p1Fps: Math.round((fpsArr[Math.floor(fpsArr.length * 0.01)] || 0) * 10) / 10,
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
                    markerCount: data.markerCount || 0,
                    threeEffectCount: data.threeEffectCount || 0,
                });
            }
            return result.sort((a,b) => a.second - b.second);
        }""")

        total_updates = page.evaluate("() => window.__perfData.updateUnitCalls")
        total_notify = page.evaluate("() => window.__perfData.notifyCalls")
        total_logs = page.evaluate("() => window.__perfData.consoleLogCount")

        # Print results
        print("\n" + "=" * 160)
        print("BATTLE FPS PROFILE — " + SCENARIO.upper())
        print("=" * 160)
        hdr = (f"{'Sec':>4} | {'Phase':>10} | {'W':>2} | {'AvgFPS':>7} | {'1%FPS':>6} | "
               f"{'Frms':>4} | {'AvgMS':>7} | {'MaxMS':>7} | "
               f"{'WS/s':>5} | {'Notfy':>5} | {'DOM':>6} | "
               f"{'sData':>5} | {'Logs':>4} | {'Units':>5} | {'H':>3} | {'F':>3} | "
               f"{'Mkrs':>4} | {'FX':>3}")
        print(hdr)
        print("-" * 160)

        for d in battle_data:
            print(f"{d['second']:4d} | {d['gamePhase']:>10} | {d['waveNum']:2d} | "
                  f"{d['avgFps']:7.1f} | {d['p1Fps']:6.1f} | "
                  f"{d['frameCount']:4d} | {d['avgFrameTimeMs']:7.2f} | {d['maxFrameTimeMs']:7.2f} | "
                  f"{d['wsCount']:5d} | {d['notifyCount']:5d} | {d['domMutCount']:6d} | "
                  f"{d['setDataCount']:5d} | {d['consoleLogCount']:4d} | "
                  f"{d['unitCount']:5d} | {d['hostileCount']:3d} | {d['friendlyCount']:3d} | "
                  f"{d['markerCount']:4d} | {d['threeEffectCount']:3d}")

        print(f"\nTotal updateUnit: {total_updates}  _notify: {total_notify}  console.log: {total_logs}")

        # Summary by phase
        if battle_data:
            phases = {}
            for d in battle_data:
                ph = d['gamePhase'] or 'unknown'
                phases.setdefault(ph, []).append(d)

            print("\n" + "=" * 100)
            print("SUMMARY BY PHASE")
            print("=" * 100)
            for ph, items in sorted(phases.items()):
                fps_vals = [i['avgFps'] for i in items]
                ws_vals = [i['wsCount'] for i in items]
                dom_vals = [i['domMutCount'] for i in items]
                sd_vals = [i['setDataCount'] for i in items]
                notify_vals = [i['notifyCount'] for i in items]
                units_vals = [i['unitCount'] for i in items if i['unitCount'] > 0]
                hostile_vals = [i['hostileCount'] for i in items if i['hostileCount'] > 0]
                logs_vals = [i['consoleLogCount'] for i in items]
                dur = len(items)
                avg_fps = sum(fps_vals) / len(fps_vals) if fps_vals else 0
                min_fps = min(fps_vals) if fps_vals else 0
                print(f"  {ph:>14} ({dur:3d}s): "
                      f"FPS={avg_fps:6.1f} avg {min_fps:6.1f} min | "
                      f"WS={sum(ws_vals)/dur:6.1f}/s | "
                      f"DOM={sum(dom_vals)/dur:6.0f}/s | "
                      f"setData={sum(sd_vals)/dur:5.1f}/s | "
                      f"notify={sum(notify_vals)/dur:5.1f}/s | "
                      f"logs={sum(logs_vals)/dur:4.1f}/s | "
                      f"units={sum(units_vals)/len(units_vals):.0f}" if units_vals else f"  {ph:>14} ({dur:3d}s): FPS={avg_fps:6.1f}")

            # Correlation for active phase
            active = [d for d in battle_data if d['gamePhase'] == 'active']
            if len(active) >= 4:
                all_fps = [d['avgFps'] for d in active]
                med_fps = sorted(all_fps)[len(all_fps)//2]
                low = [d for d in active if d['avgFps'] < med_fps]
                high = [d for d in active if d['avgFps'] >= med_fps]

                if low and high:
                    print("\n" + "=" * 100)
                    print("CORRELATION: LOW vs HIGH FPS (active phase only)")
                    print("=" * 100)
                    for m in ['wsCount', 'notifyCount', 'domMutCount', 'setDataCount',
                              'consoleLogCount', 'unitCount', 'hostileCount', 'markerCount',
                              'threeEffectCount']:
                        la = sum(d[m] for d in low) / len(low)
                        ha = sum(d[m] for d in high) / len(high)
                        r = la / ha if ha > 0 else float('inf')
                        flag = " <<<" if r > 1.5 else ""
                        print(f"  {m:20s}: low={la:8.1f}  high={ha:8.1f}  ratio={r:.2f}x{flag}")

        # Save
        output = "/home/scubasonar/Code/tritium-sc/tests/perf/battle_fps_v3.json"
        with open(output, "w") as f:
            json.dump({"battle_data": battle_data, "scenario": SCENARIO,
                       "total_updates": total_updates, "total_notify": total_notify,
                       "total_logs": total_logs}, f, indent=2)
        print(f"\n[SAVED] {output}")

        print("\n[DONE] Closing in 3s...")
        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()
