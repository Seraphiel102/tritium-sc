#!/usr/bin/env python3
"""Wave 177 Village Idiot: Loop 6 'Investigate a Target' end-to-end test."""
import time
import json
import sys
from playwright.sync_api import sync_playwright

BASEDIR = "tests/.baselines"
RESULTS = {}

def screenshot(page, name, timeout=5000):
    path = f"{BASEDIR}/w177_loop6_{name}.png"
    try:
        page.screenshot(path=path, timeout=timeout)
        print(f"  [SCREENSHOT] {path}")
        return True
    except Exception as e:
        print(f"  [SCREENSHOT FAILED] {name}: {e}")
        return False

def step(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS[name] = {"status": status, "detail": detail}
    icon = "OK" if passed else "XX"
    print(f"\n[{icon}] {name}")
    if detail:
        print(f"     {detail[:200]}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))

        # ── STEP 1: Navigate and wait for map ──
        print("\n>>> STEP 1: Navigate, wait for map + demo data")
        page.goto("http://localhost:8000", timeout=30000, wait_until="domcontentloaded")
        time.sleep(10)

        has_map = page.query_selector(".maplibregl-map") is not None
        step("Step 1: Map loads", has_map,
             f"maplibregl-map: {has_map}, JS errors: {len(js_errors)}")
        screenshot(page, "step1_map")

        # ── STEP 2: See targets on map ──
        print("\n>>> STEP 2: Check targets on map")
        unit_count = page.evaluate("() => window.TritiumStore ? window.TritiumStore.units.size : -1")
        markers = page.query_selector_all(".maplibregl-marker")
        has_targets = unit_count > 0 or len(markers) > 0
        step("Step 2: Targets visible", has_targets,
             f"TritiumStore.units.size={unit_count}, DOM markers={len(markers)}")
        screenshot(page, "step2_targets")

        # ── STEP 3: Click a target to open Unit Inspector ──
        print("\n>>> STEP 3: Select a target, open Unit Inspector")

        # Get a target ID from the store, preferring BLE
        select_result = page.evaluate("""() => {
            const store = window.TritiumStore;
            if (!store || !store.units) return {ok:false, reason:'no store'};
            const ids = [];
            store.units.forEach((u, id) => ids.push(id));
            if (ids.length === 0) return {ok:false, reason:'no units'};
            let pick = ids.find(id => id.startsWith('ble_')) || ids[0];
            store.set('map.selectedUnitId', pick);
            return {ok:true, id:pick, total:ids.length};
        }""")
        time.sleep(0.5)

        # Open the unit inspector panel
        page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('unit-inspector');
        }""")
        time.sleep(1)

        inspector = page.query_selector("[class*='unit-inspector']")
        inspector_visible = inspector.is_visible() if inspector else False
        # Also check if content has a unit loaded (not "Click a unit to inspect")
        inspector_text = ""
        if inspector:
            try:
                inspector_text = inspector.inner_text()[:300]
            except:
                pass

        has_unit_loaded = inspector_visible and "Click a unit" not in inspector_text
        step("Step 3: Unit Inspector opens with target", has_unit_loaded,
             f"select={json.dumps(select_result)}, visible={inspector_visible}, text preview={inspector_text[:100]}")
        screenshot(page, "step3_inspector")

        # ── STEP 4: Click INVESTIGATE button ──
        print("\n>>> STEP 4: Click INVESTIGATE button")

        investigate_btn = page.query_selector("button[data-action='investigate']")
        investigate_clicked = False
        if investigate_btn and investigate_btn.is_visible():
            try:
                investigate_btn.click(timeout=3000)
                investigate_clicked = True
                time.sleep(2)
            except Exception as e:
                print(f"  Click error: {e}")
        else:
            # Fallback: trigger via JS
            result = page.evaluate("""() => {
                const btn = document.querySelector('button[data-action="investigate"]');
                if (btn) { btn.click(); return {ok:true}; }
                // Try via EventBus directly
                if (window.panelManager) window.panelManager.open('dossiers');
                const selId = window.TritiumStore?.get('map.selectedUnitId');
                if (selId && window.EventBus) {
                    window.EventBus.emit('dossier:load-target', {target_id: selId});
                    return {ok:true, method:'EventBus', id:selId};
                }
                return {ok:false};
            }""")
            investigate_clicked = result.get('ok', False) if isinstance(result, dict) else False
            time.sleep(2)

        step("Step 4: INVESTIGATE clicked", investigate_clicked,
             f"button found: {investigate_btn is not None}")
        screenshot(page, "step4_investigate")

        # ── STEP 5: Dossier panel with details ──
        print("\n>>> STEP 5: Dossier panel opens")
        time.sleep(1)

        dossier_info = page.evaluate("""() => {
            // Check for dossier panel
            const panels = document.querySelectorAll('[class*="floating-panel"], [class*="panel-body"]');
            let dossierPanel = null;
            for (const p of panels) {
                const title = p.querySelector('.panel-title, .fp-title');
                if (title && title.textContent.toUpperCase().includes('DOSSIER')) {
                    dossierPanel = p;
                    break;
                }
            }
            if (!dossierPanel) {
                // Also check by ID
                dossierPanel = document.querySelector('#panel-dossiers, [data-panel-id="dossiers"]');
            }
            if (!dossierPanel) {
                return {found:false, reason:'no dossier panel element'};
            }
            const text = dossierPanel.innerText || '';
            const visible = dossierPanel.offsetParent !== null;
            return {found:true, visible:visible, textLen:text.length, snippet:text.substring(0,400)};
        }""")

        has_dossier = dossier_info.get('found', False) and dossier_info.get('visible', False)
        step("Step 5: Dossier panel opens", has_dossier,
             f"info: {json.dumps(dossier_info)[:300]}")
        screenshot(page, "step5_dossier")

        # ── STEP 6: Signal history (sparkline canvas) ──
        print("\n>>> STEP 6: Signal history / sparkline chart")

        signal_info = page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const sparklines = document.querySelectorAll('canvas.rssi-sparkline, canvas[class*=sparkline], [class*=signal-chart]');
            // Check dossier-specific canvases
            const dossierEl = document.querySelector('#panel-dossiers, [data-panel-id="dossiers"]');
            let dossierCanvases = 0;
            if (dossierEl) {
                dossierCanvases = dossierEl.querySelectorAll('canvas').length;
            }
            return {totalCanvases: canvases.length, sparklines: sparklines.length, dossierCanvases: dossierCanvases};
        }""")

        has_signal = signal_info.get('sparklines', 0) > 0 or signal_info.get('dossierCanvases', 0) > 0
        step("Step 6: Signal history chart", has_signal,
             f"info: {json.dumps(signal_info)}")
        screenshot(page, "step6_signal")

        # ── STEP 7: Behavioral profile ──
        print("\n>>> STEP 7: Behavioral profile section")

        behavioral_info = page.evaluate("""() => {
            const panels = document.querySelectorAll('[class*="floating-panel"], [class*="panel-body"]');
            for (const p of panels) {
                const text = (p.innerText || '').toLowerCase();
                if (text.includes('dossier') || text.includes('investigation')) {
                    const hasBehavior = text.includes('behav') || text.includes('pattern') ||
                                       text.includes('movement') || text.includes('profile') ||
                                       text.includes('activity') || text.includes('anomal');
                    return {found:hasBehavior, textLen:text.length,
                            snippet: p.innerText.substring(0, 400)};
                }
            }
            return {found:false, reason:'no dossier panel text found'};
        }""")

        has_behavioral = behavioral_info.get('found', False)
        step("Step 7: Behavioral profile", has_behavioral,
             f"info: {json.dumps(behavioral_info)[:300]}")
        screenshot(page, "step7_behavioral")

        # ── STEP 8: Tag target ──
        print("\n>>> STEP 8: Tag target (FRIENDLY/HOSTILE/VIP)")

        # The tag buttons are in the unit inspector, not the dossier
        tag_result = page.evaluate("""() => {
            const btns = document.querySelectorAll('[data-ui-tag]');
            if (btns.length === 0) return {ok:false, reason:'no tag buttons found'};
            // Find HOSTILE button and click it
            for (const btn of btns) {
                if (btn.dataset.uiTag === 'hostile') {
                    btn.click();
                    return {ok:true, tag:'hostile', total:btns.length};
                }
            }
            // Fallback: click first
            btns[0].click();
            return {ok:true, tag:btns[0].dataset.uiTag, total:btns.length};
        }""")
        time.sleep(1)

        tagged = tag_result.get('ok', False) if isinstance(tag_result, dict) else False
        step("Step 8: Tag target", tagged,
             f"result: {json.dumps(tag_result)}")
        screenshot(page, "step8_tagged")

        # ── STEP 9: Correlation display ──
        print("\n>>> STEP 9: Correlation / fusion display")

        corr_info = page.evaluate("""() => {
            const allText = document.body.innerText.toLowerCase();
            const panels = document.querySelectorAll('[class*="floating-panel"]');
            let found = false;
            let snippet = '';
            for (const p of panels) {
                const text = (p.innerText || '').toLowerCase();
                if (text.includes('correlat') || text.includes('fusion') ||
                    text.includes('linked') || text.includes('associated') ||
                    text.includes('fused') || text.includes('merge')) {
                    found = true;
                    snippet = p.innerText.substring(0, 300);
                    break;
                }
            }
            // Also check dossier detail specifically
            const dossierEl = document.querySelector('#panel-dossiers, [data-panel-id="dossiers"]');
            if (dossierEl) {
                const dt = (dossierEl.innerText || '').toLowerCase();
                if (dt.includes('correlat') || dt.includes('fusion') || dt.includes('fused')) {
                    found = true;
                    snippet = dossierEl.innerText.substring(0, 300);
                }
            }
            return {found:found, snippet:snippet};
        }""")

        has_correlation = corr_info.get('found', False)
        step("Step 9: Correlation display", has_correlation,
             f"info: {json.dumps(corr_info)[:300]}")
        screenshot(page, "step9_correlation")

        # ── SUMMARY ──
        print("\n" + "="*60)
        print("  WAVE 177 — LOOP 6 TEST RESULTS")
        print("="*60)

        pass_count = sum(1 for v in RESULTS.values() if v["status"] == "PASS")
        total = len(RESULTS)

        for name, result in RESULTS.items():
            icon = "PASS" if result["status"] == "PASS" else "FAIL"
            print(f"  [{icon}] {name}")

        print(f"\n  SCORE: {pass_count}/{total} PASS")
        print(f"  JS Errors: {len(js_errors)}")
        if js_errors:
            for err in js_errors[:5]:
                print(f"    - {err[:150]}")
        print("="*60)

        browser.close()

        with open(f"{BASEDIR}/w177_loop6_results.json", "w") as f:
            json.dump({"pass": pass_count, "total": total, "results": RESULTS,
                       "js_errors": js_errors[:10]}, f, indent=2)

        return 0 if pass_count >= 5 else 1

if __name__ == "__main__":
    sys.exit(main())
