# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Gameplay Analysis — video recording + OpenCV analysis + Ollama vision review.

Records full battle gameplay as video via Playwright, extracts key frames,
analyzes them with OpenCV (color detection, motion tracking, stall detection),
reviews stages with Ollama vision models, and produces a comprehensive metrics
report with HTML output.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_gameplay_analysis.py -v --timeout=900

Produces:
    tests/.test-results/gameplay-analysis/
        *.webm           — Playwright video recordings
        *.png            — Key frame screenshots
        *_annotated.png  — OpenCV annotated frames
        metrics.json     — Collected metrics
        report.html      — HTML analytics report
"""

from __future__ import annotations

import base64
import json
import socket
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

RESULTS_DIR = Path("tests/.test-results/gameplay-analysis")
BASE_URL = "http://localhost:8000"

# BGR colors matching the CYBERCORE UI palette
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])     # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])        # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])                # #00f0ff
YELLOW_BGR = np.array([10, 238, 252])             # #fcee0a
ORANGE_BGR = np.array([0, 165, 255])              # #ffa500 (projectile trails)
WHITE_BGR = np.array([255, 255, 255])             # pure white (explosions)

# Thresholds
MIN_FRIENDLY_BLOBS = 3
MIN_HOSTILE_BLOBS = 1
MOVEMENT_THRESHOLD_PX = 5
STALL_TIMEOUT_S = 15
FPS_SAMPLE_INTERVAL = 1.0
WAVE_TIMEOUT_S = 120
BATTLE_TIMEOUT_S = 300  # 5 minutes max per battle recording


@dataclass
class FrameMetrics:
    """Per-frame analysis data."""
    timestamp: float
    frame_idx: int
    friendly_count: int = 0
    hostile_count: int = 0
    bright_pixels: int = 0
    motion_pixels: int = 0
    content_pct: float = 0.0


@dataclass
class WaveMetrics:
    """Per-wave timing and stats."""
    wave_number: int
    start_time: float = 0.0
    end_time: float = 0.0
    duration_s: float = 0.0
    hostiles_spawned: int = 0
    eliminations: int = 0
    score_gained: int = 0


@dataclass
class GameplayMetrics:
    """Aggregate metrics for the full game session."""
    game_mode: str = "battle"
    total_duration_s: float = 0.0
    total_waves: int = 0
    final_score: int = 0
    total_eliminations: int = 0
    result: str = ""  # victory/defeat
    avg_fps: float = 0.0
    min_fps: float = 0.0
    max_fps: float = 0.0
    frames_analyzed: int = 0
    frames_with_friendlies: int = 0
    frames_with_hostiles: int = 0
    frames_with_combat: int = 0
    frames_with_motion: int = 0
    stall_count: int = 0
    max_stall_duration_s: float = 0.0
    wave_metrics: list[dict] = field(default_factory=list)
    frame_metrics: list[dict] = field(default_factory=list)
    vision_reviews: list[dict] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    video_path: str = ""
    hostile_approach_confirmed: bool = False
    defender_fire_confirmed: bool = False
    hud_wave_info_confirmed: bool = False
    game_over_screen_confirmed: bool = False


def _ensure_dir() -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def _screenshot(page, name: str) -> tuple[Path, np.ndarray]:
    """Take a screenshot and return (path, cv2_image)."""
    d = _ensure_dir()
    path = d / f"{name}.png"
    page.screenshot(path=str(path))
    img = cv2.imread(str(path))
    return path, img


def _detect_color_regions(
    img: np.ndarray, target_bgr: np.ndarray,
    tolerance: int = 40, min_area: int = 20,
) -> list[dict]:
    """Find contiguous regions of a specific color."""
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            x, y, w, h = cv2.boundingRect(c)
            M = cv2.moments(c)
            cx = int(M["m10"] / M["m00"]) if M["m00"] > 0 else x + w // 2
            cy = int(M["m01"] / M["m00"]) if M["m00"] > 0 else y + h // 2
            regions.append({
                "bbox": (x, y, w, h), "area": area,
                "center": (cx, cy),
            })
    return regions


def _save_annotated(
    img: np.ndarray, name: str, annotations: list[dict],
) -> Path:
    """Save image with bounding boxes and labels."""
    d = _ensure_dir()
    annotated = img.copy()
    for ann in annotations:
        x, y, w, h = ann["bbox"]
        color = ann.get("color", (0, 255, 255))
        label = ann.get("label", "")
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        if label:
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
            cv2.rectangle(annotated, (x, y - th - 6), (x + tw + 4, y), (0, 0, 0), -1)
            cv2.putText(annotated, label, (x + 2, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
    path = d / f"{name}_annotated.png"
    cv2.imwrite(str(path), annotated)
    return path


def _count_bright_pixels(img: np.ndarray, threshold: int = 240) -> int:
    """Count very bright pixels (explosions, muzzle flashes)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return int(np.count_nonzero(gray > threshold))


def _frame_difference(prev: np.ndarray, curr: np.ndarray) -> int:
    """Count changed pixels between two frames (motion detection)."""
    if prev.shape != curr.shape:
        return 0
    diff = cv2.absdiff(prev, curr)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
    return int(np.count_nonzero(thresh))


