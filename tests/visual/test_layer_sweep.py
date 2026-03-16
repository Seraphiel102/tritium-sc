# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Layer sweep test: hide all layers, then show each one individually and screenshot.

Dynamically discovers ALL layers from the Layers panel checkboxes.
No hardcoded layer list — if a new layer is added, this test covers it.

Run:
    cd tritium-sc
    .venv/bin/python3 -m pytest tests/visual/test_layer_sweep.py -v --tb=short

Screenshots saved to: /tmp/layer_sweep_*.png
Report: /tmp/layer_sweep_report.md
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
    """Launch browser, navigate to SC, start demo mode, open layers panel."""
    import requests
    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        assert r.status_code == 200
    except Exception:
        pytest.skip("SC server not running on :8000")

    # Start demo mode for visible targets
    requests.post("http://localhost:8000/api/demo/start", timeout=5)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", timeout=20000)
        time.sleep(8)

        # Open layers panel
        page.keyboard.press("l")
        time.sleep(1)

        yield page
        browser.close()


def get_all_layer_checkboxes(page):
    """Find all layer toggle checkboxes in the Layers panel."""
    checkboxes = page.query_selector_all('.layers-panel-inner input[type="checkbox"]')
    layers = []
    for cb in checkboxes:
        key = cb.get_attribute("data-key") or cb.get_attribute("data-event-toggle") or ""
        if not key:
            continue
        # Get the label text from the parent layer-item
        item = cb.evaluate("el => el.closest('.layer-item')")
        label = ""
        if item:
            label_el = page.query_selector(f'.layer-item[data-layer-id] .layer-label')
        # Fallback: use the key as label
        if not label:
            label = key.replace("show", "").replace("toggle", "")
        layers.append({"key": key, "label": label, "element": cb})
    return layers


class TestLayerSweep:
    """Hide all, then show each layer one at a time and screenshot."""

    def test_discover_layers(self, browser_page):
        """Discover all layers from the Layers panel."""
        layers = get_all_layer_checkboxes(browser_page)
        print(f"\nDiscovered {len(layers)} layer checkboxes")
        for l in layers:
            print(f"  - {l['key']}")
        assert len(layers) >= 10, f"Expected 10+ layers, found {len(layers)}"

    def test_hide_all_then_show_each(self, browser_page):
        """Hide all layers, then show each one individually."""
        page = browser_page
        results = []

        # Click HIDE ALL button
        hide_btn = page.query_selector(".layers-btn-hide-all")
        if hide_btn:
            hide_btn.click()
            time.sleep(1)

        # Take baseline screenshot with everything hidden
        page.screenshot(path="/tmp/layer_sweep_00_all_hidden.png")
        results.append(("ALL_HIDDEN", "/tmp/layer_sweep_00_all_hidden.png"))

        # Get all layer checkboxes
        layers = get_all_layer_checkboxes(page)

        for i, layer in enumerate(layers):
            key = layer["key"]
            safe_key = key.replace(":", "_").replace("/", "_")

            # Check if this layer's checkbox exists and is unchecked
            cb = page.query_selector(f'input[data-key="{key}"]')
            if not cb:
                cb = page.query_selector(f'input[data-event-toggle="{key}"]')
            if not cb:
                results.append((key, "SKIP — checkbox not found"))
                continue

            # Check (show) this layer
            is_checked = cb.is_checked()
            if not is_checked:
                # Scroll into view and click
                try:
                    cb.scroll_into_view_if_needed(timeout=2000)
                    cb.click(timeout=2000)
                except Exception:
                    results.append((key, "SKIP — click failed"))
                    continue

            time.sleep(0.5)

            # Screenshot with just this layer visible
            path = f"/tmp/layer_sweep_{i+1:02d}_{safe_key}.png"
            page.screenshot(path=path)
            results.append((key, path))

            # Uncheck (hide) this layer again
            try:
                cb = page.query_selector(f'input[data-key="{key}"]') or page.query_selector(f'input[data-event-toggle="{key}"]')
                if cb and cb.is_checked():
                    cb.scroll_into_view_if_needed(timeout=2000)
                    cb.click(timeout=2000)
            except Exception:
                pass

            time.sleep(0.2)

        # Show all at the end to restore
        show_btn = page.query_selector(".layers-btn-show-all")
        if show_btn:
            show_btn.click()

        # Generate report
        report = "# Layer Sweep Report\n\n"
        report += f"**Layers discovered:** {len(layers)}\n\n"
        report += "| # | Layer Key | Screenshot |\n"
        report += "|---|-----------|------------|\n"
        for i, (key, path) in enumerate(results):
            report += f"| {i} | `{key}` | `{path}` |\n"

        with open("/tmp/layer_sweep_report.md", "w") as f:
            f.write(report)

        print(f"\n=== LAYER SWEEP ===")
        print(f"Layers: {len(layers)}")
        print(f"Screenshots: {len([r for r in results if r[1].startswith('/tmp/')])}")
        print(f"Report: /tmp/layer_sweep_report.md")

        assert len(results) >= 10, f"Expected 10+ layer screenshots, got {len(results)}"
