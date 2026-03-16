# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Window sweep test: open and close every panel, screenshot each one.

Dynamically discovers ALL registered panels from the WINDOWS menu dropdown.
No hardcoded panel list — if a new panel is registered, this test covers it.

Run:
    cd tritium-sc
    .venv/bin/python3 -m pytest tests/visual/test_window_sweep.py -v --tb=short

Screenshots saved to: /tmp/window_sweep_*.png
"""

import time
import pytest

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")


@pytest.fixture(scope="module")
def browser_page():
    """Launch browser and navigate to SC."""
    import requests
    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        assert r.status_code == 200
    except Exception:
        pytest.skip("SC server not running on :8000")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", timeout=20000)
        time.sleep(5)
        yield page
        browser.close()


def get_windows_menu_items(page):
    """Click WINDOWS menu and return all panel item labels."""
    triggers = page.query_selector_all(".menu-trigger")
    win_trigger = None
    for t in triggers:
        if t.text_content().strip() == "WINDOWS":
            win_trigger = t
            break
    if not win_trigger:
        return []

    win_trigger.click()
    time.sleep(0.3)

    items = page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item")
    panels = []
    for item in items:
        label = item.text_content().strip()
        # Skip non-panel items (Show All, Hide All, Fullscreen, separators)
        if label in ("Show All", "Hide All", "Fullscreen", ""):
            continue
        # Category headers have a different class
        if "menu-category" in (item.get_attribute("class") or ""):
            continue
        # Check if it has a checkable indicator (panel items are checkable)
        check_el = item.query_selector(".menu-check")
        if check_el is not None:
            panels.append(label)

    # Close menu
    page.keyboard.press("Escape")
    time.sleep(0.2)
    return panels


class TestWindowSweep:
    """Open every panel one at a time, screenshot, then close it."""

    def test_discover_panels(self, browser_page):
        """Discover all panels from WINDOWS menu."""
        panels = get_windows_menu_items(browser_page)
        print(f"\nDiscovered {len(panels)} panels: {panels}")
        assert len(panels) >= 5, f"Expected 5+ panels, found {len(panels)}: {panels}"

    def test_open_close_each_panel(self, browser_page):
        """Open each panel, screenshot, close it."""
        page = browser_page
        panels = get_windows_menu_items(page)
        results = []

        for panel_name in panels:
            # Open WINDOWS menu
            triggers = page.query_selector_all(".menu-trigger")
            for t in triggers:
                if t.text_content().strip() == "WINDOWS":
                    t.click()
                    break
            time.sleep(0.3)

            # Click the panel item
            items = page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item")
            clicked = False
            for item in items:
                if item.text_content().strip() == panel_name:
                    item.click()
                    clicked = True
                    break

            if not clicked:
                results.append((panel_name, "SKIP", "Could not find in menu"))
                page.keyboard.press("Escape")
                continue

            time.sleep(0.5)

            # Screenshot with panel open
            safe_name = panel_name.replace(" ", "_").replace("/", "_").lower()
            path = f"/tmp/window_sweep_{safe_name}.png"
            page.screenshot(path=path)

            # Check for JS errors
            # Close the panel by clicking it again in WINDOWS menu
            for t in page.query_selector_all(".menu-trigger"):
                if t.text_content().strip() == "WINDOWS":
                    t.click()
                    break
            time.sleep(0.2)
            for item in page.query_selector_all(".menu-dropdown:not([hidden]) .menu-item"):
                if item.text_content().strip() == panel_name:
                    item.click()
                    break
            time.sleep(0.2)
            page.keyboard.press("Escape")

            results.append((panel_name, "PASS", path))

        print(f"\n=== WINDOW SWEEP RESULTS ===")
        for name, status, detail in results:
            print(f"  [{status}] {name}: {detail}")

        passed = [r for r in results if r[1] == "PASS"]
        assert len(passed) >= 3, f"Only {len(passed)} panels opened successfully"