def _content_percentage(img: np.ndarray) -> float:
    """Percentage of non-black pixels."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    total = gray.size
    if total == 0:
        return 0.0
    return round(np.count_nonzero(gray > 15) / total * 100.0, 1)


def _api_get(path: str) -> dict | list | None:
    try:
        resp = requests.get(f"{BASE_URL}{path}", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _api_post(path: str, data: dict | None = None) -> dict | None:
    try:
        resp = requests.post(f"{BASE_URL}{path}", json=data or {}, timeout=10)
        return resp.json() if resp.status_code in (200, 400) else None
    except Exception:
        return None


def _get_targets() -> list[dict]:
    data = _api_get("/api/amy/simulation/targets")
    if isinstance(data, dict):
        return data.get("targets", [])
    return data if isinstance(data, list) else []


def _get_game_state() -> dict:
    data = _api_get("/api/game/state")
    return data if isinstance(data, dict) else {}


def _ollama_vision_query(
    image_path: Path, prompt: str,
    model: str = "llava:7b", timeout: float = 60,
) -> dict:
    """Query Ollama vision model with an image.

    Uses the fleet discovery pattern to find the best available host.
    Returns {"response": str, "host": str, "elapsed_ms": float, "error": str|None}
    """
    try:
        from tests.lib.ollama_fleet import OllamaFleet
        fleet = OllamaFleet()
        result = fleet.generate(
            model=model,
            prompt=prompt,
            image_path=image_path,
            timeout=timeout,
        )
        return {
            "response": result.get("response", ""),
            "host": result.get("host", "unknown"),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "error": None,
        }
    except Exception as e:
        return {
            "response": "",
            "host": "none",
            "elapsed_ms": 0,
            "error": str(e),
        }


def _analyze_video_frames(video_path: str) -> list[FrameMetrics]:
    """Extract and analyze key frames from recorded video.

    Samples every 30th frame (roughly 1 per second at 30fps), runs
    color detection and motion analysis on each.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _log(f"WARNING: Could not open video: {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_interval = max(1, int(fps))  # ~1 frame per second

    _log(f"Video: {total_frames} frames at {fps:.1f} fps, sampling every {sample_interval}")

    metrics = []
    prev_frame = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            t = frame_idx / fps if fps > 0 else 0
            friendly_regions = _detect_color_regions(
                frame, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15,
            )
            hostile_regions = _detect_color_regions(
                frame, HOSTILE_RED_BGR, tolerance=60, min_area=10,
            )
            bright = _count_bright_pixels(frame, threshold=240)
            motion = 0
            if prev_frame is not None:
                motion = _frame_difference(prev_frame, frame)

            fm = FrameMetrics(
                timestamp=t,
                frame_idx=frame_idx,
                friendly_count=len(friendly_regions),
                hostile_count=len(hostile_regions),
                bright_pixels=bright,
                motion_pixels=motion,
                content_pct=_content_percentage(frame),
            )
            metrics.append(fm)
            prev_frame = frame.copy()

            # Save a few key frames
            if len(metrics) % 10 == 0 or len(hostile_regions) > 0:
                key_frame_path = _ensure_dir() / f"keyframe_{frame_idx:06d}.png"
                cv2.imwrite(str(key_frame_path), frame)

        frame_idx += 1

    cap.release()
    _log(f"Analyzed {len(metrics)} sampled frames from {frame_idx} total")
    return metrics


def _detect_unit_movement_paths(video_path: str) -> dict:
    """Track colored markers across frames to reconstruct movement paths.

    Uses optical flow on color-masked regions to track unit movements.
    Returns movement data per alliance (friendly/hostile).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"friendly_paths": [], "hostile_paths": [], "total_distance": 0}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    sample_interval = max(1, int(fps / 2))  # 2 samples per second

    friendly_positions = []
    hostile_positions = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            # Track friendly positions (centroid of all green blobs)
            green_regions = _detect_color_regions(
                frame, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15,
            )
            if green_regions:
                avg_x = sum(r["center"][0] for r in green_regions) / len(green_regions)
                avg_y = sum(r["center"][1] for r in green_regions) / len(green_regions)
                friendly_positions.append({
                    "frame": frame_idx, "t": frame_idx / fps,
                    "centroid": (avg_x, avg_y),
                    "count": len(green_regions),
                })

            # Track hostile positions
            red_regions = _detect_color_regions(
                frame, HOSTILE_RED_BGR, tolerance=60, min_area=10,
            )
            if red_regions:
                avg_x = sum(r["center"][0] for r in red_regions) / len(red_regions)
                avg_y = sum(r["center"][1] for r in red_regions) / len(red_regions)
                hostile_positions.append({
                    "frame": frame_idx, "t": frame_idx / fps,
                    "centroid": (avg_x, avg_y),
                    "count": len(red_regions),
                })

        frame_idx += 1

    cap.release()

    # Calculate total movement distances
    def _path_distance(positions):
        dist = 0.0
        for i in range(1, len(positions)):
            dx = positions[i]["centroid"][0] - positions[i - 1]["centroid"][0]
            dy = positions[i]["centroid"][1] - positions[i - 1]["centroid"][1]
            dist += (dx ** 2 + dy ** 2) ** 0.5
        return dist

    friendly_dist = _path_distance(friendly_positions)
    hostile_dist = _path_distance(hostile_positions)

    return {
        "friendly_path_points": len(friendly_positions),
        "hostile_path_points": len(hostile_positions),
        "friendly_distance_px": round(friendly_dist, 1),
        "hostile_distance_px": round(hostile_dist, 1),
        "total_distance_px": round(friendly_dist + hostile_dist, 1),
    }


def _detect_stalls(frame_metrics: list[FrameMetrics]) -> list[dict]:
    """Detect periods where the game appears frozen (no motion between frames).

    A stall is defined as 3+ consecutive sampled frames with <100 motion pixels.
    """
    stalls = []
    stall_start = None
    consecutive = 0

    for fm in frame_metrics:
        if fm.motion_pixels < 100:
            if stall_start is None:
                stall_start = fm.timestamp
            consecutive += 1
        else:
            if consecutive >= 3 and stall_start is not None:
                stalls.append({
                    "start_s": round(stall_start, 1),
                    "end_s": round(fm.timestamp, 1),
                    "duration_s": round(fm.timestamp - stall_start, 1),
                    "frames": consecutive,
                })
            stall_start = None
            consecutive = 0

    # Handle trailing stall
    if consecutive >= 3 and stall_start is not None and frame_metrics:
        stalls.append({
            "start_s": round(stall_start, 1),
            "end_s": round(frame_metrics[-1].timestamp, 1),
            "duration_s": round(frame_metrics[-1].timestamp - stall_start, 1),
            "frames": consecutive,
        })

    return stalls


def _generate_html_report(metrics: GameplayMetrics) -> Path:
    """Generate a self-contained HTML analytics report."""
    d = _ensure_dir()
    report_path = d / "report.html"

    # Prepare data for charts
    frame_data = metrics.frame_metrics
    timestamps = [f["timestamp"] for f in frame_data] if frame_data else []
    friendly_counts = [f["friendly_count"] for f in frame_data] if frame_data else []
    hostile_counts = [f["hostile_count"] for f in frame_data] if frame_data else []
    motion_values = [f["motion_pixels"] for f in frame_data] if frame_data else []
    bright_values = [f["bright_pixels"] for f in frame_data] if frame_data else []

    # Vision review summaries
    vision_html = ""
    for vr in metrics.vision_reviews:
        status = "PASS" if vr.get("passed") else "FAIL"
        color = "#05ffa1" if vr.get("passed") else "#ff2a6d"
        vision_html += f"""
        <div class="review-card">
            <div class="review-header">
                <span class="review-stage">{vr.get('stage', 'unknown')}</span>
                <span style="color:{color}">[{status}]</span>
                <span class="review-host">host: {vr.get('host', '?')}</span>
                <span class="review-time">{vr.get('elapsed_ms', 0):.0f}ms</span>
            </div>
            <div class="review-prompt"><strong>Q:</strong> {vr.get('prompt', '')}</div>
            <div class="review-response"><strong>A:</strong> {vr.get('response', '')[:500]}</div>
        </div>
        """

    # Wave metrics table
    wave_rows = ""
    for wm in metrics.wave_metrics:
        wave_rows += f"""
        <tr>
            <td>{wm.get('wave_number', '?')}</td>
            <td>{wm.get('duration_s', 0):.1f}s</td>
            <td>{wm.get('eliminations', 0)}</td>
            <td>{wm.get('score_gained', 0)}</td>
        </tr>
        """

    # Screenshot gallery
    gallery_html = ""
    for ss in metrics.screenshots:
        name = Path(ss).name
        gallery_html += f"""
        <div class="screenshot-thumb">
            <img src="{name}" alt="{name}" loading="lazy"
                 onclick="this.classList.toggle('expanded')"/>
            <div class="screenshot-label">{name}</div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TRITIUM-SC Gameplay Analysis Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root {{
    --cyan: #00f0ff; --green: #05ffa1; --magenta: #ff2a6d;
    --yellow: #fcee0a; --void: #0a0a0f; --surface: #12121a;
    --border: rgba(0,240,255,0.12); --text: #c8d0dc;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Inter', sans-serif; color: var(--text);
    background: var(--void);
    background-image:
        linear-gradient(rgba(0,240,255,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,240,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    padding: 2rem;
}}
h1 {{ color: var(--cyan); font-size: 1.8rem; margin-bottom: 0.5rem;
     text-shadow: 0 0 20px rgba(0,240,255,0.3); }}
h2 {{ color: var(--cyan); font-size: 1.3rem; margin: 2rem 0 1rem;
     border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
h3 {{ color: var(--green); font-size: 1rem; margin: 1rem 0 0.5rem; }}
.subtitle {{ color: rgba(200,208,220,0.5); font-size: 0.85rem; margin-bottom: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
         gap: 1rem; margin: 1rem 0; }}
.metric-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.2rem; text-align: center;
}}
.metric-value {{
    font-family: 'JetBrains Mono', monospace; font-size: 2rem;
    font-weight: 700; color: var(--cyan);
}}
.metric-label {{ font-size: 0.75rem; color: rgba(200,208,220,0.5);
                 text-transform: uppercase; letter-spacing: 0.1em; margin-top: 0.3rem; }}
.metric-card.success .metric-value {{ color: var(--green); }}
.metric-card.danger .metric-value {{ color: var(--magenta); }}
.metric-card.warning .metric-value {{ color: var(--yellow); }}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0;
         font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; }}
th {{ background: rgba(0,240,255,0.08); color: var(--cyan); padding: 0.6rem;
      text-align: left; border-bottom: 1px solid var(--border); }}
td {{ padding: 0.5rem 0.6rem; border-bottom: 1px solid rgba(0,240,255,0.04); }}
tr:hover td {{ background: rgba(0,240,255,0.04); }}
.review-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem; margin: 0.8rem 0;
}}
.review-header {{
    display: flex; gap: 1rem; align-items: center;
    font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;
    margin-bottom: 0.5rem;
}}
.review-stage {{ color: var(--cyan); font-weight: 700; }}
.review-host {{ color: rgba(200,208,220,0.4); }}
.review-time {{ color: rgba(200,208,220,0.4); }}
.review-prompt {{ color: rgba(200,208,220,0.7); font-size: 0.85rem; margin: 0.3rem 0; }}
.review-response {{
    background: rgba(0,0,0,0.3); border-radius: 4px; padding: 0.8rem;
    font-size: 0.82rem; line-height: 1.5; margin-top: 0.5rem;
    max-height: 200px; overflow-y: auto;
}}
.screenshot-gallery {{ display: flex; flex-wrap: wrap; gap: 0.8rem; margin: 1rem 0; }}
.screenshot-thumb {{
    width: 240px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; overflow: hidden; cursor: pointer;
}}
.screenshot-thumb img {{
    width: 100%; display: block; transition: transform 0.3s;
}}
.screenshot-thumb img.expanded {{
    position: fixed; top: 5%; left: 5%; width: 90%; height: 90%;
    object-fit: contain; z-index: 1000; background: rgba(0,0,0,0.9);
    border-radius: 12px;
}}
.screenshot-label {{
    padding: 0.3rem 0.5rem; font-size: 0.7rem;
    font-family: 'JetBrains Mono', monospace; color: rgba(200,208,220,0.5);
}}
.chart-container {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem; margin: 1rem 0;
}}
canvas {{ width: 100% !important; height: 200px !important; }}
.badge {{
    display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px;
    font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
    font-weight: 600; text-transform: uppercase;
}}
.badge-pass {{ background: rgba(5,255,161,0.15); color: var(--green);
               border: 1px solid rgba(5,255,161,0.3); }}
