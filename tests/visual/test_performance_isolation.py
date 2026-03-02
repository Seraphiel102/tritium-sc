# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Performance Isolation Test Suite.

Measures the FPS impact of each individual UI element and visual effect
in the Command Center. Produces a ranked report showing which layers
and overlays cost the most frames, plus a cumulative waterfall chart.

Methodology (subtraction method):
  1. Navigate to Command Center, wait for map to initialize.
  2. Measure baseline FPS in the default state (as the user sees it).
  3. For each element, disable ONLY that element and measure FPS.
  4. Cost = FPS gained by removing the element (positive = it was expensive).
  5. Measure FPS with ALL elements enabled (maximum load).
  6. Generate HTML + JSON report sorted by worst offenders.

The test connects to a running server at localhost:8000 (headed browser
by default per project convention).

IMPORTANT: This measures idle/observe state costs. If the system is
vsync-capped (~60 FPS) in idle mode, individual element costs will only
appear when the system is under load (during active battle). To measure
battle-state performance, start a battle via the API before running this
test, or use test_battle_performance.py (if it exists).

Run:
    .venv/bin/python3 -m pytest tests/visual/test_performance_isolation.py -v -s
"""

from __future__ import annotations

import html
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

pytestmark = pytest.mark.visual

SERVER = "http://localhost:8000"
OUT = Path("tests/.test-results/performance-isolation")
SAMPLE_SECONDS = 5        # how long to measure FPS per element
SETTLE_SECONDS = 1.5      # time to wait after toggling before measuring
TARGET_FPS = 30            # minimum acceptable FPS
VIEWPORT_W = 1920
VIEWPORT_H = 1080

# ============================================================
# FPS measurement JS — injected into the page
# ============================================================

_FPS_INJECT = """
(() => {
    window._perfIso = window._perfIso || {};
    const P = window._perfIso;
    P.frameTimes = [];
    P.measuring = false;
    P.rafId = null;

    P.start = () => {
        P.frameTimes = [];
        P.measuring = true;
        let last = performance.now();
        function tick(now) {
            if (!P.measuring) return;
            const dt = now - last;
            // Ignore unreasonably large gaps (tab hidden) and sub-1ms artifacts
            if (dt > 1 && dt < 500) P.frameTimes.push(dt);
            last = now;
            P.rafId = requestAnimationFrame(tick);
        }
        P.rafId = requestAnimationFrame(tick);
    };

    P.stop = () => {
        P.measuring = false;
        if (P.rafId) { cancelAnimationFrame(P.rafId); P.rafId = null; }
        const ft = P.frameTimes;
        if (ft.length < 2) return {
            avg_fps: 0, min_fps: 0, max_fps: 0,
            frame_count: 0, avg_frame_time_ms: 0,
            jitter_ms: 0, p50_fps: 0, p5_fps: 0, p95_fps: 0,
            variance_ms: 0,
        };
        const avg = ft.reduce((a, b) => a + b, 0) / ft.length;
        const sorted = [...ft].sort((a, b) => a - b);
        const p5  = sorted[Math.floor(sorted.length * 0.05)];
        const p50 = sorted[Math.floor(sorted.length * 0.50)];
        const p95 = sorted[Math.floor(sorted.length * 0.95)];
        const min_ft = sorted[0];
        const max_ft = sorted[sorted.length - 1];
        const mean = avg;
        const variance = ft.reduce((s, t) => s + (t - mean) ** 2, 0) / ft.length;
        const safeFps = (ms) => ms > 0 ? Math.round(1000 / ms * 10) / 10 : 0;
        return {
            avg_fps:           safeFps(avg),
            min_fps:           safeFps(max_ft),
            max_fps:           safeFps(min_ft),
            p5_fps:            safeFps(p95),
            p50_fps:           safeFps(p50),
            p95_fps:           safeFps(p5),
            frame_count:       ft.length,
            avg_frame_time_ms: Math.round(avg * 100) / 100,
            jitter_ms:         Math.round((max_ft - min_ft) * 100) / 100,
            variance_ms:       Math.round(variance * 100) / 100,
        };
    };
})();
"""


# ============================================================
# Element definitions — each maps to a toggle or panel
# ============================================================

@dataclass
class UIElement:
    """Describes a single UI element or visual effect to benchmark."""
    name: str
    category: str           # 'map_layer', 'combat_fx', 'overlay', 'panel', 'decoration'
    description: str
    # JS expression to enable this element (run after baseline is measured)
    enable_js: str
    # JS expression to disable this element (restore baseline)
    disable_js: str


# All toggleable elements discovered from map-maplibre.js _state and panel-manager.js
ELEMENTS: list[UIElement] = [
    # ---- Map Base Layers ----
    UIElement(
        "satellite", "map_layer", "Satellite imagery raster tiles",
        "window._mapActions.setLayers({ satellite: true })",
        "window._mapActions.setLayers({ satellite: false })",
    ),
    UIElement(
        "roads", "map_layer", "Road overlay raster + vector lines",
        "window._mapActions.setLayers({ roads: true })",
        "window._mapActions.setLayers({ roads: false })",
    ),
    UIElement(
        "buildings", "map_layer", "3D building extrusions + outlines",
        "window._mapActions.setLayers({ buildings: true })",
        "window._mapActions.setLayers({ buildings: false })",
    ),
    UIElement(
        "waterways", "map_layer", "Water fill layers",
        "window._mapActions.setLayers({ waterways: true })",
        "window._mapActions.setLayers({ waterways: false })",
    ),
    UIElement(
        "parks", "map_layer", "Park / green area fills",
        "window._mapActions.setLayers({ parks: true })",
        "window._mapActions.setLayers({ parks: false })",
    ),
    UIElement(
        "terrain", "map_layer", "3D terrain mesh (DEM)",
        "window._mapActions.setLayers({ terrain: true })",
        "window._mapActions.setLayers({ terrain: false })",
    ),
    UIElement(
        "grid", "map_layer", "Grid overlay (minor + major lines)",
        "window._mapActions.setLayers({ grid: true })",
        "window._mapActions.setLayers({ grid: false })",
    ),

    # ---- Tactical Layers ----
    UIElement(
        "unit_markers", "map_layer", "DOM unit marker dots",
        "window._mapActions.setLayers({ units: true })",
        "window._mapActions.setLayers({ units: false })",
    ),
    UIElement(
        "labels", "decoration", "DOM unit name labels",
        "window._mapState.showLabels = true",
        "window._mapState.showLabels = false",
    ),
    UIElement(
        "3d_models", "map_layer", "Three.js 3D unit models",
        "window._mapActions.setLayers({ models3d: true })",
        "window._mapActions.setLayers({ models3d: false })",
    ),
    UIElement(
        "fog_of_war", "overlay", "Fog of war vision cones overlay",
        "window._mapActions.setLayers({ fog: true })",
        "window._mapActions.setLayers({ fog: false })",
    ),
    UIElement(
        "mesh_network", "overlay", "Mesh radio network overlay lines",
        "window._mapState.showMesh = true",
        "window._mapState.showMesh = false",
    ),
    UIElement(
        "patrol_routes", "overlay", "Patrol route lines for friendlies",
        "window._mapActions.setLayers({ patrolRoutes: true })",
        "window._mapActions.setLayers({ patrolRoutes: false })",
    ),
    UIElement(
        "weapon_range", "overlay", "Weapon range circle on selected unit",
        "window._mapActions.setLayers({ weaponRange: true })",
        "window._mapActions.setLayers({ weaponRange: false })",
    ),
    UIElement(
        "heatmap", "overlay", "Combat zone heatmap overlay",
        "window._mapActions.setLayers({ heatmap: true })",
        "window._mapActions.setLayers({ heatmap: false })",
    ),
    UIElement(
        "swarm_hull", "overlay", "Drone swarm convex hull polygon",
        "window._mapActions.setLayers({ swarmHull: true })",
        "window._mapActions.setLayers({ swarmHull: false })",
    ),
    UIElement(
        "squad_hulls", "overlay", "Squad formation convex hull polygons",
        "window._mapActions.setLayers({ squadHulls: true })",
        "window._mapActions.setLayers({ squadHulls: false })",
    ),

    # ---- Combat FX ----
    UIElement(
        "tracers", "combat_fx", "Three.js projectile flight trails",
        "window._mapState.showTracers = true",
        "window._mapState.showTracers = false",
    ),
    UIElement(
        "explosions", "combat_fx", "Three.js + DOM elimination explosions",
        "window._mapState.showExplosions = true",
        "window._mapState.showExplosions = false",
    ),
    UIElement(
        "particles", "combat_fx", "Three.js debris / spark particles",
        "window._mapState.showParticles = true",
        "window._mapState.showParticles = false",
    ),
    UIElement(
        "hit_flashes", "combat_fx", "Three.js + DOM impact flash effects",
        "window._mapState.showHitFlashes = true",
        "window._mapState.showHitFlashes = false",
    ),
    UIElement(
        "floating_text", "combat_fx", "DOM floating damage numbers",
        "window._mapState.showFloatingText = true",
        "window._mapState.showFloatingText = false",
    ),

    # ---- Unit Decorations ----
    UIElement(
        "health_bars", "decoration", "DOM health bars + damage glow",
        "window._mapState.showHealthBars = true",
        "window._mapState.showHealthBars = false",
    ),
    UIElement(
        "selection_fx", "decoration", "Selection highlight + hostile pulse",
        "window._mapState.showSelectionFx = true",
        "window._mapState.showSelectionFx = false",
    ),
    UIElement(
        "thought_bubbles", "decoration", "NPC thought bubbles above markers",
        "window._mapState.showThoughts = true",
        "window._mapState.showThoughts = false",
    ),

    # ---- Overlays / HUD ----
    UIElement(
        "kill_feed", "overlay", "Top-right combat log overlay",
        "window._mapState.showKillFeed = true",
        "window._mapState.showKillFeed = false",
    ),
    UIElement(
        "screen_fx", "overlay", "Screen shake + flash overlay",
        "window._mapState.showScreenFx = true",
        "window._mapState.showScreenFx = false",
    ),
    UIElement(
        "banners", "overlay", "Wave / game state announcement banners",
        "window._mapState.showBanners = true",
        "window._mapState.showBanners = false",
    ),
    UIElement(
        "layer_hud", "overlay", "Top-center layer status HUD bar",
        "window._mapState.showLayerHud = true",
        "window._mapState.showLayerHud = false",
    ),
    UIElement(
        "auto_follow", "overlay", "Cinematic auto-follow camera mode",
        "window._mapActions.setLayers({ autoFollow: true })",
        "window._mapActions.setLayers({ autoFollow: false })",
    ),

    # ---- Panels ----
    UIElement(
        "amy_panel", "panel", "Amy AI commander panel",
        "window.panelManager.open('amy')",
        "window.panelManager.close('amy')",
    ),
    UIElement(
        "units_panel", "panel", "Units list panel",
        "window.panelManager.open('units')",
        "window.panelManager.close('units')",
    ),
    UIElement(
        "alerts_panel", "panel", "Alert feed panel",
        "window.panelManager.open('alerts')",
        "window.panelManager.close('alerts')",
    ),
    UIElement(
        "minimap_panel", "panel", "Minimap panel",
        "window.panelManager.open('minimap')",
        "window.panelManager.close('minimap')",
    ),
    UIElement(
        "game_hud_panel", "panel", "Game HUD / stats panel",
        "window.panelManager.open('game-hud')",
        "window.panelManager.close('game-hud')",
    ),
    UIElement(
        "mesh_panel", "panel", "Mesh network panel",
        "window.panelManager.open('mesh')",
        "window.panelManager.close('mesh')",
    ),
    UIElement(
        "system_panel", "panel", "System diagnostics panel",
        "window.panelManager.open('system')",
        "window.panelManager.close('system')",
    ),
    UIElement(
        "escalation_panel", "panel", "Escalation / threat panel",
        "window.panelManager.open('escalation')",
        "window.panelManager.close('escalation')",
    ),
    UIElement(
        "events_panel", "panel", "Events timeline panel",
        "window.panelManager.open('events')",
        "window.panelManager.close('events')",
    ),
    UIElement(
        "scenarios_panel", "panel", "Scenarios panel",
        "window.panelManager.open('scenarios')",
        "window.panelManager.close('scenarios')",
    ),
    UIElement(
        "replay_panel", "panel", "Replay panel",
        "window.panelManager.open('replay')",
        "window.panelManager.close('replay')",
    ),
    UIElement(
        "battle_stats_panel", "panel", "Battle stats panel",
        "window.panelManager.open('battle-stats')",
        "window.panelManager.close('battle-stats')",
    ),
]


# ============================================================
# Data classes for results
# ============================================================

@dataclass
class FPSMeasurement:
    avg_fps: float = 0
    min_fps: float = 0
    max_fps: float = 0
    p5_fps: float = 0
    p50_fps: float = 0
    p95_fps: float = 0
    frame_count: int = 0
    avg_frame_time_ms: float = 0
    jitter_ms: float = 0
    variance_ms: float = 0


@dataclass
class ElementResult:
    name: str
    category: str
    description: str
    measurement: FPSMeasurement
    fps_delta: float = 0       # negative means FPS dropped
    pct_drop: float = 0        # % FPS reduction from baseline
    below_target: bool = False # True if avg_fps < TARGET_FPS


@dataclass
class PerfReport:
    timestamp: str = ""
    baseline: FPSMeasurement = field(default_factory=FPSMeasurement)
    elements: list[ElementResult] = field(default_factory=list)
    target_fps: int = TARGET_FPS
    sample_seconds: int = SAMPLE_SECONDS
    viewport: dict = field(default_factory=lambda: {"w": VIEWPORT_W, "h": VIEWPORT_H})
    cumulative_fps: float = 0  # FPS with ALL elements enabled


# ============================================================
# Core measurement helpers
# ============================================================

def _measure_fps(page: Page, seconds: float = SAMPLE_SECONDS) -> FPSMeasurement:
    """Start FPS measurement, wait, stop, return results."""
    page.evaluate("window._perfIso.start()")
    page.wait_for_timeout(int(seconds * 1000))
    raw = page.evaluate("window._perfIso.stop()")
    return FPSMeasurement(**raw)


def _restore_defaults(page: Page) -> None:
    """Restore the page to default loaded state (as the user would see it).

    This is the reference state for all measurements. We enable the layers
    that are ON by default in map-maplibre.js _state, and open the default
    panels that initPanelSystem opens.
    """
    page.evaluate("""
        if (window._mapActions && window._mapActions.setLayers) {
            window._mapActions.setLayers({
                satellite: true,
                roads: true,
                buildings: true,
                waterways: true,
                parks: true,
                terrain: false,
                grid: false,
                fog: false,
                units: true,
                models3d: true,
                patrolRoutes: true,
                weaponRange: true,
                heatmap: false,
                swarmHull: true,
                squadHulls: true,
                autoFollow: false,
            });
        }
    """)
    page.evaluate("""
        if (window._mapState) {
            window._mapState.showTracers = true;
            window._mapState.showExplosions = true;
            window._mapState.showParticles = true;
            window._mapState.showHitFlashes = true;
            window._mapState.showFloatingText = true;
            window._mapState.showHealthBars = true;
            window._mapState.showSelectionFx = true;
            window._mapState.showThoughts = true;
            window._mapState.showKillFeed = true;
            window._mapState.showScreenFx = true;
            window._mapState.showBanners = true;
            window._mapState.showLayerHud = true;
            window._mapState.showMesh = true;
            window._mapState.showLabels = true;
        }
    """)
    # Open default panels, close non-defaults
    page.evaluate("""
        if (window.panelManager) {
            ['amy', 'units', 'alerts', 'minimap'].forEach(id => {
                try { window.panelManager.open(id); } catch(e) {}
            });
            ['game-hud', 'mesh', 'system', 'escalation', 'events',
             'scenarios', 'replay', 'battle-stats', 'audio', 'patrol',
             'graphlings'].forEach(id => {
                try { window.panelManager.close(id); } catch(e) {}
            });
        }
    """)


def _disable_all(page: Page) -> None:
    """Disable all visual layers and close all panels — bare minimum state."""
    page.evaluate("""
        if (window._mapActions && window._mapActions.setLayers) {
            window._mapActions.setLayers({
                allMapLayers: false,
                models3d: false,
                domMarkers: false,
                satellite: false,
                roads: false,
                buildings: false,
                grid: false,
                fog: false,
                terrain: false,
                waterways: false,
                parks: false,
                patrolRoutes: false,
                weaponRange: false,
                heatmap: false,
                swarmHull: false,
                squadHulls: false,
                autoFollow: false,
            });
        }
    """)
    page.evaluate("""
        if (window._mapState) {
            window._mapState.showTracers = false;
            window._mapState.showExplosions = false;
            window._mapState.showParticles = false;
            window._mapState.showHitFlashes = false;
            window._mapState.showFloatingText = false;
            window._mapState.showHealthBars = false;
            window._mapState.showSelectionFx = false;
            window._mapState.showThoughts = false;
            window._mapState.showKillFeed = false;
            window._mapState.showScreenFx = false;
            window._mapState.showBanners = false;
            window._mapState.showLayerHud = false;
            window._mapState.showMesh = false;
            window._mapState.showLabels = false;
        }
    """)
    page.evaluate("""
        if (window.panelManager) {
            const ids = [
                'amy', 'units', 'alerts', 'minimap', 'game-hud', 'mesh',
                'system', 'escalation', 'events', 'scenarios', 'replay',
                'battle-stats', 'audio', 'patrol', 'graphlings'
            ];
            ids.forEach(id => {
                try { window.panelManager.close(id); } catch(e) {}
            });
        }
    """)


def _enable_all(page: Page) -> None:
    """Enable ALL visual layers and open ALL panels — maximum load state."""
    page.evaluate("""
        if (window._mapActions && window._mapActions.setLayers) {
            window._mapActions.setLayers({
                satellite: true,
                roads: true,
                buildings: true,
                grid: true,
                waterways: true,
                parks: true,
                terrain: true,
                fog: true,
                patrolRoutes: true,
                weaponRange: true,
                heatmap: true,
                swarmHull: true,
                squadHulls: true,
                autoFollow: true,
            });
        }
    """)
    page.evaluate("""
        if (window._mapState) {
            window._mapState.showTracers = true;
            window._mapState.showExplosions = true;
            window._mapState.showParticles = true;
            window._mapState.showHitFlashes = true;
            window._mapState.showFloatingText = true;
            window._mapState.showHealthBars = true;
            window._mapState.showSelectionFx = true;
            window._mapState.showThoughts = true;
            window._mapState.showKillFeed = true;
            window._mapState.showScreenFx = true;
            window._mapState.showBanners = true;
            window._mapState.showLayerHud = true;
            window._mapState.showMesh = true;
            window._mapState.showLabels = true;
            window._mapState.showModels3d = true;
        }
    """)
    page.evaluate("""
        if (window.panelManager) {
            ['amy', 'units', 'alerts', 'minimap', 'game-hud', 'mesh',
             'system', 'escalation', 'events', 'scenarios', 'replay',
             'battle-stats', 'audio', 'patrol'].forEach(id => {
                try { window.panelManager.open(id); } catch(e) {}
            });
        }
    """)


# ============================================================
# HTML Report Generator
# ============================================================

def _generate_report(report: PerfReport) -> str:
    """Generate a self-contained HTML performance report."""
    sorted_elements = sorted(report.elements, key=lambda e: e.fps_delta)  # most negative first

    # Build waterfall chart data (cumulative FPS cost)
    # Only include elements that have a cost (fps_delta < 0 means the element hurts)
    costly_elements = [e for e in sorted_elements if e.fps_delta < 0]
    cumulative_drop = 0.0
    waterfall_data = []
    for elem in costly_elements:
        cost = abs(elem.fps_delta)
        cumulative_drop += cost
        waterfall_data.append({
            "name": elem.name,
            "drop": cost,
            "cumulative": cumulative_drop,
        })
    # Also include non-costly elements with zero for completeness
    for elem in sorted_elements:
        if elem.fps_delta >= 0:
            waterfall_data.append({
                "name": elem.name,
                "drop": 0,
                "cumulative": cumulative_drop,
            })

    # Color coding
    def _fps_color(fps: float) -> str:
        if fps >= TARGET_FPS:
            return "#05ffa1"  # green
        if fps >= TARGET_FPS * 0.7:
            return "#fcee0a"  # yellow
        return "#ff2a6d"      # red

    def _delta_color(delta: float) -> str:
        if abs(delta) < 1:
            return "#05ffa1"
        if abs(delta) < 3:
            return "#fcee0a"
        return "#ff2a6d"

    # Category labels
    cat_label = {
        "map_layer": "Map Layer",
        "combat_fx": "Combat FX",
        "overlay": "Overlay / HUD",
        "panel": "Panel",
        "decoration": "Decoration",
    }

    rows_html = ""
    for elem in sorted_elements:
        m = elem.measurement
        rows_html += f"""
        <tr>
          <td class="name">{html.escape(elem.name)}</td>
          <td class="cat">{cat_label.get(elem.category, elem.category)}</td>
          <td style="color:{_fps_color(m.avg_fps)}">{m.avg_fps:.1f}</td>
          <td style="color:{_delta_color(elem.fps_delta)}">{elem.fps_delta:+.1f}</td>
          <td style="color:{_delta_color(elem.fps_delta)}">{elem.pct_drop:.1f}%</td>
          <td>{m.min_fps:.1f}</td>
          <td>{m.max_fps:.1f}</td>
          <td>{m.p5_fps:.1f}</td>
          <td>{m.avg_frame_time_ms:.1f}ms</td>
          <td>{m.jitter_ms:.1f}ms</td>
          <td>{m.frame_count}</td>
          <td class="desc">{html.escape(elem.description)}</td>
        </tr>"""

    # Waterfall chart bars (SVG)
    max_cum = max((w["cumulative"] for w in waterfall_data), default=1)
    bar_height = 22
    chart_height = len(waterfall_data) * (bar_height + 4) + 40
    chart_width = 800
    label_w = 160
    bar_max_w = chart_width - label_w - 80
    bars_svg = ""
    for i, w in enumerate(waterfall_data):
        y = i * (bar_height + 4) + 30
        bw = (w["cumulative"] / max(max_cum, 0.1)) * bar_max_w if max_cum > 0 else 0
        drop_w = (w["drop"] / max(max_cum, 0.1)) * bar_max_w if max_cum > 0 else 0
        prev_w = bw - drop_w
        color = _delta_color(-w["drop"])
        bars_svg += f"""
        <rect x="{label_w}" y="{y}" width="{prev_w}" height="{bar_height}"
              fill="#1a1a2e" rx="2"/>
        <rect x="{label_w + prev_w}" y="{y}" width="{max(drop_w, 1)}" height="{bar_height}"
              fill="{color}" opacity="0.8" rx="2"/>
        <text x="{label_w - 8}" y="{y + bar_height - 5}" text-anchor="end"
              fill="#8892a4" font-size="11" font-family="'JetBrains Mono', monospace">{html.escape(w['name'])}</text>
        <text x="{label_w + bw + 6}" y="{y + bar_height - 5}"
              fill="#c8d0dc" font-size="11" font-family="'JetBrains Mono', monospace">-{w['cumulative']:.1f} FPS</text>"""

    # Recommendations
    recs = []
    severe = [e for e in sorted_elements if e.pct_drop > 10]
    moderate = [e for e in sorted_elements if 3 < e.pct_drop <= 10]
    if severe:
        names = ", ".join(e.name for e in severe)
        recs.append(f"<li class='severe'>SEVERE impact ({len(severe)}): <strong>{names}</strong> — each drops FPS by >10%. Consider disabling by default or optimizing render path.</li>")
    if moderate:
        names = ", ".join(e.name for e in moderate)
        recs.append(f"<li class='moderate'>MODERATE impact ({len(moderate)}): <strong>{names}</strong> — each drops FPS by 3-10%. Worth optimizing if combined with other effects.</li>")
    below = [e for e in sorted_elements if e.below_target]
    if below:
        names = ", ".join(e.name for e in below)
        recs.append(f"<li class='severe'>Below {TARGET_FPS} FPS target ({len(below)}): <strong>{names}</strong></li>")
    if report.cumulative_fps < TARGET_FPS:
        recs.append(f"<li class='severe'>Cumulative FPS with all elements: <strong>{report.cumulative_fps:.1f}</strong> (below {TARGET_FPS} target). Some effects must be disabled by default or optimized.</li>")
    if not recs:
        recs.append("<li class='ok'>All elements within performance budget. No optimizations needed.</li>")

    recs_html = "\n".join(recs)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TRITIUM-SC Performance Isolation Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {{
    --cyan: #00f0ff; --green: #05ffa1; --amber: #fcee0a; --magenta: #ff2a6d;
    --void: #0a0a0f; --surface-1: #0e0e14; --surface-2: #12121a; --surface-3: #1a1a2e;
    --border: rgba(0, 240, 255, 0.08); --text-primary: #c8d0dc; --text-secondary: #8892a4;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: var(--void); color: var(--text-primary);
    font-family: 'Inter', sans-serif; padding: 24px; line-height: 1.6;
}}
h1 {{ color: var(--cyan); font-size: 28px; margin-bottom: 4px;
     font-family: 'JetBrains Mono', monospace; letter-spacing: 2px; }}
.subtitle {{ color: var(--text-secondary); margin-bottom: 24px; font-size: 14px; }}
.panel {{
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px; margin-bottom: 20px;
}}
.panel h2 {{ color: var(--cyan); font-size: 16px; margin-bottom: 12px;
             font-family: 'JetBrains Mono', monospace; text-transform: uppercase;
             letter-spacing: 1px; }}
.stats-row {{
    display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 20px;
}}
.stat-card {{
    background: var(--surface-2); border: 1px solid var(--border);
    border-radius: 6px; padding: 16px 20px; min-width: 180px;
}}
.stat-card .label {{ font-size: 11px; color: var(--text-secondary);
                     text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }}
.stat-card .value {{ font-size: 28px; font-weight: 700;
                     font-family: 'JetBrains Mono', monospace; }}
table {{
    width: 100%; border-collapse: collapse; font-size: 13px;
    font-family: 'JetBrains Mono', monospace;
}}
th {{
    text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--border);
    color: var(--cyan); font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
    white-space: nowrap;
}}
td {{
    padding: 6px 10px; border-bottom: 1px solid var(--border);
    white-space: nowrap;
}}
td.name {{ color: var(--text-primary); font-weight: 600; }}
td.cat {{ color: var(--text-secondary); font-size: 11px; }}
td.desc {{ color: var(--text-secondary); font-size: 11px; white-space: normal; max-width: 200px; }}
tr:hover {{ background: rgba(0, 240, 255, 0.03); }}
.chart-container {{ overflow-x: auto; }}
ul {{ list-style: none; padding: 0; }}
li {{ padding: 8px 12px; margin-bottom: 6px; border-radius: 4px; font-size: 13px; }}
li.severe {{ background: rgba(255, 42, 109, 0.1); border-left: 3px solid var(--magenta); }}
li.moderate {{ background: rgba(252, 238, 10, 0.1); border-left: 3px solid var(--amber); }}
li.ok {{ background: rgba(5, 255, 161, 0.1); border-left: 3px solid var(--green); }}
</style>
</head>
<body>
<h1>PERFORMANCE ISOLATION REPORT</h1>
<p class="subtitle">Generated {html.escape(report.timestamp)} | Sample: {report.sample_seconds}s per element |
   Viewport: {report.viewport['w']}x{report.viewport['h']} | Target: {report.target_fps} FPS</p>

<div class="stats-row">
  <div class="stat-card">
    <div class="label">Baseline FPS</div>
    <div class="value" style="color:{_fps_color(report.baseline.avg_fps)}">{report.baseline.avg_fps:.1f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Max Load FPS</div>
    <div class="value" style="color:{_fps_color(report.cumulative_fps)}">{report.cumulative_fps:.1f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Elements Tested</div>
    <div class="value" style="color:var(--cyan)">{len(report.elements)}</div>
  </div>
  <div class="stat-card">
    <div class="label">Below Target</div>
    <div class="value" style="color:{'var(--magenta)' if any(e.below_target for e in report.elements) else 'var(--green)'}">{sum(1 for e in report.elements if e.below_target)}</div>
  </div>
  <div class="stat-card">
    <div class="label">Worst Offender</div>
    <div class="value" style="color:var(--magenta);font-size:16px">{html.escape(sorted_elements[0].name if sorted_elements else 'N/A')}</div>
  </div>
</div>

<div class="panel">
  <h2>FPS Cost per Element (sorted worst-first)</h2>
  <p style="color:var(--text-secondary);font-size:12px;margin-bottom:12px">
    Subtraction method: each row shows FPS measured <em>without</em> that element.
    Positive cost = removing the element made rendering faster.
  </p>
  <table>
    <thead>
      <tr>
        <th>Element</th><th>Category</th><th>FPS Without</th><th>Cost</th><th>% Gain</th>
        <th>Min</th><th>Max</th><th>P5</th><th>Frame Time</th><th>Jitter</th>
        <th>Frames</th><th>Description</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>

<div class="panel">
  <h2>Cumulative FPS Cost Waterfall</h2>
  <p style="color:var(--text-secondary);font-size:12px;margin-bottom:12px">
    Shows the cumulative FPS cost as elements are stacked (worst offenders first).
    Baseline (default state): {report.baseline.avg_fps:.1f} FPS.
    Note: actual cumulative cost is non-linear; this chart assumes additive costs for budget planning.
  </p>
  <div class="chart-container">
    <svg width="{chart_width}" height="{chart_height}" xmlns="http://www.w3.org/2000/svg">
      <text x="{label_w}" y="18" fill="var(--cyan)" font-size="12"
            font-family="'JetBrains Mono', monospace">Cumulative FPS Drop from Baseline ({report.baseline.avg_fps:.1f} FPS)</text>
      {bars_svg}
    </svg>
  </div>
</div>

<div class="panel">
  <h2>Recommendations</h2>
  <ul>{recs_html}</ul>
</div>

<div class="panel">
  <h2>Performance Budget Analysis</h2>
  <p style="color:var(--text-secondary);font-size:13px">
    Target: <strong style="color:var(--green)">{TARGET_FPS} FPS</strong> minimum.
    Baseline: <strong style="color:{_fps_color(report.baseline.avg_fps)}">{report.baseline.avg_fps:.1f} FPS</strong>.
    Budget available: <strong>{max(0, report.baseline.avg_fps - TARGET_FPS):.1f} FPS</strong> of overhead before hitting target.
  </p>
</div>
</body>
</html>"""


