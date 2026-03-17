#!/usr/bin/env python3
"""Village Idiot - Combat Simulation Test"""
from playwright.sync_api import sync_playwright
import time, sys

def main():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    errors = []
    page.on('pageerror', lambda e: errors.append(e.message))

    print("Navigating...", flush=True)
    page.goto('http://localhost:8000', wait_until='commit', timeout=15000)
    print("Waiting for map to render...", flush=True)
    time.sleep(10)

    print("Pressing B...", flush=True)
    page.keyboard.press('b')
    time.sleep(3)

    # List visible buttons
    btns = page.query_selector_all('button')
    for b in btns:
        try:
            t = b.inner_text().strip()
            if b.is_visible() and t:
                print(f"  BTN: [{t}]", flush=True)
        except:
            pass

    page.screenshot(path='tests/.baselines/idiot_mission_select.png')
    print("Mission select screenshot saved", flush=True)

    # Click begin/start
    clicked = False
    for b in btns:
        try:
            t = b.inner_text().strip().upper()
            if b.is_visible() and ('BEGIN' in t or 'COMMENCE' in t or 'START MISSION' in t):
                b.click()
                print(f"CLICKED: {t}", flush=True)
                clicked = True
                break
        except:
            pass

    if not clicked:
        print("Could not find start button, trying ENTER", flush=True)
        page.keyboard.press('Enter')

    # Wait for countdown
    time.sleep(5)
    page.screenshot(path='tests/.baselines/idiot_battle_countdown.png')
    print(f"Countdown screenshot. Errors: {len(errors)}", flush=True)

    # Wait for battle
    time.sleep(15)
    page.screenshot(path='tests/.baselines/idiot_battle_active.png')
    print(f"Active battle screenshot. Errors: {len(errors)}", flush=True)

    # Wait more for waves
    time.sleep(20)
    page.screenshot(path='tests/.baselines/idiot_battle_later.png')
    print(f"Later battle screenshot. Errors: {len(errors)}", flush=True)

    for e in errors[:5]:
        print(f"  ERR: {e[:150]}", flush=True)

    browser.close()
    p.stop()
    print("DONE", flush=True)

if __name__ == '__main__':
    main()
