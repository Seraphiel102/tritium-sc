"""
Battle FPS Profiler — measures frame rate during active combat.

Opens a headed Chromium browser, starts a battle via API, and injects
a detailed FPS profiler that measures frame time, WebSocket message
rate, DOM mutation count, and GeoJSON update frequency throughout
60 seconds of active gameplay.

Run:
    .venv/bin/python3 tests/perf/profile_battle_fps.py
"""

import json
import time
import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
PROFILE_DURATION_S = 60


def main():
    # First reset game to setup state
    try:
        resp = requests.post(f"{BASE}/api/game/reset")
        print(f"[RESET] {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[RESET] Failed: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-gpu-vsync",  # remove 60fps vsync cap for true measurement
                "--disable-frame-rate-limit",
            ],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Navigate to command center
        print("[NAV] Opening Command Center...")
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)  # let map load

        # Inject FPS profiler
        print("[INJECT] Installing FPS profiler...")
        page.evaluate("""() => {
            window.__perfData = {
                frames: [],         // {time, dt, fps}
                wsMessages: [],     // {time, type, size}
                wsPerSecond: [],    // {time, count}
                geojsonUpdates: [], // {time, sourceName}
                domMutations: [],   // {time, count}
                unitCounts: [],     // {time, total, hostile, friendly}
                markerUpdates: [],  // {time, count}
                setDataCalls: [],   // {time, source}
                consoleLogCount: 0,
                startTime: performance.now(),
                secondBuckets: {},  // second -> {wsCount, domMutCount, geojsonCount, fps:[]}
            };

            // 1. Frame time profiler via requestAnimationFrame
            let lastFrameTime = performance.now();
            let frameCount = 0;
            function measureFrame() {
                const now = performance.now();
                const dt = now - lastFrameTime;
                const fps = dt > 0 ? 1000 / dt : 0;
                lastFrameTime = now;
                frameCount++;

                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);

                if (!window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec] = {
                        wsCount: 0, domMutCount: 0, geojsonCount: 0,
                        fps: [], frameTimes: [], consoleLogCount: 0,
                        unitCount: 0, hostileCount: 0, friendlyCount: 0,
                        setDataCount: 0, markerUpdateCount: 0,
                    };
                }
                window.__perfData.secondBuckets[sec].fps.push(fps);
                window.__perfData.secondBuckets[sec].frameTimes.push(dt);

                // Sample unit count every 10 frames
                if (frameCount % 10 === 0) {
                    try {
                        const store = window.TritiumStore;
                        if (store && store.units) {
                            let total = 0, hostile = 0, friendly = 0;
                            store.units.forEach(u => {
                                total++;
                                if (u.alliance === 'hostile') hostile++;
                                else if (u.alliance === 'friendly') friendly++;
                            });
                            window.__perfData.secondBuckets[sec].unitCount = total;
                            window.__perfData.secondBuckets[sec].hostileCount = hostile;
                            window.__perfData.secondBuckets[sec].friendlyCount = friendly;
                        }
                    } catch(e) {}
                }

                requestAnimationFrame(measureFrame);
            }
            requestAnimationFrame(measureFrame);

            // 2. WebSocket message interceptor
            const origWS = WebSocket;
            const origSend = WebSocket.prototype.send;
            // Intercept onmessage for existing connections
            // We need to monkey-patch the WebSocket to count messages
            const _origAddEventListener = EventTarget.prototype.addEventListener;

            // Patch all existing WebSockets' onmessage
            // More reliable: patch JSON.parse to count WS message processing
            const origJSONParse = JSON.parse;
            let wsParseCount = 0;
            // Can't easily distinguish WS parse from other parse, so use a different approach

            // Hook into the WebSocket constructor
            window._wsInstances = [];
            const OrigWebSocket = window.WebSocket;
            window.WebSocket = function(url, protocols) {
                const ws = protocols ? new OrigWebSocket(url, protocols) : new OrigWebSocket(url);
                window._wsInstances.push(ws);

                const origOnMessage = Object.getOwnPropertyDescriptor(OrigWebSocket.prototype, 'onmessage');

                // Wrap the message event
                ws.addEventListener('message', function(event) {
                    const now = performance.now();
                    const elapsed = (now - window.__perfData.startTime) / 1000;
                    const sec = Math.floor(elapsed);

                    if (!window.__perfData.secondBuckets[sec]) {
                        window.__perfData.secondBuckets[sec] = {
                            wsCount: 0, domMutCount: 0, geojsonCount: 0,
                            fps: [], frameTimes: [], consoleLogCount: 0,
                            unitCount: 0, hostileCount: 0, friendlyCount: 0,
                            setDataCount: 0, markerUpdateCount: 0,
                        };
                    }
                    window.__perfData.secondBuckets[sec].wsCount++;

                    // Parse the message to check its type and size
                    try {
                        const msg = JSON.parse(event.data);
                        const type = msg.type || msg.event || 'unknown';
                        const dataLen = event.data.length;
                        window.__perfData.wsMessages.push({
                            time: elapsed.toFixed(2),
                            type: type,
                            size: dataLen,
                        });
                        // Keep last 200 messages only
                        if (window.__perfData.wsMessages.length > 200) {
                            window.__perfData.wsMessages.shift();
                        }
                    } catch(e) {}
                });

                return ws;
            };
            window.WebSocket.prototype = OrigWebSocket.prototype;
            window.WebSocket.CONNECTING = OrigWebSocket.CONNECTING;
            window.WebSocket.OPEN = OrigWebSocket.OPEN;
            window.WebSocket.CLOSING = OrigWebSocket.CLOSING;
            window.WebSocket.CLOSED = OrigWebSocket.CLOSED;

            // 3. DOM Mutation observer on the map container
            const mapContainer = document.getElementById('tactical-area')
                || document.getElementById('maplibre-map')
                || document.body;
            const mutObserver = new MutationObserver((mutations) => {
                const now = performance.now();
                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);
                if (!window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec] = {
                        wsCount: 0, domMutCount: 0, geojsonCount: 0,
                        fps: [], frameTimes: [], consoleLogCount: 0,
                        unitCount: 0, hostileCount: 0, friendlyCount: 0,
                        setDataCount: 0, markerUpdateCount: 0,
                    };
                }
                window.__perfData.secondBuckets[sec].domMutCount += mutations.length;
            });
            mutObserver.observe(mapContainer, {
                childList: true,
                subtree: true,
                attributes: true,
                characterData: true,
            });

            // 4. Console.log counter in hot path
            const origLog = console.log;
            console.log = function() {
                const now = performance.now();
                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);
                if (window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec].consoleLogCount++;
                }
                window.__perfData.consoleLogCount++;
                return origLog.apply(console, arguments);
            };

            // 5. Intercept MapLibre setData calls
            // We need to find the map instance and wrap its source objects
            function hookSetData() {
                const mapState = window._mapState;
                if (!mapState || !mapState.map) {
                    setTimeout(hookSetData, 1000);
                    return;
                }
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
                            if (!window.__perfData.secondBuckets[sec]) {
                                window.__perfData.secondBuckets[sec] = {
                                    wsCount: 0, domMutCount: 0, geojsonCount: 0,
                                    fps: [], frameTimes: [], consoleLogCount: 0,
                                    unitCount: 0, hostileCount: 0, friendlyCount: 0,
                                    setDataCount: 0, markerUpdateCount: 0,
                                };
                            }
                            window.__perfData.secondBuckets[sec].setDataCount++;
                            window.__perfData.secondBuckets[sec].geojsonCount++;
                            return origSetData(data);
                        };
                        source._hooked = true;
                    }
                    return source;
                };
            }
            hookSetData();

            // 6. Count marker DOM updates (style.cssText writes on unit markers)
            // Observe the marker container
            function hookMarkerUpdates() {
                const mapState = window._mapState;
                if (!mapState) {
                    setTimeout(hookMarkerUpdates, 1000);
                    return;
                }
                // Create a periodic sampler that counts markers
                setInterval(() => {
                    const now = performance.now();
                    const elapsed = (now - window.__perfData.startTime) / 1000;
                    const sec = Math.floor(elapsed);
                    if (!window.__perfData.secondBuckets[sec]) return;

                    const markers = document.querySelectorAll('.tritium-unit-marker');
                    window.__perfData.secondBuckets[sec].markerUpdateCount = markers.length;
                }, 200);
            }
            hookMarkerUpdates();

            console.log('[PROFILER] FPS profiler installed');
        }""")

        # Wait for profiler to settle
        page.wait_for_timeout(2000)

        # Now we need the WebSocket to connect through the NEW constructor
        # Force a reconnect by reloading
        print("[RELOAD] Reloading page to intercept WebSocket...")
        page.reload(wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Re-inject the profiler after reload
        print("[INJECT] Re-installing FPS profiler after reload...")
        page.evaluate("""() => {
            window.__perfData = {
                frames: [],
                wsMessages: [],
                secondBuckets: {},
                consoleLogCount: 0,
                startTime: performance.now(),
            };

            // Frame time profiler
            let lastFrameTime = performance.now();
            let frameCount = 0;
            function measureFrame() {
                const now = performance.now();
                const dt = now - lastFrameTime;
                const fps = dt > 0 ? 1000 / dt : 0;
                lastFrameTime = now;
                frameCount++;

                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);

                if (!window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec] = {
                        wsCount: 0, domMutCount: 0, geojsonCount: 0,
                        fps: [], frameTimes: [], consoleLogCount: 0,
                        unitCount: 0, hostileCount: 0, friendlyCount: 0,
                        setDataCount: 0,
                    };
                }
                window.__perfData.secondBuckets[sec].fps.push(fps);
                window.__perfData.secondBuckets[sec].frameTimes.push(dt);

                if (frameCount % 10 === 0) {
                    try {
                        const store = window.TritiumStore;
                        if (store && store.units) {
                            let total = 0, hostile = 0, friendly = 0;
                            store.units.forEach(u => {
                                total++;
                                if (u.alliance === 'hostile') hostile++;
                                else if (u.alliance === 'friendly') friendly++;
                            });
                            window.__perfData.secondBuckets[sec].unitCount = total;
                            window.__perfData.secondBuckets[sec].hostileCount = hostile;
                            window.__perfData.secondBuckets[sec].friendlyCount = friendly;
                        }
                    } catch(e) {}
                }

                requestAnimationFrame(measureFrame);
            }
            requestAnimationFrame(measureFrame);

            // DOM Mutation observer
            const mapContainer = document.getElementById('tactical-area')
                || document.getElementById('maplibre-map')
                || document.body;
            const mutObserver = new MutationObserver((mutations) => {
                const now = performance.now();
                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);
                if (!window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec] = {
                        wsCount: 0, domMutCount: 0, geojsonCount: 0,
                        fps: [], frameTimes: [], consoleLogCount: 0,
                        unitCount: 0, hostileCount: 0, friendlyCount: 0,
                        setDataCount: 0,
                    };
                }
                window.__perfData.secondBuckets[sec].domMutCount += mutations.length;
            });
            mutObserver.observe(mapContainer, {
                childList: true,
                subtree: true,
                attributes: true,
                characterData: true,
            });

            // Console.log counter
            const origLog = console.log;
            console.log = function() {
                const now = performance.now();
                const elapsed = (now - window.__perfData.startTime) / 1000;
                const sec = Math.floor(elapsed);
                if (window.__perfData.secondBuckets[sec]) {
                    window.__perfData.secondBuckets[sec].consoleLogCount++;
                }
                window.__perfData.consoleLogCount++;
                return origLog.apply(console, arguments);
            };

            // Hook MapLibre setData calls
            function hookSetData() {
                const mapState = window._mapState;
                if (!mapState || !mapState.map) {
                    setTimeout(hookSetData, 500);
                    return;
                }
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
                            if (!window.__perfData.secondBuckets[sec]) {
                                window.__perfData.secondBuckets[sec] = {
                                    wsCount: 0, domMutCount: 0, geojsonCount: 0,
                                    fps: [], frameTimes: [], consoleLogCount: 0,
                                    unitCount: 0, hostileCount: 0, friendlyCount: 0,
                                    setDataCount: 0,
                                };
                            }
                            window.__perfData.secondBuckets[sec].setDataCount++;
                            window.__perfData.secondBuckets[sec].geojsonCount++;
                            return origSetData(data);
                        };
                        source._hooked = true;
                    }
                    return source;
                };
            }
            hookSetData();

            // WebSocket message counter — hook onmessage via prototype
            // The WS is already connected, so we wrap onmessage
            function hookWS() {
                const wsEl = document.querySelector('[data-ws]');
                // Try to find the existing WS instance
                // Check if there's a global reference
                const checkInterval = setInterval(() => {
                    // Look for WS connections in the page
                    try {
                        // The WebSocketManager stores _ws on the instance
                        // Check performance entries for WS
                        const perfEntries = performance.getEntriesByType('resource')
                            .filter(e => e.name.includes('ws/live'));
                        if (perfEntries.length > 0) {
                            clearInterval(checkInterval);
                        }
                    } catch(e) {}
                }, 500);
            }

            // Alternative: Monitor WS activity through a message event listener on window
            // This works because MessageEvent propagates
            // Actually, WS messages DON'T propagate to window. We need to intercept differently.

            // Best approach: intercept the WebSocketManager._handleMessage method
            // by wrapping TritiumStore.updateUnit
            const origUpdateUnit = window.TritiumStore?.updateUnit?.bind(window.TritiumStore);
            if (origUpdateUnit) {
                let updateCount = 0;
                window.TritiumStore.updateUnit = function(id, data) {
                    updateCount++;
                    const now = performance.now();
                    const elapsed = (now - window.__perfData.startTime) / 1000;
                    const sec = Math.floor(elapsed);
                    if (window.__perfData.secondBuckets[sec]) {
                        window.__perfData.secondBuckets[sec].wsCount++;
                    }
                    return origUpdateUnit(id, data);
                };
            }

            console.log('[PROFILER] FPS profiler re-installed');
        }""")

        page.wait_for_timeout(2000)

        # Measure idle FPS for 5 seconds first
        print("[IDLE] Measuring idle FPS for 5 seconds...")
        page.wait_for_timeout(5000)

        idle_data = page.evaluate("""() => {
            const buckets = window.__perfData.secondBuckets;
            const result = [];
            for (const [sec, data] of Object.entries(buckets)) {
                if (data.fps.length > 0) {
                    const avgFps = data.fps.reduce((a,b) => a+b, 0) / data.fps.length;
                    result.push({
                        second: parseInt(sec),
                        avgFps: Math.round(avgFps * 10) / 10,
                        frameCount: data.fps.length,
                        wsCount: data.wsCount,
                        domMutCount: data.domMutCount,
                        setDataCount: data.setDataCount || 0,
                        consoleLogCount: data.consoleLogCount || 0,
                    });
                }
            }
            return result;
        }""")

        print("\n=== IDLE FPS (before battle) ===")
        for d in sorted(idle_data, key=lambda x: x['second']):
            print(f"  sec {d['second']:3d}: FPS={d['avgFps']:6.1f}  frames={d['frameCount']:3d}  "
                  f"ws={d['wsCount']:4d}  domMut={d['domMutCount']:5d}  "
                  f"setData={d['setDataCount']:3d}  consoleLogs={d['consoleLogCount']:3d}")

        # Reset profiler data
        page.evaluate("""() => {
            window.__perfData.secondBuckets = {};
            window.__perfData.startTime = performance.now();
            window.__perfData.consoleLogCount = 0;
        }""")

        # Start the battle via API
        print("\n[BATTLE] Starting battle via POST /api/game/begin ...")
        try:
            resp = requests.post(f"{BASE}/api/game/begin")
            print(f"[BATTLE] Response: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[BATTLE] Failed: {e}")
            # Try reset first then begin
            requests.post(f"{BASE}/api/game/reset")
            time.sleep(1)
            resp = requests.post(f"{BASE}/api/game/begin")
            print(f"[BATTLE] Retry response: {resp.status_code} {resp.text[:200]}")

        # Let the battle run for PROFILE_DURATION_S seconds
        print(f"\n[PROFILE] Recording battle FPS for {PROFILE_DURATION_S} seconds...")
        for i in range(PROFILE_DURATION_S):
            time.sleep(1)
            if (i + 1) % 10 == 0:
                # Quick progress check
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
                        wsPerSec: latest.wsCount || 0,
                        domMut: latest.domMutCount || 0,
                        setData: latest.setDataCount || 0,
                    };
                }""")
                if quick:
                    print(f"  [{i+1:3d}s] FPS={quick['fps']}  units={quick['units']}  "
                          f"hostile={quick['hostile']}  ws/s={quick['wsPerSec']}  "
                          f"domMut/s={quick['domMut']}  setData/s={quick['setData']}")

        # Collect final profiling data
        print("\n[COLLECT] Gathering profiling data...")
        battle_data = page.evaluate("""() => {
            const buckets = window.__perfData.secondBuckets;
            const result = [];
            for (const [sec, data] of Object.entries(buckets)) {
                if (data.fps.length > 0) {
                    const fpsArr = data.fps;
                    const avgFps = fpsArr.reduce((a,b) => a+b, 0) / fpsArr.length;
                    const minFps = Math.min(...fpsArr);
                    const maxFps = Math.max(...fpsArr);
                    const p1 = fpsArr.sort((a,b) => a-b)[Math.floor(fpsArr.length * 0.01)] || 0;
                    const avgFrameTime = data.frameTimes && data.frameTimes.length > 0
                        ? data.frameTimes.reduce((a,b) => a+b, 0) / data.frameTimes.length
                        : 0;
                    const maxFrameTime = data.frameTimes && data.frameTimes.length > 0
                        ? Math.max(...data.frameTimes)
                        : 0;
                    result.push({
                        second: parseInt(sec),
                        avgFps: Math.round(avgFps * 10) / 10,
                        minFps: Math.round(minFps * 10) / 10,
                        maxFps: Math.round(maxFps * 10) / 10,
                        p1Fps: Math.round(p1 * 10) / 10,
                        frameCount: fpsArr.length,
                        avgFrameTimeMs: Math.round(avgFrameTime * 100) / 100,
                        maxFrameTimeMs: Math.round(maxFrameTime * 100) / 100,
                        wsCount: data.wsCount || 0,
                        domMutCount: data.domMutCount || 0,
                        setDataCount: data.setDataCount || 0,
                        geojsonCount: data.geojsonCount || 0,
                        consoleLogCount: data.consoleLogCount || 0,
                        unitCount: data.unitCount || 0,
                        hostileCount: data.hostileCount || 0,
                        friendlyCount: data.friendlyCount || 0,
                    });
                }
            }
            return result.sort((a,b) => a.second - b.second);
        }""")

        # Also get total console.log count
        total_console_logs = page.evaluate("() => window.__perfData.consoleLogCount")

        # Get the latest WebSocket message sample
        ws_sample = page.evaluate("""() => {
            // Count message types from recent messages
            const msgs = window.__perfData.wsMessages || [];
            const typeCounts = {};
            for (const m of msgs) {
                typeCounts[m.type] = (typeCounts[m.type] || 0) + 1;
            }
            return {
                total: msgs.length,
                typeCounts,
                sampleMessages: msgs.slice(-10),
            };
        }""")

        # Print results
        print("\n" + "=" * 120)
        print("BATTLE FPS PROFILE RESULTS")
        print("=" * 120)
        print(f"{'Sec':>4} | {'AvgFPS':>7} | {'MinFPS':>7} | {'1%FPS':>6} | {'Frames':>6} | "
              f"{'AvgMS':>7} | {'MaxMS':>7} | {'WS/s':>5} | {'DOMmut':>7} | "
              f"{'setData':>7} | {'Logs':>5} | {'Units':>5} | {'Host':>4} | {'Fri':>4}")
        print("-" * 120)

        for d in battle_data:
            print(f"{d['second']:4d} | {d['avgFps']:7.1f} | {d['minFps']:7.1f} | "
                  f"{d['p1Fps']:6.1f} | {d['frameCount']:6d} | "
                  f"{d['avgFrameTimeMs']:7.2f} | {d['maxFrameTimeMs']:7.2f} | "
                  f"{d['wsCount']:5d} | {d['domMutCount']:7d} | "
                  f"{d['setDataCount']:7d} | {d['consoleLogCount']:5d} | "
                  f"{d['unitCount']:5d} | {d['hostileCount']:4d} | {d['friendlyCount']:4d}")

        print(f"\nTotal console.log calls during battle: {total_console_logs}")

        # Summary statistics
        if battle_data:
            all_fps = [d['avgFps'] for d in battle_data]
            all_min = [d['minFps'] for d in battle_data]
            all_ws = [d['wsCount'] for d in battle_data]
            all_dom = [d['domMutCount'] for d in battle_data]
            all_setdata = [d['setDataCount'] for d in battle_data]
            all_logs = [d['consoleLogCount'] for d in battle_data]
            all_units = [d['unitCount'] for d in battle_data if d['unitCount'] > 0]

            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"  Average FPS:        {sum(all_fps)/len(all_fps):.1f}")
            print(f"  Median FPS:         {sorted(all_fps)[len(all_fps)//2]:.1f}")
            print(f"  Minimum avg FPS:    {min(all_fps):.1f}")
            print(f"  Worst 1% FPS:       {min(d['p1Fps'] for d in battle_data):.1f}")
            print(f"  Max frame time:     {max(d['maxFrameTimeMs'] for d in battle_data):.1f}ms")
            print(f"  WS msgs/sec (avg):  {sum(all_ws)/len(all_ws):.1f}")
            print(f"  WS msgs/sec (max):  {max(all_ws)}")
            print(f"  DOM mutations/sec:  {sum(all_dom)/len(all_dom):.0f} avg, {max(all_dom)} max")
            print(f"  setData calls/sec:  {sum(all_setdata)/len(all_setdata):.1f} avg, {max(all_setdata)} max")
            print(f"  console.log/sec:    {sum(all_logs)/len(all_logs):.1f} avg, {max(all_logs)} max")
            if all_units:
                print(f"  Units (avg):        {sum(all_units)/len(all_units):.0f}")
                print(f"  Units (max):        {max(all_units)}")

            # Correlation analysis: find which metric correlates with low FPS
            print("\n" + "=" * 80)
            print("CORRELATION: LOW FPS SECONDS vs METRICS")
            print("=" * 80)

            # Split into low and high FPS groups
            median_fps = sorted(all_fps)[len(all_fps)//2]
            low_fps = [d for d in battle_data if d['avgFps'] < median_fps]
            high_fps = [d for d in battle_data if d['avgFps'] >= median_fps]

            if low_fps and high_fps:
                metrics = ['wsCount', 'domMutCount', 'setDataCount', 'consoleLogCount', 'unitCount']
                for m in metrics:
                    low_avg = sum(d[m] for d in low_fps) / len(low_fps)
                    high_avg = sum(d[m] for d in high_fps) / len(high_fps)
                    ratio = low_avg / high_avg if high_avg > 0 else float('inf')
                    print(f"  {m:20s}: low_fps_avg={low_avg:8.1f}  high_fps_avg={high_avg:8.1f}  ratio={ratio:.2f}x")

        print("\nWebSocket message type distribution:")
        if ws_sample and ws_sample.get('typeCounts'):
            for t, c in sorted(ws_sample['typeCounts'].items(), key=lambda x: -x[1]):
                print(f"  {t:35s}: {c}")

        # Save raw data as JSON
        output_path = "/home/scubasonar/Code/tritium-sc/tests/perf/battle_fps_profile.json"
        with open(output_path, "w") as f:
            json.dump({
                "battle_data": battle_data,
                "idle_data": idle_data,
                "total_console_logs": total_console_logs,
                "ws_sample": ws_sample,
            }, f, indent=2)
        print(f"\n[SAVED] Raw data saved to {output_path}")

        # Keep browser open for a moment so user can see
        print("\n[DONE] Closing browser in 5 seconds...")
        page.wait_for_timeout(5000)

        browser.close()


if __name__ == "__main__":
    main()
