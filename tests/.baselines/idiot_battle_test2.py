#!/usr/bin/env python3
"""Village Idiot - Combat Simulation Test 2 - Click QUICK START"""
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
    print("Mission dialog should be open", flush=True)

    # Click QUICK START button
    btns = page.query_selector_all('button')
    clicked = False
    for b in btns:
        try:
            t = b.inner_text().strip()
            if b.is_visible() and 'QUICK START' in t.upper():
                b.click()
                print(f"CLICKED: [{t}]", flush=True)
                clicked = True
                break
        except:
            pass

    if not clicked:
        print("FAILED: Could not find QUICK START button", flush=True)
        browser.close()
        p.stop()
        return

    # Screenshot immediately after clicking
    time.sleep(2)
    page.screenshot(path='tests/.baselines/idiot_battle2_2s.png')
    print(f"2s after start. Errors: {len(errors)}", flush=True)

    # Wait for countdown to finish
    time.sleep(5)
    page.screenshot(path='tests/.baselines/idiot_battle2_7s.png')
    print(f"7s after start. Errors: {len(errors)}", flush=True)

    # Battle should be active
    time.sleep(10)
    page.screenshot(path='tests/.baselines/idiot_battle2_17s.png')
    print(f"17s after start. Errors: {len(errors)}", flush=True)

    # Later in battle
    time.sleep(15)
    page.screenshot(path='tests/.baselines/idiot_battle2_32s.png')
    print(f"32s after start. Errors: {len(errors)}", flush=True)

    # Check for UI elements
    for selector in ['.kill-feed', '#kill-feed', '.wave-counter', '#wave-counter',
                     '.game-hud', '#game-hud', '.war-hud', '#war-hud',
                     '.game-over', '#game-over', '[class*="kill-feed"]',
                     '[class*="wave"]', '[class*="hud"]']:
        el = page.query_selector(selector)
        if el:
            vis = el.is_visible()
            print(f"  FOUND: {selector} visible={vis}", flush=True)

    for e in errors[:5]:
        print(f"  ERR: {e[:150]}", flush=True)

    browser.close()
    p.stop()
    print("DONE", flush=True)

if __name__ == '__main__':
    main()