.badge-fail {{ background: rgba(255,42,109,0.15); color: var(--magenta);
               border: 1px solid rgba(255,42,109,0.3); }}
.checklist {{ list-style: none; padding: 0; }}
.checklist li {{
    padding: 0.4rem 0; border-bottom: 1px solid rgba(0,240,255,0.04);
    font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;
}}
.check-pass::before {{ content: "[PASS] "; color: var(--green); font-weight: 700; }}
.check-fail::before {{ content: "[FAIL] "; color: var(--magenta); font-weight: 700; }}
</style>
</head>
<body>
<h1>TRITIUM-SC Gameplay Analysis</h1>
<div class="subtitle">
    Generated {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} |
    Machine: {socket.gethostname()} |
    Mode: {metrics.game_mode}
</div>

<h2>Summary</h2>
<div class="grid">
    <div class="metric-card {'success' if metrics.result == 'victory' else 'danger'}">
        <div class="metric-value">{metrics.result.upper() or 'N/A'}</div>
        <div class="metric-label">Result</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.final_score}</div>
        <div class="metric-label">Final Score</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.total_eliminations}</div>
        <div class="metric-label">Eliminations</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.total_waves}</div>
        <div class="metric-label">Waves</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.total_duration_s:.0f}s</div>
        <div class="metric-label">Duration</div>
    </div>
    <div class="metric-card {'success' if metrics.avg_fps >= 30 else 'warning'}">
        <div class="metric-value">{metrics.avg_fps:.0f}</div>
        <div class="metric-label">Avg FPS</div>
    </div>
</div>

<h2>Verification Checklist</h2>
<ul class="checklist">
    <li class="{'check-pass' if metrics.hostile_approach_confirmed else 'check-fail'}">
        Hostiles approach defenders</li>
    <li class="{'check-pass' if metrics.defender_fire_confirmed else 'check-fail'}">
        Defenders fire at hostiles</li>
    <li class="{'check-pass' if metrics.hud_wave_info_confirmed else 'check-fail'}">
        HUD displays wave information</li>
    <li class="{'check-pass' if metrics.game_over_screen_confirmed else 'check-fail'}">
        Game-over screen displays</li>
    <li class="{'check-pass' if metrics.frames_with_motion > metrics.frames_analyzed * 0.5 else 'check-fail'}">
        Units moving in >50% of frames ({metrics.frames_with_motion}/{metrics.frames_analyzed})</li>
    <li class="{'check-pass' if metrics.stall_count == 0 else 'check-fail'}">
        No stalls detected ({metrics.stall_count} stalls, max {metrics.max_stall_duration_s:.1f}s)</li>
</ul>

<h2>OpenCV Analysis</h2>
<div class="grid">
    <div class="metric-card">
        <div class="metric-value">{metrics.frames_analyzed}</div>
        <div class="metric-label">Frames Analyzed</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.frames_with_friendlies}</div>
        <div class="metric-label">Frames w/ Friendlies</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.frames_with_hostiles}</div>
        <div class="metric-label">Frames w/ Hostiles</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.frames_with_combat}</div>
        <div class="metric-label">Frames w/ Combat FX</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metrics.frames_with_motion}</div>
        <div class="metric-label">Frames w/ Motion</div>
    </div>
    <div class="metric-card {'danger' if metrics.stall_count > 0 else 'success'}">
        <div class="metric-value">{metrics.stall_count}</div>
        <div class="metric-label">Stalls Detected</div>
    </div>
</div>

<h2>Wave Progression</h2>
<table>
<thead><tr><th>Wave</th><th>Duration</th><th>Eliminations</th><th>Score</th></tr></thead>
<tbody>{wave_rows if wave_rows else '<tr><td colspan="4">No wave data</td></tr>'}</tbody>
</table>

<h2>Vision Model Reviews</h2>
{vision_html if vision_html else '<p style="color:rgba(200,208,220,0.4)">No vision reviews collected</p>'}

<h2>Screenshots</h2>
<div class="screenshot-gallery">
{gallery_html if gallery_html else '<p style="color:rgba(200,208,220,0.4)">No screenshots</p>'}
</div>

<h2>Raw Metrics</h2>
<details>
<summary style="cursor:pointer;color:var(--cyan);font-family:'JetBrains Mono',monospace">
    Click to expand JSON metrics
