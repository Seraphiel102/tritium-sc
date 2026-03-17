#!/usr/bin/env python3
"""Village Idiot - Combat Simulation Test 3 - Click QUICK START then LAUNCH MISSION"""
from playwright.sync_api import sync_playwright
import time

def main():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    errors = []
    page.on('pageerror', lambda e: errors.append(e.message))

    print("Navigating...", flush=True)
    page.goto('http://localhost:8000', wait_until='commit', timeout=15000)
    time.sleep(10)
    print("Page loaded", flush=True)

    # Press B to open mission dialog
    page.keyboard.press('b')
    time.sleep(2)

    # Click QUICK START
    for b in page.query_selector_all('button'):
        try:
            t = b.inner_text().strip()
            if b.is_visible() and 'QUICK START' in t.upper():
                b.click()
                print(f"Step 1: Clicked [{t}]", flush=True)
                break
        except:
            pass

    time.sleep(3)

    # Now click LAUNCH MISSION
    for b in page.query_selector_all('button'):
        try:
            t = b.inner_text().strip()
            if b.is_visible() and 'LAUNCH' in t.upper():
                b.click()
                print(f"Step 2: Clicked [{t}]", flush=True)
                break
        except:
            pass

    # Countdown phase
    time.sleep(3)
    page.screenshot(path='tests/.baselines/idiot_battle3_countdown.png')
    print(f"Countdown screenshot. Errors: {len(errors)}", flush=True)

    # Early battle
    time.sleep(7)
    page.screenshot(path='tests/.baselines/idiot_battle3_10s.png')
    print(f"10s into battle. Errors: {len(errors)}", flush=True)

    # Mid battle
    time.sleep(10)
    page.screenshot(path='tests/.baselines/idiot_battle3_20s.png')
    print(f"20s into battle. Errors: {len(errors)}", flush=True)

    # Check what API says about game state
    import urllib.request, json
    try:
        with urllib.request.urlopen('http://localhost:8000/api/amy/simulation/targets') as r:
            data = json.loads(r.read())
            hostiles = [t for t in data if t.get('alliance') == 'hostile']
            friendlies = [t for t in data if t.get('alliance') == 'friendly']
            print(f"API: {len(data)} targets, {len(hostiles)} hostile, {len(friendlies)} friendly", flush=True)
    except Exception as e:
        print(f"API error: {e}", flush=True)

    # Check game state
    try:
        with urllib.request.urlopen('http://localhost:8000/api/game/state') as r:
            data = json.loads(r.read())
            print(f"Game state: {json.dumps(data)[:300]}", flush=True)
    except Exception as e:
        print(f"Game state API: {e}", flush=True)

    # Check for UI elements
    for selector in ['.kill-feed', '#kill-feed', '[class*="kill"]',
                     '.wave-counter', '#wave-counter', '[class*="wave-count"]',
                     '.game-hud', '#game-hud', '[class*="game-hud"]',
                     '.war-hud', '#war-hud', '[class*="war-hud"]',
                     '.game-over', '#game-over', '[class*="game-over"]',
                     '[class*="countdown"]', '[class*="battle"]']:
        el = page.query_selector(selector)
        if el:
            vis = el.is_visible()
            print(f"  UI: {selector} visible={vis}", flush=True)

    for e in errors[:5]:
        print(f"  ERR: {e[:150]}", flush=True)

    browser.close()
    p.stop()
    print("DONE", flush=True)

if __name__ == '__main__':
    main()