# ============================================================
# Test Class
# ============================================================

class TestPerformanceIsolation:
    """Measure FPS impact of each UI element in isolation."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request):
        cls = request.cls
        OUT.mkdir(parents=True, exist_ok=True)
        cls._results: list[ElementResult] = []
        cls._baseline: FPSMeasurement | None = None
        cls._bare_minimum: FPSMeasurement | None = None
        cls._cumulative: FPSMeasurement | None = None

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        # headed=True by default per project convention
        browser = cls._pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})
        cls.page = ctx.new_page()

        # Capture JS errors
        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Navigate and wait for full load
        cls.page.goto(f"{SERVER}/", wait_until="networkidle")
        cls.page.wait_for_timeout(5000)  # wait for map tiles, Three.js, WebSocket

        # Inject FPS measurement code
        cls.page.evaluate(_FPS_INJECT)

        yield

        # Generate reports after all tests
        try:
            report = PerfReport(
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                baseline=cls._baseline or FPSMeasurement(),
                elements=cls._results,
                cumulative_fps=cls._cumulative.avg_fps if cls._cumulative else 0,
            )

            # HTML report
            report_html = _generate_report(report)
            html_path = OUT / "report.html"
            html_path.write_text(report_html)
            print(f"\n  Performance Report: {html_path.resolve()}")

            # JSON metrics
            bare = cls._bare_minimum or FPSMeasurement()
            metrics = {
                "timestamp": report.timestamp,
                "target_fps": TARGET_FPS,
                "sample_seconds": SAMPLE_SECONDS,
                "viewport": {"width": VIEWPORT_W, "height": VIEWPORT_H},
                "baseline_default": asdict(report.baseline),
                "bare_minimum": asdict(bare),
                "max_load_fps": report.cumulative_fps,
                "elements": [
                    {
                        "name": e.name,
                        "category": e.category,
                        "description": e.description,
                        "avg_fps": e.measurement.avg_fps,
                        "fps_delta": e.fps_delta,
                        "pct_drop": e.pct_drop,
                        "below_target": e.below_target,
                        "min_fps": e.measurement.min_fps,
                        "max_fps": e.measurement.max_fps,
                        "p5_fps": e.measurement.p5_fps,
                        "p50_fps": e.measurement.p50_fps,
                        "p95_fps": e.measurement.p95_fps,
                        "avg_frame_time_ms": e.measurement.avg_frame_time_ms,
                        "jitter_ms": e.measurement.jitter_ms,
                        "variance_ms": e.measurement.variance_ms,
                        "frame_count": e.measurement.frame_count,
                    }
                    for e in sorted(cls._results, key=lambda x: x.fps_delta)
                ],
            }
            json_path = OUT / "metrics.json"
            json_path.write_text(json.dumps(metrics, indent=2))
            print(f"  JSON Metrics: {json_path.resolve()}")

        except Exception as e:
            print(f"\n  Report generation failed: {e}")

        browser.close()
        cls._pw.stop()

    # ---- 01: Baseline (default state) ----

    def test_01_baseline_fps(self):
        """Measure baseline FPS in default loaded state (as user sees it).

        The page has already loaded and settled during fixture setup (5s wait).
        We just restore defaults and give 3s to settle so MapLibre tile
        loading and style recalculation complete before measuring.
        """
        _restore_defaults(self.page)
        self.page.wait_for_timeout(3000)  # let MapLibre fully settle

        # Take baseline screenshot
        self.page.screenshot(path=str(OUT / "baseline_default.png"))

        self.__class__._baseline = _measure_fps(self.page)
        b = self.__class__._baseline
        print(f"\n  BASELINE (default state): {b.avg_fps:.1f} FPS "
              f"(min={b.min_fps:.1f}, max={b.max_fps:.1f}, "
              f"p5={b.p5_fps:.1f}, frames={b.frame_count})")

        assert b.frame_count > 10, (
            f"Too few frames captured ({b.frame_count}). "
            "Page may not be rendering."
        )

    # ---- 02: Bare minimum (everything off) ----

    def test_02_bare_minimum_fps(self):
        """Measure FPS with all visual elements stripped (bare minimum)."""
        _disable_all(self.page)
        self.page.wait_for_timeout(int(SETTLE_SECONDS * 1000))

        self.page.screenshot(path=str(OUT / "bare_minimum.png"))

        bare = _measure_fps(self.page)
        baseline = self.__class__._baseline or FPSMeasurement()
        delta = bare.avg_fps - baseline.avg_fps
        print(f"\n  BARE MINIMUM: {bare.avg_fps:.1f} FPS "
              f"(baseline={baseline.avg_fps:.1f}, delta={delta:+.1f})")

        # Store for reference in report
        self.__class__._bare_minimum = bare

    # ---- 03: Individual Element Isolation (subtraction method) ----

    def test_03_element_isolation(self):
        """Measure FPS cost of each element using subtraction method.

        For each element:
        1. Start from default state (set once before loop)
        2. Disable ONLY that one element
        3. Measure FPS without it
        4. Re-enable it before moving to next element
        5. Cost = fps_without_element - baseline_fps (positive = removing it helped)

        Elements that use setLayers() for disable/enable will trigger MapLibre
        style recalculations, so those get extra settle time.
        """
        baseline = self.__class__._baseline
        assert baseline is not None, "Baseline not measured — run test_01 first"
        assert baseline.avg_fps > 0, "Baseline FPS is 0 — page not rendering"

        # Restore defaults once before the loop
        _restore_defaults(self.page)
        self.page.wait_for_timeout(3000)

        for elem in ELEMENTS:
            # Disable just this one element
            try:
                self.page.evaluate(elem.disable_js)
            except Exception as e:
                print(f"  SKIP {elem.name}: disable failed ({e})")
                continue

            # Settle time: longer for map layers (style recalc), shorter for flags
            uses_set_layers = "setLayers" in elem.disable_js
            settle = 2000 if uses_set_layers else 1000
            self.page.wait_for_timeout(settle)

            # Re-inject FPS code in case it was cleared
            try:
                self.page.evaluate("window._perfIso.start")
            except Exception:
                self.page.evaluate(_FPS_INJECT)

            # Measure FPS without this element
            m = _measure_fps(self.page)

            # Re-enable (restore) before moving to next
            try:
                self.page.evaluate(elem.enable_js)
            except Exception:
                pass
            # Short settle after re-enable
            if uses_set_layers:
                self.page.wait_for_timeout(1500)

            # Cost = how much removing it helped (positive = it was costing us FPS)
            fps_gain = m.avg_fps - baseline.avg_fps
            pct = (fps_gain / baseline.avg_fps * 100) if baseline.avg_fps > 0 else 0

            result = ElementResult(
                name=elem.name,
                category=elem.category,
                description=elem.description,
                measurement=m,
                fps_delta=round(-fps_gain, 1),  # negative means element costs FPS
                pct_drop=round(pct, 1) if fps_gain > 0 else 0,
                below_target=baseline.avg_fps < TARGET_FPS,
            )
            self.__class__._results.append(result)

            status = "COSTLY" if fps_gain > 2 else "OK"
            print(f"  {elem.name:25s}  without={m.avg_fps:6.1f} FPS  "
                  f"cost={fps_gain:+6.1f}  ({result.pct_drop:5.1f}% gain)  "
                  f"[{status}]")

    # ---- 04: Cumulative maximum load ----

    def test_04_cumulative_all_on(self):
        """Measure FPS with ALL elements enabled simultaneously (max load)."""
        _enable_all(self.page)
        self.page.wait_for_timeout(int(SETTLE_SECONDS * 2000))

        # Screenshot
        self.page.screenshot(path=str(OUT / "all_on.png"))

        self.__class__._cumulative = _measure_fps(self.page)
        c = self.__class__._cumulative
        baseline = self.__class__._baseline or FPSMeasurement()

        delta = c.avg_fps - baseline.avg_fps
        print(f"\n  MAX LOAD: {c.avg_fps:.1f} FPS "
              f"(baseline={baseline.avg_fps:.1f}, delta={delta:+.1f}, "
              f"min={c.min_fps:.1f}, max={c.max_fps:.1f})")

    # ---- 05: Summary ----

    def test_05_summary(self):
        """Print sorted summary of worst offenders."""
        results = self.__class__._results
        if not results:
            pytest.skip("No element results collected")

        # Sort by cost (most negative fps_delta = worst offender)
        sorted_results = sorted(results, key=lambda r: r.fps_delta)
        print("\n  === PERFORMANCE ISOLATION SUMMARY ===")
        print(f"  Baseline (default): {self.__class__._baseline.avg_fps:.1f} FPS")
        bare = getattr(self.__class__, '_bare_minimum', None)
        if bare:
            print(f"  Bare minimum (nothing on): {bare.avg_fps:.1f} FPS")
        cumul = self.__class__._cumulative
        if cumul:
            print(f"  Max load (everything on): {cumul.avg_fps:.1f} FPS")
        print()
        print(f"  {'Element':25s}  {'Without':>8s}  {'Cost':>8s}  {'% Gain':>7s}")
        print("  " + "-" * 55)
        for r in sorted_results:
            cost = -r.fps_delta  # positive = removing it helped
            print(f"  {r.name:25s}  {r.measurement.avg_fps:8.1f}  "
                  f"{cost:+8.1f}  {r.pct_drop:6.1f}%")

        costly = [r for r in results if r.fps_delta < -2]
        if costly:
            names = ", ".join(r.name for r in sorted(costly, key=lambda r: r.fps_delta))
            print(f"\n  COSTLY ELEMENTS (>2 FPS cost): {names}")

        # Report paths
        print(f"\n  HTML Report: file://{(OUT / 'report.html').resolve()}")
        print(f"  JSON Metrics: file://{(OUT / 'metrics.json').resolve()}")