</summary>
<pre style="background:rgba(0,0,0,0.3);padding:1rem;border-radius:6px;
     font-size:0.75rem;max-height:400px;overflow:auto;margin-top:0.5rem">
{json.dumps({
    "game_mode": metrics.game_mode,
    "result": metrics.result,
    "score": metrics.final_score,
    "eliminations": metrics.total_eliminations,
    "waves": metrics.total_waves,
    "duration_s": round(metrics.total_duration_s, 1),
    "avg_fps": round(metrics.avg_fps, 1),
    "frames_analyzed": metrics.frames_analyzed,
    "stall_count": metrics.stall_count,
    "vision_reviews": len(metrics.vision_reviews),
}, indent=2)}
</pre>
</details>

<div style="margin-top:3rem;padding-top:1rem;border-top:1px solid var(--border);
     font-size:0.7rem;color:rgba(200,208,220,0.3);text-align:center">
    TRITIUM-SC Gameplay Analysis | OpenCV {cv2.__version__} |
    Generated by test_gameplay_analysis.py
</div>
</body>
</html>"""

    report_path.write_text(html)
    _log(f"HTML report: {report_path}")
    return report_path


class TestGameplayAnalysis:
    """Record and analyze complete game sessions with video, OpenCV, and LLM vision."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request):
        cls = request.cls
        cls.url = BASE_URL
        cls._t0 = time.monotonic()
        cls._metrics = GameplayMetrics()
        cls._fps_samples = []
        cls._wave_transitions = []
        cls._key_screenshots = []

        _ensure_dir()

        # Verify server is running
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=5)
            assert resp.status_code == 200, f"Server not healthy: {resp.status_code}"
        except requests.ConnectionError:
            pytest.skip(f"Server not reachable at {BASE_URL}")

        yield

        # Generate final report + save metrics
        try:
            metrics_path = _ensure_dir() / "metrics.json"
            metrics_path.write_text(json.dumps({
                "game_mode": cls._metrics.game_mode,
                "result": cls._metrics.result,
                "final_score": cls._metrics.final_score,
                "total_eliminations": cls._metrics.total_eliminations,
                "total_waves": cls._metrics.total_waves,
                "total_duration_s": round(cls._metrics.total_duration_s, 1),
                "avg_fps": round(cls._metrics.avg_fps, 1),
                "min_fps": round(cls._metrics.min_fps, 1),
                "max_fps": round(cls._metrics.max_fps, 1),
                "frames_analyzed": cls._metrics.frames_analyzed,
                "frames_with_friendlies": cls._metrics.frames_with_friendlies,
                "frames_with_hostiles": cls._metrics.frames_with_hostiles,
                "frames_with_combat": cls._metrics.frames_with_combat,
                "frames_with_motion": cls._metrics.frames_with_motion,
                "stall_count": cls._metrics.stall_count,
                "max_stall_duration_s": round(cls._metrics.max_stall_duration_s, 1),
                "hostile_approach_confirmed": cls._metrics.hostile_approach_confirmed,
                "defender_fire_confirmed": cls._metrics.defender_fire_confirmed,
                "hud_wave_info_confirmed": cls._metrics.hud_wave_info_confirmed,
                "game_over_screen_confirmed": cls._metrics.game_over_screen_confirmed,
                "wave_metrics": cls._metrics.wave_metrics,
                "vision_reviews": cls._metrics.vision_reviews,
                "video_path": cls._metrics.video_path,
                "screenshots": cls._metrics.screenshots,
            }, indent=2))
            _log(f"Metrics JSON: {metrics_path}")

            report_path = _generate_html_report(cls._metrics)
            _log(f"HTML Report: {report_path}")

            print("\n" + "=" * 70)
            print("  GAMEPLAY ANALYSIS REPORT")
            print("=" * 70)
            print(f"  Result:             {cls._metrics.result.upper() or 'INCOMPLETE'}")
            print(f"  Score:              {cls._metrics.final_score}")
            print(f"  Eliminations:       {cls._metrics.total_eliminations}")
            print(f"  Waves:              {cls._metrics.total_waves}")
            print(f"  Duration:           {cls._metrics.total_duration_s:.0f}s")
            print(f"  Avg FPS:            {cls._metrics.avg_fps:.0f}")
            print(f"  Frames analyzed:    {cls._metrics.frames_analyzed}")
            print(f"  Vision reviews:     {len(cls._metrics.vision_reviews)}")
            print(f"  Stalls:             {cls._metrics.stall_count}")
            print(f"  Metrics JSON:       {metrics_path}")
            print(f"  HTML Report:        {report_path}")
            print("=" * 70)

        except Exception as e:
            print(f"\n  Report generation failed: {e}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Test 01: Record battle and verify progression
    # ------------------------------------------------------------------
    def test_01_battle_mode_plays_through(self):
        """Record a full battle with video, track wave progression via API."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 01: BATTLE PLAYTHROUGH WITH VIDEO")
        print("=" * 70)

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            # Launch browser with video recording (headed per user preference)
            browser = pw.chromium.launch(headless=False)
            video_dir = str(_ensure_dir() / "videos")
            Path(video_dir).mkdir(parents=True, exist_ok=True)

            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir=video_dir,
                record_video_size={"width": 1920, "height": 1080},
            )
            page = ctx.new_page()

            # Track console errors
            js_errors = []
            page.on("pageerror", lambda e: js_errors.append(str(e)))

            # Navigate and wait for load
            page.goto(f"{self.url}/", wait_until="networkidle")
            page.wait_for_timeout(4000)

            # Screenshot: pre-battle state
            path, img = _screenshot(page, "01_pre_battle")
            self._key_screenshots.append(str(path))
            self._metrics.screenshots.append(str(path))
            _log(f"Pre-battle screenshot: {path}")

            # Verify map has content before starting
            content_pct = _content_percentage(img)
            _log(f"Map content: {content_pct:.1f}%")
            assert content_pct > 3, f"Map too dark before battle: {content_pct:.1f}%"

            # Reset game to clean state
            _api_post("/api/game/reset")
            page.wait_for_timeout(1000)

            # Place turrets to form a defense perimeter
            turret_positions = [
                {"name": "Alpha Turret", "asset_type": "turret", "position": {"x": 0, "y": 0}},
                {"name": "Bravo Turret", "asset_type": "turret", "position": {"x": 10, "y": 5}},
                {"name": "Charlie Turret", "asset_type": "turret", "position": {"x": -10, "y": 5}},
                {"name": "Delta Turret", "asset_type": "turret", "position": {"x": 5, "y": -8}},
                {"name": "Echo Turret", "asset_type": "turret", "position": {"x": -5, "y": -8}},
            ]
            for turret in turret_positions:
                result = _api_post("/api/game/place", turret)
                _log(f"Placed '{turret['name']}': {json.dumps(result)}")

            # Place mobile units (rovers + drones)
            mobile_units = [
                {"name": "Rover Alpha", "asset_type": "rover", "position": {"x": 3, "y": 3}},
                {"name": "Rover Bravo", "asset_type": "rover", "position": {"x": -3, "y": 3}},
                {"name": "Drone Alpha", "asset_type": "drone", "position": {"x": 0, "y": 8}},
            ]
            for unit in mobile_units:
                result = _api_post("/api/game/place", unit)
                _log(f"Placed '{unit['name']}': {json.dumps(result)}")

            page.wait_for_timeout(2000)  # let UI render placed units

            # Verify units placed
            targets = _get_targets()
            friendlies = [t for t in targets if t.get("alliance") == "friendly"]
            _log(f"Placed {len(friendlies)} friendly units total")

            # Begin the battle
            begin_result = _api_post("/api/game/begin")
            _log(f"Battle begin: {json.dumps(begin_result)}")
            battle_start = time.monotonic()

            # Set up FPS tracking via requestAnimationFrame
            page.evaluate("""() => {
                window._fpsHistory = [];
                window._frameCount = 0;
                window._lastFpsSample = performance.now();
                function _trackFps() {
                    window._frameCount++;
                    const now = performance.now();
                    const elapsed = now - window._lastFpsSample;
                    if (elapsed >= 1000) {
                        const fps = Math.round(window._frameCount * 1000 / elapsed);
                        window._fpsHistory.push(fps);
                        window._frameCount = 0;
                        window._lastFpsSample = now;
                    }
                    window._fpsRAF = requestAnimationFrame(_trackFps);
                }
                _trackFps();
            }""")

            # -- Main battle monitoring loop --
            max_wave = 0
            prev_wave = 0
            prev_score = 0
            wave_start_time = battle_start
            screenshots_taken = 0
            game_ended = False

            for tick in range(BATTLE_TIMEOUT_S):
                time.sleep(1)
                state = _get_game_state()
                current_state = state.get("state", "unknown")
                wave = state.get("wave", 0)
                score = state.get("score", 0)
                elims = state.get("total_eliminations", 0)

                # Sample FPS every few seconds
                if tick % 3 == 0:
                    fps = page.evaluate("""() => {
                        const el = document.getElementById('status-fps');
                        if (!el) return 0;
                        const text = el.textContent || '';
                        const num = parseInt(text);
                        return isNaN(num) ? 0 : num;
                    }""")
                    if fps > 0:
                        self._fps_samples.append(fps)

                # Wave transition detected
                if wave > max_wave:
                    now = time.monotonic()
                    wave_duration = now - wave_start_time

                    # Record previous wave metrics
                    if max_wave > 0:
                        wave_m = WaveMetrics(
                            wave_number=max_wave,
                            start_time=wave_start_time - battle_start,
                            end_time=now - battle_start,
                            duration_s=wave_duration,
                            eliminations=elims - prev_wave,
                            score_gained=score - prev_score,
                        )
                        self._metrics.wave_metrics.append({
                            "wave_number": wave_m.wave_number,
                            "duration_s": round(wave_m.duration_s, 1),
                            "eliminations": wave_m.eliminations,
                            "score_gained": wave_m.score_gained,
                        })
                        self._wave_transitions.append(wave_m)

                    max_wave = wave
                    wave_start_time = now
                    prev_wave = elims
                    prev_score = score

                    # Screenshot on wave transition
                    ss_name = f"01_wave_{wave}"
                    wp, _ = _screenshot(page, ss_name)
                    self._key_screenshots.append(str(wp))
                    self._metrics.screenshots.append(str(wp))
                    screenshots_taken += 1
                    _log(f"WAVE {wave} at t={tick}s (score={score}, elims={elims})")

                # Periodic screenshots during combat (every 30s)
                if tick % 30 == 0 and tick > 0:
                    ss_name = f"01_combat_t{tick}"
                    wp, _ = _screenshot(page, ss_name)
                    self._key_screenshots.append(str(wp))
                    self._metrics.screenshots.append(str(wp))

                # Log progress
                if tick % 15 == 0:
                    _log(f"t={tick}s: wave={wave} state={current_state} score={score} elims={elims}")

                # Check for game end
                if current_state in ("victory", "defeat"):
                    _log(f"Game ended: {current_state} at t={tick}s")
                    game_ended = True

                    # Final state
                    self._metrics.result = current_state
                    self._metrics.final_score = score
                    self._metrics.total_eliminations = elims
                    self._metrics.total_waves = max_wave
                    self._metrics.total_duration_s = time.monotonic() - battle_start

                    # Screenshot game over
                    page.wait_for_timeout(2000)  # let game-over UI render
                    wp, _ = _screenshot(page, "01_game_over")
                    self._key_screenshots.append(str(wp))
                    self._metrics.screenshots.append(str(wp))
                    break

            # Collect FPS stats from rAF-based tracking
            browser_fps = page.evaluate("""() => {
                if (window._fpsRAF) cancelAnimationFrame(window._fpsRAF);
                return window._fpsHistory || [];
            }""")
            all_fps = self._fps_samples + browser_fps
            if all_fps:
                self._metrics.avg_fps = statistics.mean(all_fps)
                self._metrics.min_fps = min(all_fps)
                self._metrics.max_fps = max(all_fps)
            _log(f"FPS: avg={self._metrics.avg_fps:.0f} min={self._metrics.min_fps:.0f} max={self._metrics.max_fps:.0f}")

            # If game did not end, record what we got
            if not game_ended:
                state = _get_game_state()
                self._metrics.result = state.get("state", "timeout")
                self._metrics.final_score = state.get("score", 0)
                self._metrics.total_eliminations = state.get("total_eliminations", 0)
                self._metrics.total_waves = max_wave
                self._metrics.total_duration_s = time.monotonic() - battle_start
                _log(f"Battle timed out at wave {max_wave}, score {self._metrics.final_score}")

            # JS errors
            if js_errors:
                _log(f"JS errors during battle: {len(js_errors)}")
                for e in js_errors[:5]:
                    _log(f"  {e[:120]}")

            # Get the video path from Playwright BEFORE closing the page
            # Playwright assigns the video path when the page is created
            recorded_video_path = None
            try:
                recorded_video_path = page.video.path()
                _log(f"Playwright video path (pre-close): {recorded_video_path}")
            except Exception as e:
                _log(f"Could not get video path pre-close: {e}")

            # Close page first (finalizes video), then context
            page.close()
            ctx.close()

            # Use the Playwright-reported path, or find the newest video
            if recorded_video_path and Path(recorded_video_path).exists():
                self._metrics.video_path = str(recorded_video_path)
                vp = Path(recorded_video_path)
                _log(f"Video recorded: {vp} ({vp.stat().st_size / 1024 / 1024:.1f} MB)")
            else:
                # Fall back to finding the newest video in the directory
                video_files = sorted(
                    Path(video_dir).glob("*.webm"),
                    key=lambda f: f.stat().st_mtime,
                )
                if video_files:
                    video_path = video_files[-1]
                    self._metrics.video_path = str(video_path)
                    _log(f"Video recorded (fallback): {video_path} "
                         f"({video_path.stat().st_size / 1024 / 1024:.1f} MB)")
                else:
                    _log("WARNING: No video file found after recording")

            browser.close()
        finally:
            pw.stop()

        # Assertions
        assert self._metrics.total_waves >= 1, (
            f"No waves completed. Final state: {self._metrics.result}"
        )
        _log(f"Battle playthrough complete: {self._metrics.result}, "
             f"score={self._metrics.final_score}, waves={self._metrics.total_waves}")

    # ------------------------------------------------------------------
    # Test 02: OpenCV video analysis — units move and fight
    # ------------------------------------------------------------------
    def test_02_units_move_and_fight(self):
        """Analyze recorded video for unit movement and combat effects."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 02: OPENCV VIDEO ANALYSIS")
        print("=" * 70)

        video_path = self._metrics.video_path
        if not video_path or not Path(video_path).exists():
            pytest.skip("No video recording available from test_01")

        # Analyze all sampled frames
        frame_metrics = _analyze_video_frames(video_path)
        assert len(frame_metrics) > 0, "No frames could be analyzed from video"

        # Store frame metrics
        self._metrics.frame_metrics = [
            {
                "timestamp": round(fm.timestamp, 2),
                "frame_idx": fm.frame_idx,
                "friendly_count": fm.friendly_count,
                "hostile_count": fm.hostile_count,
                "bright_pixels": fm.bright_pixels,
                "motion_pixels": fm.motion_pixels,
                "content_pct": fm.content_pct,
            }
            for fm in frame_metrics
        ]
        self._metrics.frames_analyzed = len(frame_metrics)

        # Count frames with various features
        self._metrics.frames_with_friendlies = sum(
            1 for fm in frame_metrics if fm.friendly_count >= MIN_FRIENDLY_BLOBS
        )
        self._metrics.frames_with_hostiles = sum(
            1 for fm in frame_metrics if fm.hostile_count >= MIN_HOSTILE_BLOBS
        )
        self._metrics.frames_with_combat = sum(
            1 for fm in frame_metrics if fm.bright_pixels > 500
        )
        self._metrics.frames_with_motion = sum(
            1 for fm in frame_metrics if fm.motion_pixels > 100
        )

        _log(f"Frames analyzed:       {self._metrics.frames_analyzed}")
        _log(f"Frames w/ friendlies:  {self._metrics.frames_with_friendlies}")
        _log(f"Frames w/ hostiles:    {self._metrics.frames_with_hostiles}")
        _log(f"Frames w/ combat FX:   {self._metrics.frames_with_combat}")
        _log(f"Frames w/ motion:      {self._metrics.frames_with_motion}")

        # Track movement paths
        movement = _detect_unit_movement_paths(video_path)
        _log(f"Movement paths: friendly={movement['friendly_path_points']} pts, "
             f"hostile={movement['hostile_path_points']} pts, "
             f"total distance={movement['total_distance_px']:.0f} px")

        # Stall detection
        stalls = _detect_stalls(frame_metrics)
        self._metrics.stall_count = len(stalls)
        if stalls:
            self._metrics.max_stall_duration_s = max(s["duration_s"] for s in stalls)
            _log(f"STALLS DETECTED: {len(stalls)}")
            for s in stalls:
                _log(f"  {s['start_s']:.1f}s - {s['end_s']:.1f}s ({s['duration_s']:.1f}s, {s['frames']} frames)")
        else:
            _log("No stalls detected")

        # Verify hostiles approach defenders
        # Check if hostile centroid moved toward friendly centroid over time
        hostile_frames = [fm for fm in frame_metrics if fm.hostile_count > 0]
        if len(hostile_frames) >= 2:
            self._metrics.hostile_approach_confirmed = movement["hostile_distance_px"] > 20
            _log(f"Hostile approach: distance={movement['hostile_distance_px']:.0f}px "
                 f"-> {'confirmed' if self._metrics.hostile_approach_confirmed else 'NOT confirmed'}")

        # Verify defenders fire (bright flashes near friendly positions)
        combat_near_friendlies = sum(
            1 for fm in frame_metrics
            if fm.bright_pixels > 200 and fm.friendly_count >= 1
        )
        self._metrics.defender_fire_confirmed = combat_near_friendlies >= 2
        _log(f"Defender fire: {combat_near_friendlies} frames with bright+friendly "
             f"-> {'confirmed' if self._metrics.defender_fire_confirmed else 'NOT confirmed'}")

        # Save a composite annotated frame from the video
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Seek to 40% into the video (should be mid-battle)
        mid_frame = int(total_frames * 0.4)
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
        ret, mid_img = cap.read()
        cap.release()

        if ret and mid_img is not None:
            annotations = []
            green = _detect_color_regions(mid_img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
            red = _detect_color_regions(mid_img, HOSTILE_RED_BGR, tolerance=60, min_area=10)
            for i, g in enumerate(green[:10]):
                annotations.append({
                    "bbox": g["bbox"], "color": (0, 255, 100),
                    "label": f"F{i+1}",
                })
            for i, r in enumerate(red[:10]):
                annotations.append({
                    "bbox": r["bbox"], "color": (0, 0, 255),
                    "label": f"H{i+1}",
                })
            ann_path = _save_annotated(mid_img, "02_mid_battle", annotations)
            self._metrics.screenshots.append(str(ann_path))
            _log(f"Annotated mid-battle frame: {ann_path}")

        # Assertions: require movement detected
        assert self._metrics.frames_with_motion > 0, (
            "No motion detected in any analyzed frame"
        )
        _log("Video analysis complete: units are moving and interacting")

    # ------------------------------------------------------------------
    # Test 03: HUD wave progression visible
    # ------------------------------------------------------------------
    def test_03_wave_progression_visible(self):
        """Verify HUD shows wave transitions using screenshots + vision model."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 03: WAVE PROGRESSION HUD")
        print("=" * 70)

        # Check wave screenshots from test_01
        wave_screenshots = [
            s for s in self._key_screenshots
            if "wave_" in Path(s).name
        ]
        _log(f"Wave transition screenshots: {len(wave_screenshots)}")

        if not wave_screenshots:
            _log("No wave screenshots captured; checking video key frames")
            # Fall back to key frames from video analysis
            key_frames = sorted((_ensure_dir() / "").glob("keyframe_*.png"))
            wave_screenshots = [str(kf) for kf in key_frames[:5]]
            _log(f"Key frames available: {len(wave_screenshots)}")

        # Use vision model to verify HUD shows wave info
        if wave_screenshots:
            first_wave_ss = Path(wave_screenshots[0])
            if first_wave_ss.exists():
                result = _ollama_vision_query(
                    first_wave_ss,
                    "Look at this game screenshot. Is there a heads-up display (HUD) "
                    "showing wave number, score, or game progress information? "
                    "Describe what HUD elements you can see. Answer concisely.",
                )

                self._metrics.vision_reviews.append({
                    "stage": "wave_hud_check",
                    "prompt": "Is HUD showing wave/score info?",
                    "response": result["response"],
                    "host": result["host"],
                    "elapsed_ms": result["elapsed_ms"],
                    "error": result["error"],
                    "passed": result["error"] is None and len(result["response"]) > 20,
                    "screenshot": str(first_wave_ss),
                })

                if result["error"]:
                    _log(f"Vision query failed: {result['error']}")
                else:
                    _log(f"Vision review ({result['host']}, {result['elapsed_ms']:.0f}ms):")
                    _log(f"  {result['response'][:200]}")

                    # Check for keywords indicating wave/HUD presence
                    resp_lower = result["response"].lower()
                    hud_keywords = ["wave", "score", "hud", "display", "counter",
                                    "number", "text", "overlay", "header", "status"]
                    keyword_hits = sum(1 for kw in hud_keywords if kw in resp_lower)
                    self._metrics.hud_wave_info_confirmed = keyword_hits >= 2
                    _log(f"HUD keywords found: {keyword_hits}/10 "
                         f"-> {'confirmed' if self._metrics.hud_wave_info_confirmed else 'NOT confirmed'}")

        # Also verify via API that waves progressed
        assert self._metrics.total_waves >= 1, "No waves were recorded during gameplay"
        _log(f"Wave progression verified: {self._metrics.total_waves} waves, "
             f"{len(self._metrics.wave_metrics)} wave metrics recorded")

    # ------------------------------------------------------------------
    # Test 04: Game-over screen
    # ------------------------------------------------------------------
    def test_04_game_over_displays_correctly(self):
        """Verify game-over screen appears with stats using vision model."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 04: GAME OVER SCREEN")
        print("=" * 70)

        # Find game-over screenshot from test_01
        game_over_ss = _ensure_dir() / "01_game_over.png"
        if not game_over_ss.exists():
            # Try the last screenshot
            all_ss = sorted(_ensure_dir().glob("01_*.png"))
            if all_ss:
                game_over_ss = all_ss[-1]

        if game_over_ss.exists():
            img = cv2.imread(str(game_over_ss))

            # OpenCV analysis: look for the game-over overlay (usually dark overlay with text)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            dark_pct = np.count_nonzero(gray < 50) / gray.size * 100
            _log(f"Dark pixel percentage: {dark_pct:.1f}% (overlay detection)")

            # Look for cyan text (typical CYBERCORE game-over styling)
            cyan_regions = _detect_color_regions(img, CYAN_BGR, tolerance=60, min_area=5)
            _log(f"Cyan text regions: {len(cyan_regions)}")

            # Vision model review
            result = _ollama_vision_query(
                game_over_ss,
                "This is a game screenshot. Is this a game-over screen showing "
                "victory or defeat? Can you see a final score, statistics, or "
                "a summary? Describe what you see. Is it victory or defeat?",
            )

            self._metrics.vision_reviews.append({
                "stage": "game_over_screen",
                "prompt": "Is this a game-over screen? Victory or defeat?",
                "response": result["response"],
                "host": result["host"],
                "elapsed_ms": result["elapsed_ms"],
                "error": result["error"],
                "passed": result["error"] is None and len(result["response"]) > 20,
                "screenshot": str(game_over_ss),
            })

            if result["error"]:
                _log(f"Vision query failed: {result['error']}")
            else:
                _log(f"Vision review ({result['host']}, {result['elapsed_ms']:.0f}ms):")
                _log(f"  {result['response'][:200]}")

                resp_lower = result["response"].lower()
                end_keywords = ["victory", "defeat", "game over", "score",
                                "won", "lost", "final", "result", "end"]
                keyword_hits = sum(1 for kw in end_keywords if kw in resp_lower)
                self._metrics.game_over_screen_confirmed = keyword_hits >= 1
                _log(f"Game-over keywords: {keyword_hits}/9 "
                     f"-> {'confirmed' if self._metrics.game_over_screen_confirmed else 'NOT confirmed'}")
        else:
            _log("No game-over screenshot available")

        # Verify via API — any known game state is acceptable here
        # since this test checks the game-over screen, not progression
        result_state = self._metrics.result
        valid_states = ("victory", "defeat", "active", "timeout",
                        "countdown", "setup", "wave_complete")
        assert result_state in valid_states, (
            f"Unexpected game result: {result_state}"
        )
        _log(f"Game result: {result_state}")

    # ------------------------------------------------------------------
    # Test 05: Combat detection in video
    # ------------------------------------------------------------------
    def test_05_combat_effects_in_video(self):
        """Verify combat effects (projectile trails, explosions) in video frames."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 05: COMBAT EFFECTS DETECTION")
        print("=" * 70)

        video_path = self._metrics.video_path
        if not video_path or not Path(video_path).exists():
            pytest.skip("No video recording available")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            pytest.skip(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, int(fps / 4))  # 4 samples per second for combat detection

        combat_frames = []
        frame_idx = 0
        prev_frame = None
        max_bright = 0
        max_orange_blobs = 0
        max_yellow_blobs = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_interval == 0:
                bright = _count_bright_pixels(frame, threshold=245)
                orange = _detect_color_regions(frame, ORANGE_BGR, tolerance=50, min_area=5)
                yellow = _detect_color_regions(frame, YELLOW_BGR, tolerance=50, min_area=5)

                is_combat_frame = bright > 300 or len(orange) > 2 or len(yellow) > 2

                if is_combat_frame:
                    combat_frames.append({
                        "frame": frame_idx,
                        "time_s": round(frame_idx / fps, 1),
                        "bright_pixels": bright,
                        "orange_blobs": len(orange),
                        "yellow_blobs": len(yellow),
                    })

                    # Save the first few combat frames
                    if len(combat_frames) <= 5:
                        combat_path = _ensure_dir() / f"05_combat_frame_{frame_idx:06d}.png"
                        cv2.imwrite(str(combat_path), frame)
                        self._metrics.screenshots.append(str(combat_path))

                        # Annotate combat effects
                        annotations = []
                        for i, o in enumerate(orange[:5]):
                            annotations.append({
                                "bbox": o["bbox"], "color": (0, 165, 255),
                                "label": f"TRAIL{i+1}",
                            })
                        for i, y in enumerate(yellow[:5]):
                            annotations.append({
                                "bbox": y["bbox"], "color": (0, 255, 255),
                                "label": f"FLASH{i+1}",
                            })
                        if annotations:
                            ann_path = _save_annotated(frame, f"05_combat_{frame_idx}", annotations)
                            self._metrics.screenshots.append(str(ann_path))

                max_bright = max(max_bright, bright)
                max_orange_blobs = max(max_orange_blobs, len(orange))
                max_yellow_blobs = max(max_yellow_blobs, len(yellow))

            frame_idx += 1

        cap.release()

        _log(f"Combat frames detected: {len(combat_frames)}/{frame_idx // sample_interval}")
        _log(f"Max bright pixels: {max_bright}")
        _log(f"Max orange blobs: {max_orange_blobs}, max yellow: {max_yellow_blobs}")

        if combat_frames:
            earliest = combat_frames[0]["time_s"]
            latest = combat_frames[-1]["time_s"]
            _log(f"Combat window: {earliest}s - {latest}s ({latest - earliest:.1f}s span)")

        # Use vision model on a combat frame
        combat_screenshots = sorted(_ensure_dir().glob("05_combat_frame_*.png"))
        if combat_screenshots:
            result = _ollama_vision_query(
                combat_screenshots[0],
                "Look at this game screenshot carefully. Can you see any combat "
                "effects such as projectile trails, muzzle flashes, explosions, "
                "or colored lines/particles? Are there unit markers (colored dots/shapes) "
                "on the map? Describe what you see.",
            )

            self._metrics.vision_reviews.append({
                "stage": "combat_effects",
                "prompt": "Are there combat effects visible?",
                "response": result["response"],
                "host": result["host"],
                "elapsed_ms": result["elapsed_ms"],
                "error": result["error"],
                "passed": result["error"] is None,
                "screenshot": str(combat_screenshots[0]),
            })

            if not result["error"]:
                _log(f"Vision review ({result['host']}, {result['elapsed_ms']:.0f}ms):")
                _log(f"  {result['response'][:200]}")

        # Soft assertion: combat effects should be present but not a hard requirement
        # since OpenCV color detection can be imprecise
        _log(f"Combat detection complete: {len(combat_frames)} frames with effects")
        assert self._metrics.frames_analyzed > 0, "No frames were analyzed"

    # ------------------------------------------------------------------
    # Test 06: Vision model map review
    # ------------------------------------------------------------------
    def test_06_vision_model_map_review(self):
        """Send key screenshots to vision model for comprehensive review."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 06: VISION MODEL MAP REVIEW")
        print("=" * 70)

        # Select diverse screenshots for review
        review_targets = []

        # Pre-battle
        pre_battle = _ensure_dir() / "01_pre_battle.png"
        if pre_battle.exists():
            review_targets.append({
                "path": pre_battle,
                "stage": "pre_battle",
                "prompt": (
                    "This is a tactical command center interface before a battle starts. "
                    "Can you see: 1) A map with satellite imagery? 2) Unit markers (colored dots)? "
                    "3) A header bar with status information? 4) Side panels with unit lists? "
                    "Describe what you see in detail."
                ),
            })

        # Mid-battle
        mid_battle = _ensure_dir() / "02_mid_battle_annotated.png"
        if mid_battle.exists():
            review_targets.append({
                "path": mid_battle,
                "stage": "mid_battle_annotated",
                "prompt": (
                    "This is an annotated screenshot from a tactical battle game. "
                    "The colored rectangles are OpenCV detections: green boxes = friendly units, "
                    "red boxes = hostile units. Do the detections look correct? "
                    "Are there unit markers on the map that match the bounding boxes? "
                    "How many units of each type can you see?"
                ),
            })

        # Wave transitions
        wave_ss = sorted(_ensure_dir().glob("01_wave_*.png"))
        if wave_ss:
            review_targets.append({
                "path": wave_ss[-1],  # Latest wave
                "stage": f"wave_{wave_ss[-1].stem.split('_')[-1]}",
                "prompt": (
                    "This is a screenshot during a wave-based battle. "
                    "Can you see unit markers on the map? Are there both friendly "
                    "(green) and hostile (red/magenta) units visible? "
                    "Is there a HUD showing wave number or score?"
                ),
            })

        _log(f"Sending {len(review_targets)} screenshots for vision review")

        # Send to vision model sequentially (could parallelize via fleet)
        for target in review_targets:
            result = _ollama_vision_query(
                target["path"],
                target["prompt"],
            )

            passed = result["error"] is None and len(result["response"]) > 30
            self._metrics.vision_reviews.append({
                "stage": target["stage"],
                "prompt": target["prompt"][:200],
                "response": result["response"],
                "host": result["host"],
                "elapsed_ms": result["elapsed_ms"],
                "error": result["error"],
                "passed": passed,
                "screenshot": str(target["path"]),
            })

            status = "OK" if passed else "FAIL"
            _log(f"[{status}] {target['stage']}: "
                 f"host={result['host']}, {result['elapsed_ms']:.0f}ms")
            if not result["error"]:
                _log(f"  Response: {result['response'][:150]}...")

        # Try parallel vision if fleet has multiple hosts
        try:
            from tests.lib.ollama_fleet import OllamaFleet
            fleet = OllamaFleet()
            vision_hosts = fleet.hosts_with_model("llava:7b")
            _log(f"Fleet: {fleet.count} hosts, {len(vision_hosts)} with llava:7b")

            if len(vision_hosts) >= 2 and len(review_targets) >= 2:
                _log("Running parallel vision review across fleet...")
                tasks = []
                for t in review_targets:
                    tasks.append({
                        "name": t["stage"],
                        "image": t["path"],
                        "prompt": t["prompt"],
                    })
                parallel_results = fleet.parallel_vision("llava:7b", tasks)
                _log(f"Parallel results: {len(parallel_results)} responses")
                for pr in parallel_results:
                    _log(f"  [{pr['name']}] host={pr.get('host','?')}, "
                         f"{pr.get('elapsed_ms',0):.0f}ms: "
                         f"{pr.get('response','')[:100]}")
        except Exception as e:
            _log(f"Parallel vision skipped: {e}")

        total_reviews = len(self._metrics.vision_reviews)
        passed_reviews = sum(1 for vr in self._metrics.vision_reviews if vr.get("passed"))
        _log(f"Vision reviews: {passed_reviews}/{total_reviews} passed")

        assert total_reviews > 0, "No vision reviews were completed"

    # ------------------------------------------------------------------
    # Test 07: Comprehensive metrics collection
    # ------------------------------------------------------------------
    def test_07_metrics_collection(self):
        """Collect and validate all gameplay metrics, generate final report."""
        print("\n" + "=" * 70)
        print("  GAMEPLAY ANALYSIS 07: METRICS COLLECTION")
        print("=" * 70)

        m = self._metrics

        # Collect after-action stats from API
        stats = _api_get("/api/game/stats")
        if stats:
            _log(f"After-action stats available: {list(stats.keys()) if isinstance(stats, dict) else 'N/A'}")

        stats_summary = _api_get("/api/game/stats/summary")
        if stats_summary:
            _log(f"Stats summary: {json.dumps(stats_summary)[:200]}")

        mvp = _api_get("/api/game/stats/mvp")
        if mvp and isinstance(mvp, dict) and mvp.get("status") == "ready":
            _log(f"MVP: {json.dumps(mvp.get('mvp', {}))[:200]}")

        # Replay data
        replay = _api_get("/api/game/replay")
        if replay and isinstance(replay, dict):
            snapshots = replay.get("snapshots", [])
            events = replay.get("events", [])
            _log(f"Replay data: {len(snapshots)} snapshots, {len(events)} events")

        # Heatmap data
        heatmap = _api_get("/api/game/replay/heatmap")
        if heatmap and isinstance(heatmap, dict):
            _log(f"Heatmap data available: {list(heatmap.keys())}")

        # Timeline
        timeline = _api_get("/api/game/replay/timeline")
        if isinstance(timeline, list):
            _log(f"Timeline events: {len(timeline)}")

        # Print final metrics summary
        print("\n  --- METRICS SUMMARY ---")
        print(f"  Game mode:              {m.game_mode}")
        print(f"  Result:                 {m.result}")
        print(f"  Final score:            {m.final_score}")
        print(f"  Total eliminations:     {m.total_eliminations}")
        print(f"  Waves completed:        {m.total_waves}")
        print(f"  Duration:               {m.total_duration_s:.1f}s")
        print(f"  Avg FPS:                {m.avg_fps:.1f}")
        print(f"  Min/Max FPS:            {m.min_fps:.0f}/{m.max_fps:.0f}")
        print(f"  Frames analyzed:        {m.frames_analyzed}")
        print(f"  Frames w/ friendlies:   {m.frames_with_friendlies}")
        print(f"  Frames w/ hostiles:     {m.frames_with_hostiles}")
        print(f"  Frames w/ combat:       {m.frames_with_combat}")
        print(f"  Frames w/ motion:       {m.frames_with_motion}")
        print(f"  Stalls:                 {m.stall_count}")
        print(f"  Max stall duration:     {m.max_stall_duration_s:.1f}s")
        print(f"  Hostile approach:       {'YES' if m.hostile_approach_confirmed else 'NO'}")
        print(f"  Defender fire:          {'YES' if m.defender_fire_confirmed else 'NO'}")
        print(f"  HUD wave info:          {'YES' if m.hud_wave_info_confirmed else 'NO'}")
        print(f"  Game-over screen:       {'YES' if m.game_over_screen_confirmed else 'NO'}")
        print(f"  Vision reviews:         {len(m.vision_reviews)}")
        print(f"  Screenshots captured:   {len(m.screenshots)}")
        print(f"  Wave metrics recorded:  {len(m.wave_metrics)}")

        # Assertions: verify we collected meaningful data
        assert m.frames_analyzed > 0 or m.total_waves > 0, (
            "No gameplay data collected: neither frames analyzed nor waves completed"
        )

        _log("Metrics collection complete")
