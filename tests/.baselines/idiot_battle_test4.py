#!/usr/bin/env python3
"""Village Idiot - Combat Simulation Test 4 - Full battle run"""
from playwright.sync_api import sync_playwright
import time, json, urllib.request

def get_game_state():
    try:
        with urllib.request.urlopen('http://localhost:8000/api/game/state') as r:
            return json.loads(r.read())
    except:
        return {}

def main():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    errors = []
    page.on('pageerror', lambda e: errors.append(e.message))

    print("Navigating...", flush=True)
    page.goto('http://localhost:8000', wait_until='commit', timeout=15000)
    time.sleep(10)

    # Press B, click QUICK START, then LAUNCH MISSION
    page.keyboard.press('b')
    time.sleep(2)
    for b in page.query_selector_all('button'):
        try:
            t = b.inner_text().strip()
            if b.is_visible() and 'QUICK START' in t.upper():
                b.click()
                print(f"Clicked QUICK START", flush=True)
                break
        except:
            pass
    time.sleep(3)
    for b in page.query_selector_all('button'):
        try:
            t = b.inner_text().strip()
            if b.is_visible() and 'LAUNCH' in t.upper():
                b.click()
                print(f"Clicked LAUNCH MISSION", flush=True)
                break
        except:
            pass

    # Wait for countdown
    time.sleep(5)

    # Monitor battle progress every 10 seconds
    for i in range(12):  # 2 minutes total
        state = get_game_state()
        s = state.get('state', '?')
        w = state.get('wave', '?')
        score = state.get('score', 0)
        kills = state.get('total_eliminations', 0)
        remaining = state.get('wave_hostiles_remaining', '?')
        wave_name = state.get('wave_name', '')
        print(f"  T+{(i+1)*10}s: state={s} wave={w}/10 score={score} kills={kills} remaining={remaining} [{wave_name}]", flush=True)

        if s == 'game_over':
            page.screenshot(path='tests/.baselines/idiot_battle4_gameover.png')
            print("GAME OVER screenshot saved!", flush=True)
            break

        if i == 2:  # 30s mark
            page.screenshot(path='tests/.baselines/idiot_battle4_30s.png')
        elif i == 5:  # 60s mark
            page.screenshot(path='tests/.baselines/idiot_battle4_60s.png')
        elif i == 8:  # 90s mark
            page.screenshot(path='tests/.baselines/idiot_battle4_90s.png')

        time.sleep(10)

    # Final state
    state = get_game_state()
    print(f"\nFINAL STATE: {json.dumps(state)[:500]}", flush=True)
    page.screenshot(path='tests/.baselines/idiot_battle4_final.png')

    # Check for game over overlay
    go = page.query_selector('[class*="game-over"]')
    if go:
        print(f"Game over overlay visible: {go.is_visible()}", flush=True)

    print(f"\nTotal JS errors: {len(errors)}", flush=True)
    for e in errors[:5]:
        print(f"  ERR: {e[:150]}", flush=True)

    browser.close()
    p.stop()
    print("DONE", flush=True)

if __name__ == '__main__':
    main()
