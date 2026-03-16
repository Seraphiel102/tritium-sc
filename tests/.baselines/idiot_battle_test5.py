#!/usr/bin/env python3
"""Village Idiot - Wait for game over and screenshot"""
from playwright.sync_api import sync_playwright
import time, json, urllib.request

def get_game_state():
    try:
        with urllib.request.urlopen('http://localhost:8000/api/game/state') as r:
            return json.loads(r.read())
    except:
        return {}

def main():
    # First just poll API until game over
    print("Waiting for game to end...", flush=True)
    for i in range(30):  # up to 5 minutes
        state = get_game_state()
        s = state.get('state', '?')
        w = state.get('wave', '?')
        kills = state.get('total_eliminations', 0)
        score = state.get('score', 0)
        remaining = state.get('wave_hostiles_remaining', '?')
        print(f"  T+{i*10}s: state={s} wave={w}/10 kills={kills} score={score} remaining={remaining}", flush=True)

        if s == 'game_over':
            print("GAME OVER!", flush=True)
            print(f"Final: {json.dumps(state)[:500]}", flush=True)
            break

        if s not in ('active', 'countdown', 'setup', 'wave_complete'):
            print(f"Unexpected state: {s}", flush=True)

        time.sleep(10)

    # Now take screenshot of game over screen
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto('http://localhost:8000', wait_until='commit', timeout=15000)
    time.sleep(8)
    page.screenshot(path='tests/.baselines/idiot_battle5_final.png', timeout=10000)
    print("Final screenshot saved", flush=True)

    browser.close()
    p.stop()
    print("DONE", flush=True)

if __name__ == '__main__':
    main()
